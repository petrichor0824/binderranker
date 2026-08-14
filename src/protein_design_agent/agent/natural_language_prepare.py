#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
从自然语言直接准备一个可审核的蛋白骨架排名任务。

流程：

用户自然语言
    ↓
模型 Provider
    ↓
UserRequest
    ↓
确定性 Planner
    ↓
PlanningSession
    ↓
若信息不足：保存会话并停止
若信息完整：生成项目配置并运行准备工作流
    ↓
READY_FOR_REVIEW

安全边界：
- 不真正执行 BinderRanker；
- 不连接远程服务器；
- 不执行任意模型生成的 Shell；
- 默认禁止覆盖已有任务目录。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.prepare_pipeline import (
    PreparedAgentRun,
    WorkflowRunner,
    prepare_agent_run,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)


class NaturalLanguagePreparationError(ValueError):
    """
    自然语言任务准备领域错误。

    继续继承 ValueError 保持现有 API 兼容；
    public_message 只保存可以安全展示的确定事实。
    """

    def __init__(
        self,
        message: str,
        *,
        public_message: str | None = None,
    ) -> None:
        super().__init__(message)

        clean_public_message = (
            public_message.strip()
            if isinstance(public_message, str)
            else None
        )

        self.public_message = (
            clean_public_message
            if clean_public_message
            else None
        )


NaturalLanguagePrepareStatus = Literal[
    "NEEDS_INFORMATION",
    "READY_FOR_REVIEW",
]


class NaturalLanguagePrepareResult(BaseModel):
    """自然语言准备流程的统一结果。"""

    schema_version: str = "0.1"
    status: NaturalLanguagePrepareStatus

    provider_name: str
    bundle_directory: Path
    planning_session: Path
    prepare_manifest: Path

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


def check_bundle_is_available(
    bundle_dir: Path,
) -> None:
    """禁止覆盖非空任务目录。"""
    try:
        if not bundle_dir.exists():
            return

        is_nonempty = any(
            bundle_dir.iterdir()
        )

    except OSError as exc:
        raise NaturalLanguagePreparationError(
            "检查目标任务目录失败："
            f"{exc}",
            public_message=(
                "目标任务目录无法安全检查。"
            ),
        ) from exc

    if is_nonempty:
        raise NaturalLanguagePreparationError(
            f"任务目录已经存在且非空，禁止覆盖："
            f"{bundle_dir}",
            public_message=(
                "目标任务目录已经存在且非空，"
                "默认禁止覆盖。"
            ),
        )


