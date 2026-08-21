#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker Agent 自然语言对话控制层。

职责：
1. 理解用户自然语言意图；
2. 将高风险动作转化为待确认提案；
3. 用户确认后调用已有确定性 Chat 引擎；
4. 将缺失字段转换为自然语言问题；
5. 持久化待确认动作，支持会话重启。

本模块不生成 Shell，也不直接执行科学程序。
"""

from __future__ import annotations

from protein_design_agent.agent.user_errors import UserFacingError
from protein_design_agent.public_identity import (
    AGENT_NAME,
)
from protein_design_agent.agent.capability_truth import (
    CAPABILITY_TRUTH_PROMPT,
    capability_safe_reply,
)

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
)

from protein_design_agent.agent.chat_session import (
    ChatSessionError,
    ChatTurnResult,
    load_prepare_status,
    process_chat_message,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
    StructuredJSONProvider,
)
from protein_design_agent.agent.dataset_advice_adoption import (
    DatasetAdviceAdoptionError,
    adopt_dataset_advice,
)
from protein_design_agent.agent.dataset_advisor import (
    DatasetPlanningAdvice,
    inspect_dataset_for_planning,
    save_dataset_advice,
)
from protein_design_agent.agent.prepare_pipeline import (
    load_planning_session,
)
from protein_design_agent.agent.run_status import (
    RunStatusReport,
    inspect_run_status,
)
from protein_design_agent.agent.user_language import (
    lifecycle_state_label,
    pending_action_label,
    user_status,
)


DialogueIntent = Literal[
    "HELP",
    "VIEW_STATUS",
    "VIEW_PLAN",
    "START_TASK",
    "PROVIDE_INFORMATION",
    "REQUEST_DATASET_INSPECTION",
    "REQUEST_APPROVAL",
    "REQUEST_EXECUTION",
    "REQUEST_ANALYSIS",
    "REQUEST_EXPLANATION",
    "REQUEST_RESET_TASK",
    "REQUEST_ARCHIVE_TASK",
    "CONFIRM",
    "CANCEL",
    "GENERAL_QUESTION",
    "LIST_TASKS",
    "SWITCH_TASK",
]


PendingActionName = Literal[
    "APPROVE",
    "EXECUTE",
    "ANALYZE",
    "EXPLAIN",
    "ADOPT_DATASET_ADVICE",
    "CREATE_DATASET_GROUP_TASKS",
    "RESET_TASK",
    "ARCHIVE_TASK",
]


class ChatDialogueError(UserFacingError):
    """自然语言对话控制失败。"""


SafetyQuestionTopic = Literal[
    "APPROVAL_EXECUTION_SEPARATION",
    "APPROVAL_CONFIGURATION_FREEZE",
    "SMOKE_TEST_LIMITATION",
    "EXECUTION_APPROVAL_CONSUMPTION",
    "MODEL_USAGE",
]


class DialogueDecision(BaseModel):
    """模型生成的受控意图判断。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    intent: DialogueIntent
    reason: str

    # 当用户提出疑问时，模型应直接给出自然语言回答。
    # 该字段只能用于交流，不能触发执行动作。
    reply: str | None = None

    # 对批准、执行、模型调用等安全事实，
    # 模型只识别主题，最终答案由确定性代码生成。
    safety_topics: list[
        SafetyQuestionTopic
    ] = []


