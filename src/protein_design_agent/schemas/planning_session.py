#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Stable planning-session data contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from protein_design_agent.schemas.agent_models import (
    AgentPlan,
    UserRequest,
)


class PlanningSession(BaseModel):
    """一次自然语言规划会话的完整记录。"""

    schema_version: str = "0.2"

    provider_name: str = Field(
        min_length=1
    )

    request: UserRequest
    plan: AgentPlan

    # Provider 原始结构化结果中真正出现过的字段。
    #
    # None 表示旧版会话没有保存来源信息，不能安全续接；
    # 空列表表示 Provider 没有显式提取任何业务字段。
    request_explicit_fields: list[str] | None = None
