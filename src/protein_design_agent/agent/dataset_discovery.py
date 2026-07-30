#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""只读发现一个根目录下可能存在的多个 PDB 数据集。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from protein_design_agent.agent.workspace_tasks import (
    TaskPathError,
    validate_task_name,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    collect_pdb_files,
)


DiscoveryLayout = Literal[
    "EMPTY",
    "ROOT_DATASET",
    "CHILD_DATASETS",
    "MIXED_LAYOUT",
]


class DatasetDiscoveryError(RuntimeError):
    """无法安全完成只读数据集发现。"""


@dataclass(frozen=True)
class DatasetGroupCandidate:
    """一个可能独立排序的 PDB 分组。"""

    directory: Path
    relative_path: str
    directory_name: str
    pdb_count: int
    suggested_task_name: str | None
    naming_warning: str | None = None


@dataclass(frozen=True)
class DatasetDiscoveryReport:
    """根目录中的 PDB 布局证据。"""

    root_directory: Path
    layout: DiscoveryLayout
    root_level_pdb_count: int
    groups: tuple[DatasetGroupCandidate, ...]
    empty_child_directories: tuple[str, ...]
    skipped_symlink_directories: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def total_group_count(self) -> int:
        return len(self.groups)

    @property
    def total_discovered_pdb_count(self) -> int:
        return (
            self.root_level_pdb_count
            + sum(
                group.pdb_count
                for group in self.groups
            )
        )


def suggest_task_name(
    directory_name: str,
) -> tuple[str | None, str | None]:
    """
    尝试把目录名直接作为任务名。

    不静默修改非法名称，避免不同目录被映射为同一任务。
    """
    try:
        return (
            validate_task_name(directory_name),
            None,
        )
    except TaskPathError as exc:
        return (
            None,
            str(exc),
        )


def classify_layout(
    *,
    root_level_pdb_count: int,
    group_count: int,
) -> DiscoveryLayout:
    """根据真实文件位置描述目录布局，不替用户做分组决定。"""
    if (
        root_level_pdb_count == 0
        and group_count == 0
    ):
        return "EMPTY"

    if (
        root_level_pdb_count > 0
        and group_count == 0
    ):
        return "ROOT_DATASET"

    if (
        root_level_pdb_count == 0
        and group_count > 0
    ):
        return "CHILD_DATASETS"

    return "MIXED_LAYOUT"


def discover_dataset_groups(
    root_directory: Path,
) -> DatasetDiscoveryReport:
    """
    扫描根目录和所有直接子目录中的顶层 PDB。

    只读，不创建 Bundle，不修改 PDB，不自动采用分组。
    """
    root = root_directory.expanduser().resolve()

    if not root.is_dir():
        raise DatasetDiscoveryError(
            "数据根目录不存在或不是目录："
            f"{root}"
        )

    try:
        root_pdbs = collect_pdb_files(
            input_dir=root,
            recursive=False,
            max_files=None,
        )
    except OSError as exc:
        raise DatasetDiscoveryError(
            f"无法读取数据根目录：{exc}"
        ) from exc

    groups: list[DatasetGroupCandidate] = []
    empty_directories: list[str] = []
    skipped_symlinks: list[str] = []
    warnings: list[str] = []

    try:
        child_paths = sorted(
            root.iterdir(),
            key=lambda path: path.name.casefold(),
        )
    except OSError as exc:
        raise DatasetDiscoveryError(
            f"无法枚举数据根目录：{exc}"
        ) from exc

    for child in child_paths:
        if child.is_symlink():
            if child.is_dir():
                skipped_symlinks.append(child.name)
            continue

        if not child.is_dir():
            continue

        try:
            pdb_files = collect_pdb_files(
                input_dir=child,
                recursive=False,
                max_files=None,
            )
        except OSError as exc:
            warnings.append(
                "无法读取子目录："
                f"{child.name}；{exc}"
            )
            continue

        if not pdb_files:
            empty_directories.append(child.name)
            continue

        task_name, naming_warning = (
            suggest_task_name(child.name)
        )

        groups.append(
            DatasetGroupCandidate(
                directory=child.resolve(),
                relative_path=child.name,
                directory_name=child.name,
                pdb_count=len(pdb_files),
                suggested_task_name=task_name,
                naming_warning=naming_warning,
            )
        )

    layout = classify_layout(
        root_level_pdb_count=len(root_pdbs),
        group_count=len(groups),
    )

    if layout == "EMPTY":
        warnings.append(
            "根目录及其直接子目录中均未发现顶层 PDB"
        )

    if layout == "MIXED_LAYOUT":
        warnings.append(
            "根目录和子目录中同时存在 PDB；"
            "必须由用户确认是否分别排序"
        )

    invalid_names = [
        group.directory_name
        for group in groups
        if group.suggested_task_name is None
    ]

    if invalid_names:
        warnings.append(
            "部分目录名不能直接作为任务名："
            + ", ".join(invalid_names)
        )

    if skipped_symlinks:
        warnings.append(
            "为避免目录逃逸，本次未扫描符号链接目录"
        )

    return DatasetDiscoveryReport(
        root_directory=root,
        layout=layout,
        root_level_pdb_count=len(root_pdbs),
        groups=tuple(groups),
        empty_child_directories=tuple(
            empty_directories
        ),
        skipped_symlink_directories=tuple(
            skipped_symlinks
        ),
        warnings=tuple(warnings),
    )
