import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from protein_design_agent.scientific_validation import (
    BenchmarkReadinessError,
    StructuralReadinessState,
    validate_benchmark_bundle,
    validate_benchmark_readiness,
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
    positive_rank: int,
    identical_rankings: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for rank in range(1, 5):
        baseline_rank = rank
        if not identical_rankings:
            baseline_rank = 4 if rank == 1 else rank - 1
        rows.append(
            {
                "campaign_id": campaign_id,
                "target_id": target_id,
                "candidate_id": f"{campaign_id}_{rank}",
                "split": split,
                "binderranker_rank": rank,
                "binderranker_score": 1.0 - rank / 10,
                "baseline_rank": baseline_rank,
                "outcome": int(rank == positive_rank),
            }
        )
    return rows


def _benchmark_rows(
    *,
    single_evaluation_target: bool = False,
    identical_rankings: bool = False,
) -> list[dict[str, Any]]:
    rows = _campaign_rows(
        campaign_id="campaign_cal",
        target_id="target_cal",
        split="CALIBRATION",
        positive_rank=1,
        identical_rankings=identical_rankings,
    )
    rows.extend(
        _campaign_rows(
            campaign_id="campaign_eval_a",
            target_id="target_a",
            split="EVALUATION",
            positive_rank=1,
            identical_rankings=identical_rankings,
        )
    )
    if not single_evaluation_target:
        rows.extend(
            _campaign_rows(
                campaign_id="campaign_eval_b",
                target_id="target_b",
                split="EVALUATION",
                positive_rank=4,
                identical_rankings=identical_rankings,
            )
        )
    return rows


def _write_bundle(
    tmp_path: Path,
    *,
    single_evaluation_target: bool = False,
    identical_rankings: bool = False,
    evidence_type: str = "COMPUTATIONAL_PROXY",
):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    dataset_path = bundle_dir / "candidates.csv"
    with dataset_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            _benchmark_rows(
                single_evaluation_target=single_evaluation_target,
                identical_rankings=identical_rankings,
            )
        )

    manifest = {
        "schema_version": "0.1",
        "benchmark_id": "readiness_fixture",
        "description": "Synthetic benchmark readiness fixture.",
        "dataset": {
            "file": dataset_path.name,
            "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        },
        "outcome": {
            "name": "downstream_success",
            "description": "Binary fixture outcome.",
            "evidence_type": evidence_type,
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
    return validate_benchmark_bundle(manifest_path), dataset_path


def _checklist_payload(
    bundle,
    *,
    data_kind: str = "SYNTHETIC_FIXTURE",
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "benchmark_id": bundle.summary.benchmark_id,
        "manifest_sha256": bundle.summary.manifest_sha256,
        "dataset_sha256": bundle.summary.dataset_sha256,
        "data_kind": data_kind,
        "data_freeze": {
            "frozen_at": "2026-08-01T09:00:00+08:00",
            "source_system": "Immutable campaign registry export.",
            "extraction_procedure": "Predeclared query with no row edits.",
            "immutable_record_id": "registry-export-2026-08-01",
        },
        "cohort": {
            "inclusion_criteria": "All candidates in declared campaigns.",
            "exclusion_criteria": "No post-ranking exclusions.",
            "candidate_universe_complete": True,
            "missing_outcome_policy": "Missing outcomes remain unavailable.",
        },
        "review": {
            "outcome_definition_reviewed": True,
            "baseline_procedure_reviewed": True,
            "leakage_reviewed": True,
            "analysis_plan_id": "analysis-plan-v1",
            "reviewer_role": "Independent scientific reviewer",
            "review_record_id": "review-record-001",
            "reviewed_at": "2026-08-02T09:00:00+08:00",
        },
        "evidence_limitations": [
            "Retrospective association does not establish causality.",
        ],
    }


def _write_checklist(
    tmp_path: Path,
    bundle,
    *,
    payload: dict[str, Any] | None = None,
    data_kind: str = "SYNTHETIC_FIXTURE",
) -> Path:
    path = tmp_path / "readiness.yaml"
    path.write_text(
        yaml.safe_dump(
            payload or _checklist_payload(bundle, data_kind=data_kind),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_synthetic_fixture_is_structurally_ready_but_not_evidence(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path)
    checklist_path = _write_checklist(tmp_path, bundle)

    report = validate_benchmark_readiness(bundle, checklist_path)

    assert report.schema_version == "0.1"
    assert report.engineering_readiness_status == "READY"
    assert report.scientific_review_status == "FIXTURE_ONLY"
    assert report.claim_scope == "READINESS_METADATA_ONLY"
    assert report.declarations_structurally_valid is True
    assert report.declaration_truth_independently_verified is False
    assert report.formal_inference_established is False
    assert report.performance_benefit_established is False
    assert report.evaluation_target_count == 2
    assert report.evaluation_campaign_count == 2
    assert report.evaluation_candidate_count == 8
    assert report.evaluation_positive_count == 2
    assert report.evaluation_negative_count == 6
    assert report.targets_with_both_outcome_classes == 2
    assert report.campaigns_with_both_outcome_classes == 2
    assert report.minimum_campaigns_per_target == 1
    assert report.maximum_campaigns_per_target == 1
    assert report.minimum_candidates_per_campaign == 4
    assert report.maximum_candidates_per_campaign == 4
    assert report.target_removal_sensitivity.status == "AVAILABLE"
    assert (
        report.positive_denominator_target_sensitivity.status == "AVAILABLE"
    )
    assert "SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE" in report.warnings
    assert "COMPUTATIONAL_PROXY_NOT_EXPERIMENTAL_EVIDENCE" in report.warnings
    assert "FORMAL_INFERENCE_NOT_ESTABLISHED" in report.warnings
    assert report.checklist_sha256 == hashlib.sha256(
        checklist_path.read_bytes()
    ).hexdigest()


def test_declared_real_data_is_only_ready_for_scientific_review(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path, evidence_type="EXPERIMENTAL")
    checklist_path = _write_checklist(
        tmp_path,
        bundle,
        data_kind="REAL_RETROSPECTIVE",
    )

    report = validate_benchmark_readiness(bundle, checklist_path)

    assert report.scientific_review_status == "READY_FOR_SCIENTIFIC_REVIEW"
    assert report.declaration_truth_independently_verified is False
    assert report.performance_benefit_established is False
    assert "SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE" not in report.warnings
    assert "DECLARATIONS_NOT_INDEPENDENTLY_VERIFIED" in report.warnings


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("benchmark_id", "another_benchmark"),
        ("manifest_sha256", "0" * 64),
        ("dataset_sha256", "f" * 64),
    ],
)
def test_checklist_must_bind_to_exact_sealed_bundle(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    bundle, _ = _write_bundle(tmp_path)
    payload = _checklist_payload(bundle)
    payload[field] = replacement
    checklist_path = _write_checklist(tmp_path, bundle, payload=payload)

    with pytest.raises(
        BenchmarkReadinessError,
        match="does not match the current sealed bundle",
    ):
        validate_benchmark_readiness(bundle, checklist_path)


@pytest.mark.parametrize(
    "field_path",
    [
        ("cohort", "candidate_universe_complete"),
        ("review", "outcome_definition_reviewed"),
        ("review", "baseline_procedure_reviewed"),
        ("review", "leakage_reviewed"),
    ],
)
def test_required_declarations_cannot_be_false(
    tmp_path: Path,
    field_path: tuple[str, str],
) -> None:
    bundle, _ = _write_bundle(tmp_path)
    payload = _checklist_payload(bundle)
    payload[field_path[0]][field_path[1]] = False
    checklist_path = _write_checklist(tmp_path, bundle, payload=payload)

    with pytest.raises(BenchmarkReadinessError, match="不符合 schema"):
        validate_benchmark_readiness(bundle, checklist_path)


def test_review_cannot_predate_frozen_dataset(tmp_path: Path) -> None:
    bundle, _ = _write_bundle(tmp_path)
    payload = _checklist_payload(bundle)
    payload["review"]["reviewed_at"] = "2026-07-31T09:00:00+08:00"
    checklist_path = _write_checklist(tmp_path, bundle, payload=payload)

    with pytest.raises(BenchmarkReadinessError, match="cannot precede"):
        validate_benchmark_readiness(bundle, checklist_path)


def test_timestamps_must_be_timezone_aware(tmp_path: Path) -> None:
    bundle, _ = _write_bundle(tmp_path)
    payload = _checklist_payload(bundle)
    payload["data_freeze"]["frozen_at"] = "2026-08-01T09:00:00"
    checklist_path = _write_checklist(tmp_path, bundle, payload=payload)

    with pytest.raises(BenchmarkReadinessError, match="不符合 schema"):
        validate_benchmark_readiness(bundle, checklist_path)


def test_changed_sealed_bundle_is_rejected_before_readiness(
    tmp_path: Path,
) -> None:
    bundle, dataset_path = _write_bundle(tmp_path)
    checklist_path = _write_checklist(tmp_path, bundle)
    with dataset_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(
        BenchmarkReadinessError,
        match="current validated benchmark bundle",
    ):
        validate_benchmark_readiness(bundle, checklist_path)


def test_single_target_reports_structural_limits_without_size_threshold(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path, single_evaluation_target=True)
    checklist_path = _write_checklist(tmp_path, bundle)

    report = validate_benchmark_readiness(bundle, checklist_path)

    assert report.target_removal_sensitivity.status == "UNAVAILABLE"
    assert (
        report.target_removal_sensitivity.reason
        == "SINGLE_EVALUATION_TARGET"
    )
    assert report.positive_denominator_target_sensitivity.status == "UNAVAILABLE"
    assert "SINGLE_EVALUATION_TARGET" in report.warnings
    assert "FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS" in report.warnings


def test_identical_rankings_are_reported_as_a_review_warning(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path, identical_rankings=True)
    checklist_path = _write_checklist(tmp_path, bundle)

    report = validate_benchmark_readiness(bundle, checklist_path)

    assert "IDENTICAL_RANKINGS_ALL_CAMPAIGNS" in report.warnings


def test_readiness_report_is_deterministic_and_immutable(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path)
    checklist_path = _write_checklist(tmp_path, bundle)

    first = validate_benchmark_readiness(bundle, checklist_path)
    second = validate_benchmark_readiness(bundle, checklist_path)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    with pytest.raises(ValidationError):
        first.claim_scope = "PERFORMANCE"  # type: ignore[misc]


def test_report_rejects_warnings_that_disagree_with_facts(
    tmp_path: Path,
) -> None:
    bundle, _ = _write_bundle(tmp_path)
    checklist_path = _write_checklist(tmp_path, bundle)
    report = validate_benchmark_readiness(bundle, checklist_path)
    payload = report.model_dump(mode="json")
    payload["warnings"].remove("SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE")

    with pytest.raises(ValidationError, match="warnings disagree"):
        type(report).model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "AVAILABLE", "reason": "SINGLE_EVALUATION_TARGET"},
        {"status": "UNAVAILABLE"},
    ],
)
def test_structural_readiness_state_rejects_invalid_states(payload) -> None:
    with pytest.raises(ValidationError):
        StructuralReadinessState.model_validate(payload)
