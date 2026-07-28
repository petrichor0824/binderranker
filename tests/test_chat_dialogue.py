import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.chat_dialogue as module
from protein_design_agent.agent.chat_dialogue import (
    ChatDialogueError,
    DialogueDecision,
    load_pending_action,
    process_dialogue_message,
)
from protein_design_agent.agent.chat_session import (
    ChatTurnResult,
)


class FakeDialogueProvider:
    def __init__(
        self,
        intent: str,
        reply: str | None = None,
    ) -> None:
        self.intent = intent
        self.reply = reply

    @property
    def name(self) -> str:
        return "fake-provider"

    def parse_user_request(self, raw_text):
        raise AssertionError(
            "本测试不应调用任务解析"
        )

    def generate_json(self, messages):
        payload = {
            "intent": self.intent,
            "reason": "test",
        }

        if self.reply is not None:
            payload["reply"] = self.reply

        return payload


def write_json(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )


def prepared_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    return bundle


def test_natural_approval_creates_pending_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    called = False

    def fake_engine(**kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "提出批准意图时不能直接执行"
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    result = process_dialogue_message(
        message="这个方案没问题，就按它来吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == (
        "AWAITING_CONFIRMATION"
    )
    assert "请回答“确认”" in result.message
    assert called is False

    pending = load_pending_action(
        bundle
    )

    assert pending is not None
    assert pending.action == "APPROVE"


def test_confirmation_calls_deterministic_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    first = process_dialogue_message(
        message="批准这个方案",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert first.status == (
        "AWAITING_CONFIRMATION"
    )

    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)

        return ChatTurnResult(
            action="APPROVE",
            status="APPROVED",
            message="计划已批准",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    result = process_dialogue_message(
        message="确认",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "CONFIRM"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "APPROVED"
    assert (
        captured["message"]
        == "批准计划并确认小样本限制"
    )
    assert load_pending_action(
        bundle
    ) is None


def test_cancel_does_not_call_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "EXPLORATORY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    process_dialogue_message(
        message="批准吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    result = process_dialogue_message(
        message="取消",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "CANCEL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "CANCELLED"
    assert load_pending_action(
        bundle
    ) is None


def test_missing_fields_are_humanized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "missing_information": [
                "input_layout",
                "source_chain",
            ],
        },
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    result = process_dialogue_message(
        message="我还需要告诉你什么？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert "已经是不同链" in result.message
    assert "源链" in result.message
    assert "不需要输入字段名" in result.message


def test_stale_confirmation_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "EXPLORATORY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    process_dialogue_message(
        message="批准吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    # 模拟用户确认前任务清单发生变化。
    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "changed",
        },
    )

    with pytest.raises(
        ChatDialogueError,
        match="状态在等待确认期间发生了变化",
    ):
        process_dialogue_message(
            message="确认",
            bundle_dir=bundle,
            provider=FakeDialogueProvider(
                "CONFIRM"
            ),
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=True,
        )

    assert load_pending_action(
        bundle
    ) is None


def test_general_question_returns_model_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "missing_information": [
                "source_chain",
            ],
        },
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    answer = (
        "源链是指标准化之前，原始 PDB 中"
        "target 和 binder 所在的链。"
        "你刚才已经说明它们拼在同一条 A 链中，"
        "因此这里的源链应当是 A。"
    )

    result = process_dialogue_message(
        message="我咋知道源链是哪一条？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=answer,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert "标准化之前" in result.message
    assert "源链应当是 A" in result.message
    assert "还需要补充" not in result.message
