from pathlib import Path

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.chat_session import (
    ChatSessionError,
    ChatTurnResult,
)
from protein_design_agent.cli import app
from typer.testing import CliRunner


runner = CliRunner()


def test_chat_requires_model_config_when_network_enabled(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "chat",
            "--bundle-dir",
            str(tmp_path / "bundle"),
            "--approved-by",
            "tester",
            "--allow-network",
        ],
    )

    assert result.exit_code == 2
    assert "--model-config" in result.output


def test_chat_status_then_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    captured = []

    def fake_process(**kwargs):
        captured.append(kwargs)

        return ChatTurnResult(
            action="STATUS",
            status="STATUS",
            message=(
                "项目：demo\n"
                "当前阶段：EXPLAINED"
            ),
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        cli_module,
        "process_chat_message",
        fake_process,
    )

    result = runner.invoke(
        app,
        [
            "chat",
            "--bundle-dir",
            str(bundle),
            "--approved-by",
            "tester",
        ],
        input="状态\n退出\n",
    )

    assert result.exit_code == 0
    assert "当前阶段：EXPLAINED" in result.output
    assert "会话已结束" in result.output

    assert len(captured) == 1
    assert captured[0]["message"] == "状态"
    assert captured[0]["allow_network"] is False
    assert captured[0]["provider"] is None


def test_chat_error_does_not_terminate_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    calls = 0

    def fake_process(**kwargs):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise ChatSessionError(
                "当前动作不允许"
            )

        return ChatTurnResult(
            action="HELP",
            status="HELP",
            message="帮助内容",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        cli_module,
        "process_chat_message",
        fake_process,
    )

    result = runner.invoke(
        app,
        [
            "chat",
            "--bundle-dir",
            str(bundle),
            "--approved-by",
            "tester",
        ],
        input="错误操作\n帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "当前动作不允许" in result.output
    assert "帮助内容" in result.output
    assert calls == 2


def test_chat_builds_provider_only_with_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"

    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "placeholder",
        encoding="utf-8",
    )

    fake_provider = object()

    monkeypatch.setattr(
        cli_module,
        "load_model_provider_config",
        lambda path: object(),
    )

    monkeypatch.setattr(
        cli_module,
        "resolve_provider_profile",
        lambda config, profile_name=None: (
            "fake-profile",
            type(
                "Profile",
                (),
                {
                    "model": "fake-model",
                },
            )(),
        ),
    )

    monkeypatch.setattr(
        cli_module,
        "build_request_parser_provider",
        lambda config, profile_name=None: (
            fake_provider
        ),
    )

    captured = {}

    def fake_process(**kwargs):
        captured.update(kwargs)

        return ChatTurnResult(
            action="HELP",
            status="HELP",
            message="帮助内容",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        cli_module,
        "process_chat_message",
        fake_process,
    )

    result = runner.invoke(
        app,
        [
            "chat",
            "--bundle-dir",
            str(bundle),
            "--approved-by",
            "tester",
            "--model-config",
            str(model_config),
            "--profile",
            "fake-profile",
            "--allow-network",
        ],
        input="帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "fake-profile" in result.output
    assert "fake-model" in result.output
    assert captured["provider"] is fake_provider
    assert captured["allow_network"] is True
    assert (
        captured["model_config_path"]
        == model_config.resolve()
    )
