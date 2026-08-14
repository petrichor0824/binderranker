from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import protein_design_agent.cli as cli_module

from protein_design_agent.agent.approval import (
    ApprovalError,
)


runner = CliRunner()


def test_approve_run_command_is_available() -> None:
    from typer.main import get_command

    root_command = get_command(
        cli_module.app
    )

    assert "approve-run" in (
        root_command.commands
    )

    approve_command = (
        root_command.commands["approve-run"]
    )

    option_names = {
        option
        for parameter in approve_command.params
        for option in getattr(
            parameter,
            "opts",
            (),
        )
    }

    required_options = {
        "--prepare-manifest",
        "--approved-by",
    }

    assert required_options.issubset(
        option_names
    )


def test_approve_run_command_reports_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_manifest = (
        tmp_path / "agent_prepare_manifest.json"
    )
    prepare_manifest.write_text(
        "{}",
        encoding="utf-8",
    )

    output = tmp_path / "approval.json"

    fake_dataset = SimpleNamespace(
        pdb_count=5,
        combined_sha256="a" * 64,
    )

    fake_record = SimpleNamespace(
        status="APPROVED",
        approval_id="apr_test1234567890",
        approval_scope="execute_binderranker_once",
        approved_by="test_operator",
        project_name="test_project",
        provider_name="mock",
        analysis_scope_level="SMOKE_TEST_ONLY",
        smoke_test_acknowledged=True,
        normalized_dataset=fake_dataset,
        ranker_sha256="b" * 64,
        approval_digest="c" * 64,
    )

    def fake_create_approval_record(
        *,
        prepare_manifest_path: Path,
        output_path: Path,
        approved_by: str,
        approval_note: str,
        acknowledge_smoke_test: bool,
    ):
        assert (
            prepare_manifest_path
            == prepare_manifest.resolve()
        )
        assert output_path == output
        assert approved_by == "test_operator"
        assert approval_note == "test approval"
        assert acknowledge_smoke_test is True

        output_path.write_text(
            "{}",
            encoding="utf-8",
        )

        return fake_record

    monkeypatch.setattr(
        cli_module,
        "create_approval_record",
        fake_create_approval_record,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "approve-run",
            "--prepare-manifest",
            str(prepare_manifest),
            "--output",
            str(output),
            "--approved-by",
            "test_operator",
            "--approval-note",
            "test approval",
            "--acknowledge-smoke-test",
        ],
    )

    assert result.exit_code == 0
    assert "状态：APPROVED" in result.output
    assert "标准化 PDB 数量：5" in result.output
    assert "没有执行 BinderRanker" in result.output


def test_approve_run_command_reports_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_manifest = (
        tmp_path / "agent_prepare_manifest.json"
    )
    prepare_manifest.write_text(
        "{}",
        encoding="utf-8",
    )

    def failing_create_approval_record(**kwargs):
        raise ValueError(
            "simulated approval failure"
        )

    monkeypatch.setattr(
        cli_module,
        "create_approval_record",
        failing_create_approval_record,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "approve-run",
            "--prepare-manifest",
            str(prepare_manifest),
            "--output",
            str(tmp_path / "approval.json"),
            "--approved-by",
            "test_operator",
        ],
    )

    assert result.exit_code == 2

    assert "当前操作被拒绝" in result.output
    assert "任务批准未完成。" in result.output

    assert (
        "BinderRanker 执行：否"
        in result.output
    )

    assert (
        "simulated approval failure"
        not in result.output
    )

    assert "ValueError" not in result.output


def test_approve_run_preserves_safe_business_fact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_manifest = (
        tmp_path / "agent_prepare_manifest.json"
    )
    prepare_manifest.write_text(
        "{}",
        encoding="utf-8",
    )

    def failing_create_approval_record(**kwargs):
        raise ApprovalError(
            "INTERNAL_APPROVAL_STATE_DETAIL",
            public_message=(
                "只有 READY_FOR_REVIEW 任务可以批准；"
                "当前任务状态不允许批准。"
            ),
        )

    monkeypatch.setattr(
        cli_module,
        "create_approval_record",
        failing_create_approval_record,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "approve-run",
            "--prepare-manifest",
            str(prepare_manifest),
            "--output",
            str(tmp_path / "approval.json"),
            "--approved-by",
            "test_operator",
        ],
    )

    assert result.exit_code == 2

    assert (
        "只有 READY_FOR_REVIEW 任务可以批准"
        in result.output
    )

    assert (
        "当前任务状态不允许批准"
        in result.output
    )

    assert (
        "INTERNAL_APPROVAL_STATE_DETAIL"
        not in result.output
    )

    assert (
        "BinderRanker 执行：否"
        in result.output
    )


def test_approve_run_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_manifest = (
        tmp_path / "agent_prepare_manifest.json"
    )
    prepare_manifest.write_text(
        "{}",
        encoding="utf-8",
    )

    def failing_create_approval_record(**kwargs):
        raise OSError(
            "PRIVATE_APPROVAL_IO_DETAIL"
        )

    monkeypatch.setattr(
        cli_module,
        "create_approval_record",
        failing_create_approval_record,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "approve-run",
            "--prepare-manifest",
            str(prepare_manifest),
            "--output",
            str(tmp_path / "approval.json"),
            "--approved-by",
            "test_operator",
        ],
    )

    assert result.exit_code == 2

    assert (
        "当前操作被拒绝"
        in result.output
    )

    assert (
        "任务批准未完成"
        in result.output
    )

    assert (
        "BinderRanker 执行：否"
        in result.output
    )

    assert (
        "PRIVATE_APPROVAL_IO_DETAIL"
        not in result.output
    )

    assert "OSError" not in result.output
