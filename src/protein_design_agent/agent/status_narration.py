#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""把确定性任务状态安全地转述为普通用户语言。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.agent.run_status import (
    RunStatusReport,
    inspect_run_status,
)
from protein_design_agent.agent.user_language import (
    format_user_progress,
    translate_internal_terms,
    user_scope,
)


class ModelStatusNarration(BaseModel):
    """模型只能转述状态，不能改变状态或提出自动操作。"""

    model_config = ConfigDict(extra="forbid")

    current_stage: str
    execution_status: str | None = None
    analysis_status: str | None = None
    explanation_status: str | None = None

    plain_language_summary: str = Field(
        min_length=1,
        max_length=1000,
    )


def build_status_facts(
    report: RunStatusReport,
) -> dict[str, Any]:
    """只提取允许交给状态讲解模型的确定性事实。"""

    return {
        "project_name": report.project_name,
        "current_stage": report.current_stage,
        "prepare_status": report.prepare_status,
        "approval_status": report.approval_status,
        "execution_status": report.execution_status,
        "analysis_status": report.analysis_status,
        "explanation_status": (
            report.explanation_status
        ),
        "analysis_scope_level": (
            report.analysis_scope_level
        ),
        "candidate_count": report.candidate_count,
        "formal_candidate_recommendation_allowed": (
            report
            .formal_candidate_recommendation_allowed
        ),
        "approval_consumed": report.approval_consumed,
    }


def deterministic_summary(
    facts: dict[str, Any],
) -> str:
    """不依赖模型生成可靠的通俗状态摘要。"""

    stage = facts["current_stage"]
    explanation = facts["explanation_status"]

    if stage == "EMPTY":
        return (
            "当前还没有形成完整任务计划，"
            "也没有运行 BinderRanker。"
        )

    if stage == "PREPARED":
        return (
            "任务计划已经准备完成，"
            "但尚未批准，也没有开始科学计算。"
        )

    if stage == "APPROVED":
        return (
            "任务计划已经批准，"
            "但 BinderRanker 尚未真正开始运行。"
        )

    if stage == "RUNNING":
        return (
            "BinderRanker 正在运行。"
            "目前不应重复启动同一个任务。"
        )

    if stage == "EXECUTION_FAILED":
        return (
            "问题发生在 BinderRanker 执行阶段。"
            "本次执行没有产生可确认完整的排名结果。"
        )

    if stage == "EXECUTED":
        return (
            "BinderRanker 已经成功执行，"
            "原始结果已经生成，"
            "但还没有完成确定性结果分析。"
        )

    if stage == "ANALYZED":
        if explanation == "UNAVAILABLE":
            return (
                "BinderRanker 和确定性分析都已完成，"
                "排名与结构化结果仍然有效。"
                "目前只有大模型解释步骤不可用。"
            )

        if explanation == "FAILED":
            return (
                "BinderRanker 和确定性分析都已完成，"
                "但大模型解释步骤执行失败。"
                "这不会使已有确定性结果失效。"
            )

        return (
            "BinderRanker 和确定性分析都已完成，"
            "现在可以查看候选排名和分析结果。"
        )

    if stage == "EXPLAINED":
        return (
            "BinderRanker、确定性分析和大模型解释"
            "均已完成。"
        )

    return (
        "当前任务状态需要查看内部审计记录。"
        "请以随后列出的用户进度说明为准。"
    )


def completed_steps(
    facts: dict[str, Any],
) -> list[str]:
    values: list[str] = []

    if facts["prepare_status"] == "READY_FOR_REVIEW":
        values.append("任务计划已准备完成")

    if facts["approval_status"] == "APPROVED":
        values.append("任务计划已批准")

    if facts["execution_status"] == "COMPLETED":
        values.append("BinderRanker 执行已完成")

    if facts["analysis_status"] == "COMPLETED":
        values.append("确定性结果分析已完成")

    if facts["explanation_status"] == "EXPLAINED":
        values.append("大模型解释已生成")

    return values


def current_issue(
    facts: dict[str, Any],
) -> str:
    if facts["execution_status"] == "FAILED":
        return "执行阶段失败，不能把不完整输出当作排名结果。"

    if facts["analysis_status"] == "FAILED":
        return (
            "确定性分析阶段失败；"
            "已经完成的 BinderRanker 原始输出仍然保留。"
        )

    if facts["explanation_status"] == "UNAVAILABLE":
        return (
            "仅大模型解释增强功能不可用；"
            "确定性排名和分析结果不受影响。"
        )

    if facts["explanation_status"] == "FAILED":
        return (
            "仅大模型解释步骤失败；"
            "确定性结果仍然有效。"
        )

    return "未发现已记录的失败状态。"


