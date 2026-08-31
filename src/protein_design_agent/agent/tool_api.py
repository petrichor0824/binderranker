#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
框架无关的 PDA Tool API。

本模块只暴露稳定、受控的应用能力。
它不依赖 Chat runtime、模型 Provider 或 legacy intent router。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from protein_design_agent.agent.analysis_artifacts import (
    AnalysisArtifactError,
    AnalysisArtifactNotFoundError,
    resolve_analysis_artifacts,
    sha256_file,
)

from protein_design_agent.agent.dataset_advisor import (
    DatasetAdvisorError,
    DatasetPlanningAdvice,
    inspect_dataset_for_planning,
)
from protein_design_agent.agent.analyze_run import (
    AnalyzeRunError,
    AnalyzeRunResult,
    next_analysis_directory,
    run_analyze_run,
)
from protein_design_agent.agent.failure_analysis import (
    FailureAnalysisError,
    load_result_summary,
)
from protein_design_agent.agent.approval import (
    ApprovalError,
    ApprovalRecord,
    create_approval_record,
)
from protein_design_agent.agent.execution_guard import (
    ExecutionGuardError,
)
from protein_design_agent.agent.local_executor import (
    CompletedLocalExecution,
    LocalExecutionError,
    execute_approved_binderranker,
)
from protein_design_agent.agent.ranker_result_parser import (
    RankerResultSummary,
)

from protein_design_agent.agent.plan_materializer import (
    load_planning_session,
)
from protein_design_agent.agent.planning_session_builder import (
    build_planning_session_from_extraction,
)
from protein_design_agent.agent.planning_session_prepare import (
    NaturalLanguagePreparationError,
    NaturalLanguagePrepareResult,
    prepare_planning_session,
)
from protein_design_agent.agent.run_status import (
    RunStatusError,
    RunStatusReport,
    inspect_run_status,
)
from protein_design_agent.agent.request_evidence import (
    RequestEvidenceError,
    RequestExtraction,
)
from protein_design_agent.agent.planning_session_resume import (
    ResumePlanningError,
    ResumePlanningResult,
    SupplementExtraction,
    resume_planning_session_from_extraction,
)
from protein_design_agent.schemas.agent_models import (
    AgentPlan,
)
from protein_design_agent.agent.tool_adapter_errors import (
    AdapterSafeError,
)


class ToolAPIError(AdapterSafeError):
    """PDA Tool API 无法可靠完成请求。"""


class TaskStatusResult(BaseModel):
    """任务规划状态与运行生命周期的结构化只读结果。"""

    schema_version: str = "0.1"

    bundle_dir: Path
    planning_status: str | None = None
    missing_information: list[str] = Field(
        default_factory=list
    )
    planning_session: Path | None = None

    run_status: RunStatusReport


class CurrentPlanResult(BaseModel):
    """当前 PlanningSession 中计划的结构化只读视图。"""

    schema_version: str = "0.1"

    available: bool
    bundle_dir: Path

    planning_session: Path | None = None
    request_explicit_fields: list[str] = Field(
        default_factory=list
    )
    plan: AgentPlan | None = None


class SealedResultSummaryResult(BaseModel):
    """Latest integrity-verified deterministic result summary for one task."""

    schema_version: Literal["0.1"] = "0.1"
    bundle_dir: Path
    analysis_manifest: Path
    result_summary_path: Path
    result_summary_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    provenance_status: Literal["SEALED_VERIFIED"] = "SEALED_VERIFIED"
    summary: RankerResultSummary


def get_current_plan(
    bundle_dir: Path,
) -> CurrentPlanResult:
    """
    读取 canonical PlanningSession 中的当前计划。

    不调用模型，不执行工作流，不修改 Bundle。
    """
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    session_path = (
        bundle / "planning_session.json"
    )

    if not session_path.is_file():
        return CurrentPlanResult(
            available=False,
            bundle_dir=bundle,
        )

    try:
        session = load_planning_session(
            session_path
        )
    except ValueError as exc:
        raise ToolAPIError(
            f"无法读取当前规划会话：{exc}"
        ) from exc

    return CurrentPlanResult(
        available=True,
        bundle_dir=bundle,
        planning_session=(
            session_path.resolve()
        ),
        request_explicit_fields=(
            session.request_explicit_fields
            or []
        ),
        plan=session.plan,
    )


