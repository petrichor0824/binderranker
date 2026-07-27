#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试用 MockProvider。

它不访问网络、不调用真实大模型，而是返回预先设置好的
结构化数据，用于测试整个 Agent 的程序链路：

自然语言
→ Provider
→ UserRequest
→ Planner
→ AgentPlan
"""

from __future__ import annotations

from typing import Any, Mapping

from protein_design_agent.agent.providers.base import (
    validate_provider_payload,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


class MockProvider:
    """返回预设 payload 的测试模型提供者。"""

    def __init__(
        self,
        payload: UserRequest | Mapping[str, Any],
        *,
        provider_name: str = "mock",
    ) -> None:
        self._payload = payload
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        """返回 Provider 名称。"""
        return self._provider_name

    def parse_user_request(
        self,
        raw_text: str,
    ) -> UserRequest:
        """将预设内容转换成经过验证的 UserRequest。"""
        return validate_provider_payload(
            raw_text=raw_text,
            payload=self._payload,
        )
