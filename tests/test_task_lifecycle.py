import json
from pathlib import Path

from protein_design_agent.agent.task_lifecycle import (
    TaskLifecycleState,
    inspect_task_lifecycle,
)


def test_missing_bundle_is_empty(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "missing"

    report = inspect_task_lifecycle(bundle)

    assert report.state == TaskLifecycleState.EMPTY
    assert report.has_protected_evidence is False


def test_empty_directory_is_empty(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty"
    bundle.mkdir()

    report = inspect_task_lifecycle(bundle)

    assert report.state == TaskLifecycleState.EMPTY
    assert report.has_protected_evidence is False


def test_planning_only_bundle_is_incomplete(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "planning"
    bundle.mkdir()

    (
        bundle / "planning_session.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.INCOMPLETE
    )
    assert report.has_protected_evidence is False


def test_needs_information_bundle_is_incomplete(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "needs_information"
    bundle.mkdir()

    (
        bundle / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps({
            "status": "NEEDS_INFORMATION",
        }),
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.INCOMPLETE
    )
    assert report.has_protected_evidence is False


def test_legacy_failed_bundle_is_incomplete(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "failed"
    bundle.mkdir()

    (
        bundle / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps({
            "status": "FAILED",
        }),
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.INCOMPLETE
    )
    assert report.has_protected_evidence is False


def test_ready_for_review_bundle_is_protected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "ready"
    bundle.mkdir()

    (
        bundle / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps({
            "status": "READY_FOR_REVIEW",
        }),
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True


def test_approval_is_protected_evidence(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "approved"
    bundle.mkdir()

    (
        bundle / "approval.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True


def test_execution_manifest_is_protected_evidence(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "executed"
    bundle.mkdir()

    (
        bundle / "execution_apr_test.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True


def test_ranker_result_is_protected_evidence(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "ranked"

    ranker = (
        bundle
        / "workflow"
        / "ranker"
    )
    ranker.mkdir(parents=True)

    (
        ranker
        / "backbone_rank_scored.csv"
    ).write_text(
        "candidate,score\n",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True


def test_analysis_directory_is_protected_evidence(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "analyzed"
    analyses = bundle / "analyses"
    analyses.mkdir(parents=True)

    (
        analyses / "analysis.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True


def test_unknown_nonempty_file_is_protected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "unknown"
    bundle.mkdir()

    (
        bundle / "important-user-file.txt"
    ).write_text(
        "do not delete",
        encoding="utf-8",
    )

    report = inspect_task_lifecycle(bundle)

    assert report.state == (
        TaskLifecycleState.VALID_WITH_EVIDENCE
    )
    assert report.has_protected_evidence is True
