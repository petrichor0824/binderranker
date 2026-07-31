#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""保存数据集分组建议，并安全创建独立任务 Bundle。"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from protein_design_agent.agent.dataset_discovery import (
    DatasetDiscoveryReport,
)
from protein_design_agent.agent.dataset_grouping import (
    ValidatedDatasetGrouping,
)
from protein_design_agent.agent.natural_language_prepare import (
    save_incomplete_session,
)
from protein_design_agent.agent.orchestrator import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.workspace_tasks import (
    resolve_task_bundle,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    collect_pdb_files,
)


class DatasetGroupTaskError(RuntimeError):
    """数据集分组任务无法安全创建。"""


class GroupTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_name: str
    input_directory: Path
    source_relative_path: str
    pdb_count: int = Field(ge=1)
    recursive: bool = False
    reason: str


class DatasetGroupingArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1"
    created_at_utc: str
    source_bundle: Path
    root_directory: Path
    layout: str
    user_description: str
    groups: list[GroupTaskSpec] = Field(
        min_length=1,
        max_length=100,
    )
    omitted_relative_paths: list[str]
    warnings: list[str]
    questions: list[str]
    summary: str
    requires_user_review: bool


class GroupTaskCreationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_directory: Path
    created_bundles: list[Path]
    task_names: list[str]


def grouping_proposal_path(
    bundle_dir: Path,
) -> Path:
    return (
        bundle_dir.resolve()
        / "chat"
        / "dataset_grouping_proposal.json"
    )


def write_json_atomically(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )

    try:
        with temporary.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_grouping_proposal(
    *,
    bundle_dir: Path,
    report: DatasetDiscoveryReport,
    grouping: ValidatedDatasetGrouping,
    user_description: str,
) -> Path:
    artifact = DatasetGroupingArtifact(
        created_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        source_bundle=bundle_dir.resolve(),
        root_directory=(
            report.root_directory.resolve()
        ),
        layout=report.layout,
        user_description=user_description.strip(),
        groups=[
            GroupTaskSpec(
                task_name=group.task_name,
                input_directory=(
                    group.input_directory.resolve()
                ),
                source_relative_path=(
                    group.source_relative_path
                ),
                pdb_count=group.pdb_count,
                recursive=group.recursive,
                reason=group.reason,
            )
            for group in grouping.groups
        ],
        omitted_relative_paths=list(
            grouping.omitted_relative_paths
        ),
        warnings=list(grouping.warnings),
        questions=list(grouping.questions),
        summary=grouping.summary,
        requires_user_review=(
            grouping.requires_user_review
        ),
    )

    path = grouping_proposal_path(bundle_dir)

    write_json_atomically(
        path,
        artifact.model_dump(mode="json"),
    )

    return path


def load_grouping_proposal(
    bundle_dir: Path,
) -> DatasetGroupingArtifact:
    path = grouping_proposal_path(bundle_dir)

    try:
        return DatasetGroupingArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        ValidationError,
    ) as exc:
        raise DatasetGroupTaskError(
            f"无法读取分组建议：{path}；{exc}"
        ) from exc


def managed_workspace_from_bundle(
    bundle_dir: Path,
) -> Path:
    bundle = bundle_dir.resolve()
    runs_root = bundle.parent
    workspace = runs_root.parent

    if (
        runs_root.name != "runs"
        or not (
            workspace / ".pda-workspace.json"
        ).is_file()
    ):
        raise DatasetGroupTaskError(
            "批量创建命名任务需要受管工作空间；"
            "当前 Bundle 不位于 "
            "<workspace>/runs/<task> 中"
        )

    return workspace


PROJECT_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)


