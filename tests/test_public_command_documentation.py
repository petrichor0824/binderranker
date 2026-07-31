import re
from pathlib import Path

from typer.testing import CliRunner

from protein_design_agent.agent.workspace_init import QUICKSTART_TEMPLATE
from protein_design_agent.cli import app


DOCS = Path("README.md").read_text(encoding="utf-8") + "\n" + QUICKSTART_TEMPLATE
PATTERN = re.compile(r"protein-design-agent\s+([a-z][a-z0-9-]*)")


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
