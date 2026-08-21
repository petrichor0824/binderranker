#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""为不同终端生成不把 API Key 写入命令历史的设置指引。"""

from __future__ import annotations

import re
import sys
from typing import Literal


ShellKind = Literal["posix", "powershell"]


def detect_shell_kind(
    platform_name: str | None = None,
) -> ShellKind:
    """根据运行平台选择用户最可能使用的交互式 Shell。"""
    platform = (
        sys.platform
        if platform_name is None
        else platform_name
    )

    if platform.casefold().startswith("win"):
        return "powershell"

    return "posix"


def validate_environment_name(name: str) -> str:
    """拒绝把未经验证的名称插入终端命令。"""
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*",
        name,
    ):
        raise ValueError(
            "API Key 环境变量名称无效"
        )

    return name


def secure_api_key_commands(
    environment_name: str,
    *,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """返回只从隐藏提示读取凭据的当前会话设置命令。"""
    name = validate_environment_name(
        environment_name
    )

    if detect_shell_kind(platform_name) == "powershell":
        temporary_name = "binderRankerApiKey"

        return (
            (
                f"${temporary_name} = Read-Host "
                "'请粘贴真实 API Key，然后按回车' "
                "-AsSecureString"
            ),
            (
                f"$env:{name} = "
                "[System.Net.NetworkCredential]::new("
                f"'', ${temporary_name}).Password"
            ),
            f"Remove-Variable {temporary_name}",
        )

    return (
        (
            "read -rsp '请粘贴真实 API Key，然后按回车"
            "（输入不会显示）：' "
            f"{name} && echo && export {name}"
        ),
    )


def secure_api_key_setup_summary(
    *,
    platform_name: str | None = None,
) -> str:
    """返回与命令匹配的简短终端说明。"""
    if detect_shell_kind(platform_name) == "powershell":
        return (
            "在同一个 PowerShell 窗口中依次运行下面三行；"
            "第一行出现提示后再粘贴真实 Key。"
        )

    return (
        "在同一终端复制并运行下面的整行命令；"
        "出现提示后再粘贴真实 Key。"
    )
