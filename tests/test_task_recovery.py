import json
from pathlib import Path

import pytest

from protein_design_agent.agent.task_recovery import (
    TaskRecoveryError,
    archive_task,
    reset_task,
)


def make_workspace(
    tmp_path: Path,
) -> tuple[Path, Path]:
    workspace = tmp_path / ".protein-design-agent"
    runs = workspace / "runs"
    runs.mkdir(parents=True)

    (
        workspace / ".pda-workspace.json"
    ).write_text(
        json.dumps({
            "schema_version": "0.1",
            "workspace_type": "protein-design-agent",
        }),
        encoding="utf-8",
    )

    bundle = runs / "default"
    bundle.mkdir()

    return workspace, bundle


def test_reset_empty_task_keeps_clean_bundle(
    tmp_path: Path,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    result = reset_task(bundle)

    assert result.bundle_dir == bundle.resolve()
    assert result.previous_state == "EMPTY"
    assert result.status == "RESET"
    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []


def test_reset_incomplete_task_removes_only_bundle(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    failure_audit = (
        workspace
        / ".pda-failures"
        / "default"
        / "prepare-test"
    )
    failure_audit.mkdir(parents=True)

    evidence = (
        failure_audit / "failure_manifest.json"
    )
    evidence.write_text(
        '{"status":"FAILED"}',
        encoding="utf-8",
    )

    result = reset_task(bundle)

    assert result.previous_state == "INCOMPLETE"
    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []

    # Bundle 外部的失败审计必须保留。
    assert evidence.is_file()


def test_reset_protected_task_is_rejected(
    tmp_path: Path,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "approval.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        TaskRecoveryError,
        match="包含受保护证据",
    ):
        reset_task(bundle)

    assert (
        bundle / "approval.json"
    ).is_file()


def test_archive_protected_task_preserves_evidence(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(
        tmp_path
    )

    approval = bundle / "approval.json"
    approval.write_text(
        '{"approval_id":"apr_test"}',
        encoding="utf-8",
    )

    result = archive_task(bundle)

    assert result.status == "ARCHIVED"
    assert result.previous_state == (
        "VALID_WITH_EVIDENCE"
    )

    assert result.archive_dir.is_dir()

    archived_approval = (
        result.archive_dir / "approval.json"
    )
    assert archived_approval.read_text(
        encoding="utf-8"
    ) == '{"approval_id":"apr_test"}'

    # 原任务名重新获得干净 Bundle。
    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []

    assert (
        result.archive_dir
        == workspace
        / "archives"
        / "default"
        / result.archive_dir.name
    )


def test_archive_incomplete_task_is_allowed(
    tmp_path: Path,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        '{"status":"draft"}',
        encoding="utf-8",
    )

    result = archive_task(bundle)

    assert result.previous_state == "INCOMPLETE"
    assert (
        result.archive_dir
        / "planning_session.json"
    ).is_file()

    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []


def test_archive_empty_task_is_rejected(
    tmp_path: Path,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    with pytest.raises(
        TaskRecoveryError,
        match="空任务无需归档",
    ):
        archive_task(bundle)


def test_recovery_requires_managed_workspace(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "runs" / "default"
    bundle.mkdir(parents=True)

    with pytest.raises(TaskRecoveryError):
        reset_task(bundle)

    with pytest.raises(TaskRecoveryError):
        archive_task(bundle)
