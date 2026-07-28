from pathlib import Path

from typer.testing import CliRunner

from protein_design_agent.cli import app


runner = CliRunner()


def test_cli_init_success(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"

    result = runner.invoke(
        app,
        [
            "init",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 0

    assert destination.is_dir()

    assert (
        destination / "QUICKSTART.md"
    ).is_file()

    assert (
        destination
        / "configs"
        / "models"
        / "deepseek.local.yaml"
    ).is_file()

    assert (
        "网络访问：否"
        in result.output
    )

    assert (
        "写入真实 API Key：否"
        in result.output
    )

    assert (
        "覆盖已有文件：否"
        in result.output
    )


def test_cli_init_refuses_overwrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"
    destination.mkdir()

    existing = destination / ".gitignore"

    existing.write_text(
        "keep-this\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "init",
            "-d",
            str(destination),
        ],
    )

    assert result.exit_code == 2

    assert existing.read_text(
        encoding="utf-8"
    ) == "keep-this\n"

    assert (
        "工作区初始化失败"
        in result.output
    )

    assert not (
        destination / "QUICKSTART.md"
    ).exists()
