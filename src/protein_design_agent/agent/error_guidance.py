#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""面向普通用户的安全错误诊断与修复引导。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from protein_design_agent.public_identity import (
    AGENT_NAME,
)
from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.agent.failure_evidence import (
    collect_failure_evidence,
)
from protein_design_agent.agent.run_status import (
    inspect_run_status,
)


ErrorKind = Literal["REJECTED", "FAILED"]


class ModelErrorGuidance(BaseModel):
    """模型只能解释错误，不能执行修复动作。"""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1)
    possible_causes: list[str] = Field(
        default_factory=list,
        max_length=5,
    )
    recommended_actions: list[str] = Field(
        min_length=1,
        max_length=6,
    )
    safe_to_retry: bool


def redact_sensitive_text(value: str) -> str:
    """从错误文本中移除常见凭据。"""
    text = value[:6000]

    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)\S+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\bsk-[a-z0-9_-]{8,}\b",
        "[REDACTED_API_KEY]",
        text,
    )
    text = re.sub(
        (
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|"
            r"SECRET|PASSWORD))\s*=\s*[^\s,;]+"
        ),
        r"\1=[REDACTED]",
        text,
    )

    return text


def build_safe_error_context(
    *,
    kind: ErrorKind,
    error: Exception,
    bundle_dir: Path | None,
) -> dict[str, Any]:
    """只收集诊断需要的确定性事实，不发送 traceback。"""
    context: dict[str, Any] = {
        "kind": kind,
        "error_type": type(error).__name__,
        "error_message": redact_sensitive_text(
            str(error)
        ),
        "state": {},
    }

    if bundle_dir is None:
        return context

    context["bundle_name"] = (
        bundle_dir.resolve().name
    )

    failure_evidence = collect_failure_evidence(
        bundle_dir=bundle_dir,
        error=error,
    )

    if failure_evidence:
        raw_manifest_error = (
            failure_evidence.get(
                "error_message"
            )
        )

        if isinstance(raw_manifest_error, str):
            failure_evidence[
                "error_message"
            ] = redact_sensitive_text(
                raw_manifest_error
            )

        raw_stderr = failure_evidence.get(
            "stderr_tail"
        )

        if isinstance(raw_stderr, list):
            failure_evidence[
                "stderr_tail"
            ] = [
                redact_sensitive_text(line)
                for line in raw_stderr
                if isinstance(line, str)
            ]

        context["failure_evidence"] = (
            failure_evidence
        )

    try:
        report = inspect_run_status(bundle_dir)
    except Exception:
        return context

    context["state"] = {
        "current_stage": report.current_stage,
        "prepare_status": report.prepare_status,
        "approval_status": report.approval_status,
        "execution_status": report.execution_status,
        "analysis_status": report.analysis_status,
        "explanation_status": (
            report.explanation_status
        ),
        "approval_consumed": (
            report.approval_consumed
        ),
    }

    return context


def deterministic_actions(
    error_message: str,
    *,
    bundle_available: bool = True,
) -> list[str]:
    """在模型不可用时提供保守、可执行的检查方向。"""
    lower = error_message.lower()
    actions: list[str] = []

    if any(
        token in lower
        for token in (
            "不存在",
            "not found",
            "no such file",
            "不是目录",
        )
    ):
        actions.append(
            "检查输入路径是否存在、拼写是否正确，"
            "以及当前用户是否有读取权限。"
        )

    if any(
        token in lower
        for token in (
            "api",
            "provider",
            "network",
            "timeout",
            "联网",
        )
    ):
        actions.append(
            "检查模型配置、网络权限、API Key 环境变量"
            "以及服务是否可访问。"
        )

    if any(
        token in lower
        for token in (
            "sha256",
            "fingerprint",
            "发生变化",
            "指纹",
        )
    ):
        actions.append(
            "不要覆盖原始输出；核对文件是否在执行完成后"
            "被移动、替换或修改。"
        )

    if any(
        token in lower
        for token in (
            "缺少",
            "column",
            "schema",
            "字段",
            "pydantic",
        )
    ):
        actions.append(
            "检查产物格式与当前程序版本是否匹配，"
            "尤其是必需字段和输出列。"
        )

    if not actions:
        actions.append(
            (
                "保留当前 Bundle 和日志，根据原始错误检查"
                "路径、配置、输入格式及当前任务阶段。"
            )
            if bundle_available
            else (
                "检查相关路径、配置、输入格式和运行环境。"
            )
        )

    actions.append(
        (
            "修复后只重试失败的步骤；除非程序明确要求，"
            "不要删除已有结果或重新运行已完成步骤。"
        )
        if bundle_available
        else (
            "修复相关输入或配置后，再重试当前操作。"
        )
    )

    return actions


