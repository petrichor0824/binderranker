#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OpenAI Chat Completions 兼容 Provider。

可用于：
- OpenAI；
- DeepSeek；
- 兼容 OpenAI Chat Completions 格式的其他服务；
- 部分本地模型服务。

安全原则：
1. API Key 只从环境变量读取；
2. API Key 不进入配置文件、日志或 Git；
3. 模型只能返回 UserRequest JSON；
4. 输出必须经过 JSON 解析和 Pydantic 验证；
5. Provider 只负责理解语言，不执行科学工作流。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, model_validator

from protein_design_agent.agent.prompts import (
    build_request_parser_messages,
)
from protein_design_agent.agent.providers.base import (
    ProviderError,
    ProviderOutputError,
    validate_provider_payload,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


# URL、请求头、请求体、超时时间 -> 原始响应字节
HTTPTransport = Callable[
    [str, dict[str, str], bytes, float],
    bytes,
]


class OpenAICompatibleSettings(BaseModel):
    """OpenAI Chat Completions 兼容接口配置。"""

    provider_name: str = Field(
        default="openai-compatible",
        min_length=1,
    )

    # 示例：
    # OpenAI:  https://api.openai.com/v1
    # DeepSeek: https://api.deepseek.com
    # 本地服务: http://127.0.0.1:8000/v1
    base_url: str = Field(min_length=1)

    model: str = Field(min_length=1)

    # 这里只保存环境变量名称，不保存真正的 Key。
    api_key_env: str | None = "OPENAI_API_KEY"
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

    # 不同兼容服务使用的字段可能不同。
    max_tokens_field: Literal[
        "max_tokens",
        "max_completion_tokens",
        "omit",
    ] = "max_tokens"

    temperature: float | None = Field(
        default=0.0,
        ge=0,
        le=2,
    )

    @model_validator(mode="after")
    def validate_settings(
        self,
    ) -> "OpenAICompatibleSettings":
        if not self.base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "base_url 必须以 http:// 或 https:// 开头"
            )

        if self.require_api_key and not self.api_key_env:
            raise ValueError(
                "require_api_key=True 时必须提供 "
                "api_key_env"
            )

        return self


def build_chat_completions_url(
    base_url: str,
) -> str:
    """根据 base_url 构造 Chat Completions 地址。"""
    normalized = base_url.rstrip("/")

    if normalized.endswith("/chat/completions"):
        return normalized

    return normalized + "/chat/completions"


def default_http_transport(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
) -> bytes:
    """使用 Python 标准库发送 POST 请求。"""
    request = Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=timeout,
        ) as response:
            return response.read()

    except HTTPError as exc:
        try:
            response_text = exc.read().decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            response_text = ""

        # 限制错误内容长度，避免日志过大。
        response_text = response_text[:1000]

        raise ProviderError(
            f"模型 API 返回 HTTP {exc.code}："
            f"{response_text}"
        ) from exc

    except URLError as exc:
        raise ProviderError(
            f"无法连接模型 API：{exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise ProviderError(
            "模型 API 请求超时"
        ) from exc


def extract_assistant_content(
    response_payload: Mapping[str, Any],
) -> str:
    """从 Chat Completions 响应提取 assistant 文本。"""
    choices = response_payload.get("choices")

    if not isinstance(choices, list) or not choices:
        raise ProviderOutputError(
            "模型响应缺少非空 choices"
        )

    first_choice = choices[0]

    if not isinstance(first_choice, Mapping):
        raise ProviderOutputError(
            "模型响应 choices[0] 不是对象"
        )

    message = first_choice.get("message")

    if not isinstance(message, Mapping):
        raise ProviderOutputError(
            "模型响应缺少 choices[0].message"
        )

    content = message.get("content")

    if not isinstance(content, str):
        raise ProviderOutputError(
            "模型响应 message.content 不是字符串"
        )

    content = content.strip()

    if not content:
        raise ProviderOutputError(
            "模型返回了空内容"
        )

    return content


def parse_json_object_text(
    content: str,
) -> dict[str, Any]:
    """
    将模型文本转换为 JSON 对象。

    正常情况下模型应直接返回 JSON。
    为兼容部分服务，也允许外层包含 ```json 代码围栏。
    """
    clean = content.strip()

    if clean.startswith("```"):
        lines = clean.splitlines()

        if len(lines) >= 3 and lines[-1].strip() == "```":
            clean = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ProviderOutputError(
            "模型内容不是合法 JSON："
            f"第 {exc.lineno} 行，第 {exc.colno} 列，"
            f"{exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ProviderOutputError(
            "模型 JSON 最外层必须是对象"
        )

    return payload


