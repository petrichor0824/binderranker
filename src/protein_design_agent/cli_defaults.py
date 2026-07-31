#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Protein Design Agent CLI 的安全本地默认值。"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from pathlib import Path

from protein_design_agent.agent.workspace_tasks import (
    DEFAULT_TASK_NAME,
    resolve_task_bundle,
)


DEFAULT_WORKSPACE_NAME = ".protein-design-agent"


@dataclass(frozen=True)
class ChatTarget:
    """一次 chat 启动所选择的工作空间和任务。"""

    bundle_dir: Path
    workspace_dir: Path | None
    task_name: str
    uses_default_workspace: bool


def resolve_chat_workspace_dir(
    *,
    cwd: Path | None = None,
) -> Path:
    """解析无参数 chat 使用的工作空间根目录。"""
    working_directory = (
        cwd if cwd is not None else Path.cwd()
    )

    resolved = working_directory.expanduser().resolve()

    if (resolved / ".pda-workspace.json").is_file():
        return resolved

    return (
        resolved / DEFAULT_WORKSPACE_NAME
    ).resolve()


def resolve_chat_bundle_dir(
    value: Path | None,
    *,
    task_name: str = DEFAULT_TASK_NAME,
    cwd: Path | None = None,
) -> Path:
    """
    解析聊天使用的 Bundle 路径。

    显式 Bundle 永远优先；没有显式路径时，
    根据工作空间和任务名称计算独立 Bundle。
    """
    if value is not None:
        return value.expanduser().resolve()

    workspace = resolve_chat_workspace_dir(
        cwd=cwd
    )

    return resolve_task_bundle(
        workspace_dir=workspace,
        task_name=task_name,
    )


def resolve_chat_target(
    *,
    bundle_dir: Path | None,
    task_name: str | None,
    cwd: Path | None = None,
) -> ChatTarget:
    """
    统一解析 chat 的任务目标。

    --bundle-dir 与 --task 不能同时提供，
    避免出现两个互相冲突的任务来源。
    """
    if bundle_dir is not None:
        if task_name is not None:
            raise ValueError(
                "--bundle-dir 与 --task 不能同时使用；"
                "显式 Bundle 已经唯一确定任务"
            )

        resolved_bundle = (
            bundle_dir.expanduser().resolve()
        )

        return ChatTarget(
            bundle_dir=resolved_bundle,
            workspace_dir=None,
            task_name=(
                resolved_bundle.name
                or "explicit-bundle"
            ),
            uses_default_workspace=False,
        )

    workspace = resolve_chat_workspace_dir(
        cwd=cwd
    )
    selected_task = (
        task_name
        if task_name is not None
        else DEFAULT_TASK_NAME
    )

    return ChatTarget(
        bundle_dir=resolve_task_bundle(
            workspace_dir=workspace,
            task_name=selected_task,
        ),
        workspace_dir=workspace,
        task_name=selected_task,
        uses_default_workspace=True,
    )


def resolve_local_approved_by(
    value: str | None,
) -> str:
    """
    解析本地审计标识。

    该值只是本地审计记录，不代表身份认证。
    """
    if value is not None and value.strip():
        return value.strip()

    try:
        username = getpass.getuser().strip()
    except Exception:
        username = ""

    return username or "local-user"
