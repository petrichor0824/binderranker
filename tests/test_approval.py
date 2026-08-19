import hashlib
import json
from pathlib import Path

import pytest

from protein_design_agent.agent.approval import (
    ApprovalError,
    create_approval_record,
    resolve_recorded_path,
    snapshot_pdb_dataset,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def build_fake_ready_bundle(
    tmp_path: Path,
    *,
    analysis_level: str = (
        "FULL_DATASET_ANALYSIS"
    ),
    prepare_status: str = (
        "READY_FOR_REVIEW"
    ),
) -> tuple[Path, Path, Path]:
    bundle = tmp_path / "bundle"
    workflow = bundle / "workflow"
    ranker_dir = workflow / "ranker"
    normalized = workflow / "normalized_pdbs"

    ranker_dir.mkdir(
        parents=True
    )
    normalized.mkdir(
        parents=True
    )

    session = bundle / "planning_session.json"
    project = bundle / "project.yaml"
    provenance = (
        bundle / "project.provenance.json"
    )
    workflow_manifest = (
        workflow / "workflow_manifest.json"
    )
    ranker_plan = (
        ranker_dir
        / "ranker_execution_plan.json"
    )
    ranker_script = (
        bundle / "frozen_ranker.py"
    )
    prepare_manifest = (
        bundle
        / "agent_prepare_manifest.json"
    )

    session.write_text(
        '{"test": true}\n',
        encoding="utf-8",
    )
    project.write_text(
        "project_name: approval_test\n",
        encoding="utf-8",
    )
    provenance.write_text(
        '{"test": true}\n',
        encoding="utf-8",
    )
    ranker_script.write_text(
        "print('frozen ranker')\n",
        encoding="utf-8",
    )

    pdb = normalized / "candidate_1.pdb"
    pdb.write_text(
        (
            "ATOM      1  CA  ALA A   1"
            "       0.000   0.000   0.000"
            "  1.00 20.00           C\n"
            "END\n"
        ),
        encoding="utf-8",
    )

    workflow_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
                "analysis_scope": {
                    "level": analysis_level,
                },
            }
        ),
        encoding="utf-8",
    )

    ranker_plan.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "ranker_path": str(
                    ranker_script.resolve()
                ),
                "ranker_sha256": (
                    sha256_file(ranker_script)
                ),
                "input_directory": str(
                    normalized.resolve()
                ),
                "execute_requested": False,
                "analysis_scope": {
                    "level": analysis_level,
                },
            }
        ),
        encoding="utf-8",
    )

    prepare_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": prepare_status,
                "project_name": "approval_test",
                "provider_name": "mock",
                "session_copy": str(
                    session.resolve()
                ),
                "project_config": str(
                    project.resolve()
                ),
                "project_provenance": str(
                    provenance.resolve()
                ),
                "workflow_manifest": str(
                    workflow_manifest.resolve()
                ),
                "ranker_plan": str(
                    ranker_plan.resolve()
                ),
                "binderranker_executed": False,
                "remote_backend_used": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return (
        prepare_manifest,
        normalized,
        ranker_script,
    )


def test_ready_run_can_be_approved(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    output = tmp_path / "approval.json"

    record = create_approval_record(
        prepare_manifest_path=(
            prepare_manifest
        ),
        output_path=output,
        approved_by="test_operator",
        approval_note="unit test approval",
    )

    assert record.status == "APPROVED"
    assert record.approval_id.startswith(
        "apr_"
    )
    assert len(record.approval_digest) == 64
    assert record.normalized_dataset.pdb_count == 1
    assert record.binderranker_executed_at_approval is False
    assert output.exists()


def test_smoke_test_requires_explicit_acknowledgement(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(
            tmp_path,
            analysis_level="SMOKE_TEST_ONLY",
        )
    )

    with pytest.raises(
        ValueError,
        match="必须显式确认",
    ):
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=(
                tmp_path / "blocked.json"
            ),
            approved_by="test_operator",
        )

    record = create_approval_record(
        prepare_manifest_path=(
            prepare_manifest
        ),
        output_path=(
            tmp_path / "approved.json"
        ),
        approved_by="test_operator",
        acknowledge_smoke_test=True,
    )

    assert (
        record.smoke_test_acknowledged
        is True
    )


def test_non_ready_run_cannot_be_approved(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(
            tmp_path,
            prepare_status="FAILED",
        )
    )

    with pytest.raises(
        ValueError,
        match="只有 READY_FOR_REVIEW",
    ):
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=(
                tmp_path / "approval.json"
            ),
            approved_by="test_operator",
        )


