#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""从确定性 Bundle 证据重建 Chat 启动摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protein_design_agent.agent.chat_dialogue import (
    PendingChatAction,
    bundle_state_digest,
    load_pending_action,
)
from protein_design_agent.agent.plan_materializer import (
    load_planning_session,
)
from protein_design_agent.agent.run_status import (
    RunStatusReport,
    inspect_run_status,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)


PENDING_ACTION_LABELS = {
    "APPROVE": "批准计划",
    "EXECUTE": "执行 BinderRanker",
    "ANALYZE": "分析结果",
    "EXPLAIN": "生成模型解释",
    "ADOPT_DATASET_ADVICE": "采用数据集检查建议",
    "CREATE_DATASET_GROUP_TASKS": "创建分组任务",
    "RESET_TASK": "重置当前任务",
    "ARCHIVE_TASK": "归档当前任务",
}


MISSING_INFORMATION_LABELS = {
    "input_dir": "PDB 数据目录",
    "input_layout": "PDB 链布局",
    "binder_chain": "binder 链",
    "source_chain": "拼接数据的源链",
    "target_residue_count": "target 残基数量",
    "distinct_normalized_chain_ids": (
        "不同的标准化 target/binder 链名"
    ),
    "desired_regions_or_hotspots": (
        "目标区域或 hotspot"
    ),
    "region_filter_soft_or_strict": (
        "区域过滤方式"
    ),
}


@dataclass(frozen=True)
class TaskRecoverySnapshot:
    """一次只读恢复检查得到的确定性事实。"""

    bundle_dir: Path
    report: RunStatusReport | None
    planning_session: PlanningSession | None
    pending_action: PendingChatAction | None
    pending_is_current: bool | None
    unreadable_components: tuple[str, ...]


def collect_task_recovery_snapshot(
    bundle_dir: Path,
) -> TaskRecoverySnapshot:
    """分别读取各类证据，单个损坏记录不遮蔽其余状态。"""
    bundle = bundle_dir.expanduser().resolve()
    unreadable: list[str] = []

    try:
        report = inspect_run_status(bundle)
    except Exception:
        report = None
        unreadable.append("任务阶段")

    session_path = bundle / "planning_session.json"
    planning_session: PlanningSession | None = None

    if session_path.is_file():
        try:
            planning_session = load_planning_session(
                session_path
            )
        except Exception:
            unreadable.append("规划上下文")

    try:
        pending_action = load_pending_action(bundle)
    except Exception:
        pending_action = None
        unreadable.append("待确认动作")

    pending_is_current: bool | None = None

    if pending_action is not None:
        try:
            pending_is_current = (
                pending_action.state_digest
                == bundle_state_digest(bundle)
            )
        except Exception:
            unreadable.append(
                "待确认动作有效性"
            )

    return TaskRecoverySnapshot(
        bundle_dir=bundle,
        report=report,
        planning_session=planning_session,
        pending_action=pending_action,
        pending_is_current=pending_is_current,
        unreadable_components=tuple(
            unreadable
        ),
    )


def format_stage_summary(
    snapshot: TaskRecoverySnapshot,
) -> str:
    """把内部状态转换为普通用户可理解的进度。"""
    session = snapshot.planning_session
    report = snapshot.report

    if (
        session is not None
        and session.plan.status
        == "NEEDS_INFORMATION"
    ):
        return "规划尚未完成，正在等待补充信息"

    if report is None:
        return "现有任务阶段无法可靠读取"

    labels = {
        "EMPTY": "尚未形成可执行计划",
        "PREPARED": "计划已准备，等待审查和批准",
        "APPROVED": "计划已批准，尚未执行",
        "RUNNING": "BinderRanker 正在执行",
        "EXECUTION_FAILED": "上次执行没有成功完成",
        "EXECUTED": "BinderRanker 已执行，等待结果分析",
        "ANALYZED": "确定性结果分析已完成",
        "EXPLAINED": "结果分析和模型解释已完成",
    }

    return labels.get(
        report.current_stage,
        "任务已存在，当前进度未知",
    )


def format_confirmed_request(
    session: PlanningSession | None,
) -> str | None:
    """只展示有显式来源记录的科研输入。"""
    if session is None:
        return None

    explicit_fields = (
        session.request_explicit_fields
    )

    if explicit_fields is None:
        return (
            "旧版规划没有字段来源记录，"
            "因此不把默认值表述为用户已确认信息"
        )

    explicit = set(explicit_fields)
    request = session.request
    items: list[str] = []

    if (
        "input_dir" in explicit
        and request.input_dir is not None
    ):
        items.append(
            f"PDB 目录 {request.input_dir}"
        )

    if (
        "input_layout" in explicit
        and request.input_layout is not None
    ):
        layout = {
            "existing_chains": "target/binder 已分链",
            "concatenated_single_chain": (
                "target/binder 位于同一源链"
            ),
        }.get(
            request.input_layout,
            request.input_layout,
        )
        items.append(f"链布局 {layout}")

    if (
        "binder_chain" in explicit
        and request.binder_chain
    ):
        items.append(
            f"binder 链 {request.binder_chain}"
        )

    if (
        "target_chains" in explicit
        and request.target_chains
    ):
        items.append(
            "target 链 "
            + ", ".join(
                request.target_chains
            )
        )

    if (
        "source_chain" in explicit
        and request.source_chain
    ):
        items.append(
            f"源链 {request.source_chain}"
        )

    if (
        "target_residue_count" in explicit
        and request.target_residue_count
        is not None
    ):
        items.append(
            "target 残基数 "
            f"{request.target_residue_count}"
        )

    if not items:
        return "尚无可安全恢复的显式科研输入"

    return "；".join(items)


