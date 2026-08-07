#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
任务 Bundle 生命周期的确定性判定。

本模块不依赖大模型，也不执行任何删除、归档或科研工作流。
它只回答一个安全问题：

当前 Bundle 是否可以被安全重置，
还是已经包含必须保护的科研/审计证据？
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TaskLifecycleState(str, Enum):
    """任务 Bundle 的生命周期状态。"""

    EMPTY = "EMPTY"
    INCOMPLETE = "INCOMPLETE"
    VALID_WITH_EVIDENCE = "VALID_WITH_EVIDENCE"


@dataclass(frozen=True)
class TaskLifecycleReport:
    """任务生命周期只读检查结果。"""

    bundle_dir: Path
    state: TaskLifecycleState
    has_protected_evidence: bool
    reasons: tuple[str, ...]


INCOMPLETE_TOP_LEVEL_NAMES = {
    "planning_session.json",
    "pending_action.json",
}

PROTECTED_TOP_LEVEL_NAMES = {
    "project.yaml",
    "project.provenance.json",
    "approval.json",
}


def read_prepare_manifest_status(
    path: Path,
) -> str | None:
    """读取 prepare manifest 状态；损坏内容按未知处理。"""
    if not path.is_file():
        return None

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return "UNKNOWN"

    if not isinstance(value, dict):
        return "UNKNOWN"

    status = value.get("status")

    return (
        status
        if isinstance(status, str)
        else "UNKNOWN"
    )


def inspect_task_lifecycle(
    bundle_dir: Path,
) -> TaskLifecycleReport:
    """
    确定性检查 Bundle 生命周期。

    安全原则：
    无法确认安全删除的内容，一律视为受保护证据。
    """
    bundle = bundle_dir.resolve()

    if not bundle.exists():
        return TaskLifecycleReport(
            bundle_dir=bundle,
            state=TaskLifecycleState.EMPTY,
            has_protected_evidence=False,
            reasons=("bundle_missing",),
        )

    if not bundle.is_dir():
        return TaskLifecycleReport(
            bundle_dir=bundle,
            state=(
                TaskLifecycleState
                .VALID_WITH_EVIDENCE
            ),
            has_protected_evidence=True,
            reasons=("bundle_path_is_not_directory",),
        )

    items = list(bundle.iterdir())

    if not items:
        return TaskLifecycleReport(
            bundle_dir=bundle,
            state=TaskLifecycleState.EMPTY,
            has_protected_evidence=False,
            reasons=("bundle_empty",),
        )

    reasons: list[str] = []
    protected = False

    prepare_manifest = (
        bundle / "agent_prepare_manifest.json"
    )
    prepare_status = read_prepare_manifest_status(
        prepare_manifest
    )

    if prepare_status is not None:
        if prepare_status in {
            "NEEDS_INFORMATION",
            "FAILED",
        }:
            reasons.append(
                f"prepare_status:{prepare_status}"
            )
        else:
            protected = True
            reasons.append(
                f"protected_prepare_status:{prepare_status}"
            )

    for name in PROTECTED_TOP_LEVEL_NAMES:
        if (bundle / name).exists():
            protected = True
            reasons.append(
                f"protected_file:{name}"
            )

    execution_manifests = list(
        bundle.glob("execution_*.json")
    )
    if execution_manifests:
        protected = True
        reasons.append(
            "execution_manifest_present"
        )

    analyses = bundle / "analyses"
    if analyses.exists():
        protected = True
        reasons.append(
            "analysis_evidence_present"
        )

    workflow = bundle / "workflow"
    if workflow.exists():
        protected = True
        reasons.append(
            "workflow_evidence_present"
        )

    recognized_names = (
        INCOMPLETE_TOP_LEVEL_NAMES
        | PROTECTED_TOP_LEVEL_NAMES
        | {"agent_prepare_manifest.json"}
    )

    for item in items:
        if item.name in recognized_names:
            continue

        if item.name.startswith("execution_"):
            continue

        if item.name in {
            "workflow",
            "analyses",
        }:
            continue

        # 未知内容不能默认安全删除。
        protected = True
        reasons.append(
            f"unknown_item:{item.name}"
        )

    if protected:
        return TaskLifecycleReport(
            bundle_dir=bundle,
            state=(
                TaskLifecycleState
                .VALID_WITH_EVIDENCE
            ),
            has_protected_evidence=True,
            reasons=tuple(reasons),
        )

    return TaskLifecycleReport(
        bundle_dir=bundle,
        state=TaskLifecycleState.INCOMPLETE,
        has_protected_evidence=False,
        reasons=tuple(reasons),
    )
