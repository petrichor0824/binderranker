import json
from typing import Any

import pytest

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.providers.base import (
    ProviderError,
    ProviderOutputError,
)
from protein_design_agent.agent.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAICompatibleSettings,
    build_chat_completions_url,
)


class RecordingTransport:
    """记录请求并返回预设响应，不访问网络。"""

    def __init__(
        self,
        response_payload: dict[str, Any],
    ) -> None:
        self.response_payload = response_payload
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> bytes:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(
                    body.decode("utf-8")
                ),
                "timeout": timeout,
            }
        )

        return json.dumps(
            self.response_payload,
            ensure_ascii=False,
        ).encode("utf-8")


def chat_response(
    content: str,
) -> dict[str, Any]:
    return {
        "id": "test-response",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }


def complete_request_payload() -> dict[str, Any]:
    return {
        "project_name": "public_agent_test",
        "input_dir": "sample_data/test_two_chain",
        "input_layout": "existing_chains",
        "binder_chain": "A",
        "execute_requested": False,
    }


def test_chat_completions_url_is_built_correctly() -> None:
    assert build_chat_completions_url(
        "https://api.example.com/v1"
    ) == (
        "https://api.example.com/v1/chat/completions"
    )

    assert build_chat_completions_url(
        "https://api.example.com/v1/"
    ) == (
        "https://api.example.com/v1/chat/completions"
    )

    assert build_chat_completions_url(
        "https://api.example.com/v1/chat/completions"
    ) == (
        "https://api.example.com/v1/chat/completions"
    )


def test_provider_builds_request_and_returns_user_request() -> None:
    transport = RecordingTransport(
        chat_response(
            json.dumps(
                complete_request_payload(),
                ensure_ascii=False,
            )
        )
    )

    settings = OpenAICompatibleSettings(
        provider_name="test-provider",
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key_env="TEST_API_KEY",
    )

    provider = OpenAICompatibleProvider(
        settings,
        transport=transport,
        environ={
            "TEST_API_KEY": "secret-test-key"
        },
    )

    request = provider.parse_user_request(
        "用户真实请求"
    )

    assert request.raw_text == "用户真实请求"
    assert request.project_name == "public_agent_test"
    assert request.binder_chain == "A"

    assert len(transport.calls) == 1

    call = transport.calls[0]

    assert call["url"] == (
        "https://api.example.com/v1/chat/completions"
    )

    assert call["headers"]["Authorization"] == (
        "Bearer secret-test-key"
    )

    body = call["body"]

    assert body["model"] == "test-model"
    assert body["response_format"] == {
        "type": "json_object"
    }
    assert body["stream"] is False

    # API Key 不能进入请求 JSON。
    assert "secret-test-key" not in json.dumps(body)


def test_provider_integrates_with_orchestrator() -> None:
    transport = RecordingTransport(
        chat_response(
            json.dumps(
                complete_request_payload()
            )
        )
    )

    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key_env=None,
            require_api_key=False,
        ),
        transport=transport,
        environ={},
    )

    orchestrator = LocalAgentOrchestrator(
        provider
    )

    session = orchestrator.plan_from_text(
        "检查已经分链的数据，A链是binder"
    )

    assert session.provider_name == (
        "openai-compatible"
    )
    assert session.plan.status == (
        "READY_FOR_REVIEW"
    )
    assert session.plan.execution_allowed is False


def test_missing_api_key_is_rejected() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key_env="MISSING_API_KEY",
            require_api_key=True,
        ),
        transport=RecordingTransport(
            chat_response("{}")
        ),
        environ={},
    )

    with pytest.raises(
        ProviderError,
        match="缺少 API Key 环境变量",
    ):
        provider.parse_user_request(
            "测试请求"
        )


def test_invalid_model_json_is_rejected() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key_env=None,
            require_api_key=False,
        ),
        transport=RecordingTransport(
            chat_response("这不是JSON")
        ),
        environ={},
    )

    with pytest.raises(
        ProviderOutputError,
        match="不是合法 JSON",
    ):
        provider.parse_user_request(
            "测试请求"
        )


def test_empty_model_content_is_rejected() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key_env=None,
            require_api_key=False,
        ),
        transport=RecordingTransport(
            chat_response("   ")
        ),
        environ={},
    )

    with pytest.raises(
        ProviderOutputError,
        match="空内容",
    ):
        provider.parse_user_request(
            "测试请求"
        )


def test_markdown_json_fence_is_supported() -> None:
    payload = complete_request_payload()

    content = (
        "```json\n"
        + json.dumps(payload)
        + "\n```"
    )

    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
            api_key_env=None,
            require_api_key=False,
        ),
        transport=RecordingTransport(
            chat_response(content)
        ),
        environ={},
    )

    request = provider.parse_user_request(
        "本地模型测试"
    )

    assert request.project_name == (
        "public_agent_test"
    )


def test_unknown_provider_field_is_rejected() -> None:
    payload = complete_request_payload()
    payload["invented_scientific_parameter"] = 123

    provider = OpenAICompatibleProvider(
        OpenAICompatibleSettings(
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key_env=None,
            require_api_key=False,
        ),
        transport=RecordingTransport(
            chat_response(
                json.dumps(payload)
            )
        ),
        environ={},
    )

    with pytest.raises(
        ProviderOutputError,
        match="包含未定义字段",
    ):
        provider.parse_user_request(
            "测试未知字段"
        )
