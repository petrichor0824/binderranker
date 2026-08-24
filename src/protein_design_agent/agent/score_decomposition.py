#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Deterministic decomposition of BinderRanker's recorded primary score.

The functions in this module explain an already-recorded score using the
audited weights in the metric ontology. They never change a component score,
ranking, screening decision, or frozen Ranker resource.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from protein_design_agent.agent.metric_ontology import (
    ontology_for_run,
)


class ScoreDecompositionError(RuntimeError):
    """A recorded primary score cannot be reconstructed safely."""


class PrimaryScoreDecomposition(BaseModel):
    """Deterministic weighted contributions for one candidate."""

    schema_version: str = "0.1"
    weights: dict[str, float]
    contributions: dict[str, float]
    reconstructed_final_score_v4: float
    recorded_final_score_v4: float
    reconstruction_error: float = Field(ge=0.0)


class PrimaryScoreContributionDelta(BaseModel):
    """One direct-primary contribution difference between two candidates."""

    model_config = ConfigDict(
        allow_inf_nan=False
    )

    metric_key: str = Field(min_length=1)
    higher_ranked_contribution: float
    lower_ranked_contribution: float
    delta: float


class AdjacentCandidateScoreComparison(BaseModel):
    """Audited primary-score difference for one adjacent rank pair."""

    model_config = ConfigDict(
        allow_inf_nan=False
    )

    schema_version: str = "0.1"

    higher_ranked_candidate: str = Field(
        min_length=1
    )
    higher_rank: int = Field(ge=1)
    lower_ranked_candidate: str = Field(
        min_length=1
    )
    lower_rank: int = Field(ge=2)

    higher_ranked_final_score_v4: float
    lower_ranked_final_score_v4: float
    recorded_score_delta: float = Field(ge=0.0)

    contribution_deltas: list[
        PrimaryScoreContributionDelta
    ]
    reconstructed_score_delta: float
    reconstruction_error: float = Field(
        ge=0.0,
    )

    largest_positive_contribution_delta: (
        PrimaryScoreContributionDelta | None
    ) = None
    largest_negative_contribution_delta: (
        PrimaryScoreContributionDelta | None
    ) = None


class PrimaryScoreCandidateEvidence(Protocol):
    """Minimal candidate view required for adjacent score comparison."""

    pdb_name: str
    engineering_rank: int
    final_score_v4: float
    primary_score_contributions: dict[
        str,
        float,
    ]


PRIMARY_SCORE_COMPONENT_ORDER = (
    "morphology_adaptive_score",
    "score_safety",
    "score_roughness",
    "score_region",
)


def primary_score_weights(
    *,
    region_score_used: bool,
) -> dict[str, float]:
    """Return audited direct-primary weights from the metric ontology."""

    ontology = ontology_for_run(
        region_score_used=region_score_used
    )
    weights: dict[str, float] = {}

    for metric_key in PRIMARY_SCORE_COMPONENT_ORDER:
        semantics = ontology[metric_key]
        if semantics.role != "direct_primary_component":
            continue

        weight = semantics.direct_primary_weight
        if weight is None:
            raise ScoreDecompositionError(
                "直接主分分项缺少权重："
                f"{metric_key}"
            )

        weights[metric_key] = weight

    if not weights:
        raise ScoreDecompositionError(
            "没有找到直接主分分项"
        )

    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 1e-12:
        raise ScoreDecompositionError(
            "直接主分权重之和必须为 1；"
            f"实际为 {weight_sum}"
        )

    return weights


def canonical_primary_score_formula(
    *,
    region_score_used: bool,
) -> str:
    """Render the audited linear primary-score formula."""
    weights = primary_score_weights(
        region_score_used=region_score_used
    )
    return " + ".join(
        f"{weight:.2f}*{metric_key}"
        for metric_key, weight in weights.items()
    )


def validate_primary_score_formula(
    formula: str,
    *,
    region_score_used: bool,
) -> dict[str, float]:
    """Require report formula evidence to match the audited ontology."""
    weights = primary_score_weights(
        region_score_used=region_score_used
    )
    expected = canonical_primary_score_formula(
        region_score_used=region_score_used
    )
    normalized_formula = re.sub(
        r"\s+",
        "",
        str(formula),
    )
    normalized_expected = re.sub(
        r"\s+",
        "",
        expected,
    )

    if normalized_formula != normalized_expected:
        raise ScoreDecompositionError(
            "Ranker 报告中的主分公式与审计指标本体不一致："
            f"报告={formula!r}，预期={expected!r}"
        )

    return weights


