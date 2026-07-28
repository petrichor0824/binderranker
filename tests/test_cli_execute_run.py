from pathlib import Path
from types import SimpleNamespace

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.local_executor import (
    LocalExecutionError,
)
from protein_design_agent.cli import app
from typer.testing import CliRunner


runner = CliRunner()


def create_approval_file(
    tmp_path: Path,
) -> Path:
    path = tmp_path / "approval.json"

    path.write_text(
        "{}",
        encoding="utf-8",
    )

    return path


def test_execute_run_requires_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approval = create_approval_file(
        tmp_path
    )

    called = False

    def fake_execute(**kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "缺少确认时不应调用执行器"
        )

    monkeypatch.setattr(
        cli_module,
        "execute_approved_binderranker",
        fake_execute,
    )

    result = runner.invoke(
        app,
        [
            "execute-run",
            "--approval",
            str(approval),
        ],
    )

    assert result.exit_code == 1
    assert "--confirm-execute" in result.output
    assert called is False


def test_execute_run_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approval = create_approval_file(
        tmp_path
    )

    execution_manifest = (
        tmp_path
        / "execution.json"
    )

    stdout_log = tmp_path / "stdout.log"
    stderr_log = tmp_path / "stderr.log"
    output_prefix = tmp_path / "ranker_output"

    output_file = (
        tmp_path
        / "ranker_output_scored.csv"
    )

    fake_result = SimpleNamespace(
        status="COMPLETED",
        project_name="test_project",
        approval_id="apr_test",
        return_code=0,
        output_prefix=output_prefix,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        execution_manifest=execution_manifest,
        output_files=[
            SimpleNamespace(
                path=output_file,
            )
        ],
    )

    captured = {}

    def fake_execute(
        *,
        approval_path,
        confirm_execute,
    ):
        captured["approval_path"] = (
            approval_path
        )
        captured["confirm_execute"] = (
            confirm_execute
        )

        return fake_result

    monkeypatch.setattr(
        cli_module,
        "execute_approved_binderranker",
        fake_execute,
    )

    result = runner.invoke(
        app,
        [
            "execute-run",
            "--approval",
            str(approval),
            "--confirm-execute",
        ],
    )

    assert result.exit_code == 0

    assert (
        captured["approval_path"]
        == approval
    )

    assert (
        captured["confirm_execute"]
        is True
    )

    assert "COMPLETED" in result.output
    assert "test_project" in result.output
    assert "apr_test" in result.output
    assert "不能再次使用" in result.output


def test_execute_run_reports_execution_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approval = create_approval_file(
        tmp_path
    )

    execution_manifest = (
        tmp_path
        / "execution_failed.json"
    )

    def fake_execute(**kwargs):
        raise LocalExecutionError(
            "一次性批准不能重复使用",
            execution_manifest=(
                execution_manifest
            ),
        )

    monkeypatch.setattr(
        cli_module,
        "execute_approved_binderranker",
        fake_execute,
    )

    result = runner.invoke(
        app,
        [
            "execute-run",
            "--approval",
            str(approval),
            "--confirm-execute",
        ],
    )

    assert result.exit_code == 1
    assert (
        "一次性批准不能重复使用"
        in result.output
    )
    assert (
        str(execution_manifest)
        in result.output
    )
