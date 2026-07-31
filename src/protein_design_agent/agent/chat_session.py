#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Protein Design Agent 第一版安全聊天状态机。

自然语言只用于：
- 创建任务；
- 补充 NEEDS_INFORMATION 会话。

具有副作用的动作只能由固定短语触发：
- 批准计划
- 批准计划并确认小样本限制
- 确认执行
- 分析结果
- 分析并解释结果

大模型不能生成 Shell，也不能直接批准或执行任务。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from protein_design_agent.agent.analyze_run import (
    run_analyze_run,
)
from protein_design_agent.agent.approval import (
    create_approval_record,
)
from protein_design_agent.agent.local_executor import (
    execute_approved_binderranker,
)
from protein_design_agent.agent.natural_language_prepare import (
    prepare_from_natural_language,
)
from protein_design_agent.agent.ranker_result_parser import (
    RankerResultSummary,
    parse_completed_ranker_run,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
    StructuredJSONProvider,
)
from protein_design_agent.agent.resume_planning import (
    resume_planning_session,
)
from protein_design_agent.agent.run_status import (
    inspect_run_status,
)


ChatAction = Literal[
    "HELP",
    "STATUS",
    "VIEW_PLAN",
    "PREPARE",
    "RESUME",
    "APPROVE",
    "EXECUTE",
    "ANALYZE",
    "EXPLAIN",
    "INSPECT_DATASET",
    "ADOPT_DATASET_ADVICE",
    "LIST_TASKS",
    "SWITCH_TASK",
]


RESULT_PREVIEW_LIMIT = 5

COMPONENT_SCORE_LABELS = {
    "score_line": "线性界面适配",
    "score_plane": "平面界面适配",
    "score_compact": "紧凑界面适配",
    "score_roughness": "表面平滑性",
    "score_microfit": "局部微环境适配",
    "score_safety": "几何安全性",
    "score_region": "目标区域匹配",
    "score_hotspot": "热点覆盖",
}


def format_component_strengths(
    component_scores: dict[str, float],
    *,
    limit: int = 2,
) -> str:
    """
    展示已经统一为“越高越好”的组件高分。

    这里只读取 Ranker 已计算的组件分数，
    不重新计算，也不根据指标名称猜测方向。
    """
    ranked: list[tuple[str, float]] = []

    for name, value in component_scores.items():
        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            numeric != numeric
            or numeric == float("inf")
            or numeric == float("-inf")
        ):
            continue

        ranked.append((name, numeric))

    ranked.sort(
        key=lambda item: (
            -item[1],
            item[0],
        )
    )

    selected = ranked[:limit]

    if not selected:
        return "未提供"

    return "、".join(
        (
            f"{COMPONENT_SCORE_LABELS.get(name, name)} "
            f"{value:.3f}"
        )
        for name, value in selected
    )


def format_pool_summary(
    summary: RankerResultSummary,
) -> str:
    """按照既有发布政策展示候选池。"""
    view = getattr(
        summary,
        "pool_reporting",
        None,
    )
    policy = getattr(view, "policy", None)
    mode = str(
        getattr(
            policy,
            "reporting_mode",
            "UNKNOWN",
        )
    )

    if mode == "SUPPRESSED":
        return (
            "候选池：按 SMOKE_TEST_ONLY "
            "发布政策隐藏"
        )

    counts = (
        getattr(
            view,
            "public_pool_counts",
            {},
        )
        or {}
    )
    candidates = sorted(
        getattr(
            summary,
            "candidates_by_engineering_rank",
            [],
        ),
        key=lambda item: item.engineering_rank,
    )

    definitions = (
        ("broad", "宽松", "broad_pass"),
        ("medium", "中等", "medium_pass"),
        ("strict", "严格", "strict_pass"),
    )

    lines = ["候选池摘要："]

    for key, label, flag in definitions:
        count = counts.get(key)

        if count is None:
            lines.append(
                f"{label}：按发布政策隐藏"
            )
            continue

        if mode != "STANDARD":
            lines.append(
                f"{label}：{count} 个"
            )
            continue

        members = [
            item.pdb_name
            for item in candidates
            if bool(getattr(item, flag, False))
        ]
        shown = members[:5]

        if not shown:
            member_display = "无"
        else:
            member_display = "、".join(shown)
            if len(members) > len(shown):
                member_display += " 等"

        lines.append(
            f"{label}：{count} 个；"
            f"排名靠前成员：{member_display}"
        )

    if mode == "EXPLORATORY":
        lines.append(
            "说明：以上池数量仅为批内探索结果，"
            "不能单独支持正式候选推荐。"
        )

    return "\n".join(lines)


