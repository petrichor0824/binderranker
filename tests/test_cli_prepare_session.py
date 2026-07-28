from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.prepare_pipeline import (
    AgentPreparationError,
)


runner = CliRunner()


def test_prepare_session_command_is_available() -> None:
    from typer.main import get_command

    from protein_design_agent.cli import app

    root_command = get_command(app)

    assert "prepare-session" in (
        root_command.commands
    )

    command = root_command.commands[
        "prepare-session"
    ]

    option_names = {
        option
        for parameter in command.params
        for option in getattr(
            parameter,
            "opts",
            (),
        )
    }

    required_options = {
        "--session",
        "--bundle-dir",
    }

    assert required_options.issubset(
        option_names
    )


def test_prepare_session_command_reports_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = tmp_path / "session.json"
    session.write_text(
        "{}",
        encoding="utf-8",
    )

    bundle = tmp_path / "bundle"

    fake_result = SimpleNamespace(
        status="READY_FOR_REVIEW",
        project_name="test_project",
        provider_name="mock",
        bundle_directory=bundle,
        project_config=bundle / "project.yaml",
        workflow_directory=bundle / "workflow",
        workflow_manifest=(
            bundle
            / "workflow"
            / "workflow_manifest.json"
        ),
        prepare_manifest=(
            bundle
            / "agent_prepare_manifest.json"
        ),
        binderranker_executed=False,
        remote_backend_used=False,
    )

    def fake_prepare_agent_run(
        *,
        session_path: Path,
        bundle_dir: Path,
    ):
        assert session_path == session.resolve()
        assert bundle_dir == bundle
        return fake_result

    monkeypatch.setattr(
        cli_module,
        "prepare_agent_run",
        fake_prepare_agent_run,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "prepare-session",
            "--session",
            str(session),
            "--bundle-dir",
            str(bundle),
        ],
    )

    assert result.exit_code == 0
    assert "READY_FOR_REVIEW" in result.output
    assert "BinderRanker 已执行：False" in result.output
    assert "远程后端已使用：False" in result.output


def test_prepare_session_command_reports_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = tmp_path / "session.json"
    session.write_text(
        "{}",
        encoding="utf-8",
    )

    def failing_prepare_agent_run(
        *,
        session_path: Path,
        bundle_dir: Path,
    ):
        raise AgentPreparationError(
            "simulated preparation failure"
        )

    monkeypatch.setattr(
        cli_module,
        "prepare_agent_run",
        failing_prepare_agent_run,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "prepare-session",
            "--session",
            str(session),
            "--bundle-dir",
            str(tmp_path / "bundle"),
        ],
    )

    assert result.exit_code == 2
    assert "Agent 准备失败" in result.output
    assert "simulated preparation failure" in result.output
