#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""BinderRanker 本地文件系统路径语义。"""

from __future__ import annotations

import os
from pathlib import (
    Path,
    PurePosixPath,
    PureWindowsPath,
)
from typing import Literal


AbsolutePathStyle = Literal[
    "windows",
    "posix",
]


class IncompatiblePathError(ValueError):
    """路径属于其他平台的绝对路径语义。"""


def detect_absolute_path_style(
    value: str | Path,
) -> AbsolutePathStyle | None:
    """
    仅按字符串语义判断绝对路径风格。

    不访问文件系统，也不转换路径。
    """
    text = str(value)

    windows_absolute = (
        PureWindowsPath(text).is_absolute()
    )
    posix_absolute = (
        PurePosixPath(text).is_absolute()
    )

    if (
        windows_absolute
        and not posix_absolute
    ):
        return "windows"

    if (
        posix_absolute
        and not windows_absolute
    ):
        return "posix"

    return None


def resolve_local_path(
    value: str | Path,
    *,
    base_directory: Path | None = None,
    field_name: str = "path",
) -> Path:
    """
    在当前平台安全解析路径。

    相对路径相对于 base_directory；
    未提供 base_directory 时保持 pathlib 现有 cwd 语义。

    其他平台的绝对路径不会被静默解释成相对路径。
    """
    text = str(value)

    if not text.strip():
        raise ValueError(
            f"{field_name} 不能为空"
        )

    style = detect_absolute_path_style(
        text
    )

    current_style: AbsolutePathStyle = (
        "windows"
        if os.name == "nt"
        else "posix"
    )

    if (
        style is not None
        and style != current_style
    ):
        foreign_name = (
            "Windows"
            if style == "windows"
            else "POSIX"
        )
        current_name = (
            "Windows"
            if current_style == "windows"
            else "POSIX"
        )

        raise IncompatiblePathError(
            f"{field_name} 使用了 "
            f"{foreign_name} 风格绝对路径，"
            f"但 BinderRanker 当前运行在 "
            f"{current_name} 环境：{text}。"
            "不会自动转换跨平台路径；"
            "请提供当前环境实际可访问的路径。"
        )

    path = Path(text)

    if (
        not path.is_absolute()
        and base_directory is not None
    ):
        path = base_directory / path

    return path.resolve()
