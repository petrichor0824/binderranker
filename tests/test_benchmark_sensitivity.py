import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from protein_design_agent.scientific_validation import (
    LeaveOneTargetOutRange,
    TargetMetricValue,
    TargetSensitivityError,
    evaluate_target_sensitivity,
    validate_benchmark_bundle,
)


RANKER_SHA256 = (
    "92d6c02f8ca8f500917f5fa61676fe93"
    "a0acdbb59d49f2cac0c7a74a4a553ed7"
)

FIELDNAMES = [
    "campaign_id",
    "target_id",
    "candidate_id",
    "split",
    "binderranker_rank",
    "binderranker_score",
    "baseline_rank",
    "outcome",
]


def _campaign_rows(
    *,
    campaign_id: str,
    target_id: str,
    split: str,
    positive_rank: int | None,
    baseline_positive_first: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for rank in range(1, 5):
        if baseline_positive_first:
            baseline_rank = 1 if rank == 4 else rank + 1
        elif positive_rank == 1:
            baseline_rank = 4 if rank == 1 else rank - 1
        else:
            baseline_rank = rank
        rows.append(
            {
                "campaign_id": campaign_id,
                "target_id": target_id,
                "candidate_id": f"{campaign_id}_{rank}",
                "split": split,
                "binderranker_rank": rank,
                "binderranker_score": 1.0 - (rank / 10),
                "baseline_rank": baseline_rank,
                "outcome": int(rank == positive_rank),
            }
        )
    return rows


def benchmark_rows() -> list[dict[str, Any]]:
    return [
        *_campaign_rows(
            campaign_id="campaign_cal",
            target_id="target_cal",
            split="CALIBRATION",
            positive_rank=1,
        ),
        *_campaign_rows(
            campaign_id="campaign_eval_a1",
            target_id="target_a",
            split="EVALUATION",
            positive_rank=1,
        ),
        *_campaign_rows(
            campaign_id="campaign_eval_a2",
            target_id="target_a",
            split="EVALUATION",
            positive_rank=1,
        ),
        *_campaign_rows(
            campaign_id="campaign_eval_b",
            target_id="target_b",
            split="EVALUATION",
            positive_rank=4,
            baseline_positive_first=True,
        ),
        *_campaign_rows(
            campaign_id="campaign_eval_zero",
            target_id="target_zero",
            split="EVALUATION",
            positive_rank=None,
        ),
    ]


def write_bundle(
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    dataset_path = bundle_dir / "candidates.csv"
    with dataset_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(benchmark_rows() if rows is None else rows)

    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "0.1",
        "benchmark_id": "target_sensitivity_fixture",
        "description": "Synthetic target sensitivity fixture.",
        "dataset": {
            "file": "candidates.csv",
            "sha256": dataset_sha256,
        },
        "outcome": {
            "name": "downstream_success",
            "description": "Synthetic binary outcome.",
            "evidence_type": "EXPERIMENTAL",
            "source": "test fixture only",
        },
        "baseline": {
            "method_id": "fixture_order",
            "description": "Synthetic baseline.",
            "ranking_procedure": "Fixed fixture order.",
        },
        "ranker": {
            "ranker_id": "BinderRanker",
            "version": "v0.1-expert",
            "resource_sha256": RANKER_SHA256,
        },
        "protocol": {
            "parameter_selection": "CALIBRATION_ONLY",
            "ranking_blinded_to_outcomes": True,
            "baseline_blinded_to_outcomes": True,
            "target_split_unit": "TARGET",
        },
        "selection_budgets": [1, 2],
    }
    manifest_path = bundle_dir / "benchmark.yaml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return manifest_path, dataset_path


@pytest.fixture
def benchmark_bundle(tmp_path: Path):
    manifest_path, _ = write_bundle(tmp_path)
    return validate_benchmark_bundle(manifest_path)


def target_row(report, target_id: str, budget: int):
    return next(
        item
        for item in report.target_budget_metrics
        if item.target_id == target_id and item.budget == budget
    )


def metric_summary(report, metric: str, budget: int):
    return next(
        item
        for item in report.metric_summaries
        if item.metric == metric and item.budget == budget
    )


def test_target_sensitivity_binds_to_fixed_budget_report(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)

    assert report.schema_version == "0.1"
    assert report.benchmark_id == "target_sensitivity_fixture"
    assert report.manifest_sha256 == benchmark_bundle.summary.manifest_sha256
    assert report.dataset_sha256 == benchmark_bundle.summary.dataset_sha256
    assert report.selection_budgets == (1, 2)
    assert report.calibration_excluded is True
    assert report.analysis_unit == "TARGET"
    assert report.analysis_method == "LEAVE_ONE_TARGET_OUT"
    assert report.evaluation_campaign_count == 4
    assert report.evaluation_target_count == 3
    assert len(report.target_budget_metrics) == 6
    assert len(report.metric_summaries) == 10


def test_multiple_campaigns_are_pooled_within_target(benchmark_bundle) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    target = target_row(report, "target_a", 1)

    assert target.campaign_count == 2
    assert target.candidate_count == 8
    assert target.positive_count == 2
    assert target.selected_count == 2
    assert target.binderranker_hits_at_k == 2
    assert target.baseline_hits_at_k == 0
    assert target.hits_delta == 2
    assert target.hits_per_campaign_delta == 1.0
    assert target.precision_delta == 1.0
    assert target.recall_delta.value == 1.0
    assert target.enrichment_factor_delta.value == 4.0
    assert target.successful_campaign_delta == 2
    assert target.success_rate_delta == 1.0


def test_target_direction_can_disagree_with_other_targets(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    target = target_row(report, "target_b", 1)

    assert target.hits_per_campaign_delta == -1.0
    assert target.precision_delta == -1.0
    assert target.recall_delta.value == -1.0
    assert target.enrichment_factor_delta.value == -4.0
    assert target.success_rate_delta == -1.0


def test_zero_positive_target_preserves_undefined_metrics(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    target = target_row(report, "target_zero", 1)

    assert target.precision_delta == 0.0
    assert target.success_rate_delta == 0.0
    for metric in (target.recall_delta, target.enrichment_factor_delta):
        assert metric.status == "UNAVAILABLE"
        assert metric.value is None
        assert metric.reason == "NO_POSITIVE_OUTCOMES_IN_TARGET"


def test_macro_summary_preserves_target_heterogeneity(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    summary = metric_summary(report, "PRECISION_DELTA", 1)

    assert summary.target_count_total == 3
    assert summary.target_count_defined == 3
    assert summary.target_count_excluded == 0
    assert summary.macro_target_mean == 0.0
    assert summary.target_minimum == -1.0
    assert summary.target_median == 0.0
    assert summary.target_maximum == 1.0
    assert summary.positive_target_count == 1
    assert summary.zero_target_count == 1
    assert summary.negative_target_count == 1
    assert summary.leave_one_target_out.status == "AVAILABLE"
    assert summary.leave_one_target_out.lower == -0.5
    assert summary.leave_one_target_out.upper == 0.5
    assert summary.leave_one_target_out.maximum_absolute_shift == 0.5


def test_undefined_targets_are_excluded_explicitly_from_macro_metric(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    summary = metric_summary(report, "ENRICHMENT_FACTOR_DELTA", 1)

    assert summary.target_count_total == 3
    assert summary.target_count_defined == 2
    assert summary.target_count_excluded == 1
    assert summary.macro_target_mean == 0.0
    assert summary.target_minimum == -4.0
    assert summary.target_maximum == 4.0
    assert summary.leave_one_target_out.lower == -4.0
    assert summary.leave_one_target_out.upper == 4.0
    assert summary.leave_one_target_out.maximum_absolute_shift == 4.0


def test_single_target_reports_unavailable_removal_sensitivity(
    tmp_path: Path,
) -> None:
    rows = [
        row
        for row in benchmark_rows()
        if row["split"] == "CALIBRATION"
        or row["campaign_id"] == "campaign_eval_a1"
    ]
    manifest_path, _ = write_bundle(tmp_path, rows=rows)
    bundle = validate_benchmark_bundle(manifest_path)
    report = evaluate_target_sensitivity(bundle)

    assert report.evaluation_target_count == 1
    for summary in report.metric_summaries:
        sensitivity = summary.leave_one_target_out
        assert sensitivity.status == "UNAVAILABLE"
        assert sensitivity.lower is None
        assert sensitivity.upper is None
        assert sensitivity.maximum_absolute_shift is None
        assert (
            sensitivity.reason
            == "FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC"
        )


def test_sensitivity_range_is_not_a_confidence_interval(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)

    assert report.not_confidence_interval is True
    assert report.claim_scope == "DESCRIPTIVE_TARGET_SENSITIVITY_ONLY"
    assert report.statistical_significance_established is False
    assert report.generalization_established is False
    assert report.causality_established is False
    assert all(
        item.leave_one_target_out.not_confidence_interval is True
        for item in report.metric_summaries
    )


def test_sensitivity_report_is_deterministic(benchmark_bundle) -> None:
    first = evaluate_target_sensitivity(benchmark_bundle)
    second = evaluate_target_sensitivity(benchmark_bundle)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_changed_bundle_is_rejected_before_sensitivity(tmp_path: Path) -> None:
    manifest_path, dataset_path = write_bundle(tmp_path)
    bundle = validate_benchmark_bundle(manifest_path)
    with dataset_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(
        TargetSensitivityError,
        match="current validated benchmark bundle",
    ):
        evaluate_target_sensitivity(bundle)


def test_report_rejects_summary_that_disagrees_with_target_rows(
    benchmark_bundle,
) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)
    payload = report.model_dump(mode="json")
    payload["metric_summaries"][0]["macro_target_mean"] = 0.25

    with pytest.raises(ValidationError, match="disagrees with target rows"):
        type(report).model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "AVAILABLE"},
        {
            "status": "AVAILABLE",
            "value": 0.0,
            "reason": "NO_POSITIVE_OUTCOMES_IN_TARGET",
        },
        {"status": "UNAVAILABLE"},
        {
            "status": "UNAVAILABLE",
            "value": 0.0,
            "reason": "NO_POSITIVE_OUTCOMES_IN_TARGET",
        },
        {"status": "AVAILABLE", "value": float("nan")},
        {"status": "AVAILABLE", "value": float("inf")},
    ],
)
def test_target_metric_value_rejects_invalid_states(payload) -> None:
    with pytest.raises(ValidationError):
        TargetMetricValue.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "AVAILABLE", "lower": 0.0, "upper": 1.0},
        {
            "status": "AVAILABLE",
            "lower": 1.0,
            "upper": 0.0,
            "maximum_absolute_shift": 1.0,
        },
        {"status": "UNAVAILABLE"},
        {
            "status": "UNAVAILABLE",
            "lower": 0.0,
            "reason": "FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC",
        },
    ],
)
def test_leave_one_target_out_range_rejects_invalid_states(payload) -> None:
    with pytest.raises(ValidationError):
        LeaveOneTargetOutRange.model_validate(payload)


def test_sensitivity_models_are_immutable(benchmark_bundle) -> None:
    report = evaluate_target_sensitivity(benchmark_bundle)

    with pytest.raises(ValidationError):
        report.analysis_unit = "CAMPAIGN"  # type: ignore[misc]
