import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from protein_design_agent.scientific_validation import (
    BenchmarkEvaluationError,
    MetricValue,
    evaluate_fixed_budget_metrics,
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


def benchmark_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for campaign_id, target_id, positive_rank in (
        ("campaign_cal", "target_cal", 1),
        ("campaign_eval_a", "target_eval_a", 1),
        ("campaign_eval_b", "target_eval_b", 1),
        ("campaign_eval_zero", "target_eval_zero", None),
    ):
        split = "CALIBRATION" if campaign_id == "campaign_cal" else "EVALUATION"
        for rank in range(1, 5):
            rows.append(
                {
                    "campaign_id": campaign_id,
                    "target_id": target_id,
                    "candidate_id": f"{campaign_id}_{rank}",
                    "split": split,
                    "binderranker_rank": rank,
                    "binderranker_score": 1.0 - (rank / 10),
                    "baseline_rank": 4 if rank == 1 else rank - 1,
                    "outcome": int(rank == positive_rank),
                }
            )
    return rows


def write_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    dataset_path = bundle_dir / "candidates.csv"
    with dataset_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(benchmark_rows())

    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "0.1",
        "benchmark_id": "fixed_budget_fixture",
        "description": "Synthetic fixed-budget metric fixture.",
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
            "method_id": "generation_order",
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


def campaign_comparison(report, campaign_id: str, budget: int):
    return next(
        item
        for item in report.campaign_comparisons
        if item.campaign_id == campaign_id and item.budget == budget
    )


def test_metrics_exclude_calibration_and_bind_to_sealed_input(
    benchmark_bundle,
) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)

    assert report.schema_version == "0.1"
    assert report.scientifically_valid_input is True
    assert report.benchmark_id == "fixed_budget_fixture"
    assert report.manifest_sha256 == benchmark_bundle.summary.manifest_sha256
    assert report.dataset_sha256 == benchmark_bundle.summary.dataset_sha256
    assert report.outcome_evidence_type == "EXPERIMENTAL"
    assert report.baseline_method_id == "generation_order"
    assert report.ranker_resource_sha256 == RANKER_SHA256
    assert report.selection_budgets == (1, 2)
    assert report.calibration_excluded is True
    assert report.evaluation_campaign_count == 3
    assert report.evaluation_target_count == 3
    assert report.evaluation_candidate_count == 12
    assert report.evaluation_positive_count == 2
    assert report.evaluation_negative_count == 10
    assert len(report.campaign_comparisons) == 6
    assert all(
        item.campaign_id != "campaign_cal"
        for item in report.campaign_comparisons
    )


def test_campaign_comparison_uses_each_fixed_ranking(benchmark_bundle) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)
    comparison = campaign_comparison(report, "campaign_eval_a", 1)

    assert comparison.binderranker.selected_candidate_ids == (
        "campaign_eval_a_1",
    )
    assert comparison.baseline.selected_candidate_ids == (
        "campaign_eval_a_2",
    )
    assert comparison.binderranker.hits_at_k == 1
    assert comparison.baseline.hits_at_k == 0
    assert comparison.binderranker.precision_at_k == 1.0
    assert comparison.baseline.precision_at_k == 0.0
    assert comparison.binderranker.recall_at_k.value == 1.0
    assert comparison.binderranker.enrichment_factor_at_k.value == 4.0
    assert comparison.hits_delta == 1
    assert comparison.precision_delta == 1.0
    assert comparison.recall_delta.value == 1.0
    assert comparison.enrichment_factor_delta.value == 4.0


def test_zero_positive_campaign_preserves_undefined_metrics(
    benchmark_bundle,
) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)
    comparison = campaign_comparison(report, "campaign_eval_zero", 1)

    assert comparison.binderranker.precision_at_k == 0.0
    assert comparison.baseline.precision_at_k == 0.0
    for metric in (
        comparison.binderranker.recall_at_k,
        comparison.binderranker.enrichment_factor_at_k,
        comparison.baseline.recall_at_k,
        comparison.baseline.enrichment_factor_at_k,
        comparison.recall_delta,
        comparison.enrichment_factor_delta,
    ):
        assert metric.status == "UNAVAILABLE"
        assert metric.value is None
        assert metric.reason == "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN"


