#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
根据公开配置创建模型 Provider。

当前支持：
- openai_compatible

后续可以扩展：
- local_transformers
- anthropic
- gemini
- custom_http
"""

from __future__ import annotations

from collections.abc import Mapping

from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)
from protein_design_agent.agent.providers.openai_compatible import (
    HTTPTransport,
    OpenAICompatibleProvider,
    OpenAICompatibleSettings,
)
from protein_design_agent.schemas.provider_config import (
    ModelProviderConfig,
    ProviderProfile,
)


def resolve_provider_profile(
    config: ModelProviderConfig,
    profile_name: str | None = None,
) -> tuple[str, ProviderProfile]:
    """选择 active profile 或用户指定的 profile。"""
    selected_name = (
        profile_name
        if profile_name is not None
        else config.active_profile
    )

    try:
        profile = config.profiles[selected_name]
    except KeyError as exc:
        supported = ", ".join(
            sorted(config.profiles)
        )

        raise ValueError(
            f"模型 profile 不存在：{selected_name}；"
            f"可用 profile：{supported}"
        ) from exc

    return selected_name, profile


def build_request_parser_provider(
    config: ModelProviderConfig,
    *,
    profile_name: str | None = None,
    transport: HTTPTransport | None = None,
    environ: Mapping[str, str] | None = None,
) -> RequestParserProvider:
    """
    根据模型配置创建自然语言解析 Provider。

    创建 Provider 不会自动调用网络。
    """
    selected_name, profile = resolve_provider_profile(
        config,
        profile_name=profile_name,
    )

    if profile.kind == "openai_compatible":
        settings = OpenAICompatibleSettings(
            provider_name=selected_name,
            base_url=profile.base_url,
            model=profile.model,
            api_key_env=profile.api_key_env,
            require_api_key=profile.require_api_key,
            timeout_seconds=profile.timeout_seconds,
            max_output_tokens=profile.max_output_tokens,
            max_tokens_field=profile.max_tokens_field,
            temperature=profile.temperature,
        )

        return OpenAICompatibleProvider(
            settings,
            transport=transport,
            environ=environ,
        )

    # 当前 Literal 只有一种类型。
    # 保留该分支，为以后扩展 Provider 做安全保护。
    raise ValueError(
        f"暂不支持 Provider 类型：{profile.kind}"
    )
