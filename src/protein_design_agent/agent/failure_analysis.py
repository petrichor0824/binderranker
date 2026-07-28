#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 失败原因与阈值差距分析。

本模块读取 agent_result_summary.json，并确定性计算：

1. 每条失败原因对应哪个指标；
2. 指标实际值和对应池阈值；
3. 距离通过阈值还差多少；
4. 相对阈值的差距比例；
5. 哪条失败规则最接近通过；
6. 哪条失败规则差距最大。

重要限制：
- 不重新计算 BinderRanker 指标；
- 不修改原始 Ranker 输出；
- 不调用大模型；
- SMOKE_TEST_ONLY 下只能用于工程诊断；
- 差距分段是透明的工程标签，不是统计学定律。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from protein_design_agent.agent.ranker_result_parser import (
    CandidateResult,
    FilterThreshold,
    RankerResultSummary,
)


PoolName = Literal[
    "broad",
    "medium",
    "strict",
]

GapBand = Literal[
    "AT_OR_BELOW_1_PERCENT",
    "ABOVE_1_TO_5_PERCENT",
    "ABOVE_5_TO_15_PERCENT",
    "ABOVE_15_PERCENT",
    "THRESHOLD_ZERO_ABSOLUTE_ONLY",
]

InterpretationStatus = Literal[
    "ENGINEERING_DIAGNOSTIC_ONLY",
    "EXPLORATORY_ONLY",
    "FORMAL_ANALYSIS_ALLOWED",
]


class FailureAnalysisError(RuntimeError):
    """失败差距无法安全分析。"""


class FailedGateGap(BaseModel):
    """一个候选在某个过滤门槛上的失败差距。"""

    pool: PoolName
    reason_code: str

    metric: str
    direction: Literal["min", "max"]

    actual_value: float
    threshold_value: float
    quantile: float

    # 正数代表通过阈值后仍有余量；
    # 负数代表未通过，绝对值即距离通过还差多少。
    signed_pass_margin: float

    # 对已经记录为失败的规则，该值应大于 0。
    failure_gap: float = Field(ge=0)

    # 当阈值为 0 时，相对差距没有稳定含义，
    # 因此保存为 None，只报告绝对差距。
    relative_failure_gap: float | None = Field(
        default=None,
        ge=0,
    )

    gap_band: GapBand

    recorded_reason_consistent: bool
    interpretation_status: InterpretationStatus


class CandidateFailureAnalysis(BaseModel):
    """一个候选的全部失败门槛分析。"""

    pdb_name: str
    engineering_rank: int = Field(ge=1)
    final_score_v4: float

    interpretation_status: InterpretationStatus

    # 同一指标可能分别违反 broad、medium、strict，
    # 因此这是“门槛失败记录数”，不是独立缺陷数。
    failed_gate_count: int = Field(ge=0)

    # 去重后的失败指标数量，更接近“不同问题数”。
    unique_failed_metric_count: int = Field(ge=0)

    failures_by_pool: dict[
        str,
        list[FailedGateGap],
    ]

    closest_failed_gate: FailedGateGap | None
    largest_relative_failed_gate: (
        FailedGateGap | None
    )

    all_recorded_reasons_consistent: bool


class FailureAnalysisSummary(BaseModel):
    """一次 Ranker 结果的失败差距摘要。"""

    schema_version: str = "0.2"
    status: Literal["ANALYZED"] = "ANALYZED"

    project_name: str
    source_result_summary: Path

    analysis_scope_level: str
    candidate_count: int = Field(ge=1)

    interpretation_status: InterpretationStatus

    formal_candidate_recommendation_allowed: bool
    thresholds_formally_interpretable: bool

    gap_band_definition: dict[str, str]

    candidates_by_engineering_rank: list[
        CandidateFailureAnalysis
    ]


