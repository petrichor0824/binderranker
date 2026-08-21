#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""把内部任务状态确定性地翻译为普通用户语言。"""

from __future__ import annotations

from typing import Literal, Mapping


StatusArea = Literal[
    "stage",
    "prepare",
    "approval",
    "execution",
    "analysis",
    "explanation",
]


_STAGE_LABELS = {
    "EMPTY": "尚未形成可执行计划",
    "PREPARED": "计划已准备，等待审查和批准",
    "APPROVED": "计划已批准，尚未执行",
    "RUNNING": "BinderRanker 正在执行",
    "EXECUTION_FAILED": "上次执行没有成功完成",
    "EXECUTED": "BinderRanker 已执行，等待结果分析",
    "ANALYZED": "确定性结果分析已完成",
    "EXPLAINED": "结果分析和模型解释已完成",
    "RECOVERY": "正在处理任务恢复请求",
}

_STATUS_LABELS: dict[StatusArea, dict[str, str]] = {
    "stage": _STAGE_LABELS,
    "prepare": {
        "NEEDS_INFORMATION": "等待补充任务信息",
        "READY_FOR_REVIEW": "计划已准备，等待审核",
        "BLOCKED": "暂时无法继续，需先解决阻塞问题",
        "MATERIALIZED": "项目配置已生成",
        "FAILED": "任务准备未完成",
    },
    "approval": {
        "APPROVED": "已批准",
        "FAILED": "批准未完成",
    },
    "execution": {
        "RUNNING": "正在运行",
        "COMPLETED": "已完成",
        "FAILED": "未完成",
    },
    "analysis": {
        "RUNNING": "正在分析",
        "COMPLETED": "已完成",
        "FAILED": "未完成",
        "ANALYZED": "已完成",
    },
    "explanation": {
        "EXPLAINED": "已生成",
        "COMPLETED": "已生成",
        "UNAVAILABLE": "暂不可用",
        "FAILED": "未生成",
    },
}

_MISSING_LABELS: dict[StatusArea, str] = {
    "stage": "尚未确定",
    "prepare": "尚未准备",
    "approval": "尚未批准",
    "execution": "尚未执行",
    "analysis": "尚未分析",
    "explanation": "尚未生成",
}

_SCOPE_LABELS = {
    "SMOKE_TEST_ONLY": (
        "工程冒烟测试（不可作为正式科研结论）"
    ),
    "EXPLORATORY": "探索性批内比较",
    "FULL_DATASET_ANALYSIS": "完整数据集分析",
}

_PENDING_ACTION_LABELS = {
    "APPROVE": "批准计划",
    "EXECUTE": "运行 BinderRanker",
    "ANALYZE": "分析结果",
    "EXPLAIN": "生成模型解释",
    "ADOPT_DATASET_ADVICE": "采用文件检查建议",
    "CREATE_DATASET_GROUP_TASKS": "创建分组任务",
    "RESET_TASK": "重新开始当前任务",
    "ARCHIVE_TASK": "归档当前任务并重新开始",
}

_LIFECYCLE_LABELS = {
    "EMPTY": "空任务",
    "INCOMPLETE": "尚未完成的任务",
    "VALID_WITH_EVIDENCE": "包含受保护证据的任务",
}

_PLAN_STEP_LABELS = {
    "PENDING": "等待处理",
    "READY": "可以开始",
    "BLOCKED": "等待前置信息",
}

_INTERNAL_TERM_REPLACEMENTS = (
    (
        "只有 READY_FOR_REVIEW 任务可以批准",
        "只有计划准备完整并可供审核的任务才能批准",
    ),
    (
        "只有 READY_FOR_REVIEW 计划可以落地为正式项目配置",
        "只有准备完整并可供审核的计划才能落地为正式项目配置",
    ),
    (
        "准备工作流没有停在 READY_FOR_REVIEW",
        "任务准备流程尚未形成可供审核的完整计划",
    ),
    (
        "工作流不处于 READY_FOR_REVIEW",
        "任务工作流尚未形成可供审核的完整计划",
    ),
    (
        "FULL_DATASET_ANALYSIS",
        "完整数据集分析",
    ),
    (
        "SMOKE_TEST_ONLY",
        "工程冒烟测试范围",
    ),
    (
        "READY_FOR_REVIEW",
        "可供审核的完整计划",
    ),
    (
        "NEEDS_INFORMATION",
        "等待补充任务信息",
    ),
    (
        "AWAITING_CONFIRMATION",
        "等待用户确认",
    ),
    (
        "EXECUTION_FAILED",
        "执行未完成",
    ),
    ("EXPLORATORY", "探索性分析"),
    ("APPROVED", "已批准"),
    ("COMPLETED", "已完成"),
    ("RUNNING", "正在运行"),
    ("ANALYZED", "已完成分析"),
    ("EXPLAINED", "已生成解释"),
    ("PREPARED", "计划已建立"),
    ("UNAVAILABLE", "暂不可用"),
    ("FAILED", "未完成"),
    ("EMPTY", "尚未建立任务"),
)


