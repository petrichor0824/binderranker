#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""面向普通用户的安全错误诊断与修复引导。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    bundle_dir: Path,
) -> dict[str, Any]:
    """只收集诊断需要的确定性事实，不发送 traceback。"""
    context: dict[str, Any] = {
        "kind": kind,
        "error_type": type(error).__name__,
        "error_message": redact_sensitive_text(
            str(error)
        ),
        "bundle_name": bundle_dir.resolve().name,
        "state": {},
    }

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
            "保留当前 Bundle 和日志，根据原始错误检查"
            "路径、配置、输入格式及当前任务阶段。"
        )

    actions.append(
        "修复后只重试失败的步骤；除非程序明确要求，"
        "不要删除已有结果或重新运行已完成步骤。"
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
                "你是 Protein Design Agent 的错误诊断助手。"
                "只能根据给定的确定性错误事实和任务状态"
                "解释问题，不能执行命令、修改文件、改变科研"
                "参数或绕过批准机制。"
                "必须区分确定事实与可能原因。"
                "不得声称已经检查了未提供的代码、文件或日志。"
                "不得输出 API Key、Token 或其他凭据。"
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
    bundle_dir: Path,
    provider: object | None,
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

    lines = [
        heading,
        "",
        "确定性错误：",
        (
            f"{context['error_type']}: "
            f"{context['error_message']}"
        ),
    ]

    failure_evidence = (
        context.get("failure_evidence") or {}
    )

    if failure_evidence:
        lines.extend(
            [
                "",
                "已读取的失败证据：",
                (
                    "清单："
                    f"{failure_evidence.get('manifest_path')}"
                ),
                (
                    "错误："
                    f"{failure_evidence.get('error_type')}："
                    f"{failure_evidence.get('error_message')}"
                ),
            ]
        )

        if (
            failure_evidence.get("return_code")
            is not None
        ):
            lines.append(
                "进程返回码："
                f"{failure_evidence['return_code']}"
            )

        missing_outputs = (
            failure_evidence.get(
                "missing_outputs"
            )
            or []
        )

        if missing_outputs:
            lines.append(
                "缺失产物："
                + ", ".join(missing_outputs)
            )

        stderr_tail = (
            failure_evidence.get(
                "stderr_tail"
            )
            or []
        )

        if stderr_tail:
            lines.append(
                "stderr 末尾（已脱敏）："
            )
            lines.extend(
                f"  {line}"
                for line in stderr_tail[-8:]
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
        else:
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
                        context["error_message"]
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
