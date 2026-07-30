#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Protein Design Agent CLI 的安全本地默认值。"""

from __future__ import annotations

import getpass
from pathlib import Path


DEFAULT_WORKSPACE_NAME = ".protein-design-agent"
DEFAULT_BUNDLE_NAME = "default"


def resolve_chat_workspace_dir(
    *,
    cwd: Path | None = None,
) -> Path:
    """解析无参数 chat 使用的工作空间根目录。"""
    working_directory = (
        cwd if cwd is not None else Path.cwd()
    )

    return (
        working_directory.expanduser().resolve()
        / DEFAULT_WORKSPACE_NAME
    ).resolve()


def resolve_chat_bundle_dir(
    value: Path | None,
    *,
    cwd: Path | None = None,
) -> Path:
    """
    解析聊天使用的 Bundle 路径。

    显式路径永远优先。没有显式路径时，在当前目录下
    使用独立隐藏工作空间，避免污染用户现有文件。
    """
    if value is not None:
        return value.expanduser().resolve()

    workspace = resolve_chat_workspace_dir(
        cwd=cwd
    )

    return (
        workspace
        / "runs"
        / DEFAULT_BUNDLE_NAME
    ).resolve()


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