def format_result_provenance(
    summary: RankerResultSummary,
) -> str:
    """展示结构化结果的确定性证据标识。"""
    provenance = getattr(
        summary,
        "result_provenance",
        None,
    )

    if provenance is None:
        return "确定性证据：当前摘要未提供"

    execution = getattr(
        provenance,
        "execution_manifest",
        None,
    )
    digest = str(
        getattr(execution, "sha256", "")
    )
    outputs = (
        getattr(
            provenance,
            "verified_output_files",
            {},
        )
        or {}
    )

    return (
        "确定性证据：执行清单 SHA256 "
        f"{digest}；"
        f"已验证原始输出 {len(outputs)} 个"
    )


def format_execution_result_preview(
    summary: RankerResultSummary,
) -> str:
    """生成不依赖大模型的执行结果预览。"""
    candidates = sorted(
        summary.candidates_by_engineering_rank,
        key=lambda item: item.engineering_rank,
    )[:RESULT_PREVIEW_LIMIT]

    scope_level = str(
        summary.analysis_scope.get(
            "level",
            "UNKNOWN",
        )
    )

    lines = [
        "",
        (
            "结果预览："
            f"共 {summary.candidate_count} 个候选，"
            f"显示前 {len(candidates)} 名"
        ),
        f"分析范围：{scope_level}",
        format_pool_summary(summary),
        format_result_provenance(summary),
        "",
    ]

    for candidate in candidates:
        filter_display = (
            candidate.public_filter_level
            or candidate.public_filter_status
        )

        if (
            candidate
            .filter_reasons_formally_interpretable
        ):
            reasons = (
                candidate.strict_reasons
                or candidate.medium_reasons
                or candidate.broad_reasons
            )
            reason_display = (
                "、".join(reasons[:3])
                if reasons
                else "未记录过滤拖累"
            )
        else:
            reason_display = (
                "当前样本范围不展示阈值拖累"
            )

        strength_display = (
            format_component_strengths(
                getattr(
                    candidate,
                    "component_scores",
                    {},
                )
            )
        )

        lines.append(
            f"{candidate.engineering_rank}. "
            f"{candidate.pdb_name} | "
            f"总分 {candidate.final_score_v4:.4f} | "
            f"过滤 {filter_display} | "
            "主要优势（高分组件） "
            f"{strength_display} | "
            f"主要拖累 {reason_display}"
        )

    if not (
        summary
        .formal_candidate_recommendation_allowed
    ):
        lines.extend(
            [
                "",
                (
                    "注意：当前范围不允许把该排序"
                    "作为正式候选推荐或科研结论。"
                ),
            ]
        )

    return "\n".join(lines)


class ChatSessionError(RuntimeError):
    """聊天状态机拒绝或无法完成当前动作。"""


class ChatTurnResult(BaseModel):
    """一次聊天消息处理结果。"""

    schema_version: str = "0.1"

    action: ChatAction
    status: str
    message: str

    bundle_dir: Path
    artifact_paths: dict[str, Path] = Field(
        default_factory=dict
    )


HELP_COMMANDS = {
    "帮助",
    "help",
    "/help",
}