def test_existing_approval_is_protected(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    output = tmp_path / "approval.json"
    output.write_text(
        "important existing approval\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=output,
            approved_by="test_operator",
        )

    assert output.read_text(
        encoding="utf-8"
    ) == "important existing approval\n"


def test_dataset_snapshot_changes_after_pdb_change(
    tmp_path: Path,
) -> None:
    _, normalized, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    before = snapshot_pdb_dataset(
        normalized
    )

    pdb = normalized / "candidate_1.pdb"
    pdb.write_text(
        pdb.read_text(encoding="utf-8")
        + "REMARK changed after approval\n",
        encoding="utf-8",
    )

    after = snapshot_pdb_dataset(
        normalized
    )

    assert (
        before.combined_sha256
        != after.combined_sha256
    )


def test_workflow_state_rejection_has_public_message(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    prepare_payload = json.loads(
        prepare_manifest.read_text(
            encoding="utf-8"
        )
    )

    workflow_manifest = Path(
        prepare_payload["workflow_manifest"]
    )
    if not workflow_manifest.is_absolute():
        workflow_manifest = (
            prepare_manifest.parent
            / workflow_manifest
        )

    workflow_payload = json.loads(
        workflow_manifest.read_text(
            encoding="utf-8"
        )
    )
    workflow_payload["status"] = "FAILED"

    workflow_manifest.write_text(
        json.dumps(workflow_payload),
        encoding="utf-8",
    )

    with pytest.raises(
        ApprovalError
    ) as exc_info:
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=(
                tmp_path / "approval.json"
            ),
            approved_by="test_operator",
        )

    assert (
        "当前状态为 FAILED"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "工作流不处于 READY_FOR_REVIEW，"
            "不能批准。"
        )
    )


def test_requested_ranker_execution_rejection_has_public_message(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    prepare_payload = json.loads(
        prepare_manifest.read_text(
            encoding="utf-8"
        )
    )

    ranker_plan = Path(
        prepare_payload["ranker_plan"]
    )
    if not ranker_plan.is_absolute():
        ranker_plan = (
            prepare_manifest.parent
            / ranker_plan
        )

    ranker_payload = json.loads(
        ranker_plan.read_text(
            encoding="utf-8"
        )
    )
    ranker_payload["execute_requested"] = True

    ranker_plan.write_text(
        json.dumps(ranker_payload),
        encoding="utf-8",
    )

    with pytest.raises(
        ApprovalError
    ) as exc_info:
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=(
                tmp_path / "approval.json"
            ),
            approved_by="test_operator",
        )

    assert (
        "请求执行"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "Ranker 计划已进入执行请求状态，"
            "不符合审核前批准条件。"
        )
    )


def test_changed_ranker_has_safe_public_message(
    tmp_path: Path,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    prepare_payload = json.loads(
        prepare_manifest.read_text(
            encoding="utf-8"
        )
    )

    ranker_plan = Path(
        prepare_payload["ranker_plan"]
    )
    if not ranker_plan.is_absolute():
        ranker_plan = (
            prepare_manifest.parent
            / ranker_plan
        )

    ranker_payload = json.loads(
        ranker_plan.read_text(
            encoding="utf-8"
        )
    )

    ranker_path = Path(
        ranker_payload["ranker_path"]
    )

    ranker_path.write_text(
        "print('modified ranker')\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ApprovalError
    ) as exc_info:
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=(
                tmp_path / "approval.json"
            ),
            approved_by="test_operator",
        )

    assert (
        "计划记录："
        in str(exc_info.value)
    )
    assert (
        "当前文件："
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "冻结 BinderRanker 已发生变化，"
            "因此拒绝批准。"
        )
    )


def test_approval_write_failure_cleans_partial_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_manifest, _, _ = (
        build_fake_ready_bundle(tmp_path)
    )

    output = tmp_path / "approval.json"

    real_write_text = Path.write_text

    def fail_output_write(
        self: Path,
        data: str,
        *args,
        **kwargs,
    ):
        if self == output:
            real_write_text(
                self,
                "partial unreliable approval\n",
                encoding="utf-8",
            )
            raise OSError(
                "PRIVATE_APPROVAL_WRITE_DETAIL"
            )

        return real_write_text(
            self,
            data,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "write_text",
        fail_output_write,
    )

    with pytest.raises(
        ApprovalError
    ) as exc_info:
        create_approval_record(
            prepare_manifest_path=(
                prepare_manifest
            ),
            output_path=output,
            approved_by="test_operator",
        )

    assert not output.exists()

    assert (
        "PRIVATE_APPROVAL_WRITE_DETAIL"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "批准记录写入失败；"
            "已清理可能产生的不可靠输出。"
        )
    )


@pytest.mark.skipif(
    __import__("os").name == "nt",
    reason="POSIX-specific cross-platform regression",
)
def test_recorded_windows_absolute_path_is_rejected_on_posix(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="Windows 风格绝对路径",
    ):
        resolve_recorded_path(
            r"C:\Users\Alice\data\pdbs",
            base_directory=tmp_path,
            field_name="input_directory",
        )


def test_recorded_relative_path_uses_manifest_directory(
    tmp_path: Path,
) -> None:
    result = resolve_recorded_path(
        "workflow/normalized_pdbs",
        base_directory=tmp_path,
        field_name="input_directory",
    )

    assert result == (
        tmp_path
        / "workflow"
        / "normalized_pdbs"
    ).resolve()
