#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
确定性构建 PlanningSession。

本模块不负责自然语言理解、不调用模型 Provider，
只把已经验证的 UserRequest 转换为 PDA 的规划会话。
"""

from __future__ import annotations

from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)


def build_planning_session(
    *,
    request: UserRequest,
    provider_name: str,
) -> PlanningSession:
    """从合法 UserRequest 确定性构建 PlanningSession。"""
    explicit_fields = sorted(
        field_name
        for field_name in request.model_fields_set
        if field_name != "raw_text"
    )

    return PlanningSession(
        provider_name=provider_name,
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=explicit_fields,
    )
