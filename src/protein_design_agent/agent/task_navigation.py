#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""受管工作空间中的通用任务列表和任务选择。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from protein_design_agent.agent.workspace_tasks import (
    list_task_bundles,
    resolve_task_bundle,
    resolve_workspace_from_bundle,
)


class TaskNavigationError(RuntimeError):
    """无法安全列出或切换任务。"""


class TaskSelectionDecision(BaseModel):
    """模型从真实任务列表中选择一个任务。"""

    model_config = ConfigDict(extra="forbid")

    task_name: str
    reason: str


@dataclass(frozen=True)
class WorkspaceTaskSummary:
    task_name: str
    bundle_dir: Path
    prepare_status: str
    is_current: bool


def read_prepare_status(
    bundle_dir: Path,
) -> str:
    """只读获取任务的准备状态。"""
    manifest = (
        bundle_dir
        / "agent_prepare_manifest.json"
    )

    if not manifest.is_file():
        return "EMPTY"

    try:
        value = json.loads(
            manifest.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return "UNKNOWN"

    status = value.get("status")

    return (
        status
        if isinstance(status, str)
        else "UNKNOWN"
    )


def list_workspace_tasks(
    current_bundle: Path,
) -> tuple[WorkspaceTaskSummary, ...]:
    """列出当前工作空间中的任意数量任务。"""
    current = current_bundle.resolve()

    try:
        workspace = resolve_workspace_from_bundle(
            current
        )
        bundles = list_task_bundles(workspace)
    except Exception as exc:
        raise TaskNavigationError(
            f"无法读取当前工作空间任务：{exc}"
        ) from exc

    return tuple(
        WorkspaceTaskSummary(
            task_name=bundle.name,
            bundle_dir=bundle,
            prepare_status=read_prepare_status(
                bundle
            ),
            is_current=(
                bundle.resolve() == current
            ),
        )
        for bundle in bundles
    )


def format_workspace_tasks(
    tasks: tuple[WorkspaceTaskSummary, ...],
) -> str:
    """格式化任务列表。"""
    if not tasks:
        return "当前工作空间中没有任务。"

    lines = [
        "当前工作空间中的任务：",
        "",
        "任务名 | 规划状态 | 当前任务",
        "-" * 44,
    ]

    for task in tasks:
        lines.append(
            f"{task.task_name} | "
            f"{task.prepare_status} | "
            f"{'是' if task.is_current else '否'}"
        )

    lines.append("")
    lines.append(
        "可以直接说“切换到 group_a”，"
        "或使用 `/task group_a`。"
    )

    return "\n".join(lines)


def direct_task_match(
    *,
    message: str,
    task_names: list[str],
) -> str | None:
    """
    从消息中寻找唯一真实任务名。

    不清洗、不猜测，也不把相似名称静默合并。
    """
    folded_message = message.casefold()

    matches = [
        name
        for name in task_names
        if name.casefold() in folded_message
    ]

    if len(matches) == 1:
        return matches[0]

    return None


def resolve_task_reference(
    *,
    current_bundle: Path,
    message: str,
    provider: Any | None,
) -> Path:
    """
    从自然语言中选择真实存在的任务。

    任务列表来自确定性目录扫描；
    模型只能在该列表中选择，不能编造任务。
    """
    tasks = list_workspace_tasks(
        current_bundle
    )

    if not tasks:
        raise TaskNavigationError(
            "当前工作空间中没有可切换的任务"
        )

    names = [
        task.task_name
        for task in tasks
    ]

    selected = direct_task_match(
        message=message,
        task_names=names,
    )

    if selected is None:
        if (
            provider is None
            or not hasattr(
                provider,
                "generate_json",
            )
        ):
            raise TaskNavigationError(
                "没有识别出唯一任务名。"
                "请使用 `/task 任务名`，"
                "可用任务为："
                + ", ".join(names)
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是任务导航助手。"
                    "只能从 available_tasks 中选择一个"
                    "真实任务名，不能编造、修改或创建任务。"
                    "返回 task_name 和 reason。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": message,
                        "available_tasks": names,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        try:
            payload = provider.generate_json(
                messages
            )
            decision = (
                TaskSelectionDecision
                .model_validate(payload)
            )
        except Exception as exc:
            raise TaskNavigationError(
                f"无法解析目标任务：{exc}"
            ) from exc

        matches = {
            name.casefold(): name
            for name in names
        }

        selected = matches.get(
            decision.task_name.casefold()
        )

        if selected is None:
            raise TaskNavigationError(
                "模型选择了不存在的任务："
                f"{decision.task_name}"
            )

    workspace = resolve_workspace_from_bundle(
        current_bundle
    )

    target = resolve_task_bundle(
        workspace_dir=workspace,
        task_name=selected,
    )

    if not target.is_dir():
        raise TaskNavigationError(
            f"目标任务不存在：{selected}"
        )

    return target
