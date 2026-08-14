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

    assert (
        "不可安全覆盖"
        in result.output
    )

    assert (
        "写入受管文件之前停止"
        in result.output
    )

    assert (
        "检测到的冲突路径"
        in result.output
    )

    assert ".gitignore" in result.output

    assert (
        str(destination.resolve())
        not in result.output
    )

    assert not (
        destination / "QUICKSTART.md"
    ).exists()


def test_cli_init_shows_secure_api_key_guidance(
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
    assert "设置 DeepSeek API Key" in result.output
    assert "read -rsp" in result.output
    assert (
        "DEEPSEEK_API_KEY && echo && "
        "export DEEPSEEK_API_KEY"
        in result.output
    )
    assert (
        "出现提示后粘贴真实 Key"
        in result.output
    )
    assert (
        "DEEPSEEK_API_KEY 不要修改"
        in result.output
    )
    assert (
        'export DEEPSEEK_API_KEY="你的真实 API Key"'
        not in result.output
    )
    assert (
        "protein-design-agent chat"
        in result.output
    )


def test_cli_init_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "workspace"

    def fail_initialize(_destination: Path):
        raise OSError(
            "PRIVATE_WORKSPACE_INTERNAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.agent.workspace_init."
        "initialize_workspace",
        fail_initialize,
    )

    result = runner.invoke(
        app,
        [
            "init",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 2

    assert (
        "当前操作没有完成"
        in result.output
    )

    assert (
        "工作区初始化未完成"
        in result.output
    )

    assert (
        "文件系统操作失败"
        in result.output
    )

    assert (
        "检查目标路径"
        in result.output
    )

    assert (
        "PRIVATE_WORKSPACE_INTERNAL_DETAIL"
        not in result.output
    )

    assert "OSError" not in result.output
