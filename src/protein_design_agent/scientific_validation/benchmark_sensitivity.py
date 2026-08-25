"""Deterministic target-level sensitivity for fixed-budget benchmarks."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from protein_design_agent.scientific_validation.benchmark_contract import (
    EvidenceType,
    Identifier,
    ValidatedBenchmarkBundle,
)
from protein_design_agent.scientific_validation.benchmark_metrics import (
    BenchmarkEvaluationError,
    CampaignBudgetComparison,
    FixedBudgetBenchmarkReport,
    evaluate_fixed_budget_metrics,
)


SensitivityMetric = Literal[
    "HITS_PER_CAMPAIGN_DELTA",
    "PRECISION_DELTA",
    "RECALL_DELTA",
    "ENRICHMENT_FACTOR_DELTA",
    "SUCCESS_RATE_DELTA",
]
TargetMetricStatus = Literal["AVAILABLE", "UNAVAILABLE"]
TargetMetricUnavailableReason = Literal["NO_POSITIVE_OUTCOMES_IN_TARGET"]
SensitivityRangeStatus = Literal["AVAILABLE", "UNAVAILABLE"]
SensitivityRangeUnavailableReason = Literal[
    "FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC"
]
FiniteValue = Annotated[float, Field(allow_inf_nan=False)]

SENSITIVITY_METRICS: tuple[SensitivityMetric, ...] = (
    "HITS_PER_CAMPAIGN_DELTA",
    "PRECISION_DELTA",
    "RECALL_DELTA",
    "ENRICHMENT_FACTOR_DELTA",
    "SUCCESS_RATE_DELTA",
)


class TargetSensitivityError(RuntimeError):
    """A fixed-budget benchmark cannot enter target sensitivity analysis."""


class _SensitivityModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class TargetMetricValue(_SensitivityModel):
    """A target-level delta or its explicit undefined state."""

    status: TargetMetricStatus
    value: FiniteValue | None = None
    reason: TargetMetricUnavailableReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "TargetMetricValue":
        if self.status == "AVAILABLE":
            if self.value is None or self.reason is not None:
                raise ValueError(
                    "AVAILABLE target metrics require a value and no reason"
                )
        elif self.value is not None or self.reason is None:
            raise ValueError(
                "UNAVAILABLE target metrics require no value and a reason"
            )
        return self


class LeaveOneTargetOutRange(_SensitivityModel):
    """Range of estimates after removing each defined target once."""

    status: SensitivityRangeStatus
    lower: FiniteValue | None = None
    upper: FiniteValue | None = None
    maximum_absolute_shift: FiniteValue | None = Field(default=None, ge=0.0)
    reason: SensitivityRangeUnavailableReason | None = None
    not_confidence_interval: Literal[True] = True

    @model_validator(mode="after")
    def validate_state(self) -> "LeaveOneTargetOutRange":
        values = (self.lower, self.upper, self.maximum_absolute_shift)
        if self.status == "AVAILABLE":
            if any(value is None for value in values) or self.reason is not None:
                raise ValueError(
                    "AVAILABLE sensitivity ranges require all finite values"
                )
            if self.lower is not None and self.upper is not None:
                if self.lower > self.upper:
                    raise ValueError("sensitivity range lower exceeds upper")
        elif any(value is not None for value in values) or self.reason is None:
            raise ValueError(
                "UNAVAILABLE sensitivity ranges require no values and a reason"
            )
        return self


class TargetBudgetMetrics(_SensitivityModel):
    """Campaign counts pooled within one target at one fixed budget."""

    target_id: Identifier
    budget: int = Field(gt=0)
    campaign_count: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    positive_count: int = Field(ge=0)
    selected_count: int = Field(gt=0)
    binderranker_hits_at_k: int = Field(ge=0)
    baseline_hits_at_k: int = Field(ge=0)
    hits_delta: int
    hits_per_campaign_delta: FiniteValue
    precision_delta: FiniteValue = Field(ge=-1.0, le=1.0)
    recall_delta: TargetMetricValue
    enrichment_factor_delta: TargetMetricValue
    binderranker_successful_campaign_count: int = Field(ge=0)
    baseline_successful_campaign_count: int = Field(ge=0)
    successful_campaign_delta: int
    success_rate_delta: FiniteValue = Field(ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def validate_arithmetic(self) -> "TargetBudgetMetrics":
        if self.selected_count != self.budget * self.campaign_count:
            raise ValueError(
                "target selected_count must equal budget * campaign_count"
            )
        if self.candidate_count < self.selected_count:
            raise ValueError("target selected_count exceeds candidate_count")
        if self.positive_count > self.candidate_count:
            raise ValueError("target positive_count exceeds candidate_count")
        for field_name in (
            "binderranker_hits_at_k",
            "baseline_hits_at_k",
        ):
            if getattr(self, field_name) > min(
                self.selected_count,
                self.positive_count,
            ):
                raise ValueError(f"{field_name} exceeds an admissible count")
        if self.hits_delta != (
            self.binderranker_hits_at_k - self.baseline_hits_at_k
        ):
            raise ValueError("target hits_delta disagrees with method counts")
        _require_close(
            self.hits_per_campaign_delta,
            self.hits_delta / self.campaign_count,
            "hits_per_campaign_delta",
        )
        _require_close(
            self.precision_delta,
            self.hits_delta / self.selected_count,
            "precision_delta",
        )

        if self.positive_count == 0:
            _require_target_unavailable(self.recall_delta, "recall_delta")
            _require_target_unavailable(
                self.enrichment_factor_delta,
                "enrichment_factor_delta",
            )
        else:
            expected_recall = self.hits_delta / self.positive_count
            expected_enrichment = self.precision_delta / (
                self.positive_count / self.candidate_count
            )
            _require_target_available(
                self.recall_delta,
                expected_recall,
                "recall_delta",
            )
            _require_target_available(
                self.enrichment_factor_delta,
                expected_enrichment,
                "enrichment_factor_delta",
            )

        for field_name in (
            "binderranker_successful_campaign_count",
            "baseline_successful_campaign_count",
        ):
            if getattr(self, field_name) > self.campaign_count:
                raise ValueError(f"{field_name} exceeds campaign_count")
        if self.successful_campaign_delta != (
            self.binderranker_successful_campaign_count
            - self.baseline_successful_campaign_count
        ):
            raise ValueError(
                "successful_campaign_delta disagrees with method counts"
            )
        _require_close(
            self.success_rate_delta,
            self.successful_campaign_delta / self.campaign_count,
            "success_rate_delta",
        )
        return self


class TargetMetricSummary(_SensitivityModel):
    """Equal-target descriptive distribution and removal sensitivity."""

    metric: SensitivityMetric
    budget: int = Field(gt=0)
    target_count_total: int = Field(gt=0)
    target_count_defined: int = Field(gt=0)
    target_count_excluded: int = Field(ge=0)
    macro_target_mean: FiniteValue
    target_minimum: FiniteValue
    target_median: FiniteValue
    target_maximum: FiniteValue
    positive_target_count: int = Field(ge=0)
    zero_target_count: int = Field(ge=0)
    negative_target_count: int = Field(ge=0)
    leave_one_target_out: LeaveOneTargetOutRange

    @model_validator(mode="after")
    def validate_shape(self) -> "TargetMetricSummary":
        if self.target_count_total != (
            self.target_count_defined + self.target_count_excluded
        ):
            raise ValueError("defined and excluded targets do not cover total")
        if self.target_count_defined != (
            self.positive_target_count
            + self.zero_target_count
            + self.negative_target_count
        ):
            raise ValueError("direction counts do not cover defined targets")
        if not (
            self.target_minimum
            <= self.target_median
            <= self.target_maximum
        ):
            raise ValueError("target distribution order is invalid")
        if not (
            self.target_minimum
            <= self.macro_target_mean
            <= self.target_maximum
        ):
            raise ValueError("macro target mean falls outside target range")
        expected_range_status = (
            "AVAILABLE" if self.target_count_defined >= 2 else "UNAVAILABLE"
        )
        if self.leave_one_target_out.status != expected_range_status:
            raise ValueError(
                "leave-one-target-out status disagrees with defined targets"
            )
        return self


class TargetSensitivityReport(_SensitivityModel):
    """Deterministic target heterogeneity and removal-sensitivity report."""

    schema_version: Literal["0.1"] = "0.1"
    scientifically_valid_input: Literal[True] = True
    benchmark_id: Identifier
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_evidence_type: EvidenceType
    baseline_method_id: Identifier
    ranker_version: Identifier
    ranker_resource_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fixed_budget_schema_version: Literal["0.1"] = "0.1"
    selection_budgets: tuple[int, ...] = Field(min_length=1)
    calibration_excluded: Literal[True] = True
    analysis_unit: Literal["TARGET"] = "TARGET"
    analysis_method: Literal["LEAVE_ONE_TARGET_OUT"] = "LEAVE_ONE_TARGET_OUT"
    claim_scope: Literal["DESCRIPTIVE_TARGET_SENSITIVITY_ONLY"] = (
        "DESCRIPTIVE_TARGET_SENSITIVITY_ONLY"
    )
    not_confidence_interval: Literal[True] = True
    statistical_significance_established: Literal[False] = False
    generalization_established: Literal[False] = False
    causality_established: Literal[False] = False
    evaluation_campaign_count: int = Field(gt=0)
    evaluation_target_count: int = Field(gt=0)
    target_budget_metrics: tuple[TargetBudgetMetrics, ...] = Field(min_length=1)
    metric_summaries: tuple[TargetMetricSummary, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report_shape(self) -> "TargetSensitivityReport":
        if self.selection_budgets != tuple(
            sorted(set(self.selection_budgets))
        ):
            raise ValueError("selection_budgets must be increasing and unique")
        expected_target_rows = (
            self.evaluation_target_count * len(self.selection_budgets)
        )
        if len(self.target_budget_metrics) != expected_target_rows:
            raise ValueError("target/budget metric rows are incomplete")
        target_budget_pairs = {
            (item.target_id, item.budget) for item in self.target_budget_metrics
        }
        if len(target_budget_pairs) != expected_target_rows:
            raise ValueError("target/budget metric rows are duplicated")
        target_ids = {item.target_id for item in self.target_budget_metrics}
        if len(target_ids) != self.evaluation_target_count:
            raise ValueError("target identities are incomplete")
        for target_id in target_ids:
            observed_budgets = {
                item.budget
                for item in self.target_budget_metrics
                if item.target_id == target_id
            }
            if observed_budgets != set(self.selection_budgets):
                raise ValueError(
                    f"target {target_id!r} has incomplete fixed budgets"
                )

        expected_summary_pairs = {
            (metric, budget)
            for budget in self.selection_budgets
            for metric in SENSITIVITY_METRICS
        }
        summary_pairs = {
            (item.metric, item.budget) for item in self.metric_summaries
        }
        if summary_pairs != expected_summary_pairs:
            raise ValueError("target sensitivity summaries are incomplete")
        if len(self.metric_summaries) != len(expected_summary_pairs):
            raise ValueError("target sensitivity summaries are duplicated")

        for summary in self.metric_summaries:
            target_rows = tuple(
                item
                for item in self.target_budget_metrics
                if item.budget == summary.budget
            )
            expected = _summarize_target_metric(
                metric=summary.metric,
                budget=summary.budget,
                target_rows=target_rows,
            )
            if summary != expected:
                raise ValueError(
                    "target sensitivity summary disagrees with target rows"
                )
        return self


def _require_close(actual: float, expected: float, field_name: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{field_name} does not match its defining counts")


def _require_target_unavailable(
    metric: TargetMetricValue,
    field_name: str,
) -> None:
    if (
        metric.status != "UNAVAILABLE"
        or metric.reason != "NO_POSITIVE_OUTCOMES_IN_TARGET"
    ):
        raise ValueError(f"{field_name} must preserve its undefined state")


def _require_target_available(
    metric: TargetMetricValue,
    expected: float,
    field_name: str,
) -> None:
    if metric.status != "AVAILABLE" or metric.value is None:
        raise ValueError(f"{field_name} must be available")
    _require_close(metric.value, expected, field_name)


def _available(value: float) -> TargetMetricValue:
    return TargetMetricValue(status="AVAILABLE", value=value)


def _unavailable() -> TargetMetricValue:
    return TargetMetricValue(
        status="UNAVAILABLE",
        reason="NO_POSITIVE_OUTCOMES_IN_TARGET",
    )


def _target_budget_metrics(
    *,
    target_id: str,
    budget: int,
    campaigns: tuple[CampaignBudgetComparison, ...],
) -> TargetBudgetMetrics:
    campaign_count = len(campaigns)
    candidate_count = sum(item.candidate_count for item in campaigns)
    positive_count = sum(item.positive_count for item in campaigns)
    selected_count = sum(item.binderranker.selected_count for item in campaigns)
    binderranker_hits = sum(item.binderranker.hits_at_k for item in campaigns)
    baseline_hits = sum(item.baseline.hits_at_k for item in campaigns)
    hits_delta = binderranker_hits - baseline_hits
    precision_delta = hits_delta / selected_count

    if positive_count == 0:
        recall_delta = _unavailable()
        enrichment_factor_delta = _unavailable()
    else:
        recall_delta = _available(hits_delta / positive_count)
        enrichment_factor_delta = _available(
            precision_delta / (positive_count / candidate_count)
        )

    binderranker_successful_campaign_count = sum(
        item.binderranker.success_at_k for item in campaigns
    )
    baseline_successful_campaign_count = sum(
        item.baseline.success_at_k for item in campaigns
    )
    successful_campaign_delta = (
        binderranker_successful_campaign_count
        - baseline_successful_campaign_count
    )

    return TargetBudgetMetrics(
        target_id=target_id,
        budget=budget,
        campaign_count=campaign_count,
        candidate_count=candidate_count,
        positive_count=positive_count,
        selected_count=selected_count,
        binderranker_hits_at_k=binderranker_hits,
        baseline_hits_at_k=baseline_hits,
        hits_delta=hits_delta,
        hits_per_campaign_delta=hits_delta / campaign_count,
        precision_delta=precision_delta,
        recall_delta=recall_delta,
        enrichment_factor_delta=enrichment_factor_delta,
        binderranker_successful_campaign_count=(
            binderranker_successful_campaign_count
        ),
        baseline_successful_campaign_count=baseline_successful_campaign_count,
        successful_campaign_delta=successful_campaign_delta,
        success_rate_delta=successful_campaign_delta / campaign_count,
    )


def _target_metric_value(
    row: TargetBudgetMetrics,
    metric: SensitivityMetric,
) -> float | None:
    if metric == "HITS_PER_CAMPAIGN_DELTA":
        return row.hits_per_campaign_delta
    if metric == "PRECISION_DELTA":
        return row.precision_delta
    if metric == "RECALL_DELTA":
        return row.recall_delta.value
    if metric == "ENRICHMENT_FACTOR_DELTA":
        return row.enrichment_factor_delta.value
    return row.success_rate_delta


def _leave_one_target_out(values: tuple[float, ...]) -> LeaveOneTargetOutRange:
    if len(values) < 2:
        return LeaveOneTargetOutRange(
            status="UNAVAILABLE",
            reason="FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC",
        )
    full_mean = math.fsum(values) / len(values)
    leave_one_out = tuple(
        math.fsum(value for index, value in enumerate(values) if index != drop)
        / (len(values) - 1)
        for drop in range(len(values))
    )
    return LeaveOneTargetOutRange(
        status="AVAILABLE",
        lower=min(leave_one_out),
        upper=max(leave_one_out),
        maximum_absolute_shift=max(
            abs(value - full_mean) for value in leave_one_out
        ),
    )


def _summarize_target_metric(
    *,
    metric: SensitivityMetric,
    budget: int,
    target_rows: tuple[TargetBudgetMetrics, ...],
) -> TargetMetricSummary:
    values = tuple(
        value
        for row in sorted(target_rows, key=lambda item: item.target_id)
        if (value := _target_metric_value(row, metric)) is not None
    )
    positive_count = sum(value > 1e-12 for value in values)
    negative_count = sum(value < -1e-12 for value in values)
    zero_count = len(values) - positive_count - negative_count
    return TargetMetricSummary(
        metric=metric,
        budget=budget,
        target_count_total=len(target_rows),
        target_count_defined=len(values),
        target_count_excluded=len(target_rows) - len(values),
        macro_target_mean=math.fsum(values) / len(values),
        target_minimum=min(values),
        target_median=statistics.median(values),
        target_maximum=max(values),
        positive_target_count=positive_count,
        zero_target_count=zero_count,
        negative_target_count=negative_count,
        leave_one_target_out=_leave_one_target_out(values),
    )


def _build_sensitivity_report(
    fixed_budget: FixedBudgetBenchmarkReport,
) -> TargetSensitivityReport:
    target_campaigns: dict[
        tuple[str, int],
        list[CampaignBudgetComparison],
    ] = defaultdict(list)
    for comparison in fixed_budget.campaign_comparisons:
        target_campaigns[(comparison.target_id, comparison.budget)].append(
            comparison
        )

    target_rows = tuple(
        _target_budget_metrics(
            target_id=target_id,
            budget=budget,
            campaigns=tuple(
                sorted(campaigns, key=lambda item: item.campaign_id)
            ),
        )
        for (target_id, budget), campaigns in sorted(target_campaigns.items())
    )
    summaries = tuple(
        _summarize_target_metric(
            metric=metric,
            budget=budget,
            target_rows=tuple(
                item for item in target_rows if item.budget == budget
            ),
        )
        for budget in fixed_budget.selection_budgets
        for metric in SENSITIVITY_METRICS
    )
    return TargetSensitivityReport(
        benchmark_id=fixed_budget.benchmark_id,
        manifest_sha256=fixed_budget.manifest_sha256,
        dataset_sha256=fixed_budget.dataset_sha256,
        outcome_evidence_type=fixed_budget.outcome_evidence_type,
        baseline_method_id=fixed_budget.baseline_method_id,
        ranker_version=fixed_budget.ranker_version,
        ranker_resource_sha256=fixed_budget.ranker_resource_sha256,
        selection_budgets=fixed_budget.selection_budgets,
        evaluation_campaign_count=fixed_budget.evaluation_campaign_count,
        evaluation_target_count=fixed_budget.evaluation_target_count,
        target_budget_metrics=target_rows,
        metric_summaries=summaries,
    )


def evaluate_target_sensitivity(
    bundle: ValidatedBenchmarkBundle,
) -> TargetSensitivityReport:
    """Describe target heterogeneity and leave-one-target-out sensitivity."""
    try:
        fixed_budget = evaluate_fixed_budget_metrics(bundle)
    except BenchmarkEvaluationError as exc:
        raise TargetSensitivityError(
            "target sensitivity requires a current validated benchmark bundle"
        ) from exc
    return _build_sensitivity_report(fixed_budget)