def decompose_primary_score(
    *,
    component_scores: Mapping[str, float],
    recorded_final_score_v4: float,
    region_score_used: bool,
    tolerance: float = 1e-8,
) -> PrimaryScoreDecomposition:
    """Reconstruct a candidate's primary score from recorded components."""

    if tolerance < 0 or not math.isfinite(
        tolerance
    ):
        raise ValueError(
            "tolerance 必须是非负有限数值"
        )

    try:
        recorded = float(
            recorded_final_score_v4
        )
    except (TypeError, ValueError) as exc:
        raise ScoreDecompositionError(
            "记录的 final_score_v4 必须是数值"
        ) from exc
    if not math.isfinite(recorded):
        raise ScoreDecompositionError(
            "记录的 final_score_v4 必须是有限数值"
        )

    weights = primary_score_weights(
        region_score_used=region_score_used
    )
    contributions: dict[str, float] = {}

    for metric_key, weight in weights.items():
        if metric_key not in component_scores:
            raise ScoreDecompositionError(
                "主分组成指标缺失："
                f"{metric_key}"
            )

        try:
            score = float(
                component_scores[metric_key]
            )
        except (TypeError, ValueError) as exc:
            raise ScoreDecompositionError(
                "主分组成指标必须是数值："
                f"{metric_key}="
                f"{component_scores[metric_key]!r}"
            ) from exc
        if not math.isfinite(score):
            raise ScoreDecompositionError(
                "主分组成指标必须是有限数值："
                f"{metric_key}={score!r}"
            )

        contributions[metric_key] = score * weight

    reconstructed = sum(contributions.values())
    error = abs(reconstructed - recorded)

    if error > tolerance:
        raise ScoreDecompositionError(
            "主分重建与记录值不一致："
            f"重建={reconstructed}，"
            f"记录={recorded}，"
            f"误差={error}"
        )

    return PrimaryScoreDecomposition(
        weights=weights,
        contributions=contributions,
        reconstructed_final_score_v4=(
            reconstructed
        ),
        recorded_final_score_v4=recorded,
        reconstruction_error=error,
    )


