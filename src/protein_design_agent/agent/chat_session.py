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
]


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

        return ChatTurnResult(
            action=(
                "EXPLAIN"
                if with_model
                else "ANALYZE"
            ),
            status=result.status,
            message="\n".join(
                [
                    (
                        "分析与模型解释完成。"
                        if with_model
                        else "确定性分析完成。"
                    ),
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