STATUS_COMMANDS = {
    "状态",
    "查看状态",
    "当前状态",
    "status",
    "/status",
}

APPROVE_COMMANDS = {
    "批准计划": False,
    "批准计划并确认小样本限制": True,
}

EXECUTE_COMMANDS = {
    "确认执行",
}

ANALYZE_COMMANDS = {
    "分析结果": False,
    "分析并解释结果": True,
}


def normalize_message(value: str) -> str:
    """去除首尾空白，但不改写用户科研文本。"""
    clean = value.strip()

    if not clean:
        raise ChatSessionError(
            "输入内容不能为空"
        )

    return clean


def load_prepare_status(
    bundle_dir: Path,
) -> str | None:
    """读取准备清单状态。"""
    manifest_path = (
        bundle_dir
        / "agent_prepare_manifest.json"
    )

    if not manifest_path.is_file():
        return None

    try:
        value = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise ChatSessionError(
            "无法读取准备清单："
            f"{manifest_path}；{exc}"
        ) from exc

    if not isinstance(value, dict):
        raise ChatSessionError(
            "准备清单必须是 JSON 对象："
            f"{manifest_path}"
        )

    status = value.get("status")

    return (
        str(status)
        if status is not None
        else None
    )


def bundle_is_empty(
    bundle_dir: Path,
) -> bool:
    if not bundle_dir.exists():
        return True

    if not bundle_dir.is_dir():
        raise ChatSessionError(
            f"Bundle 路径不是目录：{bundle_dir}"
        )

    return not any(
        bundle_dir.iterdir()
    )


def format_status_message(
    bundle_dir: Path,
) -> str:
    try:
        report = inspect_run_status(
            bundle_dir
        )
    except Exception as exc:
        raise ChatSessionError(
            f"无法检查任务状态：{exc}"
        ) from exc

    lines = [
        f"项目：{report.project_name}",
        f"当前阶段：{report.current_stage}",
        (
            "准备："
            f"{report.prepare_status or '未发现'}"
        ),
        (
            "批准："
            f"{report.approval_status or '未发现'}"
        ),
        (
            "执行："
            f"{report.execution_status or '未发现'}"
        ),
        (
            "分析："
            f"{report.analysis_status or '未发现'}"
        ),
        (
            "模型解释："
            f"{report.explanation_status or '未发现'}"
        ),
    ]

    if report.analysis_scope_level:
        lines.append(
            "分析级别："
            f"{report.analysis_scope_level}"
        )

    if report.candidate_count is not None:
        lines.append(
            f"候选数量：{report.candidate_count}"
        )

    if report.approval_consumed is True:
        lines.append("一次性批准：已消耗")
    elif report.approval_consumed is False:
        lines.append("一次性批准：尚未消耗")

    return "\n".join(lines)


def help_message() -> str:
    return "\n".join(
        [
            "你可以直接用自然语言和我交流，例如：",
            "",
            "• “分析这个目录里的 PDB 骨架。”",
            "• “target 和 binder 拼在同一条 A 链里。”",
            "• “前 132 个残基是 target，从第 4 号开始。”",
            "• “这个方案可以，批准吧。”",
            "• “开始运行。”",
            "• “帮我分析一下结果。”",
            "• “把结果也解释一下。”",
            "",
            "当任务信息不足时，我会主动提问，"
            "不会要求你填写内部字段名。",
            "",
            "批准、执行和模型分析等动作"
            "不会因为一句模糊的话直接发生。"
            "我会先复述即将进行的操作，"
            "然后请你回答“确认”或“取消”。",
            "",
            "你仍然可以输入：",
            "• “状态”查看当前任务阶段；",
            "• “帮助”重新查看说明；",
            "• “退出”结束本次会话。",
        ]
    )


