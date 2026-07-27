#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
大模型 Provider 的公共接口。

公开版 Agent 不绑定任何特定模型厂商。

所有模型提供者都必须完成同一件事：

    用户自然语言
        ↓
    UserRequest

后续可以实现：
- MockProvider：测试使用；
- OpenAICompatibleProvider：OpenAI、DeepSeek 等兼容接口；
- LocalModelProvider：本地部署模型。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from pydantic import ValidationError

from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


class ProviderError(RuntimeError):
    """模型提供者调用或配置错误。"""


class ProviderOutputError(ProviderError):
    """模型返回内容无法转换为合法 UserRequest。"""


@runtime_checkable
class RequestParserProvider(Protocol):
    """所有自然语言解析 Provider 必须满足的接口。"""

    @property
    def name(self) -> str:
        """Provider 的公开名称。"""
        ...

    def parse_user_request(
        self,
        raw_text: str,
    ) -> UserRequest:
        """将自然语言解析为 UserRequest。"""
        ...


def validate_provider_payload(
    *,
    raw_text: str,
    payload: UserRequest | Mapping[str, Any],
) -> UserRequest:
    """
    将 Provider 输出严格转换为 UserRequest。

    安全规则：
    - raw_text 永远使用用户真实输入；
    - 不允许模型伪造或替换用户原话；
    - 所有字段必须经过 Pydantic 验证；
    - 非法字段或类型立即报错。
    """
    if isinstance(payload, UserRequest):
        data = payload.model_dump(mode="python")
    elif isinstance(payload, Mapping):
        data = dict(payload)
    else:
        raise ProviderOutputError(
            "Provider 输出必须是 UserRequest 或键值对象，"
            f"实际类型为 {type(payload).__name__}"
        )

    # 用户原始输入是可信来源，不能采用模型生成的 raw_text。
    data["raw_text"] = raw_text

    try:
        return UserRequest.model_validate(data)
    except ValidationError as exc:
        raise ProviderOutputError(
            "Provider 输出无法通过 UserRequest 验证：\n"
            f"{exc}"
        ) from exc
