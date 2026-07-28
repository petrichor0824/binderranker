#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
安全续接 NEEDS_INFORMATION 规划会话。

本模块只负责：
1. 读取旧规划会话；
2. 从补充文本提取显式字段；
3. 确定性合并并拒绝冲突；
4. 重新生成 AgentPlan；
5. 仍缺信息时原子更新；
6. 信息完整时安全晋升为 READY_FOR_REVIEW。

本模块不会执行 BinderRanker，也不会连接远程后端。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from protein_design_agent.agent.orchestrator import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.prepare_pipeline import (
    PreparedAgentRun,
    load_planning_session,
    prepare_agent_run,
)
from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


WorkflowRunner = Callable[
    [list[str], Path, Path],
    int,
]


class ResumePlanningError(RuntimeError):
    """规划会话续接失败。"""


class UserRequestPatch(BaseModel):
    """
    本轮补充文本中明确出现的字段。

    所有字段默认 None，模型必须省略未提及字段。
    不允许模型修改 raw_text、task_type，
    也不允许通过补充文本直接批准执行。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    project_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )

    input_dir: Path | None = None

    input_layout: (
        Literal[
            "existing_chains",
            "concatenated_single_chain",
        ]
        | None
    ) = None

    binder_chain: str | None = None
    target_chains: list[str] | None = None

    source_chain: str | None = None
    target_residue_count: int | None = Field(
        default=None,
        ge=1,
    )
    target_start_residue: int | None = Field(
        default=None,
        ge=1,
    )

    normalized_target_chain: str | None = None
    normalized_binder_chain: str | None = None

    desired_regions: list[str] | None = None
    undesired_regions: list[str] | None = None
    hotspots: list[str] | None = None

    region_policy: (
        Literal[
            "off",
            "diagnostic",
            "weak",
            "constraint",
        ]
        | None
    ) = None

    region_filter: (
        Literal[
            "off",
            "soft",
            "strict",
        ]
        | None
    ) = None

    requested_top_k: int | None = Field(
        default=None,
        ge=1,
    )


class SupplementExtraction(BaseModel):
    """模型对本轮补充文本的结构化提取。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    patch: UserRequestPatch
    notes: list[str] = Field(
        default_factory=list
    )


class ResumePlanningResult(BaseModel):
    """一次规划续接的公开返回结果。"""

    schema_version: str = "0.1"

    status: Literal[
        "NEEDS_INFORMATION",
        "READY_FOR_REVIEW",
    ]

    provider_name: str
    bundle_directory: Path

    planning_session: Path
    prepare_manifest: Path
    history_record: Path

    missing_information: list[str] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(
        default_factory=list
    )

    project_name: str | None = None
    project_config: Path | None = None
    workflow_directory: Path | None = None
    workflow_manifest: Path | None = None

    scientific_workflow_executed: bool = False
    binderranker_executed: bool = False
    remote_backend_used: bool = False


MISSING_FIELD_OVERRIDE_MAP: dict[
    str,
    set[str],
] = {
    "input_dir": {
        "input_dir",
    },
    "input_layout": {
        "input_layout",
    },
    "binder_chain": {
        "binder_chain",
    },
    "source_chain": {
        "source_chain",
    },
    "target_residue_count": {
        "target_residue_count",
    },
    "distinct_normalized_chain_ids": {
        "normalized_target_chain",
        "normalized_binder_chain",
    },
    "desired_regions_or_hotspots": {
        "desired_regions",
        "hotspots",
    },
    "region_filter_soft_or_strict": {
        "region_filter",
    },
}


ALLOWED_INCOMPLETE_BUNDLE_ITEMS = {
    "planning_session.json",
    "agent_prepare_manifest.json",
    "history",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(
    path: Path,
    content: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_bytes_atomically(
    path: Path,
    content: bytes,
) -> None:
    """在同一目录中写临时文件后原子替换。"""
    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )

    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True
        )


