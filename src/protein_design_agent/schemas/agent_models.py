#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local Agent v0.1 的公共数据接口。

UserRequest：
    大模型从自然语言中提取出的结构化需求。
    允许字段缺失，但绝不允许大模型用猜测填充科学参数。

AgentPlan：
    Agent 根据 UserRequest 生成的安全执行计划。
    v0.1 只能准备计划，不能自动执行科学工作流。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from protein_design_agent.schemas.project_config import (
    InputLayout,
    RegionFilter,
    RegionPolicy,
)


TaskType = Literal[
    "prepare_backbone_ranking",
]

PlanStatus = Literal[
    "NEEDS_INFORMATION",
    "READY_FOR_REVIEW",
    "BLOCKED",
]

PlanStepStatus = Literal[
    "PENDING",
    "READY",
    "BLOCKED",
]


class UserRequest(BaseModel):
    """
    从用户自然语言中解析出的需求。

    这里允许 None，因为用户可能没有提供完整信息。
    缺少的信息必须由 Agent 明确询问，不能自行猜测。
    """

    raw_text: str = Field(
        min_length=1,
        description="用户原始自然语言请求。",
    )

    task_type: TaskType = "prepare_backbone_ranking"

    project_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )

    input_dir: Path | None = None
    input_layout: InputLayout | None = None

    # 已经正确分链的数据。
    binder_chain: str | None = None
    target_chains: list[str] = Field(
        default_factory=list
    )

    # target 和 binder 拼在同一条链的数据。
    source_chain: str | None = None
    target_residue_count: int | None = Field(
        default=None,
        ge=1,
    )
    target_start_residue: int = 1

    normalized_target_chain: str = "A"
    normalized_binder_chain: str = "B"

    desired_regions: list[str] = Field(
        default_factory=list
    )
    undesired_regions: list[str] = Field(
        default_factory=list
    )
    hotspots: list[str] = Field(
        default_factory=list
    )

    region_policy: RegionPolicy = "diagnostic"
    region_filter: RegionFilter = "off"

    requested_top_k: int = Field(
        default=30,
        ge=1,
    )

    # 这里只记录用户是否提出执行要求。
    # 是否真的允许执行，由 AgentPlan 决定。
    execute_requested: bool = False

    def required_missing_fields(self) -> list[str]:
        """
        返回当前请求缺少的必要信息。

        注意：
        这里只检查确定性必填字段，
        不根据文件内容或生物学常识进行猜测。
        """
        missing: list[str] = []

        if self.input_dir is None:
            missing.append("input_dir")

        if self.input_layout is None:
            missing.append("input_layout")
            return missing

        if self.input_layout == "existing_chains":
            if not self.binder_chain:
                missing.append("binder_chain")

        if self.input_layout == "concatenated_single_chain":
            if not self.source_chain:
                missing.append("source_chain")

            if self.target_residue_count is None:
                missing.append("target_residue_count")

            if (
                self.normalized_target_chain
                == self.normalized_binder_chain
            ):
                missing.append(
                    "distinct_normalized_chain_ids"
                )

        if self.region_policy == "constraint":
            if not self.desired_regions and not self.hotspots:
                missing.append(
                    "desired_regions_or_hotspots"
                )

            if self.region_filter == "off":
                missing.append(
                    "region_filter_soft_or_strict"
                )

        return missing


class PlanStep(BaseModel):
    """Agent 计划中的一个确定性步骤。"""

    step_id: str = Field(
        pattern=r"^[A-Za-z0-9_.-]+$"
    )
    tool_name: str
    description: str

    requires_approval: bool = False
    status: PlanStepStatus = "PENDING"


class AgentPlan(BaseModel):
    """
    Local Agent v0.1 的执行计划。

    v0.1 是 plan-only：
    允许生成配置和工作流计划，
    不允许自动执行 Ranker 或远程任务。
    """

    schema_version: str = "0.1"
    status: PlanStatus

    request: UserRequest

    missing_information: list[str] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(
        default_factory=list
    )
    steps: list[PlanStep] = Field(
        default_factory=list
    )

    config_preview: dict[str, Any] | None = None

    # Local Agent v0.1 永远必须是 False。
    execution_allowed: bool = False

    @model_validator(mode="after")
    def validate_plan_state(self) -> "AgentPlan":
        if self.execution_allowed:
            raise ValueError(
                "Local Agent v0.1 只允许生成计划，"
                "execution_allowed 必须为 False"
            )

        required_missing = set(
            self.request.required_missing_fields()
        )
        declared_missing = set(
            self.missing_information
        )

        if not required_missing.issubset(
            declared_missing
        ):
            undeclared = sorted(
                required_missing - declared_missing
            )
            raise ValueError(
                "AgentPlan 未声明请求中缺失的信息："
                f"{undeclared}"
            )

        if (
            self.status == "READY_FOR_REVIEW"
            and self.missing_information
        ):
            raise ValueError(
                "存在 missing_information 时，"
                "状态不能是 READY_FOR_REVIEW"
            )

        if (
            self.status == "NEEDS_INFORMATION"
            and not self.missing_information
        ):
            raise ValueError(
                "NEEDS_INFORMATION 状态必须说明"
                "具体缺少什么信息"
            )

        if (
            self.status == "READY_FOR_REVIEW"
            and self.config_preview is None
        ):
            raise ValueError(
                "READY_FOR_REVIEW 状态必须包含"
                "config_preview"
            )

        return self
