#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
框架无关的 PDA Tool API。

本模块只暴露稳定、受控的应用能力。
它不依赖 Chat runtime、模型 Provider 或 legacy intent router。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from protein_design_agent.agent.plan_materializer import (
    load_planning_session,
)
from protein_design_agent.agent.run_status import (
    RunStatusError,
    RunStatusReport,
    inspect_run_status,
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


class ToolAPIError(RuntimeError):
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
