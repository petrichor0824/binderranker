import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.chat_session as module
from protein_design_agent.agent.chat_session import (
    ChatSessionError,
    process_chat_message,
)


class FakeProvider:
    @property
    def name(self) -> str:
        return "fake-provider"

    def parse_user_request(self, raw_text):
        raise AssertionError(
            "测试中不应直接调用真实解析"
        )

    def generate_json(self, messages):
        raise AssertionError(
            "测试中不应直接调用真实解析"
        )


def write_prepare_manifest(
    bundle: Path,
    status: str,
) -> None:
    bundle.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        bundle
        / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps(
            {"status": status}
        ),
        encoding="utf-8",
    )


def test_initial_message_calls_prepare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "new_bundle"

    expected_manifest = (
        bundle
        / "agent_prepare_manifest.json"
    )
    expected_session = (
        bundle
        / "planning_session.json"
    )

    def fake_prepare(**kwargs):
        bundle.mkdir()

        expected_manifest.write_text(
            "{}",
            encoding="utf-8",
        )
        expected_session.write_text(
            "{}",
            encoding="utf-8",
        )

        return SimpleNamespace(
            status="NEEDS_INFORMATION",
            project_name=None,
            missing_information=[
                "input_layout",
            ],
            planning_session=(
                expected_session
            ),
            prepare_manifest=(
                expected_manifest
            ),
        )

    monkeypatch.setattr(
        module,
        "prepare_from_natural_language",
        fake_prepare,
    )

    result = process_chat_message(
        message="分析这个目录",
        bundle_dir=bundle,
        provider=FakeProvider(),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "PREPARE"
    assert (
        result.status
        == "NEEDS_INFORMATION"
    )
    assert "input_layout" in result.message


def test_incomplete_bundle_calls_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"

    write_prepare_manifest(
        bundle,
        "NEEDS_INFORMATION",
    )

    history = (
        bundle / "history" / "resume_0001"
    )

    def fake_resume(**kwargs):
        history.mkdir(
            parents=True
        )

        return SimpleNamespace(
            status="READY_FOR_REVIEW",
            missing_information=[],
            planning_session=(
                bundle
                / "planning_session.json"
            ),
            prepare_manifest=(
                bundle
                / "agent_prepare_manifest.json"
            ),
            history_record=history,
        )

    monkeypatch.setattr(
        module,
        "resume_planning_session",
        fake_resume,
    )

    result = process_chat_message(
        message="binder 链是 B",
        bundle_dir=bundle,
        provider=FakeProvider(),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "RESUME"
    assert (
        result.status
        == "READY_FOR_REVIEW"
    )


def test_approval_uses_explicit_smoke_ack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"

    write_prepare_manifest(
        bundle,
        "READY_FOR_REVIEW",
    )

    captured = {}

    def fake_approval(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            status="APPROVED",
            approval_id="apr_test",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
        )

    monkeypatch.setattr(
        module,
        "create_approval_record",
        fake_approval,
    )

    result = process_chat_message(
        message=(
            "批准计划并确认小样本限制"
        ),
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "APPROVE"

    assert (
        captured[
            "acknowledge_smoke_test"
        ]
        is True
    )


def test_execution_requires_exact_phrase(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    approval = bundle / "approval.json"
    approval.write_text(
        "{}",
        encoding="utf-8",
    )

    called = False

    def fake_execute(**kwargs):
        nonlocal called
        called = True

        return SimpleNamespace(
            status="COMPLETED",
            output_files=[],
            execution_manifest=(
                bundle / "execution.json"
            ),
            stdout_log=(
                bundle / "stdout.log"
            ),
            stderr_log=(
                bundle / "stderr.log"
            ),
        )

    monkeypatch.setattr(
        module,
        "execute_approved_binderranker",
        fake_execute,
    )

    with pytest.raises(
        ChatSessionError,
    ):
        process_chat_message(
            message="你帮我运行一下",
            bundle_dir=bundle,
            provider=None,
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=False,
        )

    assert called is False

    result = process_chat_message(
        message="确认执行",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert called is True
    assert result.action == "EXECUTE"


def test_deterministic_analysis_uses_no_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            execution_status="COMPLETED",
        ),
    )

    captured = {}

    def fake_analyze(**kwargs):
        captured.update(kwargs)

        analysis = (
            bundle / kwargs["analysis_dir"]
        )

        return SimpleNamespace(
            status="COMPLETED",
            analysis_dir=analysis,
            manifest_path=(
                analysis / "manifest.json"
            ),
            result_summary_path=(
                analysis / "summary.json"
            ),
            failure_analysis_path=(
                analysis / "failure.json"
            ),
            explanation_markdown_path=None,
        )

    monkeypatch.setattr(
        module,
        "run_analyze_run",
        fake_analyze,
    )

    result = process_chat_message(
        message="分析结果",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "ANALYZE"
    assert captured["with_model"] is False
    assert captured["allow_network"] is False


def test_model_explanation_requires_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            execution_status="COMPLETED",
        ),
    )

    with pytest.raises(
        ChatSessionError,
        match="allow-network",
    ):
        process_chat_message(
            message="分析并解释结果",
            bundle_dir=bundle,
            provider=None,
            approved_by="tester",
            model_config_path=(
                tmp_path / "models.yaml"
            ),
            profile_name="fake",
            allow_network=False,
        )
