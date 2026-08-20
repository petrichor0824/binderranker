#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local Agent v0.1 的总调度器。

职责：
1. 接收用户自然语言；
2. 调用可替换的 Provider；
3. 获得经过验证的 UserRequest；
4. 调用确定性 Planner；
5. 返回可审核的 PlanningSession。

v0.1 不执行 Ranker，不连接服务器，不运行任意 Shell。
"""

from __future__ import annotations

from protein_design_agent.agent.planning_session_builder import (
    build_planning_session,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)


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

        return build_planning_session(
            request=request,
            provider_name=self.provider.name,
        )
