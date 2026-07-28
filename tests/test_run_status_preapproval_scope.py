import json
from pathlib import Path

from protein_design_agent.agent.run_status import (
    inspect_run_status,
)


def write_json(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def create_prepared_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "prepared_bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    write_json(
        bundle
        / "workflow"
        / "workflow_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "analysis_scope": {
                "level": "SMOKE_TEST_ONLY",
                "pdb_count": 5,
                (
                    "workflow_allows_"
                    "formal_interpretation"
                ): False,
                "pool_labels_reliable": False,
            },
        },
    )

    return bundle


def test_preapproval_scope_comes_from_workflow_manifest(
    tmp_path: Path,
) -> None:
    bundle = create_prepared_bundle(
        tmp_path
    )

    report = inspect_run_status(
        bundle
    )

    assert report.current_stage == "PREPARED"
    assert (
        report.prepare_status
        == "READY_FOR_REVIEW"
    )
    assert (
        report.analysis_scope_level
        == "SMOKE_TEST_ONLY"
    )
    assert report.candidate_count == 5
    assert (
        report.formal_candidate_recommendation_allowed
        is False
    )
    assert (
        report.thresholds_formally_interpretable
        is False
    )


def test_approval_scope_overrides_workflow_scope(
    tmp_path: Path,
) -> None:
    bundle = create_prepared_bundle(
        tmp_path
    )

    write_json(
        bundle / "approval.json",
        {
            "status": "APPROVED",
            "project_name": "demo",
            "approval_id": "apr_test",
            "analysis_scope_level": (
                "FULL_DATASET_ANALYSIS"
            ),
        },
    )

    report = inspect_run_status(
        bundle
    )

    assert report.current_stage == "APPROVED"
    assert (
        report.analysis_scope_level
        == "FULL_DATASET_ANALYSIS"
    )
    assert any(
        "分析级别不一致" in warning
        for warning in report.warnings
    )


def test_missing_workflow_scope_remains_unknown(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "no_scope"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    report = inspect_run_status(
        bundle
    )

    assert report.current_stage == "PREPARED"
    assert report.analysis_scope_level is None
    assert report.candidate_count is None