def format_missing_information(
    session: PlanningSession | None,
) -> str | None:
    if session is None:
        return None

    missing = session.plan.missing_information

    if not missing:
        return None

    return "、".join(
        MISSING_INFORMATION_LABELS.get(
            value,
            value,
        )
        for value in missing
    )


def recommended_next_action(
    snapshot: TaskRecoverySnapshot,
    *,
    model_status: str,
) -> str:
    """根据确定性阶段给出一个不会跨越安全边界的下一步。"""
    pending = snapshot.pending_action

    if pending is not None:
        if snapshot.pending_is_current is True:
            return (
                "上次操作仍在等待确认。"
                "输入“确认”继续，或输入“取消”放弃；"
                "重启 Chat 本身没有执行该操作。"
            )

        return (
            "上次待确认操作已失效或无法验证。"
            "请先输入“取消”清理旧确认，再输入“状态”。"
        )

    session = snapshot.planning_session

    if (
        session is not None
        and session.plan.missing_information
    ):
        return (
            "直接用自然语言补充上面列出的信息；"
            "Agent 不会自行猜测。"
        )

    report = snapshot.report

    if report is None:
        return (
            "先输入“状态”重新检查；"
            "在状态可靠前不要删除或覆盖现有 Bundle。"
        )

    stage_actions = {
        "EMPTY": (
            "输入“查看计划”；如果没有可审查计划，"
            "请继续描述任务需求。"
        ),
        "PREPARED": (
            "输入“查看计划”审查参数；确认无误后再请求批准。"
        ),
        "APPROVED": (
            "可以说“开始运行”；Agent 会先复述影响并等待确认。"
        ),
        "RUNNING": (
            "输入“状态”查看进度；不要同时发起第二次执行。"
        ),
        "EXECUTION_FAILED": (
            "输入“状态”查看失败阶段并保留现有日志；"
            "不要直接覆盖已有证据。"
        ),
        "EXECUTED": (
            "输入“分析结果”运行只读的确定性分析。"
        ),
        "EXPLAINED": (
            "输入“状态”或查看已有结果；"
            "开始新任务时请切换到独立任务。"
        ),
    }

    if report.current_stage == "ANALYZED":
        if model_status == "READY":
            return (
                "可以查看确定性结果，或请求“分析并解释结果”；"
                "模型解释仍会单独确认。"
            )

        return (
            "可以查看确定性结果；"
            "模型解释需要先按上方指引启用模型。"
        )

    return stage_actions.get(
        report.current_stage,
        "输入“状态”查看当前证据和建议步骤。",
    )


def format_task_recovery_summary(
    snapshot: TaskRecoverySnapshot,
    *,
    model_status: str,
) -> str:
    """生成不依赖模型、不会修改 Bundle 的启动摘要。"""
    report = snapshot.report
    session = snapshot.planning_session
    project_name = (
        report.project_name
        if report is not None
        else (
            session.request.project_name
            if session is not None
            and session.request.project_name
            else snapshot.bundle_dir.name
        )
    )

    lines = [
        "恢复上次任务：",
        f"• 项目：{project_name}",
        (
            "• 当前进度："
            + format_stage_summary(snapshot)
        ),
    ]

    confirmed = format_confirmed_request(
        session
    )

    if confirmed is not None:
        lines.append(
            f"• 已确认输入：{confirmed}"
        )

    missing = format_missing_information(
        session
    )

    if missing is not None:
        lines.append(
            f"• 仍需补充：{missing}"
        )

    if report is not None:
        if report.analysis_scope_level:
            lines.append(
                "• 分析范围："
                f"{report.analysis_scope_level}"
            )

        if report.candidate_count is not None:
            lines.append(
                "• 已记录候选数："
                f"{report.candidate_count}"
            )

        if (
            report.formal_candidate_recommendation_allowed
            is False
        ):
            lines.append(
                "• 结论边界：当前结果不能作为正式候选推荐。"
            )

    pending = snapshot.pending_action

    if pending is not None:
        label = PENDING_ACTION_LABELS.get(
            pending.action,
            pending.action,
        )
        suffix = (
            "仍有效"
            if snapshot.pending_is_current is True
            else "已失效或无法验证"
        )
        lines.append(
            f"• 上次待确认操作：{label}（{suffix}）"
        )

    if snapshot.unreadable_components:
        lines.append(
            "• 恢复注意："
            + "、".join(
                snapshot.unreadable_components
            )
            + "无法读取；现有文件没有被自动修改。"
        )

    lines.extend(
        [
            (
                "• 推荐下一步："
                + recommended_next_action(
                    snapshot,
                    model_status=model_status,
                )
            ),
            (
                "• 摘要来源：本地确定性任务记录；"
                "未使用模型记忆，也没有执行 BinderRanker。"
            ),
        ]
    )

    return "\n".join(lines)
