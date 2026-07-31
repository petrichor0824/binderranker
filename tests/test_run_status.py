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
        json.dumps(value),
        encoding="utf-8",
    )


def test_empty_bundle() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        report = inspect_run_status(
            Path(directory)
        )

        assert report.current_stage == "EMPTY"


def test_failed_execution_stage(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    write_json(
        bundle / "approval.json",
        {
            "status": "APPROVED",
            "approval_id": "apr_demo",
            "analysis_scope_level": (
                "EXPLORATORY"
            ),
        },
    )

    write_json(
        bundle / "execution_apr_demo.json",
        {
            "status": "FAILED",
            "approval_id": "apr_demo",
        },
    )

    report = inspect_run_status(bundle)

    assert (
        report.current_stage
        == "EXECUTION_FAILED"
    )
    assert report.approval_consumed is True


def test_completed_analysis_stage(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle / "approval.json",
        {
            "status": "APPROVED",
            "approval_id": "apr_demo",
        },
    )

    write_json(
        bundle / "execution_apr_demo.json",
        {
            "status": "COMPLETED",
            "approval_id": "apr_demo",
        },
    )

    write_json(
        bundle
        / "analyses"
        / "v1"
        / "analyze_run_manifest.json",
        {
            "status": "COMPLETED",
            "with_model": False,
            "provider_name": None,
        },
    )

    report = inspect_run_status(bundle)

    assert report.current_stage == "ANALYZED"
    assert report.analysis_status == "COMPLETED"


def test_explained_stage(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    write_json(
        bundle / "approval.json",
        {
            "status": "APPROVED",
            "approval_id": "apr_demo",
            "analysis_scope_level": (
                "SMOKE_TEST_ONLY"
            ),
        },
    )

    write_json(
        bundle / "execution_apr_demo.json",
        {
            "status": "COMPLETED",
            "approval_id": "apr_demo",
        },
    )

    analysis = (
        bundle / "analyses" / "v2"
    )

    write_json(
        analysis
        / "analyze_run_manifest.json",
        {
            "status": "COMPLETED",
            "with_model": True,
            "provider_name": "deepseek_flash",
        },
    )

    write_json(
        analysis
        / "explanation"
        / "agent_explanation.json",
        {
            "status": "EXPLAINED",
            "provider_name": "deepseek_flash",
        },
    )

    write_json(
        analysis
        / "agent_result_summary.json",
        {
            "status": "PARSED",
            "candidate_count": 5,
            "formal_candidate_"
            "recommendation_allowed": False,
            "thresholds_formally_"
            "interpretable": False,
        },
    )

    report = inspect_run_status(bundle)

    assert report.current_stage == "EXPLAINED"
    assert (
        report.explanation_status
        == "EXPLAINED"
    )
    assert report.candidate_count == 5
    assert (
        report
        .formal_candidate_recommendation_allowed
        is False
    )
    assert (
        report.thresholds_formally_interpretable
        is False
    )
    assert len(report.analysis_attempts) == 1


def test_unavailable_explanation_keeps_analyzed_stage(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle / "execution_apr_demo.json",
        {
            "status": "COMPLETED",
            "approval_id": "apr_demo",
        },
    )

    write_json(
        bundle
        / "analyses"
        / "model_failed"
        / "analyze_run_manifest.json",
        {
            "status": "COMPLETED",
            "with_model": True,
            "provider_name": None,
            "explanation_status": "UNAVAILABLE",
            "explanation_error_type": "TimeoutError",
            "explanation_error_message": (
                "model request timed out"
            ),
        },
    )

    report = inspect_run_status(bundle)

    assert report.current_stage == "ANALYZED"
    assert report.analysis_status == "COMPLETED"
    assert (
        report.explanation_status
        == "UNAVAILABLE"
    )
    assert len(report.analysis_attempts) == 1
    assert (
        report.analysis_attempts[0]
        .explanation_status
        == "UNAVAILABLE"
    )