def build_model_messages(
    context: dict[str, Any],
) -> list[dict[str, str]]:
    schema = ModelErrorGuidance.model_json_schema()

    return [
        {
            "role": "system",
            "content": (
                f"你是 {AGENT_NAME} 的错误诊断助手。"
                "只能根据给定的确定性错误事实和任务状态"
                "解释问题，不能执行命令、修改文件、改变科研"
                "参数或绕过批准机制。"
                "必须区分确定事实与可能原因。"
                "不得声称已经检查了未提供的代码、文件或日志。"
                "不得输出 API Key、Token 或其他凭据。"
                "不得在面向用户的解释中原样复述异常类名、"
                "内部路径、manifest 路径、stderr 或技术诊断原文；"
                "只能把这些事实转化为用户可理解的影响、"
                "可能原因和可执行建议。"
                "只输出符合 JSON Schema 的 JSON 对象。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "error_context": context,
                    "required_schema": schema,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def collect_model_guidance_sensitive_values(
    context: dict[str, Any],
) -> set[str]:
    """
    收集模型不得原样回显的具体内部诊断值。

    只针对错误类型、错误原文、stderr 和内部路径，
    不把 FAILED、BinderRanker 等普通状态词当作敏感词。
    """
    values: set[str] = set()

    def add_value(value: object) -> None:
        if not isinstance(value, str):
            return

        clean = value.strip()

        if len(clean) < 4:
            return

        if clean in {
            "[REDACTED]",
            "[REDACTED_API_KEY]",
        }:
            return

        values.add(clean)

    add_value(context.get("error_type"))
    add_value(context.get("error_message"))

    evidence = (
        context.get("failure_evidence")
        or {}
    )

    if isinstance(evidence, dict):
        add_value(
            evidence.get("error_type")
        )
        add_value(
            evidence.get("error_message")
        )

        stderr_tail = evidence.get(
            "stderr_tail"
        )

        if isinstance(stderr_tail, list):
            for line in stderr_tail:
                add_value(line)

        for key, value in evidence.items():
            if not isinstance(value, str):
                continue

            lower_key = key.lower()

            is_internal_path = (
                "path" in lower_key
                or "manifest" in lower_key
                or lower_key.endswith("_log")
            )

            if not is_internal_path:
                continue

            add_value(value)

            try:
                name = Path(value).name
            except (TypeError, ValueError):
                continue

            add_value(name)

    return values


def model_guidance_echoes_sensitive_context(
    guidance: ModelErrorGuidance,
    context: dict[str, Any],
) -> bool:
    """
    检查模型是否原样复述内部诊断。

    一旦命中，不做局部清洗；
    整段模型 guidance 应退回确定性兜底。
    """
    rendered_parts = [
        guidance.explanation,
        *guidance.possible_causes,
        *guidance.recommended_actions,
    ]

    rendered = " ".join(
        " ".join(part.split())
        for part in rendered_parts
    ).casefold()

    for value in (
        collect_model_guidance_sensitive_values(
            context
        )
    ):
        normalized = " ".join(
            value.split()
        ).casefold()

        if normalized and normalized in rendered:
            return True

    return False


def format_model_guidance(
    guidance: ModelErrorGuidance,
) -> list[str]:
    lines = [
        "",
        "诊断说明：",
        guidance.explanation,
    ]

    if guidance.possible_causes:
        lines.extend(["", "可能原因："])
        lines.extend(
            f"{index}. {value}"
            for index, value in enumerate(
                guidance.possible_causes,
                start=1,
            )
        )

    lines.extend(["", "建议处理："])
    lines.extend(
        f"{index}. {value}"
        for index, value in enumerate(
            guidance.recommended_actions,
            start=1,
        )
    )

    lines.append(
        ""
        + (
            "修复后可以重试当前步骤。"
            if guidance.safe_to_retry
            else
            "在确认状态和输入之前，不建议立即重试。"
        )
    )

    return lines


def format_error_guidance(
    *,
    kind: ErrorKind,
    error: Exception,
    bundle_dir: Path | None,
    provider: object | None,
    public_message_override: str | None = None,
) -> str:
    """生成永不依赖模型成功的用户错误说明。"""
    context = build_safe_error_context(
        kind=kind,
        error=error,
        bundle_dir=bundle_dir,
    )

    heading = (
        "当前操作被拒绝。"
        if kind == "REJECTED"
        else "当前操作没有完成。"
    )

    if kind == "REJECTED":
        impact = (
            "本次请求没有继续执行。"
            + (
                "请根据当前任务状态和提示调整后再继续。"
                if bundle_dir is not None
                else "请根据提示调整后再继续。"
            )
        )
    else:
        impact = (
            "本次操作没有成功完成。"
            + (
                "请先确认当前任务状态和已有产物，"
                "再决定是否重试。"
                if bundle_dir is not None
                else
                "请检查相关输入和配置后再决定是否重试。"
            )
        )

    lines = [
        heading,
    ]

    public_message = (
        public_message_override.strip()
        if (
            isinstance(
                public_message_override,
                str,
            )
            and public_message_override.strip()
        )
        else getattr(
            error,
            "public_message",
            None,
        )
    )

    if (
        isinstance(public_message, str)
        and public_message.strip()
    ):
        lines.extend(
            [
                "",
                "已确认：",
                public_message.strip(),
            ]
        )

    lines.extend(
        [
            "",
            "影响：",
            impact,
        ]
    )

    state = context.get("state") or {}
    if state:
        lines.extend(
            [
                "",
                "当前任务状态：",
                (
                    "阶段："
                    f"{state.get('current_stage')}"
                ),
                (
                    "准备 / 批准 / 执行 / 分析："
                    f"{state.get('prepare_status')} / "
                    f"{state.get('approval_status')} / "
                    f"{state.get('execution_status')} / "
                    f"{state.get('analysis_status')}"
                ),
            ]
        )

    if (
        provider is not None
        and isinstance(
            provider,
            StructuredJSONProvider,
        )
    ):
        try:
            payload = provider.generate_json(
                build_model_messages(context)
            )
            guidance = (
                ModelErrorGuidance.model_validate(
                    payload
                )
            )
        except Exception:
            guidance = None

        if (
            guidance is not None
            and not model_guidance_echoes_sensitive_context(
                guidance,
                context,
            )
        ):
            lines.extend(
                format_model_guidance(guidance)
            )
            return "\n".join(lines)

    lines.extend(
        [
            "",
            "建议处理：",
            *[
                f"{index}. {action}"
                for index, action in enumerate(
                    deterministic_actions(
                        context["error_message"],
                        bundle_available=(
                            bundle_dir is not None
                        ),
                    ),
                    start=1,
                )
            ],
            "",
            (
                "本次使用的是确定性兜底说明；"
                "错误诊断模型不可用或未启用。"
            ),
        ]
    )

    return "\n".join(lines)
