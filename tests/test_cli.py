import json
import os
import subprocess
import sys
from importlib.metadata import (
    version as distribution_version,
)
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from protein_design_agent.cli import app


runner = CliRunner()


def test_cli_streams_override_legacy_windows_encoding(
) -> None:
    repository_root = (
        Path(__file__).resolve().parents[1]
    )
    environment = os.environ.copy()
    source_root = repository_root / "src"
    existing_pythonpath = environment.get(
        "PYTHONPATH",
        "",
    )

    environment["PYTHONIOENCODING"] = "cp1252"
    environment["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (
            str(source_root),
            existing_pythonpath,
        )
        if item
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from protein_design_agent.cli import "
                "configure_cli_streams; "
                "configure_cli_streams(); "
                "print('总体状态：通过')"
            ),
        ],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.decode("utf-8").strip() == (
        "总体状态：通过"
    )


def test_cli_reports_installed_distribution_version() -> None:
    result = runner.invoke(
        app,
        ["--version"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == (
        "BinderRanker "
        f"{distribution_version('binderranker')}"
    )


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
        "extract-sample",
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
    assert "状态：计划已准备，等待审核" in result.output
    assert "READY_FOR_REVIEW" not in result.output
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
    assert "状态：等待补充任务信息" in result.output
    assert "NEEDS_INFORMATION" not in result.output
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


def test_analyze_run_error_uses_safe_user_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def fail_analyze(**kwargs):
        raise RuntimeError(
            "PRIVATE_ANALYZE_TECHNICAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.cli.run_analyze_run",
        fail_analyze,
    )

    result = runner.invoke(
        app,
        [
            "analyze-run",
            "--bundle-dir",
            str(bundle),
        ],
    )

    assert result.exit_code == 1
    assert "当前操作没有完成" in result.output
    assert "结果分析未完成。" in result.output
    assert "建议处理" in result.output

    assert (
        "PRIVATE_ANALYZE_TECHNICAL_DETAIL"
        not in result.output
    )
    assert "RuntimeError" not in result.output


def test_explain_run_error_uses_safe_user_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    config = tmp_path / "models.yaml"
    config.write_text(
        "placeholder: true\n",
        encoding="utf-8",
    )

    def fail_explain(**kwargs):
        raise RuntimeError(
            "PRIVATE_EXPLAIN_TECHNICAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.cli.run_explain_run",
        fail_explain,
    )

    result = runner.invoke(
        app,
        [
            "explain-run",
            "--bundle-dir",
            str(bundle),
            "--model-config",
            str(config),
        ],
    )

    assert result.exit_code == 1
    assert "当前操作没有完成" in result.output
    assert "模型解释未完成。" in result.output
    assert "建议处理" in result.output

    assert (
        "PRIVATE_EXPLAIN_TECHNICAL_DETAIL"
        not in result.output
    )
    assert "RuntimeError" not in result.output


def test_execute_run_generic_error_uses_safe_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text(
        "{}\n",
        encoding="utf-8",
    )

    def fail_execute(**kwargs):
        raise RuntimeError(
            "PRIVATE_EXECUTE_TECHNICAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.cli."
        "execute_approved_binderranker",
        fail_execute,
    )

    result = runner.invoke(
        app,
        [
            "execute-run",
            "--approval",
            str(approval),
            "--confirm-execute",
        ],
    )

    assert result.exit_code == 1

    assert "当前操作没有完成" in result.output
    assert (
        "BinderRanker 执行未完成。"
        in result.output
    )

    assert (
        "PRIVATE_EXECUTE_TECHNICAL_DETAIL"
        not in result.output
    )
    assert "RuntimeError" not in result.output

    assert not isinstance(
        result.exception,
        NameError,
    )


def test_execute_run_local_error_keeps_manifest_recovery_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from protein_design_agent.agent.local_executor import (
        LocalExecutionError,
    )

    approval = tmp_path / "approval.json"
    approval.write_text(
        "{}\n",
        encoding="utf-8",
    )

    manifest = (
        tmp_path
        / "execution_failed.json"
    )
    manifest.write_text(
        "{}\n",
        encoding="utf-8",
    )

    def fail_execute(**kwargs):
        raise LocalExecutionError(
            (
                "PRIVATE_EXECUTION_DETAIL；"
                "stderr=/private/internal/error.log"
            ),
            execution_manifest=manifest,
        )

    monkeypatch.setattr(
        "protein_design_agent.cli."
        "execute_approved_binderranker",
        fail_execute,
    )

    result = runner.invoke(
        app,
        [
            "execute-run",
            "--approval",
            str(approval),
            "--confirm-execute",
        ],
    )

    assert result.exit_code == 1

    assert "当前操作没有完成" in result.output
    assert (
        "BinderRanker 执行未完成。"
        in result.output
    )

    assert "执行清单：" in result.output
    assert str(manifest) in result.output

    assert (
        "PRIVATE_EXECUTION_DETAIL"
        not in result.output
    )
    assert (
        "/private/internal/error.log"
        not in result.output
    )
    assert "LocalExecutionError" not in result.output


def test_run_status_error_uses_safe_user_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    from protein_design_agent.agent.run_status import (
        RunStatusError,
    )

    def fail_status(*args, **kwargs):
        raise RunStatusError(
            "PRIVATE_STATUS_TECHNICAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.cli.inspect_run_status",
        fail_status,
    )

    result = runner.invoke(
        app,
        [
            "run-status",
            "--bundle-dir",
            str(bundle),
        ],
    )

    assert result.exit_code == 1

    assert "当前操作没有完成" in result.output
    assert "任务状态检查未完成。" in result.output

    assert (
        "PRIVATE_STATUS_TECHNICAL_DETAIL"
        not in result.output
    )
    assert "RunStatusError" not in result.output


def test_run_status_translates_internal_states(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    report = SimpleNamespace(
        project_name="demo",
        bundle_dir=bundle,
        current_stage="ANALYZED",
        prepare_status="READY_FOR_REVIEW",
        approval_status="APPROVED",
        execution_status="COMPLETED",
        analysis_status="COMPLETED",
        explanation_status="UNAVAILABLE",
        analysis_scope_level="EXPLORATORY",
        approval_id="apr_demo",
        approval_consumed=True,
        candidate_count=42,
        formal_candidate_recommendation_allowed=False,
        thresholds_formally_interpretable=False,
        analysis_attempts=[],
        warnings=[],
    )

    monkeypatch.setattr(
        "protein_design_agent.cli.inspect_run_status",
        lambda path: report,
    )

    result = runner.invoke(
        app,
        [
            "run-status",
            "--bundle-dir",
            str(bundle),
        ],
    )

    assert result.exit_code == 0
    assert (
        "当前进度：确定性结果分析已完成"
        in result.output
    )
    assert "准备：计划已准备，等待审核" in result.output
    assert "模型解释：暂不可用" in result.output
    assert (
        "结果使用范围：探索性批内比较"
        in result.output
    )
    assert "READY_FOR_REVIEW" not in result.output
    assert "ANALYZED" not in result.output
    assert "UNAVAILABLE" not in result.output


def test_validate_model_config_hides_raw_loader_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "model.yaml"
    config.write_text(
        "placeholder: true\n",
        encoding="utf-8",
    )

    def fail_load(_path: Path):
        raise ValueError(
            "PRIVATE_MODEL_CONFIG_INTERNAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.cli."
        "load_model_provider_config",
        fail_load,
    )

    result = runner.invoke(
        app,
        [
            "validate-model-config",
            "--config",
            str(config),
        ],
    )

    assert result.exit_code == 2
    assert "当前操作没有完成" in result.output
    assert (
        "模型配置文件无法读取或基础格式无效"
        in result.output
    )
    assert "网络访问：否" in result.output
    assert "没有调用模型 API" in result.output

    assert (
        "PRIVATE_MODEL_CONFIG_INTERNAL_DETAIL"
        not in result.output
    )
    assert "ValueError" not in result.output


def test_validate_model_config_reports_missing_profile_safely(
    tmp_path: Path,
) -> None:
    config = write_model_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "validate-model-config",
            "--config",
            str(config),
            "--profile",
            "missing-profile",
        ],
    )

    assert result.exit_code == 2
    assert "当前操作没有完成" in result.output
    assert (
        "指定的模型 Profile 不存在"
        in result.output
    )
    assert "missing-profile" in result.output
    assert "可用 Profile" in result.output
    assert "网络访问：否" in result.output
    assert "没有调用模型 API" in result.output
    assert "ValueError" not in result.output


def test_plan_mock_invalid_json_is_reported_safely(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "bad_payload.json"
    payload.write_text(
        "{not valid json",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--payload",
            str(payload),
            "--text",
            "测试任务",
            "--output",
            str(tmp_path / "plan.json"),
        ],
    )

    assert result.exit_code == 2

    assert (
        "Mock payload 不是合法 JSON"
        in result.output
    )

    assert (
        "plan-mock 完全离线"
        in result.output
    )

    assert "JSONDecodeError" not in result.output


def test_plan_missing_text_preserves_safe_input_fact(
    tmp_path: Path,
) -> None:
    config = write_model_config(tmp_path)

    result = runner.invoke(
        app,
        [
            "plan",
            "--model-config",
            str(config),
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


def test_plan_hides_provider_error_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import protein_design_agent.cli as cli_module
    from protein_design_agent.agent.providers.base import (
        ProviderError,
    )

    config = write_model_config(tmp_path)

    class FailingProvider:
        name = "failing"

        def parse_user_request(
            self,
            raw_text: str,
        ):
            raise ProviderError(
                "PRIVATE_MODEL_HTTP_BODY"
            )

    monkeypatch.setattr(
        cli_module,
        "build_request_parser_provider",
        lambda *args, **kwargs: FailingProvider(),
    )

    result = runner.invoke(
        app,
        [
            "plan",
            "--model-config",
            str(config),
            "--text",
            "测试任务",
            "--output",
            str(tmp_path / "plan.json"),
            "--allow-network",
        ],
    )

    assert result.exit_code == 4

    assert (
        "模型请求或响应处理"
        in result.output
    )

    assert (
        "PRIVATE_MODEL_HTTP_BODY"
        not in result.output
    )

    assert "ProviderError" not in result.output


def test_plan_mock_publish_failure_preserves_existing_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = write_mock_payload(
        tmp_path,
        complete=True,
    )

    output = tmp_path / "existing_plan.json"
    original = b"important old plan\n"
    output.write_bytes(original)

    real_replace = Path.replace

    def failing_replace(
        self: Path,
        target,
    ):
        target_path = Path(target)

        if (
            target_path == output
            and ".planning-" in self.name
        ):
            raise OSError(
                "PRIVATE_PLAN_PUBLISH_FAILURE"
            )

        return real_replace(
            self,
            target,
        )

    monkeypatch.setattr(
        Path,
        "replace",
        failing_replace,
    )

    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--payload",
            str(payload),
            "--text",
            "测试任务",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2

    assert output.read_bytes() == original

    assert (
        "规划会话输出文件写入或验证失败"
        in result.output
    )

    assert (
        "PRIVATE_PLAN_PUBLISH_FAILURE"
        not in result.output
    )

    leftovers = [
        path
        for path in tmp_path.iterdir()
        if ".planning-" in path.name
    ]

    assert leftovers == []

def test_root_help_uses_binderranker_identity() -> None:
    result = runner.invoke(
        app,
        ["--help"],
    )

    assert result.exit_code == 0
    assert "BinderRanker" in result.output
    assert "Protein Design Agent" not in result.output


def test_plan_mock_help_includes_payload_example() -> None:
    result = runner.invoke(
        app,
        [
            "plan-mock",
            "--help",
        ],
    )

    assert result.exit_code == 0
    assert '"project_name"' in result.output
    assert '"input_dir"' in result.output
    assert '"input_layout"' in result.output
    assert '"binder_chain"' in result.output
    assert "execute_requested" in result.output
    assert "不会执行 BinderRanker" in result.output
    assert "source_chain" in result.output
    assert "target_residue_count" in result.output