def test_pooled_metrics_select_budget_within_every_campaign(
    benchmark_bundle,
) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)
    pooled = report.pooled_comparisons[0]

    assert pooled.budget == 1
    assert pooled.binderranker.campaign_count == 3
    assert pooled.binderranker.candidate_count == 12
    assert pooled.binderranker.positive_count == 2
    assert pooled.binderranker.selected_count == 3
    assert pooled.binderranker.hits_at_k == 2
    assert pooled.binderranker.precision_at_k == pytest.approx(2 / 3)
    assert pooled.binderranker.recall_at_k.value == 1.0
    assert pooled.binderranker.enrichment_factor_at_k.value == 4.0
    assert pooled.binderranker.successful_campaign_count == 2
    assert pooled.binderranker.success_rate_at_k == pytest.approx(2 / 3)
    assert pooled.binderranker.campaigns_without_positive_outcomes == 1
    assert pooled.baseline.hits_at_k == 0
    assert pooled.baseline.precision_at_k == 0.0
    assert pooled.baseline.recall_at_k.value == 0.0
    assert pooled.baseline.enrichment_factor_at_k.value == 0.0
    assert pooled.hits_delta == 2
    assert pooled.recall_delta.value == 1.0
    assert pooled.enrichment_factor_delta.value == 4.0
    assert pooled.successful_campaign_delta == 2


def test_report_does_not_claim_generalization_or_causality(
    benchmark_bundle,
) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)

    assert report.claim_scope == "DESCRIPTIVE_RETROSPECTIVE_ONLY"
    assert report.generalization_established is False
    assert report.causality_established is False


def test_metrics_are_deterministic(benchmark_bundle) -> None:
    first = evaluate_fixed_budget_metrics(benchmark_bundle)
    second = evaluate_fixed_budget_metrics(benchmark_bundle)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_report_rejects_internally_inconsistent_scope(benchmark_bundle) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)
    payload = report.model_dump(mode="json")
    payload["evaluation_candidate_count"] += 1

    with pytest.raises(ValidationError, match="outcome counts"):
        type(report).model_validate(payload)


def test_changed_dataset_is_rejected_after_validation(tmp_path: Path) -> None:
    manifest_path, dataset_path = write_bundle(tmp_path)
    bundle = validate_benchmark_bundle(manifest_path)
    with dataset_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(
        BenchmarkEvaluationError,
        match="no longer passes the sealed input contract",
    ):
        evaluate_fixed_budget_metrics(bundle)


def test_forged_validated_summary_is_rejected(benchmark_bundle) -> None:
    forged = benchmark_bundle.model_copy(
        update={
            "summary": benchmark_bundle.summary.model_copy(
                update={"dataset_sha256": "0" * 64}
            )
        }
    )

    with pytest.raises(
        BenchmarkEvaluationError,
        match="does not match its current sealed files",
    ):
        evaluate_fixed_budget_metrics(forged)


def test_metrics_require_validated_bundle() -> None:
    with pytest.raises(
        BenchmarkEvaluationError,
        match="require a ValidatedBenchmarkBundle",
    ):
        evaluate_fixed_budget_metrics(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "AVAILABLE", "value": None},
        {
            "status": "AVAILABLE",
            "value": 0.0,
            "reason": "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN",
        },
        {"status": "UNAVAILABLE"},
        {
            "status": "UNAVAILABLE",
            "value": 0.0,
            "reason": "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN",
        },
        {"status": "AVAILABLE", "value": float("nan")},
        {"status": "AVAILABLE", "value": float("inf")},
    ],
)
def test_metric_value_rejects_inconsistent_or_non_finite_states(payload) -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(payload)


def test_metric_models_are_immutable(benchmark_bundle) -> None:
    report = evaluate_fixed_budget_metrics(benchmark_bundle)

    with pytest.raises(ValidationError):
        report.claim_scope = "EXPANSIVE"  # type: ignore[misc]
