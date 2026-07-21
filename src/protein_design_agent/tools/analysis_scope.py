#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""根据 PDB 数量标记本次运行允许达到的解释层级。"""

from __future__ import annotations

from typing import Any


SMOKE_TEST_UPPER_BOUND = 30
FULL_ANALYSIS_LOWER_BOUND = 200


def classify_analysis_scope(
    pdb_count: int,
) -> dict[str, Any]:
    """
    根据当前输入 PDB 数量给运行结果加安全标签。

    注意：
    这些阈值是防止 Agent 过度解释结果的工程规则，
    不是统计学充分性证明。
    """
    if pdb_count < 1:
        raise ValueError(
            f"pdb_count 必须大于 0，实际为 {pdb_count}"
        )

    if pdb_count < SMOKE_TEST_UPPER_BOUND:
        return {
            "level": "SMOKE_TEST_ONLY",
            "pdb_count": pdb_count,
            "workflow_allows_formal_interpretation": False,
            "pool_labels_reliable": False,
            "dynamic_quantile_stability": "very_low",
            "result_use": "engineering_validation_only",
            "message": (
                "样本量过小。仅允许验证解析、标准化、"
                "指标计算和输出流程；不得将当前排名、"
                "动态分位数阈值或 broad/medium/strict "
                "作为正式科研结论。"
            ),
        }

    if pdb_count < FULL_ANALYSIS_LOWER_BOUND:
        return {
            "level": "EXPLORATORY",
            "pdb_count": pdb_count,
            "workflow_allows_formal_interpretation": False,
            "pool_labels_reliable": False,
            "dynamic_quantile_stability": "limited",
            "result_use": "exploratory_comparison_only",
            "message": (
                "可用于探索候选差异和发现异常模式，"
                "但批内归一化与动态分位数仍可能不稳定；"
                "不得独立支持正式方法学结论。"
            ),
        }

    return {
        "level": "FULL_DATASET_ANALYSIS",
        "pdb_count": pdb_count,
        "workflow_allows_formal_interpretation": True,
        "pool_labels_reliable": True,
        "dynamic_quantile_stability": (
            "better_but_not_guaranteed"
        ),
        "result_use": "full_analysis_candidate",
        "message": (
            "工作流允许进入完整数据分析阶段。"
            "这不自动证明统计充分性，仍需检查数据代表性、"
            "跨批次可比性、基线对照和独立实验验证。"
        ),
    }