def get_task_status(
    bundle_dir: Path,
) -> TaskStatusResult:
    """
    同时返回规划状态与运行生命周期状态。

    planning_status 与 run_status.current_stage
    是两个独立维度，不互相推断。
    """
    bundle = bundle_dir.resolve()

    try:
        run_status = inspect_run_status(
            bundle
        )
    except RunStatusError as exc:
        raise ToolAPIError(
            str(exc)
        ) from exc

    current_plan = get_current_plan(
        bundle
    )

    planning_status = None
    missing_information: list[str] = []

    if current_plan.plan is not None:
        planning_status = (
            current_plan.plan.status
        )
        missing_information = list(
            current_plan.plan
            .missing_information
        )

    return TaskStatusResult(
        bundle_dir=bundle,
        planning_status=planning_status,
        missing_information=(
            missing_information
        ),
        planning_session=(
            current_plan.planning_session
        ),
        run_status=run_status,
    )


def get_result_summary(
    bundle_dir: Path,
) -> SealedResultSummaryResult:
    """Read the latest sealed deterministic analysis without modifying it.

    Legacy or explicit unsealed artifacts are intentionally rejected at this
    external-integration boundary. Callers must create a current deterministic
    analysis first so provenance and artifact integrity can be verified.
    """

    bundle = bundle_dir.resolve()
    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    try:
        artifacts = resolve_analysis_artifacts(
            bundle_dir=bundle,
        )
    except AnalysisArtifactNotFoundError as exc:
        raise ToolAPIError(
            "当前任务尚无可读取的完整确定性分析。"
        ) from exc
    except AnalysisArtifactError as exc:
        raise ToolAPIError(
            "确定性分析产物未通过完整性验证。",
            adapter_error_code="SCIENTIFIC_RESULT_INVALID",
        ) from exc

    if (
        artifacts.provenance_status != "SEALED_VERIFIED"
        or artifacts.analysis_manifest_path is None
    ):
        raise ToolAPIError(
            "当前结果摘要没有完整 provenance seal；"
            "请先生成当前版本的确定性分析。"
        )

    try:
        summary = load_result_summary(
            artifacts.result_summary_path
        )
    except FailureAnalysisError as exc:
        raise ToolAPIError(
            "已封存结果摘要未通过结构化科学验证。",
            adapter_error_code="SCIENTIFIC_RESULT_INVALID",
        ) from exc

    return SealedResultSummaryResult(
        bundle_dir=bundle,
        analysis_manifest=(
            artifacts.analysis_manifest_path
        ),
        result_summary_path=(
            artifacts.result_summary_path
        ),
        result_summary_sha256=sha256_file(
            artifacts.result_summary_path
        ),
        summary=summary,
    )


def provide_information(
    *,
    bundle_dir: Path,
    supplement_text: str,
    extraction: SupplementExtraction,
) -> ResumePlanningResult:
    """
    使用经过结构化提取的用户补充信息续接任务。

    Tool API 不自行合并、重规划或持久化；
    所有业务校验与状态变更均委托给稳定 resume core。
    """
    try:
        return resume_planning_session_from_extraction(
            bundle_dir=bundle_dir,
            supplement_text=supplement_text,
            extraction=extraction,
        )
    except ResumePlanningError as exc:
        raise ToolAPIError(
            f"无法应用补充信息：{exc}"
        ) from exc


def prepare_task(
    *,
    bundle_dir: Path,
    raw_text: str,
    extraction: RequestExtraction,
    provider_name: str,
) -> NaturalLanguagePrepareResult:
    """
    从带可信用户原文证据的首次请求创建任务。

    Tool API 不负责自然语言理解，也不自行构造计划；
    它只串联 trusted PlanningSession builder 与
    deterministic preparation service。
    """
    try:
        session = (
            build_planning_session_from_extraction(
                raw_text=raw_text,
                extraction=extraction,
                provider_name=provider_name,
            )
        )

        return prepare_planning_session(
            session=session,
            bundle_dir=bundle_dir,
        )

    except (
        RequestEvidenceError,
        NaturalLanguagePreparationError,
        ValueError,
    ) as exc:
        raise ToolAPIError(
            f"无法准备任务：{exc}"
        ) from exc


