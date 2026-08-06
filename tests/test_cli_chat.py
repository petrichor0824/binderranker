from pathlib import Path
from types import SimpleNamespace

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.chat_session import (
    ChatSessionError,
    ChatTurnResult,
)
from protein_design_agent.cli import app
from typer.testing import CliRunner


runner = CliRunner()



def test_chat_continues_without_model_config_when_network_enabled(
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
        input="退出\n",
    )

    assert result.exit_code == 0
    assert (
        "模型状态：NOT_CONFIGURED"
        in result.output
    )
    assert (
        "没有指定模型配置文件"
        in result.output
    )



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
        "process_dialogue_message",
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
        "process_dialogue_message",
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
    from protein_design_agent.agent.model_readiness import (
        ModelSetupReport,
    )

    bundle = tmp_path / "bundle"

    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "placeholder",
        encoding="utf-8",
    )

    fake_provider = object()
    readiness_call = {}

    def fake_assess_model_setup(**kwargs):
        readiness_call.update(kwargs)

        return ModelSetupReport(
            status="AVAILABLE",
            message=(
                "本地模型初始化条件已经通过；"
                "尚未发送网络请求。"
            ),
            config_path=model_config.resolve(),
            profile_name="fake-profile",
            model_name="fake-model",
            api_key_env="FAKE_API_KEY",
            provider=fake_provider,
        )

    monkeypatch.setattr(
        cli_module,
        "assess_model_setup",
        fake_assess_model_setup,
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
        "process_dialogue_message",
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

    assert "模型状态：READY" in result.output
    assert "fake-profile" in result.output
    assert "fake-model" in result.output

    assert "allow_network" not in readiness_call
    assert readiness_call["config_path"] == (
        model_config.resolve()
    )
    assert readiness_call["profile_name"] == (
        "fake-profile"
    )

    assert captured["provider"] is fake_provider
    assert captured["allow_network"] is True
    assert "是否允许本次 Chat 调用模型 API" not in result.output
    assert captured["model_config_path"] == (
        model_config.resolve()
    )
    assert captured["profile_name"] == (
        "fake-profile"
    )



def test_chat_routes_natural_language_through_dialogue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    received_messages = []

    def fake_dialogue(**kwargs):
        received_messages.append(
            kwargs["message"]
        )

        if len(received_messages) == 1:
            return ChatTurnResult(
                action="APPROVE",
                status=(
                    "AWAITING_CONFIRMATION"
                ),
                message=(
                    "你正在请求批准该计划。\n"
                    "请回答“确认”或“取消”。"
                ),
                bundle_dir=bundle,
            )

        return ChatTurnResult(
            action="APPROVE",
            status="APPROVED",
            message="计划已批准。",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        cli_module,
        "process_dialogue_message",
        fake_dialogue,
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
        input=(
            "这个方案没问题，批准吧\n"
            "确认\n"
            "退出\n"
        ),
    )

    assert result.exit_code == 0

    assert received_messages == [
        "这个方案没问题，批准吧",
        "确认",
    ]

    assert "等待" in result.output
    assert "计划已批准" in result.output


def test_chat_error_is_converted_to_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def fail_dialogue(**kwargs):
        raise ChatSessionError(
            "只有执行完成后才能分析"
        )

    captured = {}

    def fake_guidance(**kwargs):
        captured.update(kwargs)
        return (
            "当前操作被拒绝。\n"
            "建议处理：先完成执行步骤。"
        )

    monkeypatch.setattr(
        cli_module,
        "process_dialogue_message",
        fail_dialogue,
    )
    monkeypatch.setattr(
        cli_module,
        "format_error_guidance",
        fake_guidance,
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
        input="分析结果\n退出\n",
    )

    assert result.exit_code == 0
    assert "当前操作被拒绝" in result.output
    assert "先完成执行步骤" in result.output
    assert captured["kind"] == "REJECTED"
    assert isinstance(
        captured["error"],
        ChatSessionError,
    )


def test_chat_starts_with_safe_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    default_bundle = (
        tmp_path
        / ".protein-design-agent"
        / "runs"
        / "default"
    ).resolve()

    captured = []

    monkeypatch.setattr(
        cli_module,
        "resolve_chat_target",
        lambda **kwargs: SimpleNamespace(
            bundle_dir=default_bundle,
            workspace_dir=(
                default_bundle.parent.parent
            ),
            task_name="default",
            uses_default_workspace=True,
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "resolve_local_approved_by",
        lambda value: "local-test-user",
    )

    def fake_process(**kwargs):
        captured.append(kwargs)

        return ChatTurnResult(
            action="HELP",
            status="HELP",
            message="帮助内容",
            bundle_dir=default_bundle,
        )

    monkeypatch.setattr(
        cli_module,
        "process_dialogue_message",
        fake_process,
    )

    result = runner.invoke(
        app,
        ["chat"],
        input="帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "帮助内容" in result.output
    assert str(default_bundle) in result.output
    assert "local-test-user" in result.output

    assert len(captured) == 1
    assert (
        captured[0]["bundle_dir"]
        == default_bundle
    )
    assert (
        captured[0]["approved_by"]
        == "local-test-user"
    )


def test_chat_auto_initializes_default_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["chat"],
        input="退出\n",
    )

    workspace = (
        tmp_path / ".protein-design-agent"
    )

    assert result.exit_code == 0
    assert "已自动创建" in result.output
    assert (
        workspace / "QUICKSTART.md"
    ).is_file()
    assert (
        workspace / ".pda-workspace.json"
    ).is_file()
    assert (
        workspace
        / "runs"
        / "default"
    ).is_dir()


def test_chat_reuses_default_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(
        app,
        ["chat"],
        input="退出\n",
    )
    second = runner.invoke(
        app,
        ["chat"],
        input="退出\n",
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "已存在，安全复用" in second.output


def test_chat_selects_named_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    captured = []

    def fake_process(**kwargs):
        captured.append(kwargs)

        return ChatTurnResult(
            action="HELP",
            status="HELP",
            message="帮助内容",
            bundle_dir=kwargs["bundle_dir"],
        )

    monkeypatch.setattr(
        cli_module,
        "process_dialogue_message",
        fake_process,
    )

    result = runner.invoke(
        app,
        [
            "chat",
            "--task",
            "group_b",
        ],
        input="帮助\n退出\n",
    )

    expected_bundle = (
        tmp_path
        / ".protein-design-agent"
        / "runs"
        / "group_b"
    ).resolve()

    assert result.exit_code == 0
    assert "当前任务：group_b" in result.output
    assert str(expected_bundle) in result.output
    assert captured[0]["bundle_dir"] == (
        expected_bundle
    )


def test_chat_rejects_task_with_explicit_bundle(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "chat",
            "--bundle-dir",
            str(tmp_path / "bundle"),
            "--task",
            "group_b",
        ],
    )

    assert result.exit_code == 2
    assert "不能同时使用" in result.output


def test_interactive_chat_enables_model_after_yes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from protein_design_agent.agent.model_readiness import (
        ModelSetupReport,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "placeholder",
        encoding="utf-8",
    )

    fake_provider = object()
    captured = {}

    monkeypatch.setattr(
        cli_module,
        "assess_model_setup",
        lambda **_kwargs: ModelSetupReport(
            status="AVAILABLE",
            message="local setup ready",
            config_path=model_config.resolve(),
            profile_name="fake-profile",
            model_name="fake-model",
            api_key_env="FAKE_API_KEY",
            provider=fake_provider,
        ),
    )

    monkeypatch.setattr(
        cli_module,
        "stdin_is_interactive",
        lambda: True,
    )

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
        "process_dialogue_message",
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
        ],
        input="y\n帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "是否允许本次 Chat 调用模型 API" in result.output
    assert "模型状态：READY" in result.output
    assert captured["provider"] is fake_provider
    assert captured["allow_network"] is True


def test_interactive_chat_stays_offline_after_no(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from protein_design_agent.agent.model_readiness import (
        ModelSetupReport,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "placeholder",
        encoding="utf-8",
    )

    fake_provider = object()
    captured = {}

    monkeypatch.setattr(
        cli_module,
        "assess_model_setup",
        lambda **_kwargs: ModelSetupReport(
            status="AVAILABLE",
            message="local setup ready",
            config_path=model_config.resolve(),
            profile_name="fake-profile",
            model_name="fake-model",
            api_key_env="FAKE_API_KEY",
            provider=fake_provider,
        ),
    )

    monkeypatch.setattr(
        cli_module,
        "stdin_is_interactive",
        lambda: True,
    )

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
        "process_dialogue_message",
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
        ],
        input="n\n帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "是否允许本次 Chat 调用模型 API" in result.output
    assert "模型状态：OFFLINE" in result.output
    assert captured["provider"] is None
    assert captured["allow_network"] is False


def test_interactive_chat_defaults_offline_after_enter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from protein_design_agent.agent.model_readiness import (
        ModelSetupReport,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "placeholder",
        encoding="utf-8",
    )

    captured = {}

    monkeypatch.setattr(
        cli_module,
        "assess_model_setup",
        lambda **_kwargs: ModelSetupReport(
            status="AVAILABLE",
            message="local setup ready",
            config_path=model_config.resolve(),
            profile_name="fake-profile",
            model_name="fake-model",
            api_key_env="FAKE_API_KEY",
            provider=object(),
        ),
    )

    monkeypatch.setattr(
        cli_module,
        "stdin_is_interactive",
        lambda: True,
    )

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
        "process_dialogue_message",
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
        ],
        input="\n帮助\n退出\n",
    )

    assert result.exit_code == 0
    assert "是否允许本次 Chat 调用模型 API" in result.output
    assert "模型状态：OFFLINE" in result.output
    assert captured["provider"] is None
    assert captured["allow_network"] is False