import json
from typing import Any

import pytest

from protein_design_agent.agent.providers.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAICompatibleSettings,
)


def build_provider(
    captured: dict[str, Any],
) -> OpenAICompatibleProvider:
    def fake_transport(
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> bytes:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(
            body.decode("utf-8")
        )
        captured["timeout"] = timeout

        assistant_payload = {
            "summary": "结构化解释",
            "candidate_count": 5,
        }

        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            assistant_payload,
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        }

        return json.dumps(
            response,
            ensure_ascii=False,
        ).encode("utf-8")

    settings = OpenAICompatibleSettings(
        provider_name="test-provider",
        base_url="https://example.test/v1",
        model="test-model",
        api_key_env=None,
        require_api_key=False,
        timeout_seconds=30,
        max_output_tokens=2048,
        max_tokens_field="max_tokens",
        temperature=0.0,
    )

    return OpenAICompatibleProvider(
        settings,
        transport=fake_transport,
        environ={},
    )


def test_generate_json_uses_controlled_messages() -> None:
    captured: dict[str, Any] = {}
    provider = build_provider(captured)

    result = provider.generate_json(
        [
            {
                "role": "system",
                "content": (
                    "只根据证据输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    '{"project": "3c98"}'
                ),
            },
        ]
    )

    assert result == {
        "summary": "结构化解释",
        "candidate_count": 5,
    }

    assert captured["url"] == (
        "https://example.test/v1/"
        "chat/completions"
    )

    request_body = captured["body"]

    assert request_body["model"] == (
        "test-model"
    )
    assert request_body["messages"] == [
        {
            "role": "system",
            "content": (
                "只根据证据输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                '{"project": "3c98"}'
            ),
        },
    ]
    assert request_body["response_format"] == {
        "type": "json_object"
    }
    assert request_body["stream"] is False
    assert request_body["temperature"] == 0.0
    assert request_body["max_tokens"] == 2048


def test_generate_json_rejects_invalid_role() -> None:
    provider = build_provider({})

    with pytest.raises(
        ValueError,
        match="role 无效",
    ):
        provider.generate_json(
            [
                {
                    "role": "tool",
                    "content": "not allowed",
                }
            ]
        )


def test_generate_json_rejects_unknown_fields() -> None:
    provider = build_provider({})

    with pytest.raises(
        ValueError,
        match="未知字段",
    ):
        provider.generate_json(
            [
                {
                    "role": "user",
                    "content": "hello",
                    "command": "rm -rf /",
                }
            ]
        )


def test_generate_json_rejects_empty_messages() -> None:
    provider = build_provider({})

    with pytest.raises(
        ValueError,
        match="非空列表",
    ):
        provider.generate_json([])