def inspect_dataset(
    *,
    bundle_dir: Path,
) -> DatasetPlanningAdvice:
    """
    只读检查当前任务 PlanningSession 所记录的 PDB 数据集。

    input_dir 由 trusted PlanningSession 决定；
    Tool 调用方不能临时指定其他数据目录。
    """
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    session_path = (
        bundle / "planning_session.json"
    )

    if not session_path.is_file():
        raise ToolAPIError(
            "当前任务缺少 planning_session.json"
        )

    try:
        session = load_planning_session(
            session_path
        )
    except ValueError as exc:
        raise ToolAPIError(
            f"无法读取当前规划会话：{exc}"
        ) from exc

    input_dir = session.request.input_dir

    if input_dir is None:
        raise ToolAPIError(
            "当前任务尚未提供 input_dir，"
            "无法检查 PDB 数据集。"
        )

    try:
        return inspect_dataset_for_planning(
            input_dir=input_dir,
            recursive=False,
        )
    except DatasetAdvisorError as exc:
        raise ToolAPIError(
            f"无法检查当前数据集：{exc}"
        ) from exc


def request_approval(
    *,
    bundle_dir: Path,
    approved_by: str,
    approval_confirmed: bool = False,
    approval_note: str = "",
    acknowledge_smoke_test: bool = False,
) -> ApprovalRecord:
    """
    为当前任务创建一次性 BinderRanker 执行批准。

    approval_confirmed 是可信 runtime 提供的授权事实，
    不能由模型自行推断为 True。
    """
    if not approval_confirmed:
        raise ToolAPIError(
            "必须由用户明确确认批准，"
            "才能创建 BinderRanker 执行批准记录。"
        )

    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    prepare_manifest = (
        bundle / "agent_prepare_manifest.json"
    )
    approval_path = (
        bundle / "approval.json"
    )

    try:
        return create_approval_record(
            prepare_manifest_path=prepare_manifest,
            output_path=approval_path,
            approved_by=approved_by,
            approval_note=approval_note,
            acknowledge_smoke_test=(
                acknowledge_smoke_test
            ),
        )
    except ApprovalError as exc:
        public_message = (
            exc.public_message
            or "任务批准未完成。"
        )

        raise ToolAPIError(
            public_message
        ) from exc


def execute_ranker(
    *,
    bundle_dir: Path,
    execution_confirmed: bool = False,
) -> CompletedLocalExecution:
    """
    使用当前任务的一次性批准执行 BinderRanker。

    execution_confirmed 是独立于计划批准的第二次
    runtime 用户确认。完整 execution guard 由
    local executor 内部负责。
    """
    if not execution_confirmed:
        raise ToolAPIError(
            "必须由用户明确确认执行，"
            "才能运行 BinderRanker。"
        )

    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    approval_path = (
        bundle / "approval.json"
    )

    if not approval_path.is_file():
        raise ToolAPIError(
            "当前任务尚无 approval.json，"
            "请先批准计划。"
        )

    try:
        return execute_approved_binderranker(
            approval_path=approval_path,
            confirm_execute=True,
        )
    except ExecutionGuardError as exc:
        raise ToolAPIError(
            f"BinderRanker 执行前安全检查未通过：{exc}"
        ) from exc
    except LocalExecutionError as exc:
        public_message = (
            exc.public_message
            or "BinderRanker 执行未完成。"
        )

        raise ToolAPIError(
            public_message,
            adapter_error_code="EXECUTION_FAILED",
        ) from exc


def analyze_results(
    *,
    bundle_dir: Path,
) -> AnalyzeRunResult:
    """
    对当前任务已完成的 BinderRanker 结果执行确定性分析。

    本 Tool：
    - 不调用模型；
    - 不允许调用方指定分析目录；
    - 不允许覆盖历史分析；
    - 不执行 BinderRanker。
    """
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ToolAPIError(
            f"任务目录不存在：{bundle}"
        )

    analysis_dir = next_analysis_directory(
        bundle_dir=bundle,
        prefix="tool_deterministic",
    )

    try:
        return run_analyze_run(
            bundle_dir=bundle,
            analysis_dir=analysis_dir,
            with_model=False,
        )
    except AnalyzeRunError as exc:
        raise ToolAPIError(
            f"BinderRanker 结果分析未完成：{exc}"
        ) from exc
