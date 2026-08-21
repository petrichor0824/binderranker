#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""根据工作空间和模型状态生成首次 Chat 引导。"""

from __future__ import annotations

from pathlib import Path

from protein_design_agent.public_identity import (
    CLI_NAME,
)


def task_is_empty(bundle_dir: Path) -> bool:
    """判断任务是否还没有任何可恢复的本地状态。"""
    bundle = bundle_dir.expanduser().resolve()

    if not bundle.exists():
        return True

    if not bundle.is_dir():
        return False

    try:
        next(bundle.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False

    return False


def format_first_chat_guidance(
    *,
    task_empty: bool,
    model_status: str,
    uses_default_workspace: bool,
    workspace_status: str | None,
) -> str | None:
    """只为空任务显示一次可执行、与当前状态匹配的入口。"""
    if not task_empty:
        return None

    lines = [
        "首次工作流引导：",
    ]

    if uses_default_workspace:
        if workspace_status == "CREATED":
            lines.append(
                "• Chat 已自动初始化工作空间；"
                f"无需先运行 {CLI_NAME} init。"
            )
        else:
            lines.append(
                "• 已安全复用工作空间；"
                "当前任务尚未开始。"
            )
    else:
        lines.append(
            "• 当前外部 Bundle 尚未包含任务状态。"
        )

    if model_status == "READY":
        lines.extend(
            [
                (
                    "• 使用自己的数据：直接描述 PDB 目录、"
                    "binder 链和已知约束。"
                ),
                (
                    "  例如：分析 data/my_candidates，"
                    "binder 是 B 链。"
                ),
            ]
        )
    else:
        lines.append(
            "• 当前空任务还不能可靠地把自由文本转换为计划；"
            "请先按上方模型状态指引完成配置并重新启动 Chat。"
        )

    if uses_default_workspace:
        lines.extend(
            [
                "• 运行内置工程 smoke test：",
                (
                    "  1. 在另一个终端或退出 Chat 后运行 "
                    f"{CLI_NAME} extract-sample "
                    "--destination data/3c98_small。"
                ),
                (
                    f"  2. 重新运行 {CLI_NAME} chat，"
                    "然后输入：分析 data/3c98_small，"
                    "binder 是 B 链。"
                ),
                (
                    "  该样例仅用于安装和工程验证，"
                    "不能作为正式候选推荐。"
                ),
            ]
        )

    lines.append(
        "• 输入“帮助”可随时查看自然语言示例和安全边界。"
    )

    return "\n".join(lines)