def validate_incomplete_bundle(
    bundle_dir: Path,
) -> tuple[Path, Path, PlanningSession]:
    """验证该目录确实是可续接的不完整任务。"""
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ResumePlanningError(
            f"任务目录不存在：{bundle}"
        )

    unknown_items = sorted(
        item.name
        for item in bundle.iterdir()
        if item.name
        not in ALLOWED_INCOMPLETE_BUNDLE_ITEMS
    )

    if unknown_items:
        raise ResumePlanningError(
            "任务目录包含不属于不完整规划会话的内容，"
            "为避免覆盖正式任务，拒绝续接："
            + ", ".join(unknown_items)
        )

    session_path = (
        bundle / "planning_session.json"
    )
    manifest_path = (
        bundle / "agent_prepare_manifest.json"
    )

    if not session_path.is_file():
        raise ResumePlanningError(
            f"缺少规划会话：{session_path}"
        )

    if not manifest_path.is_file():
        raise ResumePlanningError(
            f"缺少准备清单：{manifest_path}"
        )

    try:
        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise ResumePlanningError(
            f"无法读取准备清单：{exc}"
        ) from exc

    if not isinstance(manifest, dict):
        raise ResumePlanningError(
            "准备清单必须是 JSON 对象"
        )

    if manifest.get("status") != (
        "NEEDS_INFORMATION"
    ):
        raise ResumePlanningError(
            "只有 NEEDS_INFORMATION 任务"
            "可以续接；当前准备清单状态为 "
            f"{manifest.get('status')!r}"
        )

    try:
        session = load_planning_session(
            session_path
        )
    except ValueError as exc:
        raise ResumePlanningError(
            str(exc)
        ) from exc

    if session.plan.status != (
        "NEEDS_INFORMATION"
    ):
        raise ResumePlanningError(
            "规划会话本身不是 "
            "NEEDS_INFORMATION 状态"
        )

    if session.request_explicit_fields is None:
        raise ResumePlanningError(
            "该任务来自旧版规划会话，"
            "没有字段来源记录，不能安全续接。"
            "请保留该目录作为历史记录，"
            "并使用新的 bundle 重新开始。"
        )

    return (
        session_path,
        manifest_path,
        session,
    )


def extract_supplement_patch(
    *,
    provider: StructuredJSONProvider,
    supplement_text: str,
    session: PlanningSession,
) -> SupplementExtraction:
    """让模型只提取本轮明确给出的补充字段。"""
    clean_text = supplement_text.strip()

    if not clean_text:
        raise ResumePlanningError(
            "补充文本不能为空"
        )

    schema = (
        SupplementExtraction.model_json_schema()
    )

    current_request = (
        session.request.model_dump(
            mode="json"
        )
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是蛋白设计任务的受控参数补充解析器。"
                "只提取用户在本轮补充文本中明确给出的字段。"
                "不得根据生物学常识、文件名或旧值猜测。"
                "未提及字段必须省略，不要输出 null。"
                "不得输出 raw_text、task_type、"
                "execute_requested 或任何 Shell 命令。"
                "输出必须严格符合给定 JSON Schema。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_request": (
                        current_request
                    ),
                    "currently_missing": (
                        session.plan
                        .missing_information
                    ),
                    "supplement_text": (
                        clean_text
                    ),
                    "required_schema": schema,
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]

    try:
        payload = provider.generate_json(
            messages
        )
    except Exception as exc:
        raise ResumePlanningError(
            f"补充信息模型解析失败：{exc}"
        ) from exc

    try:
        return SupplementExtraction.model_validate(
            payload
        )
    except ValidationError as exc:
        raise ResumePlanningError(
            "补充信息没有通过结构验证：\n"
            f"{exc}"
        ) from exc


def is_empty_value(value: Any) -> bool:
    return (
        value is None
        or value == ""
        or value == []
    )


def normalized_value(value: Any) -> Any:
    """仅用于确定性相等判断。"""
    if isinstance(value, Path):
        return value.expanduser().resolve()

    if isinstance(value, list):
        return tuple(value)

    return value


def allowed_override_fields(
    missing_information: list[str],
) -> set[str]:
    allowed: set[str] = set()

    for missing in missing_information:
        allowed.update(
            MISSING_FIELD_OVERRIDE_MAP.get(
                missing,
                set(),
            )
        )

    return allowed