def next_analysis_directory(
    *,
    bundle_dir: Path,
    with_model: bool,
) -> Path:
    """
    生成不覆盖历史结果的相对分析目录。
    """
    analyses_root = (
        bundle_dir / "analyses"
    )

    prefix = (
        "chat_model"
        if with_model
        else "chat_deterministic"
    )

    index = 1

    while True:
        name = f"{prefix}_{index:04d}"
        candidate = analyses_root / name

        if not candidate.exists():
            return Path("analyses") / name

        index += 1


def process_chat_message(
    *,
    message: str,
    bundle_dir: Path,
    provider: (
        RequestParserProvider
        | StructuredJSONProvider
        | None
    ),
    approved_by: str,
    model_config_path: Path | None,
    profile_name: str | None,
    allow_network: bool,
) -> ChatTurnResult:
    """
    处理一条用户聊天消息。

    该函数不使用模型判断批准或执行意图。
    """
    clean = normalize_message(message)
    bundle = bundle_dir.resolve()

    if clean.lower() in HELP_COMMANDS:
        return ChatTurnResult(
            action="HELP",
            status="HELP",
            message=help_message(),
            bundle_dir=bundle,
        )

    if clean.lower() in STATUS_COMMANDS:
        if not bundle.is_dir():
            raise ChatSessionError(
                f"任务目录尚不存在：{bundle}"
            )

        return ChatTurnResult(
            action="STATUS",
            status="STATUS",
            message=format_status_message(
                bundle
            ),
            bundle_dir=bundle,
        )

    if clean in APPROVE_COMMANDS:
        prepare_status = load_prepare_status(
            bundle
        )

        if prepare_status != "READY_FOR_REVIEW":
            raise ChatSessionError(
                "只有 READY_FOR_REVIEW 任务"
                "才能批准；当前状态为 "
                f"{prepare_status!r}"
            )

        approval_path = (
            bundle / "approval.json"
        )

        if approval_path.exists():
            raise ChatSessionError(
                "批准记录已经存在，禁止覆盖："
                f"{approval_path}"
            )

        acknowledge_smoke_test = (
            APPROVE_COMMANDS[clean]
        )

        try:
            record = create_approval_record(
                prepare_manifest_path=(
                    bundle
                    / "agent_prepare_manifest.json"
                ),
                output_path=approval_path,
                approved_by=approved_by,
                approval_note=(
                    "Approved through "
                    "Protein Design Agent chat"
                ),
                acknowledge_smoke_test=(
                    acknowledge_smoke_test
                ),
            )
        except Exception as exc:
            raise ChatSessionError(
                f"批准计划失败：{exc}"
            ) from exc

        return ChatTurnResult(
            action="APPROVE",
            status=record.status,
            message="\n".join(
                [
                    "计划已批准，但尚未执行。",
                    f"批准 ID：{record.approval_id}",
                    (
                        "分析级别："
                        f"{record.analysis_scope_level}"
                    ),
                    (
                        "请输入“确认执行”"
                        "才会运行 BinderRanker。"
                    ),
                ]
            ),
            bundle_dir=bundle,
            artifact_paths={
                "approval": approval_path,
            },
        )

    if clean in EXECUTE_COMMANDS:
        approval_path = (
            bundle / "approval.json"
        )

        if not approval_path.is_file():
            raise ChatSessionError(
                "尚未找到批准记录，"
                "请先批准计划"
            )

        try:
            result = (
                execute_approved_binderranker(
                    approval_path=approval_path,
                    confirm_execute=True,
                )
            )
        except Exception as exc:
            raise ChatSessionError(
                f"BinderRanker 执行失败：{exc}"
            ) from exc

        try:
            parsed_summary = (
                parse_completed_ranker_run(
                    bundle
                )
            )
            result_preview = (
                format_execution_result_preview(
                    parsed_summary
                )
            )
        except Exception as exc:
            # BinderRanker 已经成功完成。
            # 预览失败不得把执行结果改成失败。
            result_preview = "\n".join(
                [
                    "",
                    "结果预览暂不可用。",
                    (
                        "这不影响已经完成的 "
                        "BinderRanker 执行及原始输出。"
                    ),
                    (
                        "预览错误："
                        f"{type(exc).__name__}: {exc}"
                    ),
                ]
            )

        return ChatTurnResult(
            action="EXECUTE",
            status=result.status,
            message="\n".join(
                [
                    "BinderRanker 执行完成。",
                    (
                        "输出文件数量："
                        f"{len(result.output_files)}"
                    ),
                    result_preview,
                    (
                        "一次性批准已经消耗，"
                        "不能再次使用。"
                    ),
                    (
                        "输入“分析结果”"
                        "进行确定性分析；"
                    ),
                    (
                        "输入“分析并解释结果”"
                        "同时生成模型解释。"
                    ),
                ]
            ),
            bundle_dir=bundle,
            artifact_paths={
                "execution_manifest": (
                    result.execution_manifest
                ),
                "stdout_log": result.stdout_log,
                "stderr_log": result.stderr_log,
            },
        )

    if clean in ANALYZE_COMMANDS:
        with_model = ANALYZE_COMMANDS[clean]

        try:
            report = inspect_run_status(bundle)
        except Exception as exc:
            raise ChatSessionError(
                f"无法检查执行状态：{exc}"
            ) from exc

        if report.execution_status != "COMPLETED":
            raise ChatSessionError(
                "只有执行状态为 COMPLETED "
                "时才能分析；当前状态为 "
                f"{report.execution_status!r}"
            )

        if with_model:
            if not allow_network:
                raise ChatSessionError(
                    "模型解释需要在启动 chat 时"
                    "显式提供 --allow-network"
                )

            if model_config_path is None:
                raise ChatSessionError(
                    "模型解释需要 model_config_path"
                )

        analysis_dir = next_analysis_directory(
            bundle_dir=bundle,
            with_model=with_model,
        )

        try:
            result = run_analyze_run(
                bundle_dir=bundle,
                analysis_dir=analysis_dir,
                with_model=with_model,
                model_config_path=(
                    model_config_path
                    if with_model
                    else None
                ),
                profile_name=(
                    profile_name
                    if with_model
                    else None
                ),
                allow_network=(
                    allow_network
                    if with_model
                    else False
                ),
            )
        except Exception as exc:
            raise ChatSessionError(
                f"结果分析失败：{exc}"
            ) from exc

        artifacts = {
            "analysis_manifest": (
                result.manifest_path
            ),
            "result_summary": (
                result.result_summary_path
            ),
            "failure_analysis": (
                result.failure_analysis_path
            ),
        }

        if (
            result.explanation_markdown_path
            is not None
        ):
            artifacts[
                "explanation_markdown"
            ] = (
                result.explanation_markdown_path
            )

        explanation_status = getattr(
            result,
            "explanation_status",
            None,
        )

        if (
            with_model
            and explanation_status == "UNAVAILABLE"
        ):
            error_type = (
                getattr(
                    result,
                    "explanation_error_type",
                    None,
                )
                or "模型解释错误"
            )
            error_message = (
                getattr(
                    result,
                    "explanation_error_message",
                    None,
                )
                or "未提供详细错误信息"
            )

            completion_message = "\n".join(
                [
                    (
                        "确定性分析完成，"
                        "但模型解释暂不可用。"
                    ),
                    (
                        "结果摘要和失败分析"
                        "已经完整保留。"
                    ),
                    (
                        f"解释错误：{error_type}: "
                        f"{error_message}"
                    ),
                ]
            )
        elif with_model:
            completion_message = (
                "分析与模型解释完成。"
            )
        else:
            completion_message = (
                "确定性分析完成。"
            )

        return ChatTurnResult(
            action=(
                "EXPLAIN"
                if with_model
                else "ANALYZE"
            ),
            status=result.status,
            message="\n".join(
                [
                    completion_message,
                    (
                        "分析目录："
                        f"{result.analysis_dir}"
                    ),
                    (
                        "结果摘要："
                        f"{result.result_summary_path}"
                    ),
                    (
                        (
                            "模型报告："
                            f"{result.explanation_markdown_path}"
                        )
                        if with_model
                        else (
                            "本次没有调用大模型。"
                        )
                    ),
                ]
            ),
            bundle_dir=bundle,
            artifact_paths=artifacts,
        )

    prepare_status = load_prepare_status(
        bundle
    )

    if bundle_is_empty(bundle):
        if not allow_network:
            raise ChatSessionError(
                "解析新任务需要显式允许模型联网"
            )

        if not isinstance(
            provider,
            RequestParserProvider,
        ):
            raise ChatSessionError(
                "当前 Provider 不支持自然语言请求解析"
            )

        try:
            result = prepare_from_natural_language(
                raw_text=clean,
                provider=provider,
                bundle_dir=bundle,
            )
        except Exception as exc:
            raise ChatSessionError(
                f"自然语言任务准备失败：{exc}"
            ) from exc

        if result.status == "NEEDS_INFORMATION":
            message_text = "\n".join(
                [
                    "任务信息尚不完整。",
                    "仍需补充：",
                    *[
                        f"- {item}"
                        for item in (
                            result.missing_information
                        )
                    ],
                    "请直接用自然语言补充这些参数。",
                ]
            )
        else:
            message_text = "\n".join(
                [
                    "任务已经准备完成。",
                    f"项目：{result.project_name}",
                    "当前状态：READY_FOR_REVIEW",
                    (
                        "检查计划后输入“批准计划”。"
                    ),
                    (
                        "小样本任务需要输入"
                        "“批准计划并确认小样本限制”。"
                    ),
                ]
            )

        return ChatTurnResult(
            action="PREPARE",
            status=result.status,
            message=message_text,
            bundle_dir=bundle,
            artifact_paths={
                "planning_session": (
                    result.planning_session
                ),
                "prepare_manifest": (
                    result.prepare_manifest
                ),
            },
        )

    if prepare_status == "NEEDS_INFORMATION":
        if not allow_network:
            raise ChatSessionError(
                "解析补充信息需要显式允许模型联网"
            )

        if not isinstance(
            provider,
            StructuredJSONProvider,
        ):
            raise ChatSessionError(
                "当前 Provider 不支持结构化补充解析"
            )

        try:
            result = resume_planning_session(
                bundle_dir=bundle,
                supplement_text=clean,
                provider=provider,
            )
        except Exception as exc:
            raise ChatSessionError(
                f"补充规划信息失败：{exc}"
            ) from exc

        if result.status == "NEEDS_INFORMATION":
            message_text = "\n".join(
                [
                    "补充内容已保存。",
                    "目前仍需补充：",
                    *[
                        f"- {item}"
                        for item in (
                            result.missing_information
                        )
                    ],
                ]
            )
        else:
            message_text = "\n".join(
                [
                    "必要信息已经补齐。",
                    "当前状态：READY_FOR_REVIEW",
                    (
                        "检查计划后输入“批准计划”。"
                    ),
                    (
                        "小样本任务需要输入"
                        "“批准计划并确认小样本限制”。"
                    ),
                ]
            )

        return ChatTurnResult(
            action="RESUME",
            status=result.status,
            message=message_text,
            bundle_dir=bundle,
            artifact_paths={
                "planning_session": (
                    result.planning_session
                ),
                "prepare_manifest": (
                    result.prepare_manifest
                ),
                "history_record": (
                    result.history_record
                ),
            },
        )

    raise ChatSessionError(
        "当前任务已经不是待补充状态。"
        "请输入“状态”查看当前阶段，"
        "或使用明确操作短语继续。"
    )