def build_group_planning_session(
    *,
    group: GroupTaskSpec,
    artifact: DatasetGroupingArtifact,
) -> PlanningSession:
    """
    为一个已确认分组建立正式但未完成的规划会话。

    只采用分组阶段已经确认的数据目录和任务标识；
    不猜测链布局或其他科学参数。
    """
    project_name = (
        group.task_name
        if PROJECT_NAME_PATTERN.fullmatch(
            group.task_name
        )
        else None
    )

    user_description = (
        artifact.user_description.strip()
        or "用户确认按已发现的数据目录分别建立排序任务。"
    )

    raw_text = (
        f"{user_description}\n\n"
        f"已确认分组任务：{group.task_name}\n"
        f"已确认输入目录："
        f"{group.input_directory.resolve()}\n"
        "其余科学参数尚未确认。"
    )

    request = UserRequest(
        raw_text=raw_text,
        project_name=project_name,
        input_dir=group.input_directory.resolve(),
        execute_requested=False,
    )

    plan = build_agent_plan(request)

    if plan.status != "NEEDS_INFORMATION":
        raise DatasetGroupTaskError(
            "新分组任务没有进入预期的 "
            "NEEDS_INFORMATION 状态："
            f"{group.task_name}；{plan.status}"
        )

    explicit_fields = ["input_dir"]

    if project_name is not None:
        explicit_fields.append("project_name")

    return PlanningSession(
        provider_name=(
            "dataset-grouping-confirmed"
        ),
        request=request,
        plan=plan,
        request_explicit_fields=(
            sorted(explicit_fields)
        ),
    )


def create_group_task_bundles(
    *,
    source_bundle: Path,
) -> GroupTaskCreationResult:
    """
    确认后创建独立 Bundle 和正式规划会话。

    不批准、不执行，也不复制未经确认的科学参数。
    """
    artifact = load_grouping_proposal(
        source_bundle
    )
    workspace = managed_workspace_from_bundle(
        source_bundle
    )

    targets: list[
        tuple[GroupTaskSpec, Path]
    ] = []

    # 所有检查必须在任何写入前完成。
    for group in artifact.groups:
        input_directory = (
            group.input_directory.resolve()
        )

        if not input_directory.is_dir():
            raise DatasetGroupTaskError(
                "分组输入目录已不存在："
                f"{input_directory}"
            )

        current_count = len(
            collect_pdb_files(
                input_dir=input_directory,
                recursive=group.recursive,
                max_files=None,
            )
        )

        if current_count != group.pdb_count:
            raise DatasetGroupTaskError(
                "分组数据在确认前发生变化："
                f"{group.task_name}；"
                f"建议时={group.pdb_count}；"
                f"当前={current_count}"
            )

        target = resolve_task_bundle(
            workspace_dir=workspace,
            task_name=group.task_name,
        )

        if target.exists():
            raise DatasetGroupTaskError(
                "目标任务已经存在，未创建任何任务："
                f"{target}"
            )

        targets.append((group, target))

    created_targets: list[Path] = []

    try:
        for group, target in targets:
            session = build_group_planning_session(
                group=group,
                artifact=artifact,
            )

            prepared = save_incomplete_session(
                session=session,
                bundle_dir=target,
            )
            created_targets.append(target)

            record_path = (
                target / "group_task_source.json"
            )

            record = {
                "schema_version": "0.1",
                "status": (
                    "PLANNING_INITIALIZED_FROM_GROUPING"
                ),
                "created_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "task_name": group.task_name,
                "planning_project_name": (
                    session.request.project_name
                ),
                "input_directory": str(
                    group.input_directory.resolve()
                ),
                "source_relative_path": (
                    group.source_relative_path
                ),
                "pdb_count": group.pdb_count,
                "recursive": group.recursive,
                "reason": group.reason,
                "source_bundle": str(
                    source_bundle.resolve()
                ),
                "planning_session": str(
                    prepared.planning_session
                ),
                "prepare_manifest": str(
                    prepared.prepare_manifest
                ),
                "planning_status": prepared.status,
                "missing_information": (
                    prepared.missing_information
                ),
                "approval_created": False,
                "workflow_executed": False,
            }

            write_json_atomically(
                record_path,
                record,
            )

    except Exception as exc:
        # 目标均在写入前确认不存在，因此只回滚本轮创建目录。
        for target in reversed(created_targets):
            try:
                shutil.rmtree(target)
            except OSError:
                pass

        if isinstance(
            exc,
            DatasetGroupTaskError,
        ):
            raise

        raise DatasetGroupTaskError(
            f"创建分组规划任务失败：{exc}"
        ) from exc

    return GroupTaskCreationResult(
        workspace_directory=workspace,
        created_bundles=[
            target
            for _group, target in targets
        ],
        task_names=[
            group.task_name
            for group, _target in targets
        ],
    )
