import json

import pytest

from protein_design_agent.agent.prompts import (
    REQUEST_PARSER_SYSTEM_PROMPT,
    build_request_parser_messages,
    user_request_json_schema,
)


def test_system_prompt_forbids_scientific_guessing() -> None:
    prompt = REQUEST_PARSER_SYSTEM_PROMPT

    assert "只能提取用户明确提供的信息" in prompt
    assert "不得猜测 binder 链" in prompt
    assert "未提供的信息必须保留" in prompt


def test_system_prompt_defines_region_format() -> None:
    prompt = REQUEST_PARSER_SYSTEM_PROMPT

    assert '"A:110-135"' in prompt
    assert '"A:115"' in prompt


def test_raw_text_is_not_requested_from_model() -> None:
    schema = user_request_json_schema()

    assert "raw_text" not in schema["properties"]
    assert "raw_text" not in schema.get("required", [])


def test_parser_messages_preserve_user_text() -> None:
    raw_text = (
        "A链前132个残基是target，"
        "hotspot是A115和A127。"
    )

    messages = build_request_parser_messages(raw_text)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    assert raw_text in messages[1]["content"]


def test_parser_message_contains_valid_json_schema() -> None:
    messages = build_request_parser_messages(
        "帮我准备骨架排名"
    )

    content = messages[1]["content"]

    assert '"properties"' in content
    assert '"input_dir"' in content
    assert '"input_layout"' in content

    # 正式 Schema 本身必须可以被 JSON 序列化。
    serialized = json.dumps(
        user_request_json_schema()
    )
    assert serialized


def test_empty_text_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="用户请求不能为空",
    ):
        build_request_parser_messages("   ")