def write_json(
    path: Path,
    content: dict,
) -> None:
    """写入格式化 JSON。"""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def save_incomplete_session(
    *,
    session,
    bundle_dir: Path,
) -> NaturalLanguagePrepareResult:
    """
    原子保存信息不完整的规划会话。

    不生成项目 YAML，不检查 PDB，
    也不启动科学工作流。
    """
    bundle_dir = bundle_dir.resolve()

    staging_dir: Path | None = None
    removed_existing_empty = False

    try:
        # 发布前先确认正式目标不会被覆盖。
        check_bundle_is_available(
            bundle_dir
        )

        bundle_dir.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=(
                    f".{bundle_dir.name}"
                    ".incomplete-preparing-"
                ),
                dir=str(bundle_dir.parent),
            )
        ).resolve()

        staged_session_path = (
            staging_dir
            / "planning_session.json"
        )
        staged_manifest_path = (
            staging_dir
            / "agent_prepare_manifest.json"
        )

        final_session_path = (
            bundle_dir
            / "planning_session.json"
        )
        final_manifest_path = (
            bundle_dir
            / "agent_prepare_manifest.json"
        )

        session_payload = (
            session.model_dump(
                mode="json"
            )
        )

        staged_session_path.write_text(
            session.model_dump_json(
                indent=2
            ),
            encoding="utf-8",
        )

        try:
            reloaded_session = json.loads(
                staged_session_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise NaturalLanguagePreparationError(
                "staging PlanningSession "
                f"验证失败：{exc}",
                public_message=(
                    "规划会话保存后未通过验证，"
                    "因此没有发布正式任务目录。"
                ),
            ) from exc

        if reloaded_session != session_payload:
            raise NaturalLanguagePreparationError(
                "staging PlanningSession "
                "写入前后不一致",
                public_message=(
                    "规划会话保存后未通过"
                    "一致性验证，因此没有发布"
                    "正式任务目录。"
                ),
            )

        manifest = {
            "schema_version": "0.1",
            "status": "NEEDS_INFORMATION",
            "provider_name": session.provider_name,
            "bundle_directory": str(
                bundle_dir
            ),
            "planning_session": str(
                final_session_path
            ),
            "missing_information": (
                session.plan.missing_information
            ),
            "warnings": session.plan.warnings,
            "scientific_workflow_executed": False,
            "binderranker_executed": False,
            "remote_backend_used": False,
        }

        write_json(
            staged_manifest_path,
            manifest,
        )

        try:
            reloaded_manifest = json.loads(
                staged_manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise NaturalLanguagePreparationError(
                "staging Prepare Manifest "
                f"验证失败：{exc}",
                public_message=(
                    "准备记录保存后未通过验证，"
                    "因此没有发布正式任务目录。"
                ),
            ) from exc

        if reloaded_manifest != manifest:
            raise NaturalLanguagePreparationError(
                "staging Prepare Manifest "
                "写入前后不一致",
                public_message=(
                    "准备记录保存后未通过"
                    "一致性验证，因此没有发布"
                    "正式任务目录。"
                ),
            )

        # 在正式发布前先构造最终返回对象。
        result = NaturalLanguagePrepareResult(
            status="NEEDS_INFORMATION",
            provider_name=session.provider_name,
            bundle_directory=bundle_dir,
            planning_session=(
                final_session_path
            ),
            prepare_manifest=(
                final_manifest_path
            ),
            missing_information=(
                session.plan.missing_information
            ),
            warnings=session.plan.warnings,
            scientific_workflow_executed=False,
            binderranker_executed=False,
            remote_backend_used=False,
        )

        # staging 期间正式目录可能发生变化，
        # 发布前必须重新检查。
        check_bundle_is_available(
            bundle_dir
        )

        # 兼容调用方预先创建的空 Bundle。
        if bundle_dir.exists():
            try:
                bundle_dir.rmdir()
            except OSError as exc:
                raise NaturalLanguagePreparationError(
                    "无法移除发布前的空任务目录："
                    f"{exc}",
                    public_message=(
                        "无法安全发布任务记录；"
                        "原任务目录未被覆盖。"
                    ),
                ) from exc

            removed_existing_empty = True

        try:
            os.replace(
                staging_dir,
                bundle_dir,
            )
        except OSError as exc:
            restore_error: OSError | None = None

            if removed_existing_empty:
                try:
                    bundle_dir.mkdir(
                        parents=False,
                        exist_ok=False,
                    )
                except OSError as restore_exc:
                    restore_error = (
                        restore_exc
                    )

            internal_message = (
                "NEEDS_INFORMATION Bundle "
                f"发布失败：{exc}"
            )

            if restore_error is not None:
                internal_message += (
                    "；原空任务目录恢复失败："
                    f"{restore_error}"
                )

            public_message = (
                "任务记录发布失败；"
                "已恢复发布前的任务目录状态。"
                if restore_error is None
                else (
                    "任务记录发布失败，且无法确认"
                    "原任务目录已经恢复。"
                    "请检查目标任务目录后再重试。"
                )
            )

            raise NaturalLanguagePreparationError(
                internal_message,
                public_message=public_message,
            ) from exc

        # staging 已被移动成正式 Bundle。
        staging_dir = None

        return result

    except NaturalLanguagePreparationError:
        raise

    except (
        OSError,
        ValueError,
    ) as exc:
        raise NaturalLanguagePreparationError(
            "保存 NEEDS_INFORMATION "
            f"任务失败：{exc}",
            public_message=(
                "信息不完整的任务记录保存失败；"
                "正式任务目录没有发布。"
            ),
        ) from exc

    finally:
        # 只清理仍未发布的 staging。
        # 清理失败不能掩盖主异常。
        if (
            staging_dir is not None
            and staging_dir.exists()
        ):
            shutil.rmtree(
                staging_dir,
                ignore_errors=True,
            )


def convert_prepared_run(
    prepared: PreparedAgentRun,
) -> NaturalLanguagePrepareResult:
    """将底层准备结果转换成统一公开结果。"""
    return NaturalLanguagePrepareResult(
        status="READY_FOR_REVIEW",
        provider_name=prepared.provider_name,
        bundle_directory=(
            prepared.bundle_directory
        ),
        planning_session=prepared.session_copy,
        prepare_manifest=(
            prepared.prepare_manifest
        ),
        missing_information=[],
        warnings=[],
        project_name=prepared.project_name,
        project_config=prepared.project_config,
        workflow_directory=(
            prepared.workflow_directory
        ),
        workflow_manifest=(
            prepared.workflow_manifest
        ),
        scientific_workflow_executed=False,
        binderranker_executed=False,
        remote_backend_used=False,
    )


def prepare_from_natural_language(
    *,
    raw_text: str,
    provider: RequestParserProvider,
    bundle_dir: Path,
    runner: WorkflowRunner | None = None,
) -> NaturalLanguagePrepareResult:
    """
    使用自然语言准备一个 Agent 任务。

    Provider 可以是云端模型、本地模型或 MockProvider。
    """
    clean_text = raw_text.strip()

    if not clean_text:
        raise NaturalLanguagePreparationError(
            "用户请求不能为空",
            public_message="用户请求不能为空。",
        )

    bundle_dir = bundle_dir.resolve()

    # 在调用模型前先检查目标目录，避免花费 API 后才发现
    # 输出目录无法使用。
    check_bundle_is_available(bundle_dir)

    orchestrator = LocalAgentOrchestrator(
        provider
    )

    session = orchestrator.plan_from_text(
        clean_text
    )

    if session.plan.status == "NEEDS_INFORMATION":
        return save_incomplete_session(
            session=session,
            bundle_dir=bundle_dir,
        )

    if session.plan.status != "READY_FOR_REVIEW":
        raise NaturalLanguagePreparationError(
            "当前自然语言准备流程只支持 "
            "NEEDS_INFORMATION 或 READY_FOR_REVIEW；"
            f"实际状态为 {session.plan.status}",
            public_message=(
                "自然语言规划返回了不支持的"
                "任务状态，准备任务已停止。"
            ),
        )

    # prepare_agent_run 接收一个会话文件。
    # 这里先在系统临时目录中保存，随后它会复制到正式 bundle。
    with tempfile.TemporaryDirectory(
        prefix="protein-design-agent-"
    ) as temporary_directory:
        temporary_session = (
            Path(temporary_directory)
            / "planning_session.json"
        )

        temporary_session.write_text(
            session.model_dump_json(indent=2),
            encoding="utf-8",
        )

        prepared = prepare_agent_run(
            session_path=temporary_session,
            bundle_dir=bundle_dir,
            runner=runner,
        )

    return convert_prepared_run(prepared)
