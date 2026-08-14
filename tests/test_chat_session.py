import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.chat_session as module
from protein_design_agent.agent.providers.mock import MockProvider
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


def test_execution_immediately_shows_rank_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    (bundle / "approval.json").write_text(
        "{}",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "execute_approved_binderranker",
        lambda **kwargs: SimpleNamespace(
            status="COMPLETED",
            output_files=[
                bundle / "metrics.csv",
                bundle / "scored.csv",
                bundle / "ranking.xlsx",
                bundle / "report.txt",
            ],
            execution_manifest=(
                bundle / "execution_apr_test.json"
            ),
            stdout_log=bundle / "stdout.log",
            stderr_log=bundle / "stderr.log",
        ),
    )

    candidates = [
        SimpleNamespace(
            pdb_name="_2577",
            engineering_rank=1,
            final_score_v4=0.6141,
            public_filter_level="MEDIUM",
            public_filter_status=(
                "EXPLORATORY_ONLY"
            ),
            filter_reasons_formally_interpretable=True,
            strict_reasons=[
                "low_contact_map_continuity_score",
            ],
            medium_reasons=[],
            broad_reasons=[],
        ),
        SimpleNamespace(
            pdb_name="_498",
            engineering_rank=2,
            final_score_v4=0.5977,
            public_filter_level="MEDIUM",
            public_filter_status=(
                "EXPLORATORY_ONLY"
            ),
            filter_reasons_formally_interpretable=True,
            strict_reasons=[
                "high_contact_map_jump_fraction",
            ],
            medium_reasons=[],
            broad_reasons=[],
        ),
    ]

    monkeypatch.setattr(
        module,
        "parse_completed_ranker_run",
        lambda path: SimpleNamespace(
            candidate_count=2,
            analysis_scope={
                "level": "EXPLORATORY",
            },
            candidates_by_engineering_rank=(
                candidates
            ),
            formal_candidate_recommendation_allowed=(
                False
            ),
        ),
    )

    result = process_chat_message(
        message="确认执行",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.status == "COMPLETED"
    assert "结果预览：共 2 个候选" in (
        result.message
    )
    assert "1. _2577" in result.message
    assert "总分 0.6141" in result.message
    assert (
        "low_contact_map_continuity_score"
        in result.message
    )
    assert "正式候选推荐" in result.message
    assert "科研结论" in result.message
    assert "不允许" in result.message


def test_preview_failure_does_not_change_execution_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    (bundle / "approval.json").write_text(
        "{}",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "execute_approved_binderranker",
        lambda **kwargs: SimpleNamespace(
            status="COMPLETED",
            output_files=[],
            execution_manifest=(
                bundle / "execution_apr_test.json"
            ),
            stdout_log=bundle / "stdout.log",
            stderr_log=bundle / "stderr.log",
        ),
    )

    def fail_preview(path):
        raise RuntimeError("preview unavailable")

    monkeypatch.setattr(
        module,
        "parse_completed_ranker_run",
        fail_preview,
    )

    result = process_chat_message(
        message="确认执行",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.status == "COMPLETED"
    assert "结果预览暂不可用" in result.message
    assert "不影响已经完成" in result.message


def test_chat_reports_model_explanation_fallback(
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

    analysis_dir = (
        bundle
        / "analyses"
        / "chat_model_fallback"
    )

    monkeypatch.setattr(
        module,
        "next_analysis_directory",
        lambda **kwargs: analysis_dir,
    )

    monkeypatch.setattr(
        module,
        "run_analyze_run",
        lambda **kwargs: SimpleNamespace(
            status="COMPLETED",
            analysis_dir=analysis_dir,
            manifest_path=(
                analysis_dir
                / "analyze_run_manifest.json"
            ),
            result_summary_path=(
                analysis_dir
                / "agent_result_summary.json"
            ),
            failure_analysis_path=(
                analysis_dir
                / "agent_failure_analysis_v2.json"
            ),
            explanation_markdown_path=None,
            explanation_status="UNAVAILABLE",
            explanation_error_type=(
                "ResultExplanationError"
            ),
            explanation_error_message=(
                "自动修正后仍未通过"
            ),
        ),
    )

    result = process_chat_message(
        message="分析并解释结果",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=(
            tmp_path / "models.yaml"
        ),
        profile_name="fake",
        allow_network=True,
    )

    assert result.status == "COMPLETED"
    assert result.action == "EXPLAIN"
    assert (
        "确定性分析完成"
        in result.message
    )
    assert (
        "模型解释暂不可用"
        in result.message
    )
    assert (
        "结果摘要和失败分析"
        in result.message
    )
    assert (
        "自动修正后仍未通过"
        not in result.message
    )
    assert (
        "ResultExplanationError"
        not in result.message
    )
    assert (
        "解释错误："
        not in result.message
    )

def test_initial_message_reuses_precreated_empty_bundle(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "runs" / "default"
    bundle.mkdir(parents=True)

    result = process_chat_message(
        message="分析这个目录",
        bundle_dir=bundle,
        provider=MockProvider({}),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "PREPARE"
    assert result.status == "NEEDS_INFORMATION"
    assert (
        bundle / "planning_session.json"
    ).is_file()
    assert (
        bundle / "agent_prepare_manifest.json"
    ).is_file()
    assert not (
        bundle / "workflow"
    ).exists()
