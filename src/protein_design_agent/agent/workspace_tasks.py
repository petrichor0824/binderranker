#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""工作空间内多任务 Bundle 的统一命名与路径规则。"""

from __future__ import annotations

from pathlib import Path


DEFAULT_TASK_NAME = "default"
MAX_TASK_NAME_LENGTH = 64

# 保留工作空间结构名，避免任务名称造成概念混乱；
# 同时避开 Windows 保留设备名，保证发布包可移植。
RESERVED_TASK_NAMES = frozenset(
    {
        "analyses",
        "chat",
        "configs",
        "data",
        "logs",
        "runs",
        "workflow",
        "con",
        "prn",
        "aux",
        "nul",
        *{
            f"com{index}"
            for index in range(1, 10)
        },
        *{
            f"lpt{index}"
            for index in range(1, 10)
        },
    }
)


class TaskPathError(ValueError):
    """任务名称或 Bundle 路径不安全。"""


def validate_task_name(value: str) -> str:
    """
    校验用户可见的任务名称。

    支持中文、英文、数字、下划线和连字符；
    不静默替换非法字符，避免两个原始名称映射到同一目录。
    """
    if not isinstance(value, str):
        raise TaskPathError(
            "任务名称必须是字符串"
        )

    clean = value.strip()

    if not clean:
        raise TaskPathError(
            "任务名称不能为空"
        )

    if clean != value:
        raise TaskPathError(
            "任务名称首尾不能包含空白字符"
        )

    if len(clean) > MAX_TASK_NAME_LENGTH:
        raise TaskPathError(
            "任务名称过长；最多允许 "
            f"{MAX_TASK_NAME_LENGTH} 个字符"
        )

    if clean in {".", ".."}:
        raise TaskPathError(
            "任务名称不能是 '.' 或 '..'"
        )

    if clean.casefold() in RESERVED_TASK_NAMES:
        raise TaskPathError(
            f"任务名称属于保留名称：{clean}"
        )

    if not clean[0].isalnum():
        raise TaskPathError(
            "任务名称必须以中文、英文字母或数字开头"
        )

    invalid_characters = [
        character
        for character in clean
        if not (
            character.isalnum()
            or character in {"_", "-"}
        )
    ]

    if invalid_characters:
        rendered = ", ".join(
            repr(character)
            for character in sorted(
                set(invalid_characters)
            )
        )
        raise TaskPathError(
            "任务名称只能包含中文、英文字母、数字、"
            "下划线和连字符；发现非法字符："
            f"{rendered}"
        )

    return clean


def ensure_path_within(
    *,
    child: Path,
    parent: Path,
    description: str,
) -> None:
    """拒绝符号链接或路径解析造成的目录逃逸。"""
    try:
        child.relative_to(parent)
    except ValueError as exc:
        raise TaskPathError(
            f"{description}超出允许的工作空间范围"
        ) from exc


def resolve_task_bundle(
    *,
    workspace_dir: Path,
    task_name: str,
) -> Path:
    """
    将任务名称解析为工作空间内的独立 Bundle。

    本函数只计算路径，不创建目录，不写入文件。
    """
    valid_name = validate_task_name(
        task_name
    )

    workspace = (
        workspace_dir.expanduser().resolve()
    )
    runs_root = (
        workspace / "runs"
    ).resolve()

    ensure_path_within(
        child=runs_root,
        parent=workspace,
        description="任务根目录",
    )

    bundle = (
        runs_root / valid_name
    ).resolve()

    ensure_path_within(
        child=bundle,
        parent=runs_root,
        description="任务 Bundle",
    )

    return bundle


def resolve_workspace_from_bundle(
    bundle_dir: Path,
) -> Path:
    """
    从受管 Bundle 解析所属工作空间。

    Bundle 必须位于 <workspace>/runs/<task>。
    """
    bundle = bundle_dir.expanduser().resolve()
    runs_root = bundle.parent
    workspace = runs_root.parent

    if (
        runs_root.name != "runs"
        or not (
            workspace / ".pda-workspace.json"
        ).is_file()
    ):
        raise TaskPathError(
            "当前任务不属于可导航的受管工作空间"
        )

    ensure_path_within(
        child=bundle,
        parent=runs_root.resolve(),
        description="任务 Bundle",
    )

    return workspace


def list_task_bundles(
    workspace_dir: Path,
) -> tuple[Path, ...]:
    """只读列出工作空间中所有合法任务 Bundle。"""
    workspace = (
        workspace_dir.expanduser().resolve()
    )
    runs_root = (workspace / "runs").resolve()

    ensure_path_within(
        child=runs_root,
        parent=workspace,
        description="任务根目录",
    )

    if not runs_root.is_dir():
        return ()

    bundles: list[Path] = []

    for child in sorted(
        runs_root.iterdir(),
        key=lambda item: item.name.casefold(),
    ):
        if (
            child.is_symlink()
            or not child.is_dir()
        ):
            continue

        try:
            validate_task_name(child.name)
        except TaskPathError:
            continue

        resolved = child.resolve()

        ensure_path_within(
            child=resolved,
            parent=runs_root,
            description="任务 Bundle",
        )

        bundles.append(resolved)

    return tuple(bundles)