class PendingChatAction(BaseModel):
    """等待用户确认的高风险或有副作用动作。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    schema_version: str = "0.1"

    action: PendingActionName
    created_at_utc: str

    state_digest: str
    summary: str


MISSING_INFORMATION_QUESTIONS = {
    "input_dir": (
        "请告诉我 PDB 文件所在的目录。"
    ),
    "input_layout": (
        "这些 PDB 当前属于哪一种情况？\n"
        "  1. target 和 binder 已经是不同链；\n"
        "  2. target 与 binder 拼在同一条源链中。"
    ),
    "binder_chain": (
        "对于已经分链的数据，哪一条链是 binder？"
    ),
    "source_chain": (
        "对于拼接在一起的数据，原始蛋白位于哪一条源链？"
    ),
    "target_residue_count": (
        "target 在源链中包含多少个残基？"
    ),
    "distinct_normalized_chain_ids": (
        "标准化后的 target 链和 binder 链必须不同。"
        "请分别指定两个链名。"
    ),
    "desired_regions_or_hotspots": (
        "你选择了区域约束模式。"
        "请给出至少一个目标区域或 hotspot。"
    ),
    "region_filter_soft_or_strict": (
        "区域约束模式需要选择 soft 或 strict 过滤。"
    ),
}


EXACT_INTENTS: dict[str, DialogueIntent] = {
    "帮助": "HELP",
    "help": "HELP",
    "/help": "HELP",

    "状态": "VIEW_STATUS",
    "查看状态": "VIEW_STATUS",
    "当前状态": "VIEW_STATUS",
    "status": "VIEW_STATUS",
    "/status": "VIEW_STATUS",

    "检查文件": "REQUEST_DATASET_INSPECTION",
    "检查pdb": "REQUEST_DATASET_INSPECTION",
    "帮我检查文件": "REQUEST_DATASET_INSPECTION",
    "帮我看看文件": "REQUEST_DATASET_INSPECTION",

    "确认": "CONFIRM",
    "确认继续": "CONFIRM",
    "确认，继续": "CONFIRM",
    "好的，确认": "CONFIRM",
    "继续": "CONFIRM",
    "同意继续": "CONFIRM",

    "取消": "CANCEL",
    "算了": "CANCEL",
    "不做了": "CANCEL",

    # 故障恢复必须保留确定性入口：
    # 即使规划记录损坏，也应允许用户请求恢复。
    "/reset": "REQUEST_RESET_TASK",
    "重新开始这个任务": "REQUEST_RESET_TASK",
    "清空这个任务重新开始": "REQUEST_RESET_TASK",
    "/archive": "REQUEST_ARCHIVE_TASK",
    "归档当前任务": "REQUEST_ARCHIVE_TASK",
    "归档当前任务然后重新开始": (
        "REQUEST_ARCHIVE_TASK"
    ),

    # 兼容旧命令，但这些词现在只会生成待确认提案。
    "批准计划": "REQUEST_APPROVAL",
    "批准计划并确认小样本限制": (
        "REQUEST_APPROVAL"
    ),
    "确认执行": "REQUEST_EXECUTION",
    "分析结果": "REQUEST_ANALYSIS",
    "分析并解释结果": (
        "REQUEST_EXPLANATION"
    ),
}


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def confirmation_prompt(
    action: PendingActionName,
) -> str:
    """为所有待确认动作生成一致、简短的提示。"""
    label = pending_action_label(action)

    return (
        f"回复“确认”，继续{label}；"
        "回复“取消”，放弃本次操作。"
    )


def pending_confirmation_reminder(
    pending: PendingChatAction,
) -> str:
    """在回答插入问题后简短提醒，不重复整段提案。"""
    label = pending_action_label(
        pending.action
    )

    return (
        f"\n\n待确认仍保留：{label}。\n"
        + confirmation_prompt(
            pending.action
        )
    )


def pending_action_path(
    bundle_dir: Path,
) -> Path:
    return (
        bundle_dir.resolve()
        / "chat"
        / "pending_action.json"
    )


def write_json_atomically(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )

    try:
        with temporary.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True
        )


def bundle_state_digest(
    bundle_dir: Path,
) -> str:
    """
    对会影响动作合法性的清单建立摘要。

    chat/ 本身不参与摘要，避免 pending_action
    写入后改变自己的状态摘要。
    """
    bundle = bundle_dir.resolve()

    digest = hashlib.sha256()

    if not bundle.exists():
        digest.update(b"EMPTY")
        return digest.hexdigest()

    patterns = (
        "planning_session.json",
        "agent_prepare_manifest.json",
        "chat/dataset_advice.json",
        "chat/dataset_grouping_proposal.json",
        "approval.json",
        "execution_*.json",
        "agent_result_summary.json",
        "analyses/*/analyze_run_manifest.json",
        (
            "analyses/*/explanation/"
            "agent_explanation.json"
        ),
    )

    paths: set[Path] = set()

    for pattern in patterns:
        for path in bundle.glob(pattern):
            if path.is_file():
                paths.add(path.resolve())

    for path in sorted(
        paths,
        key=lambda item: str(item),
    ):
        relative = path.relative_to(bundle)

        digest.update(
            str(relative).encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return digest.hexdigest()


def load_pending_action(
    bundle_dir: Path,
) -> PendingChatAction | None:
    path = pending_action_path(
        bundle_dir
    )

    if not path.is_file():
        return None

    try:
        raw = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return PendingChatAction.model_validate(
            raw
        )

    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise ChatDialogueError(
            "待确认动作记录损坏："
            f"{path}；{exc}",
            public_message=(
                "待确认动作记录损坏，"
                "当前确认操作无法继续。"
            ),
        ) from exc


def save_pending_action(
    *,
    bundle_dir: Path,
    action: PendingActionName,
    summary: str,
) -> PendingChatAction:
    path = pending_action_path(
        bundle_dir
    )

    if path.exists():
        raise ChatDialogueError(
            "当前已有一个动作等待确认。"
            "请先回答“确认”或“取消”。",
            public_message=(
                "当前已有一个动作等待确认。"
                "请先回答“确认”或“取消”。"
            ),
        )

    pending = PendingChatAction(
        action=action,
        created_at_utc=utc_now(),
        state_digest=bundle_state_digest(
            bundle_dir
        ),
        summary=summary,
    )

    write_json_atomically(
        path,
        pending.model_dump(
            mode="json"
        ),
    )

    return pending


def clear_pending_action(
    bundle_dir: Path,
) -> None:
    path = pending_action_path(
        bundle_dir
    )

    path.unlink(
        missing_ok=True
    )

    parent = path.parent

    try:
        parent.rmdir()
    except OSError:
        pass


def missing_information_questions(
    bundle_dir: Path,
) -> list[str]:
    manifest_path = (
        bundle_dir.resolve()
        / "agent_prepare_manifest.json"
    )

    if not manifest_path.is_file():
        return []

    try:
        value = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise ChatDialogueError(
            "无法读取缺失信息清单："
            f"{exc}",
            public_message="无法读取任务缺失信息。",
        ) from exc

    if not isinstance(value, dict):
        return []

    missing = value.get(
        "missing_information",
        [],
    )

    if not isinstance(missing, list):
        return []

    return [
        MISSING_INFORMATION_QUESTIONS.get(
            str(field),
            f"还需要补充：{field}",
        )
        for field in missing
    ]


def natural_missing_message(
    bundle_dir: Path,
) -> str:
    questions = missing_information_questions(
        bundle_dir
    )

    if not questions:
        return (
            "当前任务仍缺少必要信息，"
            "但清单中没有可展示的问题。"
        )

    lines = [
        "我还需要确认一些信息，"
        "不会根据文件名或生物学常识替你猜测：",
        "",
    ]

    for index, question in enumerate(
        questions,
        start=1,
    ):
        lines.append(
            f"{index}. {question}"
        )

    lines.extend(
        [
            "",
            "你可以直接用正常语言回答，"
            "不需要输入字段名或命令格式。",
        ]
    )

    return "\n".join(lines)


def inspect_bundle(
    bundle_dir: Path,
) -> tuple[
    str,
    RunStatusReport | None,
]:
    bundle = bundle_dir.resolve()

    if not bundle.exists():
        return "EMPTY", None

    if not bundle.is_dir():
        raise ChatDialogueError(
            f"Bundle 路径不是目录：{bundle}",
            public_message="指定的 Bundle 路径不是目录。",
        )

    # chat/ 只保存对话控制状态，不代表已经形成科研任务。
    non_chat_items = [
        item
        for item in bundle.iterdir()
        if item.name != "chat"
    ]

    if not non_chat_items:
        return "EMPTY", None

    try:
        report = inspect_run_status(
            bundle
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"无法检查任务状态：{exc}",
            public_message="无法检查任务状态。",
        ) from exc

    return report.current_stage, report


def load_dialogue_context(
    bundle_dir: Path,
) -> dict[str, Any]:
    """
    为对话模型提供已确认上下文。

    这里只读取规划记录，不执行工作流，也不修改参数。
    """
    session_path = (
        bundle_dir.resolve()
        / "planning_session.json"
    )

    if not session_path.is_file():
        return {
            "conversation_record": None,
            "known_explicit_information": {},
            "missing_information": [],
        }

    try:
        session = load_planning_session(
            session_path
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"无法读取规划会话上下文：{exc}",
            public_message="无法读取当前规划会话。",
        ) from exc

    explicit_fields = (
        session.request_explicit_fields
        or []
    )

    request_data = session.request.model_dump(
        mode="json"
    )

    known_information = {
        field_name: request_data.get(
            field_name
        )
        for field_name in explicit_fields
    }

    return {
        "conversation_record": (
            session.request.raw_text
        ),
        "known_explicit_information": (
            known_information
        ),
        "missing_information": (
            session.plan.missing_information
        ),
    }



MAX_DIALOGUE_RESULT_CANDIDATES = 50



def load_current_plan_evidence(
    bundle_dir: Path,
) -> dict[str, Any] | None:
    """
    只读加载当前计划的真实参数。

    不调用模型，不执行工作流，不修改 Bundle。
    """
    bundle = bundle_dir.resolve()
    session_path = bundle / "planning_session.json"

    if not session_path.is_file():
        return None

    try:
        session = load_planning_session(
            session_path
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"无法读取当前计划：{exc}",
            public_message="无法读取当前计划。",
        ) from exc

    workflow_manifest = None
    workflow_path = (
        bundle
        / "workflow"
        / "workflow_manifest.json"
    )
    if workflow_path.is_file():
        try:
            value = json.loads(
                workflow_path.read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(value, dict):
                workflow_manifest = value
        except (
            OSError,
            json.JSONDecodeError,
        ):
            workflow_manifest = None

    ranker_plan = None
    ranker_path = (
        bundle
        / "workflow"
        / "ranker"
        / "ranker_execution_plan.json"
    )
    if ranker_path.is_file():
        try:
            value = json.loads(
                ranker_path.read_text(
                    encoding="utf-8"
                )
            )
            if isinstance(value, dict):
                ranker_plan = value
        except (
            OSError,
            json.JSONDecodeError,
        ):
            ranker_plan = None

    return {
        "status": session.plan.status,
        "request": session.request.model_dump(
            mode="json"
        ),
        "missing_information": (
            session.plan.missing_information
        ),
        "warnings": session.plan.warnings,
        "steps": [
            step.model_dump(mode="json")
            for step in session.plan.steps
        ],
        "config_preview": (
            session.plan.config_preview
        ),
        "execution_allowed": (
            session.plan.execution_allowed
        ),
        "workflow_manifest": workflow_manifest,
        "ranker_plan": ranker_plan,
    }


def format_current_plan(
    bundle_dir: Path,
) -> str:
    """
    将真实计划转换为适合用户审阅的摘要。
    """
    evidence = load_current_plan_evidence(
        bundle_dir
    )

    if evidence is None:
        return (
            "当前 Bundle 还没有生成任务计划。"
            "你可以先描述希望分析的 PDB 数据和目标。"
        )

    config = (
        evidence.get("config_preview")
        or {}
    )
    input_config = config.get("input") or {}
    regions = config.get("regions") or {}
    ranking = config.get("ranking") or {}

    workflow = (
        evidence.get("workflow_manifest")
        or {}
    )
    scope = (
        workflow.get("analysis_scope")
        or {}
    )

    ranker = (
        evidence.get("ranker_plan")
        or {}
    )
    input_summary = (
        ranker.get("input_summary")
        or {}
    )

    desired = regions.get("desired") or []
    undesired = (
        regions.get("undesired") or []
    )
    hotspots = regions.get("hotspots") or []

    def show_list(value: list[Any]) -> str:
        if not value:
            return "未设置"
        return ", ".join(str(item) for item in value)

    lines = [
        "当前任务计划",
        "",
        f"项目：{config.get('project_name', '未命名')}",
        f"计划状态：{evidence.get('status')}",
        (
            "输入目录："
            f"{input_config.get('pdb_dir', '未设置')}"
        ),
        (
            "候选数量："
            f"{input_summary.get('pdb_count', '尚未确定')}"
        ),
        (
            "原始链布局："
            f"{input_config.get('layout', '未设置')}"
        ),
        (
            "源链："
            f"{input_config.get('source_chain', '不适用')}"
        ),
        (
            "target 起始位置："
            f"{input_config.get('target_start_residue', '未设置')}"
        ),
        (
            "target 残基数量："
            f"{input_config.get('target_residue_count', '未设置')}"
        ),
        (
            "标准化 target 链："
            f"{input_config.get('normalized_target_chain', '未设置')}"
        ),
        (
            "标准化 binder 链："
            f"{input_config.get('normalized_binder_chain', '未设置')}"
        ),
        f"目标区域：{show_list(desired)}",
        f"排除区域：{show_list(undesired)}",
        f"hotspot：{show_list(hotspots)}",
        (
            "区域评分模式："
            f"{ranking.get('region_policy', '未设置')}"
        ),
        (
            "区域过滤："
            f"{ranking.get('region_filter', '未设置')}"
        ),
        (
            "Ranker 版本："
            f"{ranking.get('ranker_version', '未设置')}"
        ),
        (
            "报告 Top K："
            f"{ranking.get('top_k_report', '未设置')}"
        ),
        (
            "分析范围："
            f"{scope.get('level', '尚未确定')}"
        ),
        (
            "允许正式科研解释："
            f"{scope.get('workflow_allows_formal_interpretation', '尚未确定')}"
        ),
        (
            "当前允许直接执行："
            f"{evidence.get('execution_allowed')}"
        ),
        "",
        "计划步骤：",
    ]

    for index, step in enumerate(
        evidence.get("steps") or [],
        start=1,
    ):
        approval = (
            "需要批准"
            if step.get("requires_approval")
            else "只读/准备步骤"
        )
        lines.append(
            f"{index}. {step.get('description', step.get('step_id'))}"
            f"（{approval}）"
        )

    warnings = evidence.get("warnings") or []
    if warnings:
        lines.extend(["", "注意事项："])
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)

def load_latest_result_evidence(
    bundle_dir: Path,
) -> dict[str, Any] | None:
    """
    读取当前 Bundle 最新的确定性结果摘要。

    只提取对解释和筛选有用的受控字段，
    不执行分析，也不修改任何文件。
    """
    bundle = bundle_dir.resolve()

    paths = sorted(
        (
            path.resolve()
            for path in bundle.glob(
                "analyses/*/agent_result_summary.json"
            )
            if path.is_file()
        ),
        key=lambda item: str(item),
    )

    root_summary = (
        bundle / "agent_result_summary.json"
    )
    if root_summary.is_file():
        paths.append(root_summary.resolve())
        paths.sort(key=lambda item: str(item))

    if not paths:
        return None

    summary_path = paths[-1]

    try:
        raw = json.loads(
            summary_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        return {
            "status": "UNAVAILABLE",
            "source_path": str(
                summary_path.relative_to(bundle)
            ),
            "reason": (
                "确定性结果摘要无法读取："
                f"{exc}"
            ),
        }

    if not isinstance(raw, dict):
        return {
            "status": "UNAVAILABLE",
            "source_path": str(
                summary_path.relative_to(bundle)
            ),
            "reason": "确定性结果摘要不是 JSON 对象",
        }

    rows = raw.get(
        "candidates_by_engineering_rank",
        [],
    )
    if not isinstance(rows, list):
        rows = []

    allowed_fields = (
        "pdb_name",
        "engineering_rank",
        "final_score_v4",
        "raw_filter_level",
        "public_filter_level",
        "public_filter_status",
        "broad_pass",
        "medium_pass",
        "strict_pass",
        "broad_reasons",
        "medium_reasons",
        "strict_reasons",
        "filter_reasons_formally_interpretable",
        "component_scores",
        "key_metrics",
        "row_error",
    )

    candidates = []
    for row in rows[
        :MAX_DIALOGUE_RESULT_CANDIDATES
    ]:
        if not isinstance(row, dict):
            continue

        candidates.append(
            {
                field: row.get(field)
                for field in allowed_fields
            }
        )

    return {
        "status": "AVAILABLE",
        "source_path": str(
            summary_path.relative_to(bundle)
        ),
        "analysis_scope": raw.get(
            "analysis_scope"
        ),
        "candidate_count": raw.get(
            "candidate_count"
        ),
        "candidates_by_engineering_rank": (
            candidates
        ),
        "truncated": (
            len(rows)
            > MAX_DIALOGUE_RESULT_CANDIDATES
        ),
    }

def classify_dialogue_intent(
    *,
    provider: StructuredJSONProvider,
    message: str,
    bundle_dir: Path,
    current_stage: str,
    prepare_status: str | None,
    pending_action: PendingChatAction | None,
) -> DialogueDecision:
    """
    大模型只判断意图，不执行动作。
    """
    schema = DialogueDecision.model_json_schema()

    dialogue_context = load_dialogue_context(
        bundle_dir
    )
    dialogue_context[
        "latest_result_evidence"
    ] = load_latest_result_evidence(
        bundle_dir
    )

    context = {
        "current_stage": current_stage,
        "prepare_status": prepare_status,
        "pending_action": (
            pending_action.action
            if pending_action is not None
            else None
        ),
        "user_message": message,
        "conversation_context": (
            dialogue_context
        ),
        "allowed_intents": [
            "HELP",
            "VIEW_STATUS",
            "VIEW_PLAN",
            "LIST_TASKS",
            "SWITCH_TASK",
              "START_TASK",
            "PROVIDE_INFORMATION",
            "REQUEST_DATASET_INSPECTION",
            "REQUEST_APPROVAL",
            "REQUEST_EXECUTION",
            "REQUEST_ANALYSIS",
            "REQUEST_EXPLANATION",
            "REQUEST_RESET_TASK",
            "REQUEST_ARCHIVE_TASK",
            "CONFIRM",
            "CANCEL",
            "GENERAL_QUESTION",
        ],
        "allowed_safety_topics": [
            "APPROVAL_EXECUTION_SEPARATION",
            "APPROVAL_CONFIGURATION_FREEZE",
            "SMOKE_TEST_LIMITATION",
            "EXECUTION_APPROVAL_CONSUMPTION",
            "MODEL_USAGE",
        ],
        "required_schema": schema,
    }

    messages = [
        {
            "role": "system",
            "content": (
                f"你是 {AGENT_NAME} 的"
                "受控对话意图分类器。"
                "你只能判断用户意图，不能执行任何动作，"
                "不能输出 Shell 命令，也不能修改科研参数。"
                "在 EMPTY 阶段，只有用户明确要求分析、"
                "排名或处理 PDB，或者主动提供目录、链、"
                "残基边界等任务信息时，"
                "才选择 START_TASK。"
                "问候、模型连接测试、程序介绍、使用方法、"
                "原理、能力、局限和安全机制等内容，"
                "必须选择 GENERAL_QUESTION 并自然回答。"
                "当用户在补充链、残基、目录、区域等参数时，"
                "选择 PROVIDE_INFORMATION。"
                "当用户用任何自然表达希望查看、核对、"
                "复述或解释当前任务方案、参数、步骤、"
                "输入设置或执行前配置时，选择 VIEW_PLAN。"
                "不要要求用户使用固定口令，也不要把"
                "查看计划误判为批准、执行或普通状态查询。"
                "当用户表达‘同意方案、按这个方案来’时，"
                "选择 REQUEST_APPROVAL。"
                "当用户表达‘开始跑、开始计算、执行吧’时，"
                "选择 REQUEST_EXECUTION。"
                "当已有 pending_action 且用户明确同意"
                "当前提案时，选择 CONFIRM；"
                "明确放弃当前提案时选择 CANCEL。"
                "如果用户补充参数、纠正事实、"
                "表示刚才说错了或要求修改方案，"
                "必须选择 PROVIDE_INFORMATION。"
                "不能仅因句中出现不、不要、不是，"
                "就判断用户要取消整个动作。"

                "用户在确认前仍然可以询问动作影响。"
                "此时选择 GENERAL_QUESTION，"
                "并根据问题填写 safety_topics："
                "询问批准是否会立即运行，填写 "
                "APPROVAL_EXECUTION_SEPARATION；"
                "询问批准后能否改参数，填写 "
                "APPROVAL_CONFIGURATION_FREEZE；"
                "询问小样本限制，填写 "
                "SMOKE_TEST_LIMITATION；"
                "询问执行是否消耗批准，填写 "
                "EXECUTION_APPROVAL_CONSUMPTION；"
                "询问是否调用大模型，填写 MODEL_USAGE。"
                "一个问题可以包含多个主题。"

                "涉及 safety_topics 时，"
                "不要在 reply 中自行断言批准、执行、"
                "配置冻结或科研解释权限。"
                "最终安全答案由确定性控制器生成。"

                "当用户询问当前有哪些任务、任务列表或"
                "所有分组状态时，选择 LIST_TASKS。"
                "当用户要求进入、切换或继续某个已存在任务时，"
                "选择 SWITCH_TASK。任务名由后续确定性导航器"
                "根据真实任务列表验证。"

                "当已有 NEEDS_INFORMATION 计划，且用户明确要求查看、检查、读取 PDB 文件，"
                "要求识别多个目录、按目录分组或分别排序，"
                "或者说自己无法判断并要求 Agent 根据文件分析时，"
                "选择 REQUEST_DATASET_INSPECTION。"

                "仅仅询问‘链布局是什么意思’或"
                "‘应该怎样判断’时，不要检查文件，"
                "选择 GENERAL_QUESTION 并直接解释。"

                "当用户在询问概念、原因、如何判断，"
                "或者表达‘我不知道’时，"
                "选择 GENERAL_QUESTION，"
                "并在 reply 中直接、耐心地回答。"

                "回答问题时必须遵守："
                "一、优先解释术语和判断方法；"
                "二、结合 conversation_context 中"
                "用户已经明确说过的信息；"
                "三、若用户之前的话已经隐含答案，"
                "指出依据并用简单语言确认；"
                "四、不要只重复缺失字段或原来的问题；"
                "五、不能编造文件内容或科研事实；"
                "六、不能因为回答问题而批准或执行任务。"

                "例如：用户已经说 target 和 binder "
                "拼在同一条 A 链中，随后问‘源链是什么’，"
                "应解释源链是标准化前的原始链，"
                "并指出根据他刚才的话，源链应是 A。"

                "conversation_context 中的 "
                "latest_result_evidence 来自当前 Bundle "
                "已经生成的确定性结果摘要。"
                "当用户询问刚才的排名、候选优缺点、"
                "筛选结果或为什么靠前靠后时，"
                "必须优先使用其中的证据回答，"
                "不能要求用户再次粘贴 JSON。"
                "不得声称未提供的相关性、因果关系、"
                "统计显著性或正式科研结论。"

                "输出必须严格符合 JSON Schema。"
                + "\n\n真实科学能力边界：\n"
                + CAPABILITY_TRUTH_PROMPT
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                context,
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]

    try:
        payload = provider.generate_json(
            messages
        )

        return DialogueDecision.model_validate(
            payload
        )

    except Exception as exc:
        raise ChatDialogueError(
            f"无法判断用户意图：{exc}",
            public_message="无法完成本次自然语言意图解析。",
        ) from exc


def determine_intent(
    *,
    message: str,
    bundle_dir: Path,
    provider: (
        RequestParserProvider
        | StructuredJSONProvider
        | None
    ),
    allow_network: bool,
) -> tuple[
    DialogueDecision,
    PendingChatAction | None,
    str,
    RunStatusReport | None,
]:
    clean = message.strip()

    if not clean:
        raise ChatDialogueError(
            "输入内容不能为空",
            public_message="输入内容不能为空。",
        )

    pending = load_pending_action(
        bundle_dir
    )

    exact = EXACT_INTENTS.get(
        clean.lower()
    )

    # 故障恢复入口必须能绕过损坏的科研任务状态。
    # 否则 planning/manifest 损坏时，用户反而无法 reset/archive。
    recovery_pending = (
        pending is not None
        and pending.action in {
            "RESET_TASK",
            "ARCHIVE_TASK",
        }
    )

    if (
        exact in {
            "REQUEST_RESET_TASK",
            "REQUEST_ARCHIVE_TASK",
        }
        or (
            exact in {"CONFIRM", "CANCEL"}
            and recovery_pending
        )
    ):
        return (
            DialogueDecision(
                intent=exact,
                reason="确定性任务恢复入口",
            ),
            pending,
            "RECOVERY",
            None,
        )

    current_stage, report = inspect_bundle(
        bundle_dir
    )

    prepare_status = load_prepare_status(
        bundle_dir.resolve()
    )

    if exact is not None:
        return (
            DialogueDecision(
                intent=exact,
                reason="确定性快捷表达",
            ),
            pending,
            current_stage,
            report,
        )

    # 空 Bundle 中不能假定用户已经开始科研任务。
    # 已启用模型时，先判断用户是在普通交流、
    # 了解程序，还是明确提出了新的排名任务。
    if (
        current_stage == "EMPTY"
        and not (
            allow_network
            and isinstance(
                provider,
                StructuredJSONProvider,
            )
        )
    ):
        return (
            DialogueDecision(
                intent="GENERAL_QUESTION",
                reason=(
                    "空 Bundle 且没有可用的"
                    "自然语言意图模型"
                ),
            ),
            pending,
            current_stage,
            report,
        )

    if (
        allow_network
        and isinstance(
            provider,
            StructuredJSONProvider,
        )
    ):
        decision = classify_dialogue_intent(
            provider=provider,
            message=clean,
            bundle_dir=bundle_dir,
            current_stage=current_stage,
            prepare_status=prepare_status,
            pending_action=pending,
        )

        return (
            decision,
            pending,
            current_stage,
            report,
        )

    # 未允许联网时仍支持确定性的状态和确认流程。
    if pending is not None:
        return (
            DialogueDecision(
                intent="GENERAL_QUESTION",
                reason=(
                    "未识别为确定性确认或取消表达"
                ),
            ),
            pending,
            current_stage,
            report,
        )

    if (
        prepare_status == "NEEDS_INFORMATION"
        and provider is not None
    ):
        return (
            DialogueDecision(
                intent="PROVIDE_INFORMATION",
                reason=(
                    "当前任务正在等待补充参数，"
                    "且存在显式请求解析器"
                ),
            ),
            pending,
            current_stage,
            report,
        )

    return (
        DialogueDecision(
            intent="GENERAL_QUESTION",
            reason="没有启用自然语言意图模型",
        ),
        pending,
        current_stage,
        report,
    )


def format_dataset_advice(
    advice: DatasetPlanningAdvice,
) -> str:
    """把确定性文件证据转成人类可读说明。"""
    lines = [
        "我已经只读检查了当前任务的 PDB 文件。",
        "",
        (
            f"- 共处理 {advice.processed_file_count} 个 PDB"
        ),
        (
            f"- 有效文件：{advice.valid_file_count}"
        ),
        (
            f"- 无效文件：{advice.invalid_file_count}"
        ),
    ]

    if (
        advice.all_valid_files_are_single_chain
        and advice.common_single_chain_id
    ):
        lines.extend(
            [
                "- 所有有效文件都只有一条链",
                (
                    "- 所有有效文件的唯一链名均为 "
                    f"{advice.common_single_chain_id}"
                ),
            ]
        )

    suggestion = advice.conditional_suggestion

    if suggestion is None:
        lines.extend(
            [
                "",
                "目前的文件结构不足以形成统一建议。",
            ]
        )

    else:
        patch = suggestion.candidate_patch

        lines.extend(
            [
                "",
                "根据文件证据，我可以提出一个条件建议：",
                (
                    "- 链布局：target 与 binder "
                    "尚未拆分在不同链中"
                ),
                (
                    "- 原始源链："
                    f"{patch.get('source_chain')}"
                ),
                "",
                "但这里有一个重要边界：",
                (
                    "单链文件只能证明文件里只有一条链，"
                    "不能单独证明这条链同时包含 "
                    "target 和 binder。"
                ),
            ]
        )

    if advice.cautions:
        lines.append("")
        lines.append("检查中还发现：")

        for caution in advice.cautions:
            lines.append(
                f"- {caution}"
            )

    if suggestion is not None:
        lines.extend(
            [
                "",
                (
                    "这些建议来自 PDB 文件检查和文件 SHA256，"
                    "不是大模型猜测。"
                ),
                (
                    "假如你确认这些单链结构确实同时包含 "
                    "target 和 binder，可以采用这项建议。"
                ),
                confirmation_prompt(
                    "ADOPT_DATASET_ADVICE"
                ),
            ]
        )

    return "\n".join(lines)


def inspect_dataset_and_propose_adoption(
    *,
    bundle_dir: Path,
    provider: Any | None = None,
    user_message: str = "",
) -> ChatTurnResult:
    """
    只读检查当前规划的输入目录。

    有条件建议时建立待确认动作，但不直接修改参数。
    """
    bundle = bundle_dir.resolve()

    prepare_status = load_prepare_status(
        bundle
    )

    if prepare_status != "NEEDS_INFORMATION":
        raise ChatDialogueError(
            "文件规划建议只用于仍在补充信息的任务；"
            f"当前状态为 {prepare_status!r}",
            public_message=(
                "文件规划建议只用于仍在补充信息的任务。"
            ),
        )

    session_path = (
        bundle / "planning_session.json"
    )

    if not session_path.is_file():
        raise ChatDialogueError(
            f"缺少规划会话：{session_path}",
            public_message="当前任务缺少规划会话记录。",
        )

    try:
        session = load_planning_session(
            session_path
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"无法读取规划会话：{exc}",
            public_message="无法读取规划会话。",
        ) from exc

    input_dir = session.request.input_dir

    if input_dir is None:
        raise ChatDialogueError(
            "目前还不知道 PDB 输入目录。"
            "请先告诉我文件位于哪个目录，"
            "然后我才能进行只读检查。",
            public_message=(
                "目前还不知道 PDB 输入目录。"
                "请先提供输入目录，"
                "然后才能进行只读检查。"
            ),
        )

    from protein_design_agent.agent.dataset_discovery import (
        discover_dataset_groups,
    )
    from protein_design_agent.agent.dataset_grouping import (
        DatasetGroupingError,
        format_dataset_grouping_preview,
        propose_dataset_grouping,
    )

    try:
        discovery = discover_dataset_groups(
            input_dir
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"PDB 目录只读发现失败：{exc}",
            public_message="PDB 目录只读检查未完成。",
        ) from exc

    if discovery.layout in {
        "CHILD_DATASETS",
        "MIXED_LAYOUT",
    }:
        if (
            provider is None
            or not hasattr(
                provider,
                "generate_json",
            )
        ):
            candidates = "\n".join(
                (
                    f"- {group.relative_path}："
                    f"{group.pdb_count} 个顶层 PDB"
                )
                for group in discovery.groups
            )

            return ChatTurnResult(
                action="INSPECT_DATASET",
                status="MODEL_REQUIRED",
                message=(
                    "检测到多个可能独立的数据集：\n"
                    f"{candidates}\n\n"
                    "需要启用结构化模型，才能结合你的"
                    "自然语言说明提出分组方案。"
                    "当前没有创建、批准或执行任何任务。"
                ),
                bundle_dir=bundle,
            )

        try:
            grouping = propose_dataset_grouping(
                provider=provider,
                user_description=user_message,
                report=discovery,
            )
        except DatasetGroupingError as exc:
            raise ChatDialogueError(
                f"无法生成可靠的多数据集分组建议：{exc}",
                public_message=(
                    "无法生成可靠的多数据集分组建议。"
                ),
            ) from exc

        if load_pending_action(bundle) is not None:
            raise ChatDialogueError(
                "当前已有动作等待确认，"
                "请先确认或取消旧动作",
                public_message=(
                    "当前已有动作等待确认，"
                    "请先确认或取消旧动作。"
                ),
            )

        from protein_design_agent.agent.dataset_group_tasks import (
            save_grouping_proposal,
        )

        preview = format_dataset_grouping_preview(
            grouping=grouping,
            report=discovery,
        )

        proposal_path = save_grouping_proposal(
            bundle_dir=bundle,
            report=discovery,
            grouping=grouping,
            user_description=user_message,
        )

        save_pending_action(
            bundle_dir=bundle,
            action="CREATE_DATASET_GROUP_TASKS",
            summary=preview,
        )

        return ChatTurnResult(
            action="INSPECT_DATASET",
            status="AWAITING_CONFIRMATION",
            message=(
                preview
                + "\n\n确认后只会创建相互隔离的任务 "
                "Bundle，不会批准或执行。"
                "\n"
                + confirmation_prompt(
                    "CREATE_DATASET_GROUP_TASKS"
                )
            ),
            bundle_dir=bundle,
            artifact_paths={
                "dataset_grouping_proposal": (
                    proposal_path
                ),
                "pending_action": (
                    pending_action_path(bundle)
                ),
            },
        )

    try:
        advice = inspect_dataset_for_planning(
            input_dir=input_dir,
            recursive=False,
        )

        advice_path = save_dataset_advice(
            bundle_dir=bundle,
            advice=advice,
        )

    except Exception as exc:
        raise ChatDialogueError(
            f"PDB 文件只读检查失败：{exc}",
            public_message="PDB 文件只读检查未完成。",
        ) from exc

    message = format_dataset_advice(
        advice
    )

    if advice.conditional_suggestion is None:
        return ChatTurnResult(
            action="INSPECT_DATASET",
            status="INCONCLUSIVE",
            message=message,
            bundle_dir=bundle,
            artifact_paths={
                "dataset_advice": advice_path,
            },
        )

    save_pending_action(
        bundle_dir=bundle,
        action="ADOPT_DATASET_ADVICE",
        summary=message,
    )

    return ChatTurnResult(
        action="INSPECT_DATASET",
        status="AWAITING_CONFIRMATION",
        message=message,
        bundle_dir=bundle,
        artifact_paths={
            "dataset_advice": advice_path,
            "pending_action": (
                pending_action_path(bundle)
            ),
        },
    )


def maybe_auto_inspect_after_information(
    *,
    result: ChatTurnResult,
    bundle_dir: Path,
    provider: Any | None,
    user_message: str,
) -> ChatTurnResult | None:
    """
    参数写入规划会话后，自动衔接只读数据检查。

    这里只读取文件并提出建议，不批准、不执行，
    也不会覆盖已经存在的待确认动作。
    """
    if result.status != "NEEDS_INFORMATION":
        return None

    bundle = bundle_dir.resolve()
    session_path = bundle / "planning_session.json"

    if not session_path.is_file():
        return None

    if load_pending_action(bundle) is not None:
        return None

    try:
        session = load_planning_session(
            session_path
        )
    except Exception as exc:
        raise ChatDialogueError(
            f"无法读取刚更新的规划会话：{exc}",
            public_message="无法读取更新后的规划会话。",
        ) from exc

    if session.request.input_dir is None:
        return None

    return inspect_dataset_and_propose_adoption(
        bundle_dir=bundle,
        provider=provider,
        user_message=user_message,
    )


def deterministic_pending_safety_answer(
    *,
    pending: PendingChatAction,
    topics: list[SafetyQuestionTopic],
    report: RunStatusReport | None,
) -> str | None:
    """
    根据结构化主题生成确定性的高风险动作说明。

    模型的 reply 不参与这些事实的最终回答。
    """
    requested = set(topics)
    lines: list[str] = []

    if (
        "APPROVAL_EXECUTION_SEPARATION"
        in requested
    ):
        lines.append(
            "批准不会立即运行 BinderRanker。"
            "批准只会冻结当前配置、输入数据集指纹"
            "和 Ranker 哈希；真正执行还需要你"
            "另行提出执行请求并再次确认。"
        )

    if (
        "APPROVAL_CONFIGURATION_FREEZE"
        in requested
    ):
        lines.append(
            "批准后不能直接修改同一个 Bundle "
            "中的科研参数或已冻结文件。"
            "需要修改时，应在批准前取消；"
            "若已经批准，则应重新建立或重新准备"
            "一个新的 Bundle，并重新审核批准。"
        )

    if "SMOKE_TEST_LIMITATION" in requested:
        candidate_text = ""

        if (
            report is not None
            and report.candidate_count
            is not None
        ):
            candidate_text = (
                f"当前只有 {report.candidate_count} "
                "个候选。"
            )

        if (
            report is not None
            and report.analysis_scope_level
            == "SMOKE_TEST_ONLY"
        ):
            lines.append(
                candidate_text
                + "当前属于 SMOKE_TEST_ONLY，"
                "只能用于验证解析、标准化、"
                "评分和输出流程；不能把本次排名、"
                "动态阈值或候选优劣作为正式科研结论。"
            )
        else:
            lines.append(
                "是否属于小样本限制，应以工作流清单"
                "中的 analysis_scope 为准；"
                "当前状态没有确认这是 "
                "SMOKE_TEST_ONLY。"
            )

    if (
        "EXECUTION_APPROVAL_CONSUMPTION"
        in requested
    ):
        lines.append(
            "执行会消耗当前一次性批准。"
            "同一个批准不能用于重复启动 "
            "BinderRanker；需要再次运行时，"
            "必须重新准备并取得新的批准。"
        )

    if "MODEL_USAGE" in requested:
        if pending.action == "EXPLAIN":
            lines.append(
                "该解释动作会先读取确定性分析结果，"
                "然后调用已配置的大模型生成受控解释。"
                "模型不能重新计算分数、修改排名"
                "或放宽科研解释权限。"
            )
        elif pending.action == "ANALYZE":
            lines.append(
                "该分析动作只运行确定性结果解析"
                "和失败分析，不调用大模型。"
            )
        elif pending.action == "ADOPT_DATASET_ADVICE":
            lines.append(
                "采用文件建议时不会调用大模型决定参数。"
                "参数来自只读 PDB 检查、文件 SHA256"
                "和你的明确确认。"
            )
        elif pending.action == "CREATE_DATASET_GROUP_TASKS":
            lines.append(
                "确认后只创建相互隔离的任务 Bundle"
                "和数据来源记录。不会批准、执行或生成排名。"
            )
        else:
            lines.append(
                "批准和执行动作由确定性代码处理，"
                "不会让大模型决定是否批准、"
                "修改参数或运行命令。"
            )

    if not lines:
        return None

    return "\n\n".join(lines)


def proposal_summary(
    *,
    action: PendingActionName,
    report: RunStatusReport | None,
) -> str:
    project = (
        report.project_name
        if report is not None
        else "未知项目"
    )

    scope = (
        report.analysis_scope_level
        if report is not None
        else None
    )

    label = pending_action_label(action)

    if action == "APPROVE":
        lines = [
            f"待确认：{label}",
            f"项目：{project}",
            (
                "影响：冻结配置、数据集指纹和 Ranker 哈希；"
                "不会运行 BinderRanker。"
            ),
        ]

        if scope == "SMOKE_TEST_ONLY":
            lines.append(
                "当前只有工程冒烟测试规模，"
                "不能作为正式科研筛选结论。"
            )

    elif action == "EXECUTE":
        lines = [
            f"待确认：{label}",
            f"项目：{project}",
            (
                "影响：运行 BinderRanker，"
                "并消耗当前一次性批准。"
            ),
        ]

    elif action == "ANALYZE":
        lines = [
            f"待确认：{label}",
            f"项目：{project}",
            (
                "影响：生成新的确定性结果摘要和失败分析；"
                "不会调用大模型。"
            ),
        ]

    else:
        lines = [
            f"待确认：{label}",
            f"项目：{project}",
            (
                "影响：读取确定性分析结果，"
                "并调用已配置的大模型生成解释报告。"
            ),
        ]

    lines.extend(
        [
            "",
            confirmation_prompt(action),
        ]
    )

    return "\n".join(lines)


def create_task_recovery_proposal(
    *,
    action: PendingActionName,
    bundle_dir: Path,
) -> ChatTurnResult:
    """为 reset/archive 创建受控确认提案。"""
    from protein_design_agent.agent.task_lifecycle import (
        TaskLifecycleState,
        inspect_task_lifecycle,
    )

    lifecycle = inspect_task_lifecycle(
        bundle_dir
    )

    if action == "RESET_TASK":
        if (
            lifecycle.state
            == TaskLifecycleState.VALID_WITH_EVIDENCE
        ):
            raise ChatDialogueError(
                "当前任务包含受保护证据，"
                "不能直接重置。请改为归档当前任务。",
                public_message=(
                    "当前任务包含受保护证据，"
                    "不能直接重置。请改为归档当前任务。"
                ),
            )

        summary = (
            "待确认：重新开始当前任务\n"
            "当前内容："
            f"{lifecycle_state_label(lifecycle.state.value)}\n"
            "确认后会清除当前 Bundle 中可安全重置的"
            "不完整任务状态，并重新建立同名空 Bundle。\n"
            "Bundle 外部的失败审计记录不会被删除。\n\n"
            + confirmation_prompt("RESET_TASK")
        )

    elif action == "ARCHIVE_TASK":
        if lifecycle.state == TaskLifecycleState.EMPTY:
            raise ChatDialogueError(
                "当前任务为空，空任务无需归档。",
                public_message=(
                    "当前任务为空，无需归档。"
                ),
            )

        summary = (
            "待确认：归档当前任务并重新开始\n"
            "当前内容："
            f"{lifecycle_state_label(lifecycle.state.value)}\n"
            "确认后会把当前 Bundle 完整移动到工作区"
            " archives，并重新建立同名空 Bundle。\n"
            "该操作不会运行 BinderRanker，"
            "也不会修改已有科研结果。\n\n"
            + confirmation_prompt("ARCHIVE_TASK")
        )

    else:
        raise ChatDialogueError(
            f"不支持的任务恢复动作：{action}",
            public_message="不支持当前任务恢复操作。",
        )

    save_pending_action(
        bundle_dir=bundle_dir,
        action=action,
        summary=summary,
    )

    return ChatTurnResult(
        action=action,
        status="AWAITING_CONFIRMATION",
        message=summary,
        bundle_dir=bundle_dir.resolve(),
        artifact_paths={
            "pending_action": (
                pending_action_path(bundle_dir)
            )
        },
    )


def create_action_proposal(
    *,
    action: PendingActionName,
    bundle_dir: Path,
    report: RunStatusReport | None,
) -> ChatTurnResult:
    prepare_status = load_prepare_status(
        bundle_dir.resolve()
    )

    if action == "APPROVE":
        if prepare_status != "READY_FOR_REVIEW":
            raise ChatDialogueError(
                "当前任务尚未达到 READY_FOR_REVIEW，"
                "不能批准。",
                public_message=(
                    "当前任务计划尚未准备完整，"
                    "暂时不能批准。请先补齐信息并审核计划。"
                ),
            )

        if report is not None and (
            report.approval_status == "APPROVED"
        ):
            raise ChatDialogueError(
                "当前任务已经批准。",
                public_message="当前任务已经批准。",
            )

    elif action == "EXECUTE":
        if report is None or (
            report.current_stage != "APPROVED"
        ):
            raise ChatDialogueError(
                "只有已批准且尚未执行的任务"
                "才能开始运行。",
                public_message=(
                    "只有已批准且尚未执行的任务"
                    "才能开始运行。"
                ),
            )

    elif action in {
        "ANALYZE",
        "EXPLAIN",
    }:
        if report is None or (
            report.execution_status != "COMPLETED"
        ):
            raise ChatDialogueError(
                "只有 BinderRanker 执行完成后"
                "才能分析结果。",
                public_message=(
                    "只有 BinderRanker 执行完成后"
                    "才能分析结果。"
                ),
            )

    summary = proposal_summary(
        action=action,
        report=report,
    )

    display_message = summary

    if action == "APPROVE":
        display_message = (
            format_current_plan(bundle_dir)
            + "\n\n"
            + summary
        )

    save_pending_action(
        bundle_dir=bundle_dir,
        action=action,
        summary=summary,
    )

    action_mapping = {
        "APPROVE": "APPROVE",
        "EXECUTE": "EXECUTE",
        "ANALYZE": "ANALYZE",
        "EXPLAIN": "EXPLAIN",
    }

    return ChatTurnResult(
        action=action_mapping[action],
        status="AWAITING_CONFIRMATION",
        message=display_message,
        bundle_dir=bundle_dir.resolve(),
        artifact_paths={
            "pending_action": (
                pending_action_path(
                    bundle_dir
                )
            )
        },
    )


def confirm_pending_action(
    *,
    pending: PendingChatAction,
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
    current_digest = bundle_state_digest(
        bundle_dir
    )

    if current_digest != (
        pending.state_digest
    ):
        clear_pending_action(
            bundle_dir
        )

        raise ChatDialogueError(
            "任务状态在等待确认期间发生了变化。"
            "旧确认请求已经作废，请重新提出操作。",
            public_message=(
                "任务状态在等待确认期间发生了变化。"
                "旧确认请求已经作废，请重新提出操作。"
            ),
        )

    if pending.action in {
        "RESET_TASK",
        "ARCHIVE_TASK",
    }:
        from protein_design_agent.agent.task_recovery import (
            TaskRecoveryError,
            archive_task,
            reset_task,
        )

        # pending_action 属于交互控制状态，
        # 不应该被 reset/archive 当作科研证据保留。
        clear_pending_action(bundle_dir)

        try:
            if pending.action == "RESET_TASK":
                recovered = reset_task(
                    bundle_dir
                )

                return ChatTurnResult(
                    action="RESET_TASK",
                    status="RESET",
                    message=(
                        "当前任务已安全重置。\n"
                        "原任务内容："
                        + lifecycle_state_label(
                            recovered.previous_state
                        )
                        + "\n"
                        "现在可以开始新的骨架排名任务。"
                    ),
                    bundle_dir=(
                        recovered.bundle_dir
                    ),
                )

            archived = archive_task(
                bundle_dir
            )

            return ChatTurnResult(
                action="ARCHIVE_TASK",
                status="ARCHIVED",
                message=(
                    "当前任务已安全归档，"
                    "并重新建立同名空 Bundle。\n"
                    "原任务内容："
                    + lifecycle_state_label(
                        archived.previous_state
                    )
                    + "\n"
                    "归档位置："
                    f"{archived.archive_dir}"
                ),
                bundle_dir=archived.bundle_dir,
                artifact_paths={
                    "archive": (
                        archived.archive_dir
                    )
                },
            )

        except TaskRecoveryError as exc:
            raise ChatDialogueError(
                f"任务恢复失败：{exc}",
                public_message="任务恢复未完成。",
            ) from exc

    _, report = inspect_bundle(
        bundle_dir
    )

    if pending.action == "CREATE_DATASET_GROUP_TASKS":
        from protein_design_agent.agent.dataset_group_tasks import (
            DatasetGroupTaskError,
            create_group_task_bundles,
        )

        try:
            created = create_group_task_bundles(
                source_bundle=bundle_dir
            )
        except DatasetGroupTaskError as exc:
            clear_pending_action(bundle_dir)
            raise ChatDialogueError(
                f"无法创建分组任务：{exc}",
                public_message="无法创建分组任务。",
            ) from exc

        clear_pending_action(bundle_dir)

        task_lines = "\n".join(
            f"- {name}：{bundle}"
            for name, bundle in zip(
                created.task_names,
                created.created_bundles,
            )
        )

        return ChatTurnResult(
            action="INSPECT_DATASET",
            status="TASKS_CREATED",
            message=(
                "已创建相互隔离的任务 Bundle：\n"
                f"{task_lines}\n\n"
                "尚未批准或执行任何任务。"
            ),
            bundle_dir=bundle_dir.resolve(),
        )

    if pending.action == "ADOPT_DATASET_ADVICE":
        try:
            adopted = adopt_dataset_advice(
                bundle_dir=bundle_dir
            )
        except DatasetAdviceAdoptionError as exc:
            clear_pending_action(
                bundle_dir
            )

            raise ChatDialogueError(
                f"无法采用文件建议：{exc}",
                public_message="无法采用当前文件建议。",
            ) from exc

        clear_pending_action(
            bundle_dir
        )

        if adopted.status == "NEEDS_INFORMATION":
            message = (
                "已采用经过文件验证且由你确认的建议。\n\n"
                + natural_missing_message(
                    bundle_dir
                )
            )
        else:
            message = (
                "已采用经过文件验证且由你确认的建议。\n\n"
                "必要信息已经补齐，"
                "任务计划已经准备完成，"
                "可以审核后申请批准。"
            )

        return ChatTurnResult(
            action="ADOPT_DATASET_ADVICE",
            status=adopted.status,
            message=message,
            bundle_dir=bundle_dir.resolve(),
            artifact_paths={
                "planning_session": (
                    adopted.planning_session
                ),
                "prepare_manifest": (
                    adopted.prepare_manifest
                ),
                "history_record": (
                    adopted.history_record
                ),
            },
        )

    if pending.action == "APPROVE":
        if (
            report is not None
            and report.analysis_scope_level
            == "SMOKE_TEST_ONLY"
        ):
            internal_message = (
                "批准计划并确认小样本限制"
            )
        else:
            internal_message = "批准计划"

    elif pending.action == "EXECUTE":
        internal_message = "确认执行"

    elif pending.action == "ANALYZE":
        internal_message = "分析结果"

    else:
        internal_message = (
            "分析并解释结果"
        )

    try:
        result = process_chat_message(
            message=internal_message,
            bundle_dir=bundle_dir,
            provider=provider,
            approved_by=approved_by,
            model_config_path=(
                model_config_path
            ),
            profile_name=profile_name,
            allow_network=allow_network,
        )

    except Exception:
        # 失败动作可能已经产生部分状态变化，
        # 不允许继续复用旧确认。
        clear_pending_action(
            bundle_dir
        )
        raise

    clear_pending_action(
        bundle_dir
    )

    return result


def stage_guidance(
    *,
    bundle_dir: Path,
    current_stage: str,
    report: RunStatusReport | None,
) -> str:
    prepare_status = load_prepare_status(
        bundle_dir.resolve()
    )

    if prepare_status == "NEEDS_INFORMATION":
        return natural_missing_message(
            bundle_dir
        )

    if current_stage == "PREPARED":
        return (
            "任务计划已经准备完成。"
            "你可以先查看状态或计划，"
            "也可以直接说“这个方案可以，批准吧”。"
        )

    if current_stage == "APPROVED":
        return (
            "任务已经批准，但尚未执行。"
            "你可以说“开始运行吧”。"
            "Agent 会先向你复述影响，再等待确认。"
        )

    if current_stage == "EXECUTED":
        return (
            "BinderRanker 已经执行完成。"
            "你可以说“帮我分析结果”，"
            "或“分析并解释一下结果”。"
        )

    if current_stage in {
        "ANALYZED",
        "EXPLAINED",
    }:
        return (
            "当前进度："
            + user_status(
                current_stage,
                area="stage",
            )
            + "。"
            "你可以查看状态、阅读结果，"
            "或提出新的分析请求。"
        )

    if report is not None:
        return (
            "当前进度："
            + user_status(
                report.current_stage,
                area="stage",
            )
            + "。"
            "请先查看状态，再决定下一步。"
        )

    return (
        "请直接描述你希望完成的蛋白骨架排名任务。"
    )


def list_tasks_for_chat(
    *,
    bundle_dir: Path,
) -> ChatTurnResult:
    from protein_design_agent.agent.task_navigation import (
        format_workspace_tasks,
        list_workspace_tasks,
    )

    tasks = list_workspace_tasks(
        bundle_dir
    )

    return ChatTurnResult(
        action="LIST_TASKS",
        status="TASKS_LISTED",
        message=format_workspace_tasks(tasks),
        bundle_dir=bundle_dir.resolve(),
    )


def switch_task_for_chat(
    *,
    bundle_dir: Path,
    message: str,
    provider: Any | None,
) -> ChatTurnResult:
    from protein_design_agent.agent.task_navigation import (
        resolve_task_reference,
    )

    target = resolve_task_reference(
        current_bundle=bundle_dir,
        message=message,
        provider=provider,
    )

    return ChatTurnResult(
        action="SWITCH_TASK",
        status="TASK_SWITCHED",
        message=(
            f"已切换到任务：{target.name}\n"
            f"Bundle：{target}\n"
            "后续消息只读取和修改该任务。"
        ),
        bundle_dir=target,
    )


def process_dialogue_message(
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
    处理一条自然语言对话消息。

    大模型只能提出意图，不得直接执行有副作用动作。
    """
    navigation_message = message.strip()

    if navigation_message.casefold() in {
        "/tasks",
        "任务列表",
        "列出任务",
        "有哪些任务",
    }:
        return list_tasks_for_chat(
            bundle_dir=bundle_dir
        )

    if navigation_message.casefold().startswith(
        "/task "
    ):
        return switch_task_for_chat(
            bundle_dir=bundle_dir,
            message=navigation_message[6:].strip(),
            provider=provider,
        )
    (
        decision,
        pending,
        current_stage,
        report,
    ) = determine_intent(
        message=message,
        bundle_dir=bundle_dir,
        provider=provider,
        allow_network=allow_network,
    )

    intent = decision.intent

    if intent == "CONFIRM":
        if pending is None:
            raise ChatDialogueError(
                "当前没有等待确认的动作。",
                public_message="当前没有等待确认的动作。",
            )

        return confirm_pending_action(
            pending=pending,
            bundle_dir=bundle_dir,
            provider=provider,
            approved_by=approved_by,
            model_config_path=model_config_path,
            profile_name=profile_name,
            allow_network=allow_network,
        )

    if intent == "CANCEL":
        if pending is None:
            return ChatTurnResult(
                action="HELP",
                status="NOTHING_TO_CANCEL",
                message=(
                    "当前没有等待确认的动作。"
                ),
                bundle_dir=(
                    bundle_dir.resolve()
                ),
            )

        clear_pending_action(
            bundle_dir
        )

        return ChatTurnResult(
            action="HELP",
            status="CANCELLED",
            message=(
                "已取消："
                + pending_action_label(
                    pending.action
                )
            ),
            bundle_dir=bundle_dir.resolve(),
        )

    if intent == "REQUEST_RESET_TASK":
        return create_task_recovery_proposal(
            action="RESET_TASK",
            bundle_dir=bundle_dir,
        )

    if intent == "REQUEST_ARCHIVE_TASK":
        return create_task_recovery_proposal(
            action="ARCHIVE_TASK",
            bundle_dir=bundle_dir,
        )

    if pending is not None:
        if intent == "PROVIDE_INFORMATION":
            old_action = pending.action
            clear_pending_action(bundle_dir)

            updated = process_chat_message(
                message=message.strip(),
                bundle_dir=bundle_dir,
                provider=provider,
                approved_by=approved_by,
                model_config_path=model_config_path,
                profile_name=profile_name,
                allow_network=allow_network,
            )

            return updated.model_copy(
                update={
                    "message": (
                        "已收到你的补充或纠正。"
                        "原待确认的“"
                        + pending_action_label(
                            old_action
                        )
                        + "”已取消，"
                        "任务已经按新信息重新处理。\n\n"
                        + updated.message
                    )
                }
            )

        pending_reminder = pending_confirmation_reminder(
            pending
        )

        if intent == "GENERAL_QUESTION":
            safety_answer = (
                deterministic_pending_safety_answer(
                    pending=pending,
                    topics=decision.safety_topics,
                    report=report,
                )
            )

            if safety_answer is not None:
                return ChatTurnResult(
                    action="HELP",
                    status="ANSWER",
                    message=(
                        safety_answer
                        + pending_reminder
                    ),
                    bundle_dir=(
                        bundle_dir.resolve()
                    ),
                    artifact_paths={
                        "pending_action": (
                            pending_action_path(
                                bundle_dir
                            )
                        )
                    },
                )

            if (
                decision.reply
                and decision.reply.strip()
            ):
                return ChatTurnResult(
                    action="HELP",
                    status="ANSWER",
                    message=(
                        capability_safe_reply(
                            decision.reply
                        )
                        + pending_reminder
                    ),
                    bundle_dir=(
                        bundle_dir.resolve()
                    ),
                    artifact_paths={
                        "pending_action": (
                            pending_action_path(
                                bundle_dir
                            )
                        )
                    },
                )

            return ChatTurnResult(
                action="HELP",
                status=(
                    "AWAITING_CONFIRMATION"
                ),
                message=(
                    pending.summary
                    + pending_reminder
                ),
                bundle_dir=(
                    bundle_dir.resolve()
                ),
                artifact_paths={
                    "pending_action": (
                        pending_action_path(
                            bundle_dir
                        )
                    )
                },
            )

        if intent == "VIEW_PLAN":
            return ChatTurnResult(
                action="VIEW_PLAN",
                status="PLAN_AVAILABLE",
                message=(
                    format_current_plan(
                        bundle_dir
                    )
                    + pending_reminder
                ),
                bundle_dir=bundle_dir.resolve(),
                artifact_paths={
                    "pending_action": (
                        pending_action_path(
                            bundle_dir
                        )
                    )
                },
            )

        if intent == "VIEW_STATUS":
            status_result = (
                process_chat_message(
                    message="状态",
                    bundle_dir=bundle_dir,
                    provider=provider,
                    approved_by=approved_by,
                    model_config_path=(
                        model_config_path
                    ),
                    profile_name=profile_name,
                    allow_network=(
                        allow_network
                    ),
                )
            )

            return status_result.model_copy(
                update={
                    "message": (
                        status_result.message
                        + pending_reminder
                    )
                }
            )

        if intent == "HELP":
            help_result = (
                process_chat_message(
                    message="帮助",
                    bundle_dir=bundle_dir,
                    provider=provider,
                    approved_by=approved_by,
                    model_config_path=(
                        model_config_path
                    ),
                    profile_name=profile_name,
                    allow_network=(
                        allow_network
                    ),
                )
            )

            return help_result.model_copy(
                update={
                    "message": (
                        help_result.message
                        + pending_reminder
                    )
                }
            )

        return ChatTurnResult(
            action="HELP",
            status="AWAITING_CONFIRMATION",
            message=(
                "当前操作暂未开始；"
                "一次只处理一个待确认请求。"
                + pending_reminder
            ),
            bundle_dir=bundle_dir.resolve(),
            artifact_paths={
                "pending_action": (
                    pending_action_path(
                        bundle_dir
                    )
                )
            },
        )

    if intent == "HELP":
        return process_chat_message(
            message="帮助",
            bundle_dir=bundle_dir,
            provider=provider,
            approved_by=approved_by,
            model_config_path=model_config_path,
            profile_name=profile_name,
            allow_network=allow_network,
        )

    if intent == "VIEW_PLAN":
        return ChatTurnResult(
            action="VIEW_PLAN",
            status="PLAN_AVAILABLE",
            message=format_current_plan(
                bundle_dir
            ),
            bundle_dir=bundle_dir.resolve(),
            artifact_paths={
                "planning_session": (
                    bundle_dir.resolve()
                    / "planning_session.json"
                )
            },
        )

    if intent == "VIEW_STATUS":
        return process_chat_message(
            message="状态",
            bundle_dir=bundle_dir,
            provider=provider,
            approved_by=approved_by,
            model_config_path=model_config_path,
            profile_name=profile_name,
            allow_network=allow_network,
        )

    if intent == "LIST_TASKS":
        return list_tasks_for_chat(
            bundle_dir=bundle_dir
        )

    if intent == "SWITCH_TASK":
        return switch_task_for_chat(
            bundle_dir=bundle_dir,
            message=message,
            provider=provider,
        )

    if intent == "REQUEST_DATASET_INSPECTION":
        return inspect_dataset_and_propose_adoption(
            bundle_dir=bundle_dir,
            provider=provider,
            user_message=message,
        )

    if intent == "REQUEST_APPROVAL":
        return create_action_proposal(
            action="APPROVE",
            bundle_dir=bundle_dir,
            report=report,
        )

    if intent == "REQUEST_EXECUTION":
        return create_action_proposal(
            action="EXECUTE",
            bundle_dir=bundle_dir,
            report=report,
        )

    if intent == "REQUEST_ANALYSIS":
        if (
            report is None
            or report.execution_status != "COMPLETED"
        ):
            raise ChatDialogueError(
                "只有 BinderRanker 执行完成后"
                "才能分析结果。",
                public_message=(
                    "只有 BinderRanker 执行完成后"
                    "才能分析结果。"
                ),
            )

        # 确定性分析是只读操作：
        # 不调用模型、不修改 Ranker 原始输出，
        # 因此不需要额外确认。
        return process_chat_message(
            message="分析结果",
            bundle_dir=bundle_dir,
            provider=None,
            approved_by=approved_by,
            model_config_path=None,
            profile_name=None,
            allow_network=False,
        )

    if intent == "REQUEST_EXPLANATION":
        if not allow_network:
            raise ChatDialogueError(
                "生成模型解释需要在启动 Chat 时"
                "显式允许联网。",
                public_message=(
                    "当前 Chat 会话没有允许模型联网，"
                    "因此不能生成模型解释。"
                ),
            )

        return create_action_proposal(
            action="EXPLAIN",
            bundle_dir=bundle_dir,
            report=report,
        )

    if intent in {"START_TASK", "PROVIDE_INFORMATION"}:
        result = process_chat_message(
            message=message,
            bundle_dir=bundle_dir,
            provider=provider,
            approved_by=approved_by,
            model_config_path=model_config_path,
            profile_name=profile_name,
            allow_network=allow_network,
        )

        automatic_inspection = (
            maybe_auto_inspect_after_information(
                result=result,
                bundle_dir=bundle_dir,
                provider=provider,
                user_message=message,
            )
        )

        if automatic_inspection is not None:
            return automatic_inspection

        if result.status == "NEEDS_INFORMATION":
            return result.model_copy(
                update={
                    "message": (
                        natural_missing_message(
                            bundle_dir
                        )
                    )
                }
            )

        return result

    if intent == "GENERAL_QUESTION":
        if (
            decision.reply
            and decision.reply.strip()
        ):
            return ChatTurnResult(
                action="HELP",
                status="ANSWER",
                message=capability_safe_reply(
                    decision.reply
                ),
                bundle_dir=bundle_dir.resolve(),
            )

        if not allow_network:
            guidance = (
                "当前处于离线只读模式，"
                "没有可用的自然语言模型回答这个问题。"
                "为避免误解，我不会把这句话当作科研参数，"
                "也不会修改当前任务。"
                "你仍可使用“帮助”“状态”“查看计划”"
                "和“任务列表”等确定性功能。"
            )
        else:
            guidance = stage_guidance(
                bundle_dir=bundle_dir,
                current_stage=current_stage,
                report=report,
            )

        return ChatTurnResult(
            action="HELP",
            status="GUIDANCE",
            message=guidance,
            bundle_dir=bundle_dir.resolve(),
        )

    return ChatTurnResult(
        action="HELP",
        status="GUIDANCE",
        message=stage_guidance(
            bundle_dir=bundle_dir,
            current_stage=current_stage,
            report=report,
        ),
        bundle_dir=bundle_dir.resolve(),
    )
