#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
公开版 Agent 的模型 Provider 配置。

该配置只保存：
- 接口类型；
- 接口地址；
- 模型名称；
- API Key 所在的环境变量名称。

绝不保存真实 API Key。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


ProviderKind = Literal[
    "openai_compatible",
]

MaxTokensField = Literal[
    "max_tokens",
    "max_completion_tokens",
    "omit",
]


class ProviderProfile(BaseModel):
    """一个可选择的模型服务配置。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    kind: ProviderKind = "openai_compatible"

    base_url: str = Field(
        min_length=1
    )
    model: str = Field(
        min_length=1
    )

    # 这里只保存环境变量名称。
    api_key_env: str | None = None
    require_api_key: bool = True

    timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
    )

    max_output_tokens: int = Field(
        default=4096,
        ge=128,
        le=100000,
    )

    max_tokens_field: MaxTokensField = (
        "max_tokens"
    )

    temperature: float | None = Field(
        default=0.0,
        ge=0,
        le=2,
    )

    @model_validator(mode="after")
    def validate_profile(
        self,
    ) -> "ProviderProfile":
        if not self.base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "base_url 必须以 http:// 或 https:// 开头"
            )

        if self.require_api_key and not self.api_key_env:
            raise ValueError(
                "require_api_key=True 时必须配置 "
                "api_key_env"
            )

        if self.api_key_env is not None:
            valid_env_name = re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                self.api_key_env,
            )

            if valid_env_name is None:
                raise ValueError(
                    "api_key_env 不是合法的环境变量名称："
                    f"{self.api_key_env}"
                )

        return self


class ModelProviderConfig(BaseModel):
    """一个公开 Agent 可用的模型配置文件。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    schema_version: Literal["0.1"] = "0.1"

    active_profile: str = Field(
        min_length=1
    )

    profiles: dict[str, ProviderProfile] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def validate_profiles(
        self,
    ) -> "ModelProviderConfig":
        for profile_name in self.profiles:
            valid_name = re.fullmatch(
                r"[A-Za-z0-9_.-]+",
                profile_name,
            )

            if valid_name is None:
                raise ValueError(
                    "模型 profile 名称只能包含字母、"
                    "数字、点、下划线和连字符："
                    f"{profile_name}"
                )

        if self.active_profile not in self.profiles:
            raise ValueError(
                "active_profile 不存在于 profiles："
                f"{self.active_profile}"
            )

        return self


def load_model_provider_config(
    path: Path,
) -> ModelProviderConfig:
    """读取并严格验证模型配置 YAML。"""
    try:
        raw = yaml.safe_load(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ValueError(
            f"无法读取模型配置：{exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"模型配置 YAML 格式错误：{exc}"
        ) from exc

    if raw is None:
        raise ValueError("模型配置文件为空")

    if not isinstance(raw, dict):
        raise ValueError(
            "模型配置最外层必须是键值对象"
        )

    return ModelProviderConfig.model_validate(raw)
