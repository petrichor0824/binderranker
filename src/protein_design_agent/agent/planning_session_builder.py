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
from protein_design_agent.agent.request_evidence import (
    RequestExtraction,
    validate_request_evidence,
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


def build_planning_session_from_extraction(
    *,
    raw_text: str,
    extraction: RequestExtraction,
    provider_name: str,
) -> PlanningSession:
    """
    从带用户原文证据的结构化请求构建 PlanningSession。

    模型提供的结构化字段必须先通过确定性 evidence 校验；
    未在 patch 中显式提供的 UserRequest 字段使用领域默认值。
    """
    clean_text = raw_text.strip()

    if not clean_text:
        raise ValueError(
            "用户请求不能为空"
        )

    validate_request_evidence(
        extraction=extraction,
        evidence_text=clean_text,
    )

    explicit_data = extraction.patch.model_dump(
        mode="python",
        exclude_unset=True,
        exclude_none=True,
    )

    request = UserRequest(
        raw_text=clean_text,
        **explicit_data,
    )

    return build_planning_session(
        request=request,
        provider_name=provider_name,
    )
