from pathlib import Path

from typer.testing import CliRunner

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.model_readiness import (
    ModelReadinessReport,
)
from protein_design_agent.cli import app


runner = CliRunner()


def test_default_chat_discovers_workspace_model_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    captured = {}

    def fake_assess_model_readiness(**kwargs):
        captured.update(kwargs)

        return ModelReadinessReport(
            status="OFFLINE",
            message="offline test",
            network_allowed=False,
            config_path=kwargs["config_path"],
        )

    monkeypatch.setattr(
        cli_module,
        "assess_model_readiness",
        fake_assess_model_readiness,
    )

    result = runner.invoke(
        app,
        ["chat"],
        input="退出\n",
    )

    assert result.exit_code == 0

    workspace = (
        tmp_path / ".protein-design-agent"
    ).resolve()

    expected = (
        workspace
        / "configs"
        / "models"
        / "deepseek.local.yaml"
    ).resolve()

    assert expected.is_file()
    assert captured["config_path"] == expected
    assert captured["allow_network"] is False
