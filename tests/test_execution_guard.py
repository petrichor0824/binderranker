import hashlib
import json
import sys
from pathlib import Path

import pytest

from protein_design_agent.agent.approval import (
    create_approval_record,
)
from protein_design_agent.agent.execution_guard import (
    ExecutionGuardError,
    default_execution_manifest_path,
    verify_approval_for_local_execution,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def build_approved_bundle(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    Path,
    Path,
]:
    bundle = tmp_path / "bundle"
    workflow = bundle / "workflow"
    ranker_dir = workflow / "ranker"
    normalized = (
        workflow / "normalized_pdbs"
    )

    ranker_dir.mkdir(
        parents=True
    )
    normalized.mkdir(
        parents=True
    )

    session = (
        bundle / "planning_session.json"
    )
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
    approval = bundle / "approval.json"

    session.write_text(
        '{"test": true}\n',
        encoding="utf-8",
    )
    project.write_text(
        "project_name: execution_guard_test\n",
        encoding="utf-8",
    )
    provenance.write_text(
        '{"test": true}\n',
        encoding="utf-8",
    )
    ranker_script.write_text(
        "print('ranker')\n",
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

    output_prefix = (
        ranker_dir / "backbone_rank"
    )

    workflow_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
                "analysis_scope": {
                    "level": (
                        "FULL_DATASET_ANALYSIS"
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    command = [
        sys.executable,
        str(ranker_script.resolve()),
        "--input_dir",
        str(normalized.resolve()),
        "--output_prefix",
        str(output_prefix.resolve()),
        "--binder_chain",
        "B",
        "--undesired_regions",
        "",
    ]

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
                "output_prefix": str(
                    output_prefix.resolve()
                ),
                "command": command,
                "execute_requested": False,
                "analysis_scope": {
                    "level": (
                        "FULL_DATASET_ANALYSIS"
                    )
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    prepare_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
                "project_name": (
                    "execution_guard_test"
                ),
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

    create_approval_record(
        prepare_manifest_path=(
            prepare_manifest
        ),
        output_path=approval,
        approved_by="test_operator",
    )

    return (
        approval,
        project,
        pdb,
        output_prefix,
    )


def test_valid_approval_passes_guard(
    tmp_path: Path,
) -> None:
    approval, _, _, _ = (
        build_approved_bundle(tmp_path)
    )

    verified = (
        verify_approval_for_local_execution(
            approval
        )
    )

    assert verified.status == (
        "VERIFIED_FOR_LOCAL_EXECUTION"
    )
    assert verified.binderranker_executed is False
    assert verified.remote_backend_used is False
    assert len(verified.command) >= 2
    assert len(verified.expected_outputs) == 4


def test_tampered_approval_is_rejected(
    tmp_path: Path,
) -> None:
    approval, _, _, _ = (
        build_approved_bundle(tmp_path)
    )

    data = json.loads(
        approval.read_text(encoding="utf-8")
    )
    data["approved_by"] = "tampered_user"

    approval.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(
        ExecutionGuardError,
        match="批准记录摘要不匹配",
    ):
        verify_approval_for_local_execution(
            approval
        )


def test_changed_critical_file_is_rejected(
    tmp_path: Path,
) -> None:
    approval, project, _, _ = (
        build_approved_bundle(tmp_path)
    )

    project.write_text(
        "project_name: changed_after_approval\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ExecutionGuardError,
        match="关键文件发生变化",
    ):
        verify_approval_for_local_execution(
            approval
        )


def test_changed_pdb_dataset_is_rejected(
    tmp_path: Path,
) -> None:
    approval, _, pdb, _ = (
        build_approved_bundle(tmp_path)
    )

    pdb.write_text(
        pdb.read_text(encoding="utf-8")
        + "REMARK changed\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ExecutionGuardError,
        match="PDB 数据集发生变化",
    ):
        verify_approval_for_local_execution(
            approval
        )


def test_existing_execution_manifest_blocks_reuse(
    tmp_path: Path,
) -> None:
    approval, _, _, _ = (
        build_approved_bundle(tmp_path)
    )

    verified = (
        verify_approval_for_local_execution(
            approval
        )
    )

    execution_manifest = (
        default_execution_manifest_path(
            approval,
            verified.approval_id,
        )
    )

    execution_manifest.write_text(
        '{"status": "COMPLETED"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ExecutionGuardError,
        match="一次性批准不能重复使用",
    ):
        verify_approval_for_local_execution(
            approval
        )


def test_existing_ranker_output_is_rejected(
    tmp_path: Path,
) -> None:
    approval, _, _, output_prefix = (
        build_approved_bundle(tmp_path)
    )

    existing_output = Path(
        str(output_prefix)
        + "_scored.csv"
    )

    existing_output.write_text(
        "old results\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ExecutionGuardError,
        match="已有 Ranker 结果",
    ):
        verify_approval_for_local_execution(
            approval
        )
