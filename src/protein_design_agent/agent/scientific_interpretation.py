#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 科学结果的共享解释契约。

该契约封存：
- 当前运行公开指标的受控语义；
- 分数和动态阈值的批次相对边界；
- 禁止从工程排序直接推出的科学结论；
- 做出下游生物学判断前仍需完成的验证。

本模块不计算指标，不修改排名或筛选结果。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
    MetricSemantics,
    ontology_for_run,
)
from protein_design_agent.agent.result_policy import (
    PoolReportingPolicy,
)


AnalysisScopeLevel = Literal[
    "SMOKE_TEST_ONLY",
    "EXPLORATORY",
    "FULL_DATASET_ANALYSIS",
]

ThresholdInterpretationMode = Literal[
    "SUPPRESSED",
    "EXPLORATORY",
    "STANDARD",
]


KNOWN_LIMITATIONS = (
    "Scores and ranks are relative engineering evidence for the "
    "current target and candidate batch.",
    "Dynamic thresholds are derived from the current candidate "
    "batch and are not universal scientific cutoffs.",
    "Backbone-level geometry does not establish sequence "
    "compatibility, binding affinity, stability, solubility, or "
    "experimental success.",
)

PROHIBITED_CLAIMS = (
    "The score establishes binding affinity.",
    "The score establishes protein stability or solubility.",
    "The ranking establishes experimental success probability.",
    "A dynamic filter threshold is a universal biophysical cutoff.",
    "Scores from unrelated targets or candidate batches are "
    "directly comparable without calibration.",
)

REQUIRED_DOWNSTREAM_VALIDATION = (
    "Inspect the candidate and target structures directly.",
    "Perform sequence design and sequence-compatibility checks.",
    "Use complex-structure prediction where appropriate.",
    "Use simulation or energetic analysis where appropriate.",
    "Obtain experimental validation before biological claims.",
)


class ScientificInterpretationContract(BaseModel):
    """Machine-readable boundaries for one validated result summary."""

    schema_version: str = "0.1"

    analysis_scope_level: AnalysisScopeLevel
    threshold_interpretation_mode: (
        ThresholdInterpretationMode
    )
    threshold_interpretation: str = Field(
        min_length=1
    )

    ranking_scope: Literal[
        "CURRENT_TARGET_AND_CANDIDATE_BATCH"
    ] = "CURRENT_TARGET_AND_CANDIDATE_BATCH"

    scores_are_empirical: Literal[True] = True
    scores_are_batch_relative: Literal[True] = True
    cross_batch_score_comparison_allowed: (
        Literal[False]
    ) = False
    cross_target_score_comparison_allowed: (
        Literal[False]
    ) = False

    dynamic_thresholds_are_batch_relative: (
        Literal[True]
    ) = True
    cross_batch_threshold_comparison_allowed: (
        Literal[False]
    ) = False
    empirical_weights_are_universal_biophysical_parameters: (
        Literal[False]
    ) = False

    metric_semantics: dict[
        str,
        MetricSemantics,
    ]

    known_limitations: tuple[str, ...] = (
        KNOWN_LIMITATIONS
    )
    prohibited_claims: tuple[str, ...] = (
        PROHIBITED_CLAIMS
    )
    required_downstream_validation: tuple[
        str,
        ...,
    ] = REQUIRED_DOWNSTREAM_VALIDATION

    @model_validator(mode="after")
    def validate_contract(
        self,
    ) -> "ScientificInterpretationContract":
        expected_keys = set(
            BASE_METRIC_ONTOLOGY
        )

        if set(self.metric_semantics) != expected_keys:
            raise ValueError(
                "科学解释契约必须覆盖完整受控指标本体"
            )

        for key, semantics in (
            self.metric_semantics.items()
        ):
            if semantics.key != key:
                raise ValueError(
                    "科学解释契约的指标键与语义记录不一致："
                    f"{key}"
                )

        expected_mode = {
            "SMOKE_TEST_ONLY": "SUPPRESSED",
            "EXPLORATORY": "EXPLORATORY",
            "FULL_DATASET_ANALYSIS": "STANDARD",
        }[self.analysis_scope_level]

        if (
            self.threshold_interpretation_mode
            != expected_mode
        ):
            raise ValueError(
                "科学解释契约的分析级别与阈值模式不一致"
            )

        if (
            self.known_limitations
            != KNOWN_LIMITATIONS
            or self.prohibited_claims
            != PROHIBITED_CLAIMS
            or self.required_downstream_validation
            != REQUIRED_DOWNSTREAM_VALIDATION
        ):
            raise ValueError(
                "科学解释契约的固定能力边界被修改"
            )

        return self


def build_scientific_interpretation_contract(
    *,
    region_score_used: bool,
    pool_reporting_policy: PoolReportingPolicy,
) -> ScientificInterpretationContract:
    """Build the authoritative interpretation contract for one run."""
    return ScientificInterpretationContract(
        analysis_scope_level=(
            pool_reporting_policy
            .analysis_scope_level
        ),
        threshold_interpretation_mode=(
            pool_reporting_policy.reporting_mode
        ),
        threshold_interpretation=(
            pool_reporting_policy.message
        ),
        metric_semantics=ontology_for_run(
            region_score_used=region_score_used
        ),
    )
