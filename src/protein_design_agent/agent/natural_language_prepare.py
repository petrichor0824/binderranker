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
    if not bundle_dir.exists():
        return

    if any(bundle_dir.iterdir()):
        raise ValueError(
            f"任务目录已经存在且非空，禁止覆盖："
            f"{bundle_dir}"
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
    保存信息不完整的规划会话。

    不生成项目 YAML，不检查 PDB，也不启动科学工作流。
    """
    bundle_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    session_path = (
        bundle_dir / "planning_session.json"
    )
    manifest_path = (
        bundle_dir / "agent_prepare_manifest.json"
    )

    session_path.write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "0.1",
        "status": "NEEDS_INFORMATION",
        "provider_name": session.provider_name,
        "bundle_directory": str(bundle_dir),
        "planning_session": str(session_path),
        "missing_information": (
            session.plan.missing_information
        ),
        "warnings": session.plan.warnings,
        "scientific_workflow_executed": False,
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    write_json(
        manifest_path,
        manifest,
    )

    return NaturalLanguagePrepareResult(
        status="NEEDS_INFORMATION",
        provider_name=session.provider_name,
        bundle_directory=bundle_dir,
        planning_session=session_path,
        prepare_manifest=manifest_path,
        missing_information=(
            session.plan.missing_information
        ),
        warnings=session.plan.warnings,
        scientific_workflow_executed=False,
        binderranker_executed=False,
        remote_backend_used=False,
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
        scientific_workflow_executed=True,
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
        raise ValueError("用户请求不能为空")

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
        raise ValueError(
            "当前自然语言准备流程只支持 "
            "NEEDS_INFORMATION 或 READY_FOR_REVIEW；"
            f"实际状态为 {session.plan.status}"
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
