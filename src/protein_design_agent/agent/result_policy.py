#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ranker 结果发布策略。

本模块不修改 BinderRanker 原始结果，只决定：

1. broad / medium / strict 池数量能否对外展示；
2. 池标签能否被当作可靠筛选结论；
3. 当前是否允许正式推荐实验候选；
4. 小样本内部池结果应如何标记。

原始 Ranker 文件始终保留，用于复现和工程调试。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PoolReportingMode = Literal[
    "SUPPRESSED",
    "EXPLORATORY",
    "STANDARD",
]


class PoolReportingPolicy(BaseModel):
    """根据分析级别生成的池结果发布政策。"""

    schema_version: str = "0.1"

    analysis_scope_level: str
    reporting_mode: PoolReportingMode

    publish_pool_counts: bool
    pool_labels_reliable: bool
    formal_interpretation_allowed: bool
    formal_candidate_recommendation_allowed: bool

    raw_ranker_outputs_retained: bool = True
    message: str


class PoolReportingView(BaseModel):
    """
    对原始池数量应用发布政策后的结构化结果。

    raw_pool_counts:
        Ranker 原始计算值，仅供复现和工程调试。

    public_pool_counts:
        对外允许展示的数量。
        SMOKE_TEST_ONLY 下统一为 None。

    public_pool_status:
        每个池在用户报告中的显示状态。
    """

    schema_version: str = "0.1"

    policy: PoolReportingPolicy

    raw_pool_counts: dict[str, int]
    public_pool_counts: dict[
        str,
        int | None,
    ]
    public_pool_status: dict[str, str]


def require_boolean(
    analysis_scope: dict[str, Any],
    key: str,
) -> bool:
    """读取一个必须明确存在的布尔字段。"""
    value = analysis_scope.get(key)

    if not isinstance(value, bool):
        raise ValueError(
            f"analysis_scope 中的 {key} "
            "必须是布尔值"
        )

    return value


def derive_pool_reporting_policy(
    analysis_scope: dict[str, Any],
) -> PoolReportingPolicy:
    """
    根据工作流 analysis_scope 生成发布政策。

    不仅检查 level，还检查相关安全标志是否一致，
    避免某个 Manifest 中出现互相矛盾的字段。
    """
    if not isinstance(
        analysis_scope,
        dict,
    ):
        raise ValueError(
            "analysis_scope 必须是字典"
        )

    level = analysis_scope.get("level")

    if not isinstance(level, str) or not level:
        raise ValueError(
            "analysis_scope 缺少有效 level"
        )

    pool_labels_reliable = require_boolean(
        analysis_scope,
        "pool_labels_reliable",
    )

    formal_interpretation = require_boolean(
        analysis_scope,
        (
            "workflow_allows_"
            "formal_interpretation"
        ),
    )

    if level == "SMOKE_TEST_ONLY":
        if (
            pool_labels_reliable
            or formal_interpretation
        ):
            raise ValueError(
                "SMOKE_TEST_ONLY 与可靠池标签或"
                "正式解释许可相矛盾"
            )

        return PoolReportingPolicy(
            analysis_scope_level=level,
            reporting_mode="SUPPRESSED",
            publish_pool_counts=False,
            pool_labels_reliable=False,
            formal_interpretation_allowed=False,
            formal_candidate_recommendation_allowed=False,
            message=(
                "当前仅为工程冒烟测试。"
                "原始 Ranker 内部可能仍计算 "
                "broad、medium 和 strict，"
                "但这些池数量和标签不得作为"
                "用户筛选结论展示，也不得据此"
                "推荐实验候选。"
            ),
        )

    if level == "EXPLORATORY":
        if (
            pool_labels_reliable
            or formal_interpretation
        ):
            raise ValueError(
                "EXPLORATORY 与可靠池标签或"
                "正式解释许可相矛盾"
            )

        return PoolReportingPolicy(
            analysis_scope_level=level,
            reporting_mode="EXPLORATORY",
            publish_pool_counts=True,
            pool_labels_reliable=False,
            formal_interpretation_allowed=False,
            formal_candidate_recommendation_allowed=False,
            message=(
                "当前结果仅用于探索性比较。"
                "可以附带展示池数量，但必须明确"
                "标记为批内探索结果；动态阈值和"
                "池标签仍不可靠，不能独立支持"
                "正式候选推荐。"
            ),
        )

    if level == "FULL_DATASET_ANALYSIS":
        if (
            not pool_labels_reliable
            or not formal_interpretation
        ):
            raise ValueError(
                "FULL_DATASET_ANALYSIS 必须同时"
                "允许正式解释并标记池标签可靠"
            )

        return PoolReportingPolicy(
            analysis_scope_level=level,
            reporting_mode="STANDARD",
            publish_pool_counts=True,
            pool_labels_reliable=True,
            formal_interpretation_allowed=True,
            formal_candidate_recommendation_allowed=True,
            message=(
                "当前允许进入完整结果报告和"
                "候选推荐阶段。池标签仍需结合"
                "数据代表性、跨批次对照和实验"
                "验证进行解释。"
            ),
        )

    raise ValueError(
        f"不支持的 analysis_scope level：{level}"
    )


def validate_raw_pool_counts(
    raw_pool_counts: dict[str, int],
) -> dict[str, int]:
    """验证 Ranker 原始池数量。"""
    if not isinstance(
        raw_pool_counts,
        dict,
    ):
        raise ValueError(
            "raw_pool_counts 必须是字典"
        )

    required = (
        "broad",
        "medium",
        "strict",
    )

    missing = [
        name
        for name in required
        if name not in raw_pool_counts
    ]

    if missing:
        raise ValueError(
            "缺少原始池数量："
            f"{missing}"
        )

    normalized: dict[str, int] = {}

    for name, value in raw_pool_counts.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError(
                f"池 {name} 的数量必须是"
                "大于等于 0 的整数"
            )

        normalized[name] = value

    return normalized


def build_pool_reporting_view(
    *,
    analysis_scope: dict[str, Any],
    raw_pool_counts: dict[str, int],
) -> PoolReportingView:
    """
    对原始池数量应用发布策略。

    SMOKE_TEST_ONLY：
        原始数值保留在 raw_pool_counts，
        但 public_pool_counts 全部为 None。

    EXPLORATORY：
        可以展示数值，但状态必须标记为探索性。

    FULL_DATASET_ANALYSIS：
        正常展示。
    """
    policy = derive_pool_reporting_policy(
        analysis_scope
    )

    raw_counts = validate_raw_pool_counts(
        raw_pool_counts
    )

    if policy.reporting_mode == "SUPPRESSED":
        public_counts = {
            name: None
            for name in raw_counts
        }

        public_status = {
            name: "NOT_AVAILABLE_SMALL_SAMPLE"
            for name in raw_counts
        }

    elif policy.reporting_mode == "EXPLORATORY":
        public_counts = dict(raw_counts)

        public_status = {
            name: "EXPLORATORY_ONLY"
            for name in raw_counts
        }

    else:
        public_counts = dict(raw_counts)

        public_status = {
            name: "REPORTABLE"
            for name in raw_counts
        }

    return PoolReportingView(
        policy=policy,
        raw_pool_counts=raw_counts,
        public_pool_counts=public_counts,
        public_pool_status=public_status,
    )