class OpenAICompatibleProvider:
    """
    通过 Chat Completions 兼容接口解析用户请求。

    默认 transport 会真实联网；
    测试中可以注入假 transport，避免网络和费用。
    """

    def __init__(
        self,
        settings: OpenAICompatibleSettings,
        *,
        transport: HTTPTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self._transport = (
            transport
            if transport is not None
            else default_http_transport
        )
        self._environ = (
            environ
            if environ is not None
            else os.environ
        )

    @property
    def name(self) -> str:
        return self.settings.provider_name

    def _read_api_key(self) -> str | None:
        env_name = self.settings.api_key_env

        if env_name is None:
            return None

        api_key = self._environ.get(env_name)

        if api_key:
            return api_key

        if self.settings.require_api_key:
            raise ProviderError(
                f"缺少 API Key 环境变量：{env_name}"
            )

        return None

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "protein-design-agent/0.1",
        }

        api_key = self._read_api_key()

        if api_key is not None:
            headers["Authorization"] = (
                f"Bearer {api_key}"
            )

        return headers

    def _build_request_body(
        self,
        raw_text: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": build_request_parser_messages(
                raw_text
            ),
            "response_format": {
                "type": "json_object"
            },
            "stream": False,
        }

        if self.settings.temperature is not None:
            body["temperature"] = (
                self.settings.temperature
            )

        token_field = self.settings.max_tokens_field

        if token_field != "omit":
            body[token_field] = (
                self.settings.max_output_tokens
            )

        return body

    def _call_api(
        self,
        raw_text: str,
    ) -> dict[str, Any]:
        endpoint = build_chat_completions_url(
            self.settings.base_url
        )

        headers = self._build_headers()
        request_body = self._build_request_body(
            raw_text
        )

        encoded_body = json.dumps(
            request_body,
            ensure_ascii=False,
        ).encode("utf-8")

        raw_response = self._transport(
            endpoint,
            headers,
            encoded_body,
            self.settings.timeout_seconds,
        )

        try:
            decoded_response = raw_response.decode(
                "utf-8"
            )
        except UnicodeDecodeError as exc:
            raise ProviderOutputError(
                "模型 API 响应不是有效 UTF-8"
            ) from exc

        try:
            payload = json.loads(decoded_response)
        except json.JSONDecodeError as exc:
            raise ProviderOutputError(
                "模型 API 响应不是合法 JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderOutputError(
                "模型 API 响应最外层不是对象"
            )

        if "error" in payload:
            raise ProviderError(
                "模型 API 返回 error 对象："
                f"{payload['error']}"
            )

        return payload

    def generate_json(
        self,
        messages: list[Mapping[str, str]],
    ) -> dict[str, Any]:
        """
        根据调用方提供的受控消息生成 JSON 对象。

        该接口用于：
        - Ranker 结果解释；
        - 后续科学报告生成；
        - 其他需要结构化模型输出的 Agent 阶段。

        安全限制：
        - 不执行模型返回的任何命令；
        - 只接受 system/user/assistant 文本消息；
        - 只返回合法 JSON 对象；
        - API Key 仍只从环境变量读取。
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError(
                "messages 必须是非空列表"
            )

        normalized_messages: list[
            dict[str, str]
        ] = []

        allowed_roles = {
            "system",
            "user",
            "assistant",
        }

        for index, message in enumerate(messages):
            if not isinstance(message, Mapping):
                raise ValueError(
                    f"messages[{index}] 必须是对象"
                )

            unknown_keys = (
                set(message) - {"role", "content"}
            )

            if unknown_keys:
                raise ValueError(
                    f"messages[{index}] 包含未知字段："
                    f"{sorted(unknown_keys)}"
                )

            role = message.get("role")
            content = message.get("content")

            if role not in allowed_roles:
                raise ValueError(
                    f"messages[{index}].role 无效："
                    f"{role!r}"
                )

            if (
                not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError(
                    f"messages[{index}].content "
                    "必须是非空字符串"
                )

            normalized_messages.append(
                {
                    "role": str(role),
                    "content": content.strip(),
                }
            )

        request_body: dict[str, Any] = {
            "model": self.settings.model,
            "messages": normalized_messages,
            "response_format": {
                "type": "json_object"
            },
            "stream": False,
        }

        if self.settings.temperature is not None:
            request_body["temperature"] = (
                self.settings.temperature
            )

        token_field = (
            self.settings.max_tokens_field
        )

        if token_field != "omit":
            request_body[token_field] = (
                self.settings.max_output_tokens
            )

        endpoint = build_chat_completions_url(
            self.settings.base_url
        )

        raw_response = self._transport(
            endpoint,
            self._build_headers(),
            json.dumps(
                request_body,
                ensure_ascii=False,
            ).encode("utf-8"),
            self.settings.timeout_seconds,
        )

        try:
            response_payload = json.loads(
                raw_response.decode("utf-8")
            )
        except UnicodeDecodeError as exc:
            raise ProviderOutputError(
                "模型 API 响应不是合法 UTF-8"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderOutputError(
                "模型 API 响应不是合法 JSON："
                f"第 {exc.lineno} 行，"
                f"第 {exc.colno} 列"
            ) from exc

        if not isinstance(
            response_payload,
            Mapping,
        ):
            raise ProviderOutputError(
                "模型 API 响应最外层必须是对象"
            )

        assistant_content = (
            extract_assistant_content(
                response_payload
            )
        )

        return parse_json_object_text(
            assistant_content
        )

    def parse_user_request(
        self,
        raw_text: str,
    ) -> UserRequest:
        """自然语言 -> API -> JSON -> UserRequest。"""
        clean_text = raw_text.strip()

        if not clean_text:
            raise ValueError("用户请求不能为空")

        response_payload = self._call_api(
            clean_text
        )

        assistant_content = extract_assistant_content(
            response_payload
        )

        provider_payload = parse_json_object_text(
            assistant_content
        )

        return validate_provider_payload(
            raw_text=clean_text,
            payload=provider_payload,
        )
