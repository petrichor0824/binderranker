#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自然语言请求解析提示词。

该模块不调用任何模型，只负责生成模型无关的提示词。

设计原则：
1. 模型只能提取用户明确提供的信息；
2. 不得根据文件名、蛋白名称或常识猜测科学参数；
3. 未提供的信息必须从输出 JSON 中完全省略；
4. 输出必须满足 UserRequest 的 JSON Schema；
5. Provider 输出仍需经过 Pydantic 验证。
"""

from __future__ import annotations

import json
from typing import Any

from protein_design_agent.public_identity import (
    AGENT_NAME,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


REQUEST_PARSER_SYSTEM_PROMPT = f"""
你是 {AGENT_NAME} 的请求解析器。

你的唯一任务是：
把用户的自然语言需求转换为结构化 UserRequest。

你不是工作流执行器，也不是科研结论生成器。

严格规则：

1. 只能提取用户明确提供的信息。
2. 不得猜测 binder 链、target 链、残基边界、hotspot、
   region、输入路径或执行后端。
3. 未提供的信息必须从 JSON 中完全省略。
   不得为未提及字段输出 null、默认值或空列表。
4. 不得因为文件名、蛋白名称或既往常识自动补全参数。
5. 残基区域统一使用字符串，例如：
   "A:110-135"
6. 单个 hotspot 统一使用字符串，例如：
   "A:115"
7. 如果用户写“A115”，可以规范化为“A:115”；
   但不得改变链名或残基编号。
8. 如果用户说“先准备”“不要执行”“只看计划”，
   execute_requested 必须为 false。
9. 如果用户明确要求执行，execute_requested 可以为 true；
   但后续 Planner 仍会要求人工审核。
10. 不要在结构化结果之外输出解释、Markdown 或代码块。
11. raw_text 由程序写入，你不需要生成或修改它。
12. 当前只支持 prepare_backbone_ranking 任务。
""".strip()


def remove_schema_defaults(
    value: Any,
) -> Any:
    """
    从发送给模型的 JSON Schema 中移除 default。

    Pydantic 本地验证仍然保留默认值；
    这里只避免模型误以为应该主动输出全部默认字段。
    """
    if isinstance(value, dict):
        cleaned = {
            key: remove_schema_defaults(item)
            for key, item in value.items()
            if key != "default"
        }

        return cleaned

    if isinstance(value, list):
        return [
            remove_schema_defaults(item)
            for item in value
        ]

    return value


def user_request_json_schema() -> dict[str, Any]:
    """返回 UserRequest 的正式 JSON Schema。"""
    schema = remove_schema_defaults(
        UserRequest.model_json_schema()
    )

    # raw_text 由程序使用用户真实输入填入，
    # 不应要求模型生成。
    properties = schema.get("properties", {})
    properties.pop("raw_text", None)

    required = schema.get("required", [])
    schema["required"] = [
        item
        for item in required
        if item != "raw_text"
    ]

    return schema


def build_request_parser_messages(
    raw_text: str,
) -> list[dict[str, str]]:
    """
    构造 Provider 通用的 system/user 消息。

    JSON Schema 同时写进提示词，作为不支持原生
    Structured Outputs 的 Provider 的兼容保护。
    """
    clean_text = raw_text.strip()

    if not clean_text:
        raise ValueError("用户请求不能为空")

    schema_text = json.dumps(
        user_request_json_schema(),
        ensure_ascii=False,
        indent=2,
    )

    user_message = (
        "请解析下面的用户请求。\n\n"
        "用户请求：\n"
        f"{clean_text}\n\n"
        "输出必须符合以下 JSON Schema：\n"
        f"{schema_text}\n\n"
        "只输出一个 JSON 对象。"
    )

    return [
        {
            "role": "system",
            "content": REQUEST_PARSER_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_message,
        },
    ]
