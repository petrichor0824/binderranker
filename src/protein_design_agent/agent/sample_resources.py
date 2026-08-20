#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""访问和提取随 Wheel 发布的最小示例数据。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from protein_design_agent.agent.user_errors import (
    UserFacingError,
)


SAMPLE_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)

PACKAGED_SAMPLE_NAMES = (
    "3c98_small",
)


class PackagedSampleError(UserFacingError):
    """无法安全读取或提取包内示例数据。"""


@dataclass(frozen=True)
class PackagedSampleExtraction:
    sample_name: str
    destination: Path
    pdb_files: tuple[Path, ...]


def validate_sample_name(
    sample_name: str,
) -> str:
    clean = sample_name.strip()

    if (
        not clean
        or SAMPLE_NAME_PATTERN.fullmatch(
            clean
        ) is None
        or clean not in PACKAGED_SAMPLE_NAMES
    ):
        raise PackagedSampleError(
            "未知或无效的包内样例名称："
            f"{sample_name!r}；"
            "可用样例："
            + ", ".join(PACKAGED_SAMPLE_NAMES),
            public_message=(
                "未知或无效的包内样例名称。"
                "可用样例："
                + ", ".join(PACKAGED_SAMPLE_NAMES)
            ),
        )

    return clean


def packaged_sample_pdb_names(
    sample_name: str = "3c98_small",
) -> tuple[str, ...]:
    """只读列出包内样例的 PDB 文件名。"""
    clean = validate_sample_name(
        sample_name
    )

    sample_root = (
        resources.files("protein_design_agent")
        .joinpath("resources")
        .joinpath("samples")
        .joinpath(clean)
    )

    if not sample_root.is_dir():
        raise PackagedSampleError(
            "安装包中缺少样例目录："
            f"{clean}",
            public_message=(
                f"安装包中缺少样例目录：{clean}。"
            ),
        )

    names = tuple(
        sorted(
            item.name
            for item in sample_root.iterdir()
            if (
                item.is_file()
                and item.name.lower().endswith(
                    ".pdb"
                )
            )
        )
    )

    if not names:
        raise PackagedSampleError(
            f"安装包中的样例 {clean} "
            "没有 PDB 文件",
            public_message=(
                f"安装包中的样例 {clean} "
                "没有 PDB 文件。"
            ),
        )

    return names


def extract_packaged_sample(
    *,
    destination: Path,
    sample_name: str = "3c98_small",
) -> PackagedSampleExtraction:
    """
    将包内样例复制到真实文件系统目录。

    目标目录可以不存在或为空；禁止覆盖非空目录。
    """
    clean = validate_sample_name(
        sample_name
    )
    target_root = (
        destination.expanduser().resolve()
    )

    if target_root.exists():
        if not target_root.is_dir():
            raise PackagedSampleError(
                "样例目标路径不是目录："
                f"{target_root}",
                public_message=(
                    "样例目标路径不是目录。"
                ),
            )

        if any(target_root.iterdir()):
            raise PackagedSampleError(
                "样例目标目录非空，禁止覆盖："
                f"{target_root}",
                public_message=(
                    "样例目标目录非空，禁止覆盖。"
                ),
            )
    else:
        target_root.mkdir(
            parents=True,
            exist_ok=False,
        )

    resource_root = (
        resources.files("protein_design_agent")
        .joinpath("resources")
        .joinpath("samples")
        .joinpath(clean)
    )

    created: list[Path] = []

    try:
        for name in packaged_sample_pdb_names(
            clean
        ):
            source = resource_root.joinpath(name)
            target = target_root / name

            target.write_bytes(
                source.read_bytes()
            )
            created.append(target)

    except Exception as exc:
        for path in reversed(created):
            path.unlink(missing_ok=True)

        try:
            target_root.rmdir()
        except OSError:
            pass

        if isinstance(
            exc,
            PackagedSampleError,
        ):
            raise

        raise PackagedSampleError(
            f"提取包内样例失败：{exc}",
            public_message="样例提取未完成。",
        ) from exc

    return PackagedSampleExtraction(
        sample_name=clean,
        destination=target_root,
        pdb_files=tuple(created),
    )