def merge_request_patch(
    *,
    old_request: UserRequest,
    old_missing_information: list[str],
    old_explicit_fields: set[str],
    patch: UserRequestPatch,
    supplement_text: str,
) -> tuple[UserRequest, list[str]]:
    """
    只填补空字段或当前明确缺失字段。

    非空且已确认字段不能被本轮补充静默修改。
    """
    merged = old_request.model_dump(
        mode="python"
    )

    overrides = allowed_override_fields(
        old_missing_information
    )

    accepted_fields: list[str] = []
    conflicts: list[str] = []

    for field_name in sorted(
        patch.model_fields_set
    ):
        new_value = getattr(
            patch,
            field_name
        )

        if new_value is None:
            continue

        old_value = getattr(
            old_request,
            field_name
        )

        if (
            normalized_value(old_value)
            == normalized_value(new_value)
        ):
            continue

        if (
            field_name not in old_explicit_fields
            or field_name in overrides
            or is_empty_value(old_value)
        ):
            merged[field_name] = new_value
            accepted_fields.append(
                field_name
            )
            continue

        conflicts.append(
            (
                f"{field_name}: "
                f"旧值={old_value!r}, "
                f"补充值={new_value!r}"
            )
        )

    if conflicts:
        raise ResumePlanningError(
            "补充内容试图修改已经确认的字段；"
            "当前版本不允许静默覆盖：\n- "
            + "\n- ".join(conflicts)
        )

    if not accepted_fields:
        raise ResumePlanningError(
            "补充文本没有提供新的可用字段。"
            "请回答当前缺失的问题；"
            "修改已确认参数需要重新建立任务。"
        )

    merged["raw_text"] = (
        old_request.raw_text.rstrip()
        + "\n\n[补充信息]\n"
        + supplement_text.strip()
    )

    try:
        request = UserRequest.model_validate(
            merged
        )
    except ValidationError as exc:
        raise ResumePlanningError(
            "合并后的用户请求无法通过结构验证：\n"
            f"{exc}"
        ) from exc

    return request, accepted_fields


def next_history_directory(
    history_root: Path,
) -> Path:
    history_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    indexes: list[int] = []

    for path in history_root.glob(
        "resume_*"
    ):
        suffix = path.name.removeprefix(
            "resume_"
        )

        if suffix.isdigit():
            indexes.append(int(suffix))

    next_index = (
        max(indexes, default=0) + 1
    )

    return (
        history_root
        / f"resume_{next_index:04d}"
    )


def save_history_record(
    *,
    destination_bundle: Path,
    previous_bundle: Path,
    supplement_text: str,
    extraction: SupplementExtraction,
    merged_session: PlanningSession,
    accepted_fields: list[str],
) -> Path:
    """保存本轮续接的完整审计记录。"""
    history_directory = (
        next_history_directory(
            destination_bundle / "history"
        )
    )

    history_directory.mkdir(
        parents=False,
        exist_ok=False,
    )

    previous_session = (
        previous_bundle
        / "planning_session.json"
    )
    previous_manifest = (
        previous_bundle
        / "agent_prepare_manifest.json"
    )

    shutil.copy2(
        previous_session,
        history_directory
        / "previous_planning_session.json",
    )

    shutil.copy2(
        previous_manifest,
        history_directory
        / "previous_prepare_manifest.json",
    )

    (
        history_directory / "supplement.txt"
    ).write_text(
        supplement_text.strip() + "\n",
        encoding="utf-8",
    )

    write_json(
        history_directory
        / "supplement_extraction.json",
        extraction.model_dump(
            mode="json",
            exclude_none=True,
        ),
    )

    (
        history_directory
        / "merged_planning_session.json"
    ).write_text(
        merged_session.model_dump_json(
            indent=2
        )
        + "\n",
        encoding="utf-8",
    )

    write_json(
        history_directory
        / "resume_record.json",
        {
            "schema_version": "0.1",
            "status": (
                merged_session.plan.status
            ),
            "provider_name": (
                merged_session.provider_name
            ),
            "accepted_fields": (
                accepted_fields
            ),
            "missing_information": (
                merged_session.plan
                .missing_information
            ),
            "binderranker_executed": False,
            "remote_backend_used": False,
        },
    )

    return history_directory


