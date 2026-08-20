#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
受管工作空间中的安全任务恢复。

本模块只负责确定性的 reset / archive。
大模型可以提出恢复意图，但无权绕过生命周期检查。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from protein_design_agent.agent.task_lifecycle import (
    TaskLifecycleState,
    inspect_task_lifecycle,
)
from protein_design_agent.agent.workspace_tasks import (
    TaskPathError,
    resolve_workspace_from_bundle,
)


class TaskRecoveryError(RuntimeError):
    """任务无法按照安全规则恢复。"""


@dataclass(frozen=True)
class TaskResetReport:
    """安全重置结果。"""

    bundle_dir: Path
    previous_state: str
    status: str = "RESET"


@dataclass(frozen=True)
class TaskArchiveReport:
    """安全归档结果。"""

    bundle_dir: Path
    archive_dir: Path
    previous_state: str
    status: str = "ARCHIVED"


def require_managed_workspace(
    bundle_dir: Path,
) -> Path:
    """确认 Bundle 属于受管工作空间。"""
    try:
        return resolve_workspace_from_bundle(
            bundle_dir
        )
    except TaskPathError as exc:
        raise TaskRecoveryError(
            f"任务不属于受管工作空间：{exc}"
        ) from exc


def reset_task(
    bundle_dir: Path,
) -> TaskResetReport:
    """
    重置 EMPTY 或 INCOMPLETE 任务。

    包含正式科研/审计证据的任务禁止直接删除，
    必须先归档。
    """
    bundle = bundle_dir.expanduser().resolve()

    require_managed_workspace(bundle)

    report = inspect_task_lifecycle(bundle)

    if (
        report.state
        == TaskLifecycleState.VALID_WITH_EVIDENCE
    ):
        raise TaskRecoveryError(
            "当前任务包含受保护证据，禁止直接重置；"
            "请先归档任务。"
        )

    previous_state = report.state.value

    if bundle.exists():
        if not bundle.is_dir():
            raise TaskRecoveryError(
                f"任务路径不是目录：{bundle}"
            )

        shutil.rmtree(bundle)

    bundle.mkdir(
        parents=True,
        exist_ok=False,
    )

    return TaskResetReport(
        bundle_dir=bundle,
        previous_state=previous_state,
    )


def build_archive_destination(
    *,
    workspace: Path,
    task_name: str,
) -> Path:
    """生成不会覆盖历史记录的归档目录。"""
    archive_root = (
        workspace
        / "archives"
        / task_name
    )

    archive_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    destination = archive_root / timestamp

    if destination.exists():
        raise TaskRecoveryError(
            "归档目标发生时间戳冲突，"
            "为避免覆盖历史记录已停止操作。"
        )

    return destination


def archive_task(
    bundle_dir: Path,
) -> TaskArchiveReport:
    """
    将非空任务完整归档，并重新建立同名空 Bundle。

    原 Bundle 和 archives 位于同一工作空间，
    使用原子 rename 发布归档。
    """
    bundle = bundle_dir.expanduser().resolve()

    workspace = require_managed_workspace(
        bundle
    )

    report = inspect_task_lifecycle(bundle)

    if report.state == TaskLifecycleState.EMPTY:
        raise TaskRecoveryError(
            "当前是空任务，空任务无需归档；"
            "可以直接继续使用或重置。"
        )

    if not bundle.is_dir():
        raise TaskRecoveryError(
            f"任务 Bundle 不存在或不是目录：{bundle}"
        )

    destination = build_archive_destination(
        workspace=workspace,
        task_name=bundle.name,
    )

    try:
        os.replace(
            bundle,
            destination,
        )
    except OSError as exc:
        raise TaskRecoveryError(
            f"无法原子归档任务：{exc}"
        ) from exc

    try:
        bundle.mkdir(
            parents=False,
            exist_ok=False,
        )
    except Exception as exc:
        # 新空 Bundle 创建失败时优先恢复原任务，
        # 避免用户突然失去当前任务路径。
        try:
            if (
                destination.exists()
                and not bundle.exists()
            ):
                os.replace(
                    destination,
                    bundle,
                )
        except Exception:
            pass

        raise TaskRecoveryError(
            "任务已经移动到归档阶段，"
            "但重新建立当前 Bundle 失败；"
            f"{exc}"
        ) from exc

    return TaskArchiveReport(
        bundle_dir=bundle,
        archive_dir=destination,
        previous_state=report.state.value,
    )
