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
from collections.abc import Mapping

from pydantic import BaseModel, Field

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