def valid_results(
    facts: dict[str, Any],
) -> list[str]:
    values: list[str] = []

    if facts["execution_status"] == "COMPLETED":
        values.append("BinderRanker 原始输出")

    if facts["analysis_status"] == "COMPLETED":
        values.append("结构化结果摘要和确定性分析")

    if facts["explanation_status"] == "EXPLAINED":
        values.append("受证据约束的大模型解释")

    if not values:
        values.append("当前尚无可确认完成的科学结果")

    return values


def next_action(
    facts: dict[str, Any],
) -> str:
    stage = facts["current_stage"]

    actions = {
        "EMPTY": "直接描述任务和输入数据位置。",
        "PREPARED": "先查看完整计划，确认无误后再批准。",
        "APPROVED": "确认影响后，只启动当前已批准任务。",
        "RUNNING": "等待运行结束并再次查看状态。",
        "EXECUTION_FAILED": (
            "先查看失败证据并修正原因，"
            "确认后只重试失败的执行步骤。"
        ),
        "EXECUTED": "进行确定性结果分析。",
        "EXPLAINED": "查看结果，或提出新的只读分析问题。",
    }

    if stage == "ANALYZED":
        if facts["explanation_status"] in {
            "UNAVAILABLE",
            "FAILED",
        }:
            return (
                "可以直接使用现有确定性结果；"
                "模型恢复后只需重新尝试解释步骤，"
                "不需要重跑 BinderRanker。"
            )

        return "查看候选结果，或请求受证据约束的模型解释。"

    return actions.get(
        stage,
        "先查看状态明细，再决定下一步。",
    )


def build_model_messages(
    facts: dict[str, Any],
    fallback_summary: str,
) -> list[dict[str, str]]:
    schema = ModelStatusNarration.model_json_schema()

    return [
        {
            "role": "system",
            "content": (
                "你负责把任务状态转述成普通用户能理解的中文。"
                "只能依据给出的确定性事实，不得改变状态，"
                "不得声称未完成步骤已经完成，"
                "不得提出自动重试、删除、覆盖、批准或执行。"
                "只返回符合给定 Schema 的 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "facts": facts,
                    "deterministic_reference": (
                        fallback_summary
                    ),
                    "required_schema": schema,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def model_summary(
    *,
    provider: object | None,
    facts: dict[str, Any],
    fallback_summary: str,
    allow_model: bool,
) -> str:
    if (
        not allow_model
        or provider is None
        or not isinstance(
            provider,
            StructuredJSONProvider,
        )
    ):
        return fallback_summary

    try:
        payload = provider.generate_json(
            build_model_messages(
                facts,
                fallback_summary,
            )
        )
        narration = (
            ModelStatusNarration.model_validate(
                payload
            )
        )

        expected = {
            "current_stage": facts["current_stage"],
            "execution_status": (
                facts["execution_status"]
            ),
            "analysis_status": (
                facts["analysis_status"]
            ),
            "explanation_status": (
                facts["explanation_status"]
            ),
        }

        for field, value in expected.items():
            if getattr(narration, field) != value:
                raise ValueError(
                    f"模型改变了确定性状态字段：{field}"
                )

        return translate_internal_terms(
            narration.plain_language_summary.strip()
        )

    except Exception:
        return fallback_summary


def format_status_narration(
    *,
    bundle_dir: Path,
    provider: object | None,
    allow_model: bool,
) -> str:
    """生成模型可增强、但永不依赖模型成功的状态说明。"""

    report = inspect_run_status(
        bundle_dir.resolve()
    )
    facts = build_status_facts(report)
    fallback = deterministic_summary(facts)

    summary = model_summary(
        provider=provider,
        facts=facts,
        fallback_summary=fallback,
        allow_model=allow_model,
    )

    completed = completed_steps(facts)
    valid = valid_results(facts)

    return "\n".join(
        [
            "通俗说明：",
            summary,
            "",
            "已确认完成：",
            *(
                f"- {item}"
                for item in (
                    completed
                    or ["尚无已确认完成的主要步骤"]
                )
            ),
            "",
            "当前问题：",
            current_issue(facts),
            "",
            "仍然有效的产物：",
            *(f"- {item}" for item in valid),
            "",
            "最安全的下一步：",
            next_action(facts),
            "",
            "任务进度（来自确定性记录）：",
            f"项目：{facts['project_name']}",
            *format_user_progress(
                facts,
                include_explanation=True,
            ),
            (
                "结果使用范围："
                + user_scope(
                    facts["analysis_scope_level"]
                )
            ),
            (
                "候选数量："
                + (
                    str(facts["candidate_count"])
                    if facts["candidate_count"]
                    is not None
                    else "尚未确定"
                )
            ),
        ]
    )
