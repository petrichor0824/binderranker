from pathlib import Path

from typer.testing import CliRunner

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.prepare_pipeline import (
    AgentPreparationError,
)
from protein_design_agent.agent.providers.base import (
    ProviderError,
)


runner = CliRunner()


def write_model_config(tmp_path: Path) -> Path:
    config = tmp_path / "models.yaml"
    config.write_text(
        """
schema_version: "0.1"
active_profile: test_local

profiles:
  test_local:
    kind: openai_compatible
    base_url: http://127.0.0.1:8000/v1
    model: local-test-model
    api_key_env: null
    require_api_key: false
    timeout_seconds: 60
    max_output_tokens: 4096
    max_tokens_field: "max_tokens"
    temperature: 0.0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def test_prepare_preserves_safe_input_fact(
    tmp_path: Path,
) -> None:
    config = write_model_config(tmp_path)

    result = runner.invoke(
        cli_module.app,
        [
            "prepare",
            "--model-config",
            str(config),
            "--bundle-dir",
            str(tmp_path / "bundle"),
        ],
    )

    assert result.exit_code == 2

    assert (
        "必须提供 --text 或 --text-file"
        in result.output
    )

    assert (
        "尚未调用模型 API"
        in result.output
    )


def test_prepare_hides_provider_error_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = write_model_config(tmp_path)

    class FakeProvider:
        pass

    monkeypatch.setattr(
        cli_module,
        "build_request_parser_provider",
        lambda *args, **kwargs: FakeProvider(),
    )

    def failing_prepare(**kwargs):
        raise ProviderError(
            "PRIVATE_HTTP_RESPONSE_BODY"
        )

    monkeypatch.setattr(
        cli_module,
        "prepare_from_natural_language",
        failing_prepare,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "prepare",
            "--model-config",
            str(config),
            "--text",
            "测试任务",
            "--bundle-dir",
            str(tmp_path / "bundle"),
            "--allow-network",
        ],
    )

    assert result.exit_code == 4

    assert (
        "模型请求或响应处理"
        in result.output
    )

    assert (
        "PRIVATE_HTTP_RESPONSE_BODY"
        not in result.output
    )

    assert "ProviderError" not in result.output


def test_prepare_preserves_agent_preparation_fact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = write_model_config(tmp_path)

    class FakeProvider:
        pass

    monkeypatch.setattr(
        cli_module,
        "build_request_parser_provider",
        lambda *args, **kwargs: FakeProvider(),
    )

    def failing_prepare(**kwargs):
        raise AgentPreparationError(
            "INTERNAL_PREPARATION_DETAIL",
            public_message=(
                "准备工作流没有停在 "
                "READY_FOR_REVIEW，"
                "因此不能发布正式任务。"
            ),
        )

    monkeypatch.setattr(
        cli_module,
        "prepare_from_natural_language",
        failing_prepare,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "prepare",
            "--model-config",
            str(config),
            "--text",
            "测试任务",
            "--bundle-dir",
            str(tmp_path / "bundle"),
            "--allow-network",
        ],
    )

    assert result.exit_code == 4

    assert (
        "任务准备流程尚未形成"
        "可供审核的完整计划"
        in result.output
    )
    assert "READY_FOR_REVIEW" not in result.output

    assert (
        "INTERNAL_PREPARATION_DETAIL"
        not in result.output
    )


def test_prepare_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = write_model_config(tmp_path)

    class FakeProvider:
        pass

    monkeypatch.setattr(
        cli_module,
        "build_request_parser_provider",
        lambda *args, **kwargs: FakeProvider(),
    )

    def failing_prepare(**kwargs):
        raise OSError(
            "PRIVATE_PREPARE_IO_DETAIL"
        )

    monkeypatch.setattr(
        cli_module,
        "prepare_from_natural_language",
        failing_prepare,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "prepare",
            "--model-config",
            str(config),
            "--text",
            "测试任务",
            "--bundle-dir",
            str(tmp_path / "bundle"),
            "--allow-network",
        ],
    )

    assert result.exit_code == 4

    assert (
        "自然语言任务准备未完成"
        in result.output
    )

    assert (
        "PRIVATE_PREPARE_IO_DETAIL"
        not in result.output
    )

    assert "OSError" not in result.output
