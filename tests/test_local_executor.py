import csv
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
    verify_approval_for_local_execution,
)
from protein_design_agent.agent.local_executor import (
    LocalExecutionError,
    execute_approved_binderranker,
)
from protein_design_agent.agent.scientific_result_validation import (
    REQUIRED_FINITE_SCORE_COLUMNS,
    REQUIRED_SCORED_COLUMNS,
)
from protein_design_agent.tools.run_binderranker import (
    expected_output_files,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def build_approved_bundle(
    tmp_path: Path,
) -> Path:
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
        "project_name: local_executor_test\n",
        encoding="utf-8",
    )
    provenance.write_text(
        '{"test": true}\n',
        encoding="utf-8",
    )
    ranker_script.write_text(
        "print('fake ranker')\n",
        encoding="utf-8",
    )

    (
        normalized / "candidate_1.pdb"
    ).write_text(
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
                    "local_executor_test"
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

    return approval


def output_prefix_from_command(
    command: list[str],
) -> Path:
    index = command.index(
        "--output_prefix"
    )

    return Path(
        command[index + 1]
    )


def fake_success_runner(
    command: list[str],
    stdout_log: Path,
    stderr_log: Path,
    working_directory: Path,
) -> int:
    stdout_log.write_text(
        "fake ranker success\n",
        encoding="utf-8",
    )
    stderr_log.write_text(
        "",
        encoding="utf-8",
    )

    output_prefix = (
        output_prefix_from_command(
            command
        )
    )

    for output in expected_output_files(output_prefix):
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if output.name.endswith("_metrics.csv"):
            output.write_text(
                "pdb_name\ncandidate_1\n",
                encoding="utf-8",
            )
        elif output.name.endswith("_scored.csv"):
            row = {
                column: ""
                for column in REQUIRED_SCORED_COLUMNS
            }
            row.update(
                {
                    column: "0.5"
                    for column in (
                        REQUIRED_FINITE_SCORE_COLUMNS
                    )
                }
            )
            row.update(
                {
                    "pdb_name": "candidate_1",
                    "filter_level": "BROAD",
                    "filter_broad_pass": "YES",
                    "filter_medium_pass": "NO",
                    "filter_strict_pass": "NO",
                    "rank_final_score_v4": "1",
                    "clash_pairs": "0",
                    "error": "",
                }
            )

            with output.open(
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=sorted(
                        REQUIRED_SCORED_COLUMNS
                    ),
                )
                writer.writeheader()
                writer.writerow(row)
        elif output.name.endswith("_ranking.xlsx"):
            output.write_bytes(b"synthetic workbook")
        else:
            output.write_text(
                "synthetic report\n",
                encoding="utf-8",
            )

    return 0


def test_execution_requires_confirmation(
    tmp_path: Path,
) -> None:
    approval = build_approved_bundle(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="confirm_execute=True",
    ):
        execute_approved_binderranker(
            approval_path=approval,
        )


def test_successful_local_execution(
    tmp_path: Path,
) -> None:
    approval = build_approved_bundle(
        tmp_path
    )

    result = execute_approved_binderranker(
        approval_path=approval,
        confirm_execute=True,
        runner=fake_success_runner,
    )

    assert result.status == "COMPLETED"
    assert result.return_code == 0
    assert result.binderranker_executed is True
    assert result.remote_backend_used is False
    assert result.approval_reusable is False

    assert len(result.output_files) == 4

    manifest = json.loads(
        result.execution_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["status"] == "COMPLETED"
    assert manifest["return_code"] == 0
    assert len(manifest["output_files"]) == 4
    assert (
        manifest["scientific_validation"]
        ["scientifically_valid"]
        is True
    )
    assert (
        manifest["scientific_validation"]
        ["valid_candidate_count"]
        == 1
    )
    assert manifest["approval_reusable"] is False

    # 同一批准不能执行第二次。
    with pytest.raises(
        ExecutionGuardError,
        match="一次性批准不能重复使用",
    ):
        verify_approval_for_local_execution(
            approval
        )


def test_nonzero_exit_is_recorded_as_failed(
    tmp_path: Path,
) -> None:
    approval = build_approved_bundle(
        tmp_path
    )

    def failing_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
        working_directory: Path,
    ) -> int:
        stdout_log.write_text(
            "",
            encoding="utf-8",
        )
        stderr_log.write_text(
            "simulated ranker failure\n",
            encoding="utf-8",
        )

        return 7

    with pytest.raises(
        LocalExecutionError,
        match="退出码=7",
    ) as captured:
        execute_approved_binderranker(
            approval_path=approval,
            confirm_execute=True,
            runner=failing_runner,
        )

    manifest = json.loads(
        captured.value.execution_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["status"] == "FAILED"
    assert manifest["return_code"] == 7
    assert manifest["approval_reusable"] is False


def test_missing_outputs_are_recorded_as_failed(
    tmp_path: Path,
) -> None:
    approval = build_approved_bundle(
        tmp_path
    )

    def no_output_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
        working_directory: Path,
    ) -> int:
        stdout_log.write_text(
            "returned zero but no outputs\n",
            encoding="utf-8",
        )
        stderr_log.write_text(
            "",
            encoding="utf-8",
        )

        return 0

    with pytest.raises(
        LocalExecutionError,
        match="未生成完整",
    ) as captured:
        execute_approved_binderranker(
            approval_path=approval,
            confirm_execute=True,
            runner=no_output_runner,
        )

    manifest = json.loads(
        captured.value.execution_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["status"] == "FAILED"
    assert manifest["return_code"] == 0
    assert len(
        manifest["missing_outputs"]
    ) == 4
    assert manifest["approval_reusable"] is False


def test_zero_valid_candidates_are_recorded_as_failed(
    tmp_path: Path,
) -> None:
    approval = build_approved_bundle(
        tmp_path
    )

    def zero_valid_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
        working_directory: Path,
    ) -> int:
        result = fake_success_runner(
            command,
            stdout_log,
            stderr_log,
            working_directory,
        )
        output_prefix = output_prefix_from_command(
            command
        )
        scored = Path(
            f"{output_prefix}_scored.csv"
        )

        with scored.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            rows = list(reader)

        rows[0]["error"] = (
            "No binder residues found for binder_chain=B"
        )

        with scored.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=headers,
            )
            writer.writeheader()
            writer.writerows(rows)

        return result

    with pytest.raises(
        LocalExecutionError,
        match="没有有效候选",
    ) as captured:
        execute_approved_binderranker(
            approval_path=approval,
            confirm_execute=True,
            runner=zero_valid_runner,
        )

    manifest = json.loads(
        captured.value.execution_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["status"] == "FAILED"
    assert manifest["return_code"] == 0
    assert (
        manifest["error_type"]
        == "ScientificResultValidationError"
    )
    assert "没有有效候选" in manifest["error_message"]
    assert manifest["approval_reusable"] is False
