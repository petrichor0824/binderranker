import re
from pathlib import Path

from typer.testing import CliRunner

from protein_design_agent.agent.workspace_init import QUICKSTART_TEMPLATE
from protein_design_agent.cli import app
from protein_design_agent.public_identity import (
    CLI_NAME,
    LEGACY_CLI_NAME,
)


DOCS = (
    Path("README.md").read_text(encoding="utf-8")
    + "\n"
    + Path("README.zh-CN.md").read_text(encoding="utf-8")
    + "\n"
    + QUICKSTART_TEMPLATE
)
PATTERN = re.compile(
    rf"{re.escape(CLI_NAME)}\s+([a-z][a-z0-9-]*)"
)
LEGACY_COMMAND_PATTERN = re.compile(
    rf"(?m)^\s*{re.escape(LEGACY_CLI_NAME)}(?:\s|$)"
)


def test_documented_commands_exist() -> None:
    commands = set(PATTERN.findall(DOCS))
    assert {
        "chat",
        "doctor",
        "extract-sample",
        "init",
        "validate-model-config",
    } <= commands

    runner = CliRunner()
    for command in sorted(commands):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, (
            f"Invalid documented command: {command}\n{result.output}"
        )


def test_public_docs_do_not_teach_legacy_cli() -> None:
    assert LEGACY_COMMAND_PATTERN.search(DOCS) is None


def test_public_docs_do_not_require_repo_paths() -> None:
    forbidden = (
        "python -m pip install dist/",
        "sample_data/real/3c98_small",
        "/home/petrichor/",
        "/root/",
        ".venv/bin/python",
    )
    for value in forbidden:
        assert value not in DOCS
