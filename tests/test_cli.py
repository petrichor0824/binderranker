import json
from pathlib import Path

from typer.testing import CliRunner

from protein_design_agent.cli import app


runner = CliRunner()


def write_model_config(
    tmp_path: Path,
) -> Path:
    path = tmp_path / "models.yaml"

    path.write_text(
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

    return path


def write_mock_payload(
    tmp_path: Path,
    *,
    complete: bool,
) -> Path:
    path = tmp_path / "payload.json"

    if complete:
        payload = {
            "project_name": "cli_test",
            "input_dir": (
                "sample_data/test_two_chain"
            ),
            "input_layout": "existing_chains",
            "binder_chain": "A",
            "execute_requested": False,
        }
    else:
        payload = {}

    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    return path


def test_cli_has_expected_commands() -> None:
    from typer.main import get_command

    from protein_design_agent.cli import app

    root_command = get_command(app)

    expected_commands = {
        "init",
        "doctor",
        "chat",
        "plan",
        "plan-mock",
        "prepare",
        "prepare-session",
        "materialize-plan",
        "approve-run",
        "execute-run",
        "run-status",
        "analyze-run",
        "explain-run",
        "validate-model-config",
    }

    assert expected_commands.issubset(
        set(root_command.commands)
    )


def test_validate_model_config_does_not_use_network(
    tmp_path: Path,
) -> None:
    config = write_model_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "validate-model-config",
            "--config",
            str(config),
        ],
    )

    assert result.exit_code == 0
    assert "模型配置验证成功" in result.output
    assert "本命令没有访问网络" in result.output


def test_plan_requires_explicit_network_permission(
    tmp_path: Path,
) -> None:
    config = write_model_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "plan",
            "--model-config",
            str(config),
            "--text",
            "帮我检查骨架",
        ],
    )

    assert result.exit_code == 3
    assert "未提供 --allow-network" in result.output
    assert "没有访问模型 API" in result.output


def test_complete_mock_plan_is_ready(
    tmp_path: Path,
) -> None:
    payload = write_mock_payload(
        tmp_path,
        complete=True,
    )
    output = tmp_path / "plan.json"

    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--payload",
            str(payload),
            "--text",
            "检查已经分链的数据，A链是binder",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "READY_FOR_REVIEW" in result.output
    assert output.exists()

    data = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert data["provider_name"] == "mock"
    assert data["plan"]["status"] == (
        "READY_FOR_REVIEW"
    )
    assert (
        data["plan"]["execution_allowed"]
        is False
    )


def test_incomplete_mock_plan_requests_information(
    tmp_path: Path,
) -> None:
    payload = write_mock_payload(
        tmp_path,
        complete=False,
    )
    output = tmp_path / "incomplete.json"

    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--payload",
            str(payload),
            "--text",
            "帮我排名这批骨架",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "NEEDS_INFORMATION" in result.output
    assert "input_dir" in result.output
    assert "input_layout" in result.output


def test_text_and_text_file_cannot_be_used_together(
    tmp_path: Path,
) -> None:
    payload = write_mock_payload(
        tmp_path,
        complete=True,
    )

    text_file = tmp_path / "request.txt"
    text_file.write_text(
        "测试请求",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--payload",
            str(payload),
            "--text",
            "另一个请求",
            "--text-file",
            str(text_file),
        ],
    )

    assert result.exit_code == 2
    assert "不能同时使用" in result.output