GAP_BAND_DEFINITION = {
    "AT_OR_BELOW_1_PERCENT": (
        "失败差距不超过对应阈值绝对值的 1%；"
        "仅表示数值上非常接近该批次动态阈值。"
    ),
    "ABOVE_1_TO_5_PERCENT": (
        "失败差距超过 1%，但不超过 5%。"
    ),
    "ABOVE_5_TO_15_PERCENT": (
        "失败差距超过 5%，但不超过 15%。"
    ),
    "ABOVE_15_PERCENT": (
        "失败差距超过对应阈值绝对值的 15%。"
    ),
    "THRESHOLD_ZERO_ABSOLUTE_ONLY": (
        "阈值为 0，不能稳定计算相对差距；"
        "只能解释绝对差距。"
    ),
}


def load_result_summary(
    path: Path,
) -> RankerResultSummary:
    """读取并验证 Agent 结果摘要。"""
    path = path.resolve()

    if not path.exists():
        raise FailureAnalysisError(
            f"结果摘要不存在：{path}"
        )

    try:
        return (
            RankerResultSummary
            .model_validate_json(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )

    except Exception as exc:
        raise FailureAnalysisError(
            f"无法验证结果摘要：{path}"
        ) from exc


def interpretation_status_for(
    summary: RankerResultSummary,
) -> InterpretationStatus:
    """根据分析级别生成差距解释权限。"""
    level = str(
        summary.analysis_scope.get(
            "level",
            "",
        )
    )

    if level == "SMOKE_TEST_ONLY":
        return (
            "ENGINEERING_DIAGNOSTIC_ONLY"
        )

    if level == "EXPLORATORY":
        return "EXPLORATORY_ONLY"

    if level == "FULL_DATASET_ANALYSIS":
        return "FORMAL_ANALYSIS_ALLOWED"

    raise FailureAnalysisError(
        f"不支持的分析级别：{level!r}"
    )


def reason_to_metric(
    reason_code: str,
) -> tuple[
    str,
    Literal["min", "max"],
]:
    """
    将失败原因转换为指标和阈值方向。

    low_x：
        指标 x 必须大于等于最小阈值。

    high_x：
        指标 x 必须小于等于最大阈值。
    """
    if reason_code.startswith("low_"):
        metric = reason_code[4:]

        if not metric:
            raise FailureAnalysisError(
                f"无效失败原因：{reason_code}"
            )

        return metric, "min"

    if reason_code.startswith("high_"):
        metric = reason_code[5:]

        if not metric:
            raise FailureAnalysisError(
                f"无效失败原因：{reason_code}"
            )

        return metric, "max"

    raise FailureAnalysisError(
        "无法从失败原因推导阈值方向："
        f"{reason_code}"
    )


def candidate_metric_value(
    candidate: CandidateResult,
    metric: str,
) -> float:
    """从候选摘要中读取失败规则对应指标。"""
    if metric in candidate.key_metrics:
        value = candidate.key_metrics[
            metric
        ]

    elif metric in candidate.component_scores:
        value = candidate.component_scores[
            metric
        ]

    else:
        raise FailureAnalysisError(
            f"候选 {candidate.pdb_name} "
            f"缺少失败原因对应指标：{metric}"
        )

    value = float(value)

    if not math.isfinite(value):
        raise FailureAnalysisError(
            f"候选 {candidate.pdb_name} "
            f"的 {metric} 不是有限数值"
        )

    return value


def classify_gap_band(
    *,
    failure_gap: float,
    threshold_value: float,
) -> tuple[float | None, GapBand]:
    """
    根据相对阈值差距产生透明工程分段。

    这些分段只用于帮助排序诊断优先级，
    不是科研显著性或统计充分性结论。
    """
    denominator = abs(threshold_value)

    if denominator <= 1e-12:
        return (
            None,
            "THRESHOLD_ZERO_ABSOLUTE_ONLY",
        )

    relative = failure_gap / denominator

    if relative <= 0.01:
        band: GapBand = (
            "AT_OR_BELOW_1_PERCENT"
        )

    elif relative <= 0.05:
        band = "ABOVE_1_TO_5_PERCENT"

    elif relative <= 0.15:
        band = "ABOVE_5_TO_15_PERCENT"

    else:
        band = "ABOVE_15_PERCENT"

    return relative, band


def analyze_failed_gate(
    *,
    candidate: CandidateResult,
    pool: PoolName,
    reason_code: str,
    threshold: FilterThreshold,
    interpretation_status: (
        InterpretationStatus
    ),
) -> FailedGateGap:
    """分析一条记录在 CSV 中的失败规则。"""
    metric, expected_direction = (
        reason_to_metric(reason_code)
    )

    if threshold.metric != metric:
        raise FailureAnalysisError(
            "失败原因和阈值指标不一致："
            f"原因={reason_code}，"
            f"阈值指标={threshold.metric}"
        )

    if threshold.direction != expected_direction:
        raise FailureAnalysisError(
            "失败原因和阈值方向不一致："
            f"原因={reason_code}，"
            f"阈值方向={threshold.direction}"
        )

    actual = candidate_metric_value(
        candidate,
        metric,
    )

    if threshold.direction == "min":
        # actual >= threshold 时通过。
        signed_pass_margin = (
            actual - threshold.value
        )

    else:
        # actual <= threshold 时通过。
        signed_pass_margin = (
            threshold.value - actual
        )

    tolerance = max(
        1e-12,
        abs(threshold.value) * 1e-10,
    )

    consistent = (
        signed_pass_margin < -tolerance
    )

    if not consistent:
        raise FailureAnalysisError(
            "CSV 记录为失败，但数值与报告阈值"
            "不一致：\n"
            f"候选={candidate.pdb_name}\n"
            f"池={pool}\n"
            f"原因={reason_code}\n"
            f"实际值={actual}\n"
            f"阈值={threshold.value}\n"
            f"方向={threshold.direction}"
        )

    failure_gap = -signed_pass_margin

    relative_gap, gap_band = (
        classify_gap_band(
            failure_gap=failure_gap,
            threshold_value=threshold.value,
        )
    )

    return FailedGateGap(
        pool=pool,
        reason_code=reason_code,
        metric=metric,
        direction=threshold.direction,
        actual_value=actual,
        threshold_value=threshold.value,
        quantile=threshold.quantile,
        signed_pass_margin=(
            signed_pass_margin
        ),
        failure_gap=failure_gap,
        relative_failure_gap=relative_gap,
        gap_band=gap_band,
        recorded_reason_consistent=True,
        interpretation_status=(
            interpretation_status
        ),
    )


def reasons_for_pool(
    candidate: CandidateResult,
    pool: PoolName,
) -> list[str]:
    """读取候选在指定池的失败原因。"""
    if pool == "broad":
        return candidate.broad_reasons

    if pool == "medium":
        return candidate.medium_reasons

    return candidate.strict_reasons


def analyze_candidate(
    *,
    candidate: CandidateResult,
    summary: RankerResultSummary,
    interpretation_status: (
        InterpretationStatus
    ),
) -> CandidateFailureAnalysis:
    """分析一个候选的全部失败门槛。"""
    failures_by_pool: dict[
        str,
        list[FailedGateGap],
    ] = {
        "broad": [],
        "medium": [],
        "strict": [],
    }

    all_failures: list[
        FailedGateGap
    ] = []

    for pool in (
        "broad",
        "medium",
        "strict",
    ):
        pool_name: PoolName = pool

        thresholds = (
            summary.raw_filter_thresholds[
                pool
            ]
        )

        for reason_code in reasons_for_pool(
            candidate,
            pool_name,
        ):
            metric, _direction = (
                reason_to_metric(reason_code)
            )

            threshold = thresholds.get(
                metric
            )

            if threshold is None:
                raise FailureAnalysisError(
                    "失败原因在对应池中没有阈值："
                    f"候选={candidate.pdb_name}，"
                    f"池={pool}，"
                    f"原因={reason_code}"
                )

            failure = analyze_failed_gate(
                candidate=candidate,
                pool=pool_name,
                reason_code=reason_code,
                threshold=threshold,
                interpretation_status=(
                    interpretation_status
                ),
            )

            failures_by_pool[
                pool
            ].append(failure)

            all_failures.append(failure)

    for pool_failures in (
        failures_by_pool.values()
    ):
        pool_failures.sort(
            key=lambda item: (
                item.failure_gap,
                item.metric,
            )
        )

    # 不同指标的绝对差值具有不同量纲，
    # 不能直接互相比较。
    #
    # “最接近通过”优先按照相对阈值差距判断。
    # 只有阈值为 0、无法计算相对差距时，
    # 才退回绝对差距。
    relative_candidates = [
        item
        for item in all_failures
        if (
            item.relative_failure_gap
            is not None
        )
    ]

    closest: FailedGateGap | None = None

    if relative_candidates:
        closest = min(
            relative_candidates,
            key=lambda item: (
                item.relative_failure_gap,
                item.metric,
                item.pool,
            ),
        )

    elif all_failures:
        closest = min(
            all_failures,
            key=lambda item: (
                item.failure_gap,
                item.metric,
                item.pool,
            ),
        )

    largest_relative: (
        FailedGateGap | None
    ) = None

    if relative_candidates:
        largest_relative = max(
            relative_candidates,
            key=lambda item: (
                item.relative_failure_gap,
                item.metric,
            ),
        )

    return CandidateFailureAnalysis(
        pdb_name=candidate.pdb_name,
        engineering_rank=(
            candidate.engineering_rank
        ),
        final_score_v4=(
            candidate.final_score_v4
        ),
        interpretation_status=(
            interpretation_status
        ),
        failed_gate_count=len(
            all_failures
        ),
        unique_failed_metric_count=len(
            {
                item.metric
                for item in all_failures
            }
        ),
        failures_by_pool=(
            failures_by_pool
        ),
        closest_failed_gate=closest,
        largest_relative_failed_gate=(
            largest_relative
        ),
        all_recorded_reasons_consistent=all(
            item.recorded_reason_consistent
            for item in all_failures
        ),
    )


def analyze_ranker_failures(
    result_summary_path: Path,
) -> FailureAnalysisSummary:
    """分析一份 Agent Ranker 结果摘要。"""
    result_summary_path = (
        result_summary_path.resolve()
    )

    summary = load_result_summary(
        result_summary_path
    )

    interpretation_status = (
        interpretation_status_for(
            summary
        )
    )

    candidates = [
        analyze_candidate(
            candidate=candidate,
            summary=summary,
            interpretation_status=(
                interpretation_status
            ),
        )
        for candidate in (
            summary
            .candidates_by_engineering_rank
        )
    ]

    candidates.sort(
        key=lambda item: (
            item.engineering_rank,
            item.pdb_name,
        )
    )

    return FailureAnalysisSummary(
        project_name=summary.project_name,
        source_result_summary=(
            result_summary_path
        ),
        analysis_scope_level=str(
            summary.analysis_scope[
                "level"
            ]
        ),
        candidate_count=(
            summary.candidate_count
        ),
        interpretation_status=(
            interpretation_status
        ),
        formal_candidate_recommendation_allowed=(
            summary
            .formal_candidate_recommendation_allowed
        ),
        thresholds_formally_interpretable=(
            summary
            .thresholds_formally_interpretable
        ),
        gap_band_definition=(
            GAP_BAND_DEFINITION
        ),
        candidates_by_engineering_rank=(
            candidates
        ),
    )


def write_failure_analysis(
    *,
    result_summary_path: Path,
    output_path: Path | None = None,
) -> Path:
    """生成失败差距分析 JSON，禁止覆盖。"""
    result_summary_path = (
        result_summary_path.resolve()
    )

    if output_path is None:
        output_path = (
            result_summary_path.parent
            / "agent_failure_analysis_v2.json"
        )
    else:
        output_path = output_path.resolve()

    if output_path.exists():
        raise ValueError(
            f"失败分析已经存在，禁止覆盖："
            f"{output_path}"
        )

    analysis = analyze_ranker_failures(
        result_summary_path
    )

    output_path.write_text(
        analysis.model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )

    reloaded = (
        FailureAnalysisSummary
        .model_validate_json(
            output_path.read_text(
                encoding="utf-8"
            )
        )
    )

    if reloaded != analysis:
        output_path.unlink(
            missing_ok=True
        )

        raise FailureAnalysisError(
            "失败分析写入前后不一致，"
            "已删除不可靠文件"
        )

    return output_path
