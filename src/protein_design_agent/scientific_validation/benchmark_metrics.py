"""Compute fixed-budget metrics from a validated benchmark bundle."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from protein_design_agent.scientific_validation.benchmark_contract import (
    BenchmarkCandidateRecord,
    BenchmarkContractError,
    EvidenceType,
    Identifier,
    ValidatedBenchmarkBundle,
    validate_benchmark_bundle,
)


MetricStatus = Literal["AVAILABLE", "UNAVAILABLE"]
MetricMethod = Literal["BINDERRANKER", "BASELINE"]
UnavailableReason = Literal["NO_POSITIVE_OUTCOMES_IN_CAMPAIGN"]
FiniteMetric = Annotated[float, Field(allow_inf_nan=False)]


class BenchmarkEvaluationError(RuntimeError):
    """A benchmark cannot safely enter fixed-budget evaluation."""


class _MetricModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class MetricValue(_MetricModel):
    """A finite metric or an explicit scientifically undefined state."""

    status: MetricStatus
    value: FiniteMetric | None = None
    reason: UnavailableReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "MetricValue":
        if self.status == "AVAILABLE":
            if self.value is None or self.reason is not None:
                raise ValueError(
                    "AVAILABLE metrics require a finite value and no reason"
                )
        elif self.value is not None or self.reason is None:
            raise ValueError(
                "UNAVAILABLE metrics require no value and an explicit reason"
            )
        return self


class CampaignMethodMetrics(_MetricModel):
    """One ranking method evaluated in one campaign at one fixed budget."""

    method: MetricMethod
    budget: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    positive_count: int = Field(ge=0)
    selected_count: int = Field(gt=0)
    selected_candidate_ids: tuple[Identifier, ...]
    hits_at_k: int = Field(ge=0)
    precision_at_k: FiniteMetric = Field(ge=0.0, le=1.0)
    recall_at_k: MetricValue
    enrichment_factor_at_k: MetricValue
    success_at_k: bool

    @model_validator(mode="after")
    def validate_arithmetic(self) -> "CampaignMethodMetrics":
        if self.selected_count != self.budget:
            raise ValueError("selected_count must equal the fixed budget")
        if len(self.selected_candidate_ids) != self.selected_count:
            raise ValueError("selected candidate count does not match IDs")
        if len(set(self.selected_candidate_ids)) != self.selected_count:
            raise ValueError("selected candidate IDs must be unique")
        if self.candidate_count < self.selected_count:
            raise ValueError("fixed budget exceeds the campaign size")
        if self.positive_count > self.candidate_count:
            raise ValueError("positive_count exceeds candidate_count")
        if self.hits_at_k > min(self.selected_count, self.positive_count):
            raise ValueError("hits_at_k exceeds an admissible count")

        expected_precision = self.hits_at_k / self.selected_count
        _require_close(
            self.precision_at_k,
            expected_precision,
            "precision_at_k",
        )
        if self.success_at_k != (self.hits_at_k > 0):
            raise ValueError("success_at_k disagrees with hits_at_k")

        if self.positive_count == 0:
            _require_unavailable(self.recall_at_k, "recall_at_k")
            _require_unavailable(
                self.enrichment_factor_at_k,
                "enrichment_factor_at_k",
            )
        else:
            expected_recall = self.hits_at_k / self.positive_count
            expected_enrichment = expected_precision / (
                self.positive_count / self.candidate_count
            )
            _require_available_close(
                self.recall_at_k,
                expected_recall,
                "recall_at_k",
            )
            _require_available_close(
                self.enrichment_factor_at_k,
                expected_enrichment,
                "enrichment_factor_at_k",
            )
        return self


class CampaignBudgetComparison(_MetricModel):
    """BinderRanker and baseline results for one campaign and budget."""

    campaign_id: Identifier
    target_id: Identifier
    budget: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    positive_count: int = Field(ge=0)
    binderranker: CampaignMethodMetrics
    baseline: CampaignMethodMetrics
    hits_delta: int
    precision_delta: FiniteMetric = Field(ge=-1.0, le=1.0)
    recall_delta: MetricValue
    enrichment_factor_delta: MetricValue

    @model_validator(mode="after")
    def validate_comparison(self) -> "CampaignBudgetComparison":
        _require_method_alignment(
            method=self.binderranker,
            expected_method="BINDERRANKER",
            budget=self.budget,
            candidate_count=self.candidate_count,
            positive_count=self.positive_count,
        )
        _require_method_alignment(
            method=self.baseline,
            expected_method="BASELINE",
            budget=self.budget,
            candidate_count=self.candidate_count,
            positive_count=self.positive_count,
        )
        if self.hits_delta != (
            self.binderranker.hits_at_k - self.baseline.hits_at_k
        ):
            raise ValueError("hits_delta disagrees with method results")
        _require_close(
            self.precision_delta,
            self.binderranker.precision_at_k
            - self.baseline.precision_at_k,
            "precision_delta",
        )
        _require_metric_delta(
            self.recall_delta,
            self.binderranker.recall_at_k,
            self.baseline.recall_at_k,
            "recall_delta",
        )
        _require_metric_delta(
            self.enrichment_factor_delta,
            self.binderranker.enrichment_factor_at_k,
            self.baseline.enrichment_factor_at_k,
            "enrichment_factor_delta",
        )
        return self


class PooledMethodMetrics(_MetricModel):
    """Counts pooled after selecting the fixed budget in every campaign."""

    method: MetricMethod
    budget: int = Field(gt=0)
    campaign_count: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    positive_count: int = Field(gt=0)
    selected_count: int = Field(gt=0)
    hits_at_k: int = Field(ge=0)
    precision_at_k: FiniteMetric = Field(ge=0.0, le=1.0)
    recall_at_k: MetricValue
    enrichment_factor_at_k: MetricValue
    successful_campaign_count: int = Field(ge=0)
    success_rate_at_k: FiniteMetric = Field(ge=0.0, le=1.0)
    campaigns_without_positive_outcomes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_arithmetic(self) -> "PooledMethodMetrics":
        if self.selected_count != self.budget * self.campaign_count:
            raise ValueError(
                "pooled selected_count must equal budget * campaign_count"
            )
        if self.candidate_count < self.selected_count:
            raise ValueError("pooled selected_count exceeds candidate_count")
        if self.positive_count > self.candidate_count:
            raise ValueError("positive_count exceeds candidate_count")
        if self.hits_at_k > min(self.selected_count, self.positive_count):
            raise ValueError("hits_at_k exceeds an admissible pooled count")
        if self.successful_campaign_count > self.campaign_count:
            raise ValueError("successful campaign count exceeds total")
        if self.campaigns_without_positive_outcomes > self.campaign_count:
            raise ValueError("zero-positive campaign count exceeds total")

        expected_precision = self.hits_at_k / self.selected_count
        expected_recall = self.hits_at_k / self.positive_count
        expected_enrichment = expected_precision / (
            self.positive_count / self.candidate_count
        )
        expected_success_rate = (
            self.successful_campaign_count / self.campaign_count
        )
        _require_close(
            self.precision_at_k,
            expected_precision,
            "precision_at_k",
        )
        _require_available_close(
            self.recall_at_k,
            expected_recall,
            "recall_at_k",
        )
        _require_available_close(
            self.enrichment_factor_at_k,
            expected_enrichment,
            "enrichment_factor_at_k",
        )
        _require_close(
            self.success_rate_at_k,
            expected_success_rate,
            "success_rate_at_k",
        )
        return self


class PooledBudgetComparison(_MetricModel):
    """Pooled BinderRanker/baseline comparison at a fixed budget."""

    budget: int = Field(gt=0)
    binderranker: PooledMethodMetrics
    baseline: PooledMethodMetrics
    hits_delta: int
    precision_delta: FiniteMetric = Field(ge=-1.0, le=1.0)
    recall_delta: MetricValue
    enrichment_factor_delta: MetricValue
    successful_campaign_delta: int
    success_rate_delta: FiniteMetric = Field(ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def validate_comparison(self) -> "PooledBudgetComparison":
        if self.binderranker.method != "BINDERRANKER":
            raise ValueError("binderranker metrics have the wrong method")
        if self.baseline.method != "BASELINE":
            raise ValueError("baseline metrics have the wrong method")
        if self.binderranker.budget != self.budget:
            raise ValueError("BinderRanker budget mismatch")
        if self.baseline.budget != self.budget:
            raise ValueError("baseline budget mismatch")

        aligned_fields = (
            "campaign_count",
            "candidate_count",
            "positive_count",
            "selected_count",
            "campaigns_without_positive_outcomes",
        )
        for field_name in aligned_fields:
            if getattr(self.binderranker, field_name) != getattr(
                self.baseline, field_name
            ):
                raise ValueError(
                    f"pooled method field {field_name!r} is not aligned"
                )

        if self.hits_delta != (
            self.binderranker.hits_at_k - self.baseline.hits_at_k
        ):
            raise ValueError("hits_delta disagrees with pooled results")
        if self.successful_campaign_delta != (
            self.binderranker.successful_campaign_count
            - self.baseline.successful_campaign_count
        ):
            raise ValueError(
                "successful_campaign_delta disagrees with pooled results"
            )
        _require_close(
            self.precision_delta,
            self.binderranker.precision_at_k
            - self.baseline.precision_at_k,
            "precision_delta",
        )
        _require_metric_delta(
            self.recall_delta,
            self.binderranker.recall_at_k,
            self.baseline.recall_at_k,
            "recall_delta",
        )
        _require_metric_delta(
            self.enrichment_factor_delta,
            self.binderranker.enrichment_factor_at_k,
            self.baseline.enrichment_factor_at_k,
            "enrichment_factor_delta",
        )
        _require_close(
            self.success_rate_delta,
            self.binderranker.success_rate_at_k
            - self.baseline.success_rate_at_k,
            "success_rate_delta",
        )
        return self


class FixedBudgetBenchmarkReport(_MetricModel):
    """Deterministic retrospective comparison bound to a sealed bundle."""

    schema_version: Literal["0.1"] = "0.1"
    scientifically_valid_input: Literal[True] = True
    benchmark_id: Identifier
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_evidence_type: EvidenceType
    baseline_method_id: Identifier
    ranker_version: Identifier
    ranker_resource_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_budgets: tuple[int, ...] = Field(min_length=1)
    calibration_excluded: Literal[True] = True
    claim_scope: Literal["DESCRIPTIVE_RETROSPECTIVE_ONLY"] = (
        "DESCRIPTIVE_RETROSPECTIVE_ONLY"
    )
    generalization_established: Literal[False] = False
    causality_established: Literal[False] = False
    evaluation_campaign_count: int = Field(gt=0)
    evaluation_target_count: int = Field(gt=0)
    evaluation_candidate_count: int = Field(gt=0)
    evaluation_positive_count: int = Field(gt=0)
    evaluation_negative_count: int = Field(gt=0)
    campaign_comparisons: tuple[CampaignBudgetComparison, ...] = Field(
        min_length=1
    )
    pooled_comparisons: tuple[PooledBudgetComparison, ...] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def validate_report_shape(self) -> "FixedBudgetBenchmarkReport":
        if self.evaluation_candidate_count != (
            self.evaluation_positive_count + self.evaluation_negative_count
        ):
            raise ValueError("evaluation outcome counts do not cover candidates")
        if self.selection_budgets != tuple(
            sorted(set(self.selection_budgets))
        ):
            raise ValueError("selection_budgets must be increasing and unique")
        expected_campaign_rows = (
            self.evaluation_campaign_count * len(self.selection_budgets)
        )
        if len(self.campaign_comparisons) != expected_campaign_rows:
            raise ValueError("campaign comparison count is incomplete")
        if tuple(item.budget for item in self.pooled_comparisons) != (
            self.selection_budgets
        ):
            raise ValueError("pooled comparisons do not match fixed budgets")

        observed_campaign_budget_pairs = {
            (item.campaign_id, item.budget)
            for item in self.campaign_comparisons
        }
        if len(observed_campaign_budget_pairs) != expected_campaign_rows:
            raise ValueError("campaign/budget comparisons are duplicated")
        campaign_ids = {
            item.campaign_id for item in self.campaign_comparisons
        }
        if len(campaign_ids) != self.evaluation_campaign_count:
            raise ValueError("campaign comparison identities are incomplete")
        target_ids = {item.target_id for item in self.campaign_comparisons}
        if len(target_ids) != self.evaluation_target_count:
            raise ValueError("campaign comparison targets are incomplete")
        for campaign_id in campaign_ids:
            campaign_items = tuple(
                item
                for item in self.campaign_comparisons
                if item.campaign_id == campaign_id
            )
            campaign_budgets = {
                item.budget for item in campaign_items
            }
            if campaign_budgets != set(self.selection_budgets):
                raise ValueError(
                    f"campaign {campaign_id!r} has incomplete fixed budgets"
                )
            campaign_shapes = {
                (item.target_id, item.candidate_count, item.positive_count)
                for item in campaign_items
            }
            if len(campaign_shapes) != 1:
                raise ValueError(
                    f"campaign {campaign_id!r} changes across fixed budgets"
                )
        if {item.budget for item in self.campaign_comparisons} != set(
            self.selection_budgets
        ):
            raise ValueError("campaign comparisons do not match fixed budgets")

        first_budget = self.selection_budgets[0]
        representative_campaigns = tuple(
            item
            for item in self.campaign_comparisons
            if item.budget == first_budget
        )
        if sum(item.candidate_count for item in representative_campaigns) != (
            self.evaluation_candidate_count
        ):
            raise ValueError("campaign candidate counts do not match report")
        if sum(item.positive_count for item in representative_campaigns) != (
            self.evaluation_positive_count
        ):
            raise ValueError("campaign positive counts do not match report")

        for comparison in self.pooled_comparisons:
            for method in (comparison.binderranker, comparison.baseline):
                expected_shape = (
                    self.evaluation_campaign_count,
                    self.evaluation_candidate_count,
                    self.evaluation_positive_count,
                )
                observed_shape = (
                    method.campaign_count,
                    method.candidate_count,
                    method.positive_count,
                )
                if observed_shape != expected_shape:
                    raise ValueError("pooled counts do not match report scope")
        return self


def _require_close(actual: float, expected: float, field_name: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{field_name} does not match its defining counts")


def _require_unavailable(metric: MetricValue, field_name: str) -> None:
    if (
        metric.status != "UNAVAILABLE"
        or metric.reason != "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN"
    ):
        raise ValueError(f"{field_name} must preserve its undefined state")


def _require_available_close(
    metric: MetricValue,
    expected: float,
    field_name: str,
) -> None:
    if metric.status != "AVAILABLE" or metric.value is None:
        raise ValueError(f"{field_name} must be available")
    _require_close(metric.value, expected, field_name)


def _require_metric_delta(
    delta: MetricValue,
    binderranker: MetricValue,
    baseline: MetricValue,
    field_name: str,
) -> None:
    if binderranker.status != baseline.status:
        raise ValueError(f"{field_name} inputs have different availability")
    if binderranker.status == "UNAVAILABLE":
        _require_unavailable(binderranker, field_name)
        _require_unavailable(baseline, field_name)
        _require_unavailable(delta, field_name)
        return
    if binderranker.value is None or baseline.value is None:
        raise ValueError(f"{field_name} inputs are inconsistent")
    _require_available_close(
        delta,
        binderranker.value - baseline.value,
        field_name,
    )


def _require_method_alignment(
    *,
    method: CampaignMethodMetrics,
    expected_method: MetricMethod,
    budget: int,
    candidate_count: int,
    positive_count: int,
) -> None:
    if method.method != expected_method:
        raise ValueError(f"expected method {expected_method!r}")
    if method.budget != budget:
        raise ValueError("method budget does not match comparison budget")
    if method.candidate_count != candidate_count:
        raise ValueError("method candidate_count does not match campaign")
    if method.positive_count != positive_count:
        raise ValueError("method positive_count does not match campaign")


def _available(value: float) -> MetricValue:
    return MetricValue(status="AVAILABLE", value=value)


def _unavailable() -> MetricValue:
    return MetricValue(
        status="UNAVAILABLE",
        reason="NO_POSITIVE_OUTCOMES_IN_CAMPAIGN",
    )


def _metric_delta(
    binderranker: MetricValue,
    baseline: MetricValue,
) -> MetricValue:
    if binderranker.status == "UNAVAILABLE":
        return _unavailable()
    if binderranker.value is None or baseline.value is None:
        raise BenchmarkEvaluationError(
            "aligned method metrics contain inconsistent availability states"
        )
    return _available(binderranker.value - baseline.value)


def _campaign_method_metrics(
    *,
    method: MetricMethod,
    budget: int,
    records: tuple[BenchmarkCandidateRecord, ...],
) -> CampaignMethodMetrics:
    rank_attribute = (
        "binderranker_rank" if method == "BINDERRANKER" else "baseline_rank"
    )
    ordered = sorted(records, key=lambda item: getattr(item, rank_attribute))
    selected = ordered[:budget]
    positive_count = sum(item.outcome for item in records)
    hits_at_k = sum(item.outcome for item in selected)
    precision_at_k = hits_at_k / budget

    if positive_count == 0:
        recall_at_k = _unavailable()
        enrichment_factor_at_k = _unavailable()
    else:
        recall_at_k = _available(hits_at_k / positive_count)
        enrichment_factor_at_k = _available(
            precision_at_k / (positive_count / len(records))
        )

    return CampaignMethodMetrics(
        method=method,
        budget=budget,
        candidate_count=len(records),
        positive_count=positive_count,
        selected_count=len(selected),
        selected_candidate_ids=tuple(item.candidate_id for item in selected),
        hits_at_k=hits_at_k,
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        enrichment_factor_at_k=enrichment_factor_at_k,
        success_at_k=hits_at_k > 0,
    )


def _campaign_comparison(
    *,
    budget: int,
    records: tuple[BenchmarkCandidateRecord, ...],
) -> CampaignBudgetComparison:
    binderranker = _campaign_method_metrics(
        method="BINDERRANKER",
        budget=budget,
        records=records,
    )
    baseline = _campaign_method_metrics(
        method="BASELINE",
        budget=budget,
        records=records,
    )
    first = records[0]
    return CampaignBudgetComparison(
        campaign_id=first.campaign_id,
        target_id=first.target_id,
        budget=budget,
        candidate_count=len(records),
        positive_count=binderranker.positive_count,
        binderranker=binderranker,
        baseline=baseline,
        hits_delta=binderranker.hits_at_k - baseline.hits_at_k,
        precision_delta=(
            binderranker.precision_at_k - baseline.precision_at_k
        ),
        recall_delta=_metric_delta(
            binderranker.recall_at_k,
            baseline.recall_at_k,
        ),
        enrichment_factor_delta=_metric_delta(
            binderranker.enrichment_factor_at_k,
            baseline.enrichment_factor_at_k,
        ),
    )


def _pooled_method_metrics(
    *,
    method: MetricMethod,
    budget: int,
    campaign_metrics: tuple[CampaignMethodMetrics, ...],
) -> PooledMethodMetrics:
    campaign_count = len(campaign_metrics)
    candidate_count = sum(item.candidate_count for item in campaign_metrics)
    positive_count = sum(item.positive_count for item in campaign_metrics)
    selected_count = sum(item.selected_count for item in campaign_metrics)
    hits_at_k = sum(item.hits_at_k for item in campaign_metrics)
    successful_campaign_count = sum(
        item.success_at_k for item in campaign_metrics
    )
    campaigns_without_positive_outcomes = sum(
        item.positive_count == 0 for item in campaign_metrics
    )
    precision_at_k = hits_at_k / selected_count

    return PooledMethodMetrics(
        method=method,
        budget=budget,
        campaign_count=campaign_count,
        candidate_count=candidate_count,
        positive_count=positive_count,
        selected_count=selected_count,
        hits_at_k=hits_at_k,
        precision_at_k=precision_at_k,
        recall_at_k=_available(hits_at_k / positive_count),
        enrichment_factor_at_k=_available(
            precision_at_k / (positive_count / candidate_count)
        ),
        successful_campaign_count=successful_campaign_count,
        success_rate_at_k=successful_campaign_count / campaign_count,
        campaigns_without_positive_outcomes=(
            campaigns_without_positive_outcomes
        ),
    )


def _pooled_comparison(
    *,
    budget: int,
    campaign_comparisons: tuple[CampaignBudgetComparison, ...],
) -> PooledBudgetComparison:
    binderranker = _pooled_method_metrics(
        method="BINDERRANKER",
        budget=budget,
        campaign_metrics=tuple(
            item.binderranker for item in campaign_comparisons
        ),
    )
    baseline = _pooled_method_metrics(
        method="BASELINE",
        budget=budget,
        campaign_metrics=tuple(item.baseline for item in campaign_comparisons),
    )
    return PooledBudgetComparison(
        budget=budget,
        binderranker=binderranker,
        baseline=baseline,
        hits_delta=binderranker.hits_at_k - baseline.hits_at_k,
        precision_delta=(
            binderranker.precision_at_k - baseline.precision_at_k
        ),
        recall_delta=_metric_delta(
            binderranker.recall_at_k,
            baseline.recall_at_k,
        ),
        enrichment_factor_delta=_metric_delta(
            binderranker.enrichment_factor_at_k,
            baseline.enrichment_factor_at_k,
        ),
        successful_campaign_delta=(
            binderranker.successful_campaign_count
            - baseline.successful_campaign_count
        ),
        success_rate_delta=(
            binderranker.success_rate_at_k - baseline.success_rate_at_k
        ),
    )


def _revalidate_bundle(
    bundle: ValidatedBenchmarkBundle,
) -> ValidatedBenchmarkBundle:
    if not isinstance(bundle, ValidatedBenchmarkBundle):
        raise BenchmarkEvaluationError(
            "fixed-budget metrics require a ValidatedBenchmarkBundle"
        )
    try:
        refreshed = validate_benchmark_bundle(bundle.manifest_path)
    except BenchmarkContractError as exc:
        raise BenchmarkEvaluationError(
            "benchmark bundle no longer passes the sealed input contract"
        ) from exc
    if refreshed != bundle:
        raise BenchmarkEvaluationError(
            "validated bundle does not match its current sealed files; "
            "validate the bundle again before evaluation"
        )
    return refreshed


def evaluate_fixed_budget_metrics(
    bundle: ValidatedBenchmarkBundle,
) -> FixedBudgetBenchmarkReport:
    """Compare BinderRanker and baseline at every declared fixed budget."""
    refreshed = _revalidate_bundle(bundle)
    campaigns: dict[str, list[BenchmarkCandidateRecord]] = defaultdict(list)
    for record in refreshed.records:
        if record.split == "EVALUATION":
            campaigns[record.campaign_id].append(record)

    ordered_campaigns = tuple(
        (
            campaign_id,
            tuple(
                sorted(
                    records,
                    key=lambda item: (
                        item.binderranker_rank,
                        item.candidate_id,
                    ),
                )
            ),
        )
        for campaign_id, records in sorted(campaigns.items())
    )

    campaign_comparisons = tuple(
        _campaign_comparison(budget=budget, records=records)
        for campaign_id, records in ordered_campaigns
        for budget in refreshed.manifest.selection_budgets
    )
    pooled_comparisons = tuple(
        _pooled_comparison(
            budget=budget,
            campaign_comparisons=tuple(
                item for item in campaign_comparisons if item.budget == budget
            ),
        )
        for budget in refreshed.manifest.selection_budgets
    )
    evaluation_records = tuple(
        record for _, records in ordered_campaigns for record in records
    )

    return FixedBudgetBenchmarkReport(
        benchmark_id=refreshed.manifest.benchmark_id,
        manifest_sha256=refreshed.summary.manifest_sha256,
        dataset_sha256=refreshed.summary.dataset_sha256,
        outcome_evidence_type=refreshed.manifest.outcome.evidence_type,
        baseline_method_id=refreshed.manifest.baseline.method_id,
        ranker_version=refreshed.manifest.ranker.version,
        ranker_resource_sha256=refreshed.manifest.ranker.resource_sha256,
        selection_budgets=refreshed.manifest.selection_budgets,
        evaluation_campaign_count=refreshed.summary.evaluation_campaign_count,
        evaluation_target_count=refreshed.summary.evaluation_target_count,
        evaluation_candidate_count=len(evaluation_records),
        evaluation_positive_count=refreshed.summary.evaluation_positive_count,
        evaluation_negative_count=refreshed.summary.evaluation_negative_count,
        campaign_comparisons=campaign_comparisons,
        pooled_comparisons=pooled_comparisons,
    )
