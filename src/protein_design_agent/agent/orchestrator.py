#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local Agent v0.1 的总调度器。

职责：
1. 接收用户自然语言；
2. 调用可替换的 Provider；
3. 获得经过验证的 UserRequest；
4. 调用确定性 Planner；
5. 返回可审核的 AgentPlan。

v0.1 不执行 Ranker，不连接服务器，不运行任意 Shell。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)
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


class LocalAgentOrchestrator:
    """
    Local Agent v0.1 总调度器。

    Provider 可替换，但 Planner 和安全规则保持不变。
    """

    def __init__(
        self,
        provider: RequestParserProvider,
    ) -> None:
        self.provider = provider

    def plan_from_text(
        self,
        raw_text: str,
    ) -> PlanningSession:
        """从用户自然语言生成可审核计划。"""
        clean_text = raw_text.strip()

        if not clean_text:
            raise ValueError(
                "用户请求不能为空"
            )

        request = self.provider.parse_user_request(
            clean_text
        )

        plan = build_agent_plan(request)

        explicit_fields = sorted(
            field_name
            for field_name
            in request.model_fields_set
            if field_name != "raw_text"
        )

        return PlanningSession(
            provider_name=self.provider.name,
            request=request,
            plan=plan,
            request_explicit_fields=explicit_fields,
        )