def compare_adjacent_primary_scores(
    *,
    higher_ranked_candidate: str,
    higher_rank: int,
    higher_ranked_final_score_v4: float,
    higher_ranked_contributions: Mapping[
        str,
        float,
    ],
    lower_ranked_candidate: str,
    lower_rank: int,
    lower_ranked_final_score_v4: float,
    lower_ranked_contributions: Mapping[
        str,
        float,
    ],
    tolerance: float = 1e-8,
) -> AdjacentCandidateScoreComparison:
    """Explain one adjacent recorded rank gap using contribution deltas."""
    higher_name = str(
        higher_ranked_candidate
    ).strip()
    lower_name = str(
        lower_ranked_candidate
    ).strip()

    if (
        not higher_name
        or not lower_name
        or higher_name == lower_name
    ):
        raise ScoreDecompositionError(
            "相邻候选标识必须非空且互不相同"
        )

    if (
        isinstance(higher_rank, bool)
        or isinstance(lower_rank, bool)
        or not isinstance(higher_rank, int)
        or not isinstance(lower_rank, int)
        or higher_rank < 1
        or lower_rank != higher_rank + 1
    ):
        raise ScoreDecompositionError(
            "候选比较必须使用连续的相邻排名"
        )

    if tolerance < 0 or not math.isfinite(
        tolerance
    ):
        raise ValueError(
            "tolerance 必须是非负有限数值"
        )

    try:
        higher_score = float(
            higher_ranked_final_score_v4
        )
        lower_score = float(
            lower_ranked_final_score_v4
        )
    except (TypeError, ValueError) as exc:
        raise ScoreDecompositionError(
            "候选比较分数必须是数值"
        ) from exc

    if not all(
        math.isfinite(value)
        for value in (
            higher_score,
            lower_score,
        )
    ):
        raise ScoreDecompositionError(
            "候选比较分数必须是有限数值"
        )

    recorded_delta = (
        higher_score - lower_score
    )
    if recorded_delta < 0:
        raise ScoreDecompositionError(
            "相邻候选的记录分数与排名顺序不一致"
        )

    higher_keys = set(
        higher_ranked_contributions
    )
    lower_keys = set(
        lower_ranked_contributions
    )

    if (
        not higher_keys
        or higher_keys != lower_keys
        or any(
            not isinstance(key, str)
            or not key.strip()
            for key in higher_keys
        )
    ):
        raise ScoreDecompositionError(
            "相邻候选的主分贡献项不完整或不一致"
        )

    component_order = {
        metric_key: index
        for index, metric_key in enumerate(
            PRIMARY_SCORE_COMPONENT_ORDER
        )
    }
    ordered_keys = sorted(
        higher_keys,
        key=lambda metric_key: (
            component_order.get(
                metric_key,
                len(component_order),
            ),
            metric_key,
        ),
    )

    contribution_deltas: list[
        PrimaryScoreContributionDelta
    ] = []

    for metric_key in ordered_keys:
        try:
            higher_value = float(
                higher_ranked_contributions[
                    metric_key
                ]
            )
            lower_value = float(
                lower_ranked_contributions[
                    metric_key
                ]
            )
        except (TypeError, ValueError) as exc:
            raise ScoreDecompositionError(
                "主分贡献差值必须来自数值："
                f"{metric_key}"
            ) from exc

        if not all(
            math.isfinite(value)
            for value in (
                higher_value,
                lower_value,
            )
        ):
            raise ScoreDecompositionError(
                "主分贡献差值必须来自有限数值："
                f"{metric_key}"
            )

        contribution_deltas.append(
            PrimaryScoreContributionDelta(
                metric_key=metric_key,
                higher_ranked_contribution=(
                    higher_value
                ),
                lower_ranked_contribution=(
                    lower_value
                ),
                delta=(
                    higher_value
                    - lower_value
                ),
            )
        )

    reconstructed_delta = sum(
        item.delta
        for item in contribution_deltas
    )
    error = abs(
        reconstructed_delta
        - recorded_delta
    )

    if error > tolerance:
        raise ScoreDecompositionError(
            "主分贡献差值无法重建相邻候选分数差："
            f"重建={reconstructed_delta}，"
            f"记录={recorded_delta}，"
            f"误差={error}"
        )

    positive = [
        item
        for item in contribution_deltas
        if item.delta > tolerance
    ]
    negative = [
        item
        for item in contribution_deltas
        if item.delta < -tolerance
    ]

    return AdjacentCandidateScoreComparison(
        higher_ranked_candidate=higher_name,
        higher_rank=higher_rank,
        lower_ranked_candidate=lower_name,
        lower_rank=lower_rank,
        higher_ranked_final_score_v4=(
            higher_score
        ),
        lower_ranked_final_score_v4=(
            lower_score
        ),
        recorded_score_delta=(
            recorded_delta
        ),
        contribution_deltas=(
            contribution_deltas
        ),
        reconstructed_score_delta=(
            reconstructed_delta
        ),
        reconstruction_error=error,
        largest_positive_contribution_delta=(
            None
            if not positive
            else max(
                positive,
                key=lambda item: item.delta,
            )
        ),
        largest_negative_contribution_delta=(
            None
            if not negative
            else min(
                negative,
                key=lambda item: item.delta,
            )
        ),
    )


def build_adjacent_primary_score_comparisons(
    candidates: Sequence[
        PrimaryScoreCandidateEvidence
    ],
) -> list[AdjacentCandidateScoreComparison]:
    """Build the linear N-1 comparison chain for ranked candidates."""
    return [
        compare_adjacent_primary_scores(
            higher_ranked_candidate=(
                higher.pdb_name
            ),
            higher_rank=(
                higher.engineering_rank
            ),
            higher_ranked_final_score_v4=(
                higher.final_score_v4
            ),
            higher_ranked_contributions=(
                higher
                .primary_score_contributions
            ),
            lower_ranked_candidate=(
                lower.pdb_name
            ),
            lower_rank=(
                lower.engineering_rank
            ),
            lower_ranked_final_score_v4=(
                lower.final_score_v4
            ),
            lower_ranked_contributions=(
                lower
                .primary_score_contributions
            ),
        )
        for higher, lower in zip(
            candidates[:-1],
            candidates[1:],
            strict=True,
        )
    ]