def user_status(
    value: object,
    *,
    area: StatusArea,
) -> str:
    """返回不泄露未知内部枚举值的状态说明。"""
    if value is None:
        return _MISSING_LABELS[area]

    clean = str(value).strip()

    if not clean:
        return _MISSING_LABELS[area]

    return _STATUS_LABELS[area].get(
        clean,
        "状态需要查看内部审计记录",
    )


def user_scope(value: object) -> str:
    """把分析范围枚举翻译为科研边界清晰的说明。"""
    if value is None or not str(value).strip():
        return "尚未确定"

    return _SCOPE_LABELS.get(
        str(value).strip(),
        "范围需要查看内部审计记录",
    )


def pending_action_label(value: object) -> str:
    """返回待确认动作的人类可读名称。"""
    return _PENDING_ACTION_LABELS.get(
        str(value).strip(),
        "当前操作",
    )


def lifecycle_state_label(value: object) -> str:
    """返回任务恢复流程使用的生命周期说明。"""
    return _LIFECYCLE_LABELS.get(
        str(value).strip(),
        "需要查看内部审计记录的任务",
    )


def plan_step_status_label(value: object) -> str:
    """返回计划步骤的用户可读状态。"""
    return _PLAN_STEP_LABELS.get(
        str(value).strip(),
        "状态需要查看内部审计记录",
    )


def translate_internal_terms(value: str) -> str:
    """替换允许出现在内部诊断、但不应直出的枚举词。"""
    translated = value

    for internal, public in (
        _INTERNAL_TERM_REPLACEMENTS
    ):
        translated = translated.replace(
            internal,
            public,
        )

    return translated


def format_user_progress(
    state: Mapping[str, object],
    *,
    include_explanation: bool = False,
) -> list[str]:
    """将状态记录格式化为稳定、可读的进度明细。"""
    lines = [
        (
            "总体："
            + user_status(
                state.get("current_stage"),
                area="stage",
            )
        ),
        (
            "准备："
            + user_status(
                state.get("prepare_status"),
                area="prepare",
            )
        ),
        (
            "批准："
            + user_status(
                state.get("approval_status"),
                area="approval",
            )
        ),
        (
            "执行："
            + user_status(
                state.get("execution_status"),
                area="execution",
            )
        ),
        (
            "分析："
            + user_status(
                state.get("analysis_status"),
                area="analysis",
            )
        ),
    ]

    if include_explanation:
        lines.append(
            "模型解释："
            + user_status(
                state.get(
                    "explanation_status"
                ),
                area="explanation",
            )
        )

    return lines


def next_safe_action_for_stage(
    stage: object,
) -> str | None:
    """根据确定性阶段给出单一、保守的下一步。"""
    actions = {
        "EMPTY": "直接描述任务目标和 PDB 数据位置。",
        "PREPARED": "先查看计划；信息完整且无误后再申请批准。",
        "APPROVED": "确认执行影响后，再单独申请运行 BinderRanker。",
        "RUNNING": "等待当前运行结束，不要重复启动同一任务。",
        "EXECUTION_FAILED": (
            "保留现有 Bundle，先检查失败证据并修正原因。"
        ),
        "EXECUTED": "只运行确定性结果分析，不需要重跑 BinderRanker。",
        "ANALYZED": "查看现有确定性结果，或按需请求模型解释。",
        "EXPLAINED": "查看现有结果，或提出新的只读分析问题。",
    }

    return actions.get(str(stage).strip())