def update_incomplete_bundle(
    *,
    bundle_dir: Path,
    previous_session_path: Path,
    previous_manifest_path: Path,
    merged_session: PlanningSession,
    supplement_text: str,
    extraction: SupplementExtraction,
    accepted_fields: list[str],
) -> ResumePlanningResult:
    """原子更新仍然缺少信息的会话。"""
    old_session_bytes = (
        previous_session_path.read_bytes()
    )
    old_manifest_bytes = (
        previous_manifest_path.read_bytes()
    )

    history_record = save_history_record(
        destination_bundle=bundle_dir,
        previous_bundle=bundle_dir,
        supplement_text=supplement_text,
        extraction=extraction,
        merged_session=merged_session,
        accepted_fields=accepted_fields,
    )

    session_bytes = (
        merged_session.model_dump_json(
            indent=2
        )
        + "\n"
    ).encode("utf-8")

    manifest = {
        "schema_version": "0.2",
        "status": "NEEDS_INFORMATION",
        "provider_name": (
            merged_session.provider_name
        ),
        "bundle_directory": str(
            bundle_dir
        ),
        "planning_session": str(
            previous_session_path
        ),
        "planning_session_sha256": (
            sha256_bytes(session_bytes)
        ),
        "missing_information": (
            merged_session.plan
            .missing_information
        ),
        "warnings": (
            merged_session.plan.warnings
        ),
        "scientific_workflow_executed": False,
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    try:
        write_bytes_atomically(
            previous_session_path,
            session_bytes,
        )

        write_bytes_atomically(
            previous_manifest_path,
            manifest_bytes,
        )

    except BaseException:
        write_bytes_atomically(
            previous_session_path,
            old_session_bytes,
        )

        write_bytes_atomically(
            previous_manifest_path,
            old_manifest_bytes,
        )

        raise

    return ResumePlanningResult(
        status="NEEDS_INFORMATION",
        provider_name=(
            merged_session.provider_name
        ),
        bundle_directory=bundle_dir,
        planning_session=(
            previous_session_path
        ),
        prepare_manifest=(
            previous_manifest_path
        ),
        history_record=history_record,
        missing_information=(
            merged_session.plan
            .missing_information
        ),
        warnings=(
            merged_session.plan.warnings
        ),
        scientific_workflow_executed=False,
        binderranker_executed=False,
        remote_backend_used=False,
    )


def promote_to_ready_for_review(
    *,
    bundle_dir: Path,
    merged_session: PlanningSession,
    supplement_text: str,
    extraction: SupplementExtraction,
    accepted_fields: list[str],
    runner: WorkflowRunner | None,
) -> ResumePlanningResult:
    """
    先暂存旧 bundle，再使用原路径进行完整 prepare。

    因 prepare 清单记录绝对路径，不能在 staging 路径中
    prepare 后直接改名；必须让 prepare 从一开始就在最终路径运行。
    """
    parent = bundle_dir.parent

    transaction_id = uuid.uuid4().hex

    backup_bundle = (
        parent
        / (
            f".{bundle_dir.name}."
            f"resume-backup.{transaction_id}"
        )
    )

    if backup_bundle.exists():
        raise ResumePlanningError(
            f"事务备份目录意外存在：{backup_bundle}"
        )

    with tempfile.TemporaryDirectory(
        prefix="protein-design-resume-",
        dir=parent,
    ) as temporary_directory:
        temporary_session = (
            Path(temporary_directory)
            / "planning_session.json"
        )

        temporary_session.write_text(
            merged_session.model_dump_json(
                indent=2
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            bundle_dir,
            backup_bundle,
        )

        try:
            prepared = prepare_agent_run(
                session_path=temporary_session,
                bundle_dir=bundle_dir,
                runner=runner,
            )

            previous_history = (
                backup_bundle / "history"
            )

            if previous_history.is_dir():
                shutil.copytree(
                    previous_history,
                    bundle_dir / "history",
                    dirs_exist_ok=True,
                )

            history_record = save_history_record(
                destination_bundle=bundle_dir,
                previous_bundle=backup_bundle,
                supplement_text=(
                    supplement_text
                ),
                extraction=extraction,
                merged_session=merged_session,
                accepted_fields=accepted_fields,
            )

        except BaseException as exc:
            if bundle_dir.exists():
                shutil.rmtree(
                    bundle_dir,
                    ignore_errors=True,
                )

            os.replace(
                backup_bundle,
                bundle_dir,
            )

            if isinstance(
                exc,
                ResumePlanningError,
            ):
                raise

            raise ResumePlanningError(
                "完整准备失败，原不完整任务已恢复："
                f"{exc}"
            ) from exc

        else:
            shutil.rmtree(
                backup_bundle
            )

    return ResumePlanningResult(
        status="READY_FOR_REVIEW",
        provider_name=prepared.provider_name,
        bundle_directory=(
            prepared.bundle_directory
        ),
        planning_session=(
            prepared.session_copy
        ),
        prepare_manifest=(
            prepared.prepare_manifest
        ),
        history_record=history_record,
        missing_information=[],
        warnings=(
            merged_session.plan.warnings
        ),
        project_name=prepared.project_name,
        project_config=prepared.project_config,
        workflow_directory=(
            prepared.workflow_directory
        ),
        workflow_manifest=(
            prepared.workflow_manifest
        ),
        scientific_workflow_executed=True,
        binderranker_executed=False,
        remote_backend_used=False,
    )


def resume_planning_session(
    *,
    bundle_dir: Path,
    supplement_text: str,
    provider: StructuredJSONProvider,
    runner: WorkflowRunner | None = None,
) -> ResumePlanningResult:
    """
    续接一个 NEEDS_INFORMATION 任务。

    该函数不会执行 BinderRanker。
    """
    bundle = bundle_dir.resolve()

    if not isinstance(
        provider,
        StructuredJSONProvider,
    ):
        raise ResumePlanningError(
            "Provider 不支持受控结构化 JSON 生成"
        )

    (
        session_path,
        manifest_path,
        old_session,
    ) = validate_incomplete_bundle(bundle)

    if provider.name != (
        old_session.provider_name
    ):
        raise ResumePlanningError(
            "续接 Provider 与原会话不一致："
            f"原={old_session.provider_name!r}, "
            f"当前={provider.name!r}"
        )

    extraction = extract_supplement_patch(
        provider=provider,
        supplement_text=supplement_text,
        session=old_session,
    )

    merged_request, accepted_fields = (
        merge_request_patch(
            old_request=old_session.request,
            old_missing_information=(
                old_session.plan
                .missing_information
            ),
            old_explicit_fields=set(
                old_session.request_explicit_fields
            ),
            patch=extraction.patch,
            supplement_text=(
                supplement_text
            ),
        )
    )

    merged_plan = build_agent_plan(
        merged_request
    )

    merged_explicit_fields = sorted(
        set(old_session.request_explicit_fields)
        | set(accepted_fields)
    )

    merged_session = PlanningSession(
        provider_name=old_session.provider_name,
        request=merged_request,
        plan=merged_plan,
        request_explicit_fields=(
            merged_explicit_fields
        ),
    )

    if merged_plan.status == (
        "NEEDS_INFORMATION"
    ):
        return update_incomplete_bundle(
            bundle_dir=bundle,
            previous_session_path=(
                session_path
            ),
            previous_manifest_path=(
                manifest_path
            ),
            merged_session=merged_session,
            supplement_text=supplement_text,
            extraction=extraction,
            accepted_fields=accepted_fields,
        )

    if merged_plan.status == (
        "READY_FOR_REVIEW"
    ):
        return promote_to_ready_for_review(
            bundle_dir=bundle,
            merged_session=merged_session,
            supplement_text=supplement_text,
            extraction=extraction,
            accepted_fields=accepted_fields,
            runner=runner,
        )

    raise ResumePlanningError(
        "续接后的计划状态不受支持："
        f"{merged_plan.status}"
    )
