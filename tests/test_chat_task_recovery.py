import json
from pathlib import Path

import pytest

import protein_design_agent.agent.chat_dialogue as module
from protein_design_agent.agent.chat_dialogue import (
    ChatDialogueError,
    load_pending_action,
    process_dialogue_message,
)


class FakeRecoveryProvider:
    def __init__(self, intent: str) -> None:
        self.intent = intent

    @property
    def name(self) -> str:
        return "fake-recovery-provider"

    def parse_user_request(self, raw_text):
        raise AssertionError(
            "恢复测试不应该解析新的科研任务"
        )

    def generate_json(self, messages):
        return {
            "intent": self.intent,
            "reason": "test",
        }


def make_workspace(
    tmp_path: Path,
) -> tuple[Path, Path]:
    workspace = tmp_path / ".protein-design-agent"
    runs = workspace / "runs"
    runs.mkdir(parents=True)

    (
        workspace / ".pda-workspace.json"
    ).write_text(
        json.dumps({
            "schema_version": "0.1",
            "workspace_type": "protein-design-agent",
        }),
        encoding="utf-8",
    )

    bundle = runs / "default"
    bundle.mkdir()

    return workspace, bundle


def fake_inspect(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "inspect_bundle",
        lambda path: ("PREPARED", None),
    )


def test_chat_only_control_state_is_not_run_state(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    chat = bundle / "chat"
    chat.mkdir(parents=True)

    (
        chat / "pending_action.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    stage, report = module.inspect_bundle(bundle)

    assert stage == "EMPTY"
    assert report is None


def test_reset_request_only_creates_proposal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    planning = bundle / "planning_session.json"
    planning.write_text(
        "{}",
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    result = process_dialogue_message(
        message="重新开始这个任务",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_RESET_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "AWAITING_CONFIRMATION"
    assert planning.is_file()

    pending = load_pending_action(bundle)

    assert pending is not None
    assert pending.action == "RESET_TASK"


def test_confirm_reset_calls_recovery_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    process_dialogue_message(
        message="重新开始这个任务",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_RESET_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    result = process_dialogue_message(
        message="确认",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "CONFIRM"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "RESET"
    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []
    assert load_pending_action(bundle) is None


def test_protected_task_cannot_request_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "approval.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    with pytest.raises(
        ChatDialogueError,
        match="受保护证据",
    ):
        process_dialogue_message(
            message="清空这个任务重新开始",
            bundle_dir=bundle,
            provider=FakeRecoveryProvider(
                "REQUEST_RESET_TASK"
            ),
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=True,
        )

    assert (
        bundle / "approval.json"
    ).is_file()


def test_archive_request_and_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "approval.json"
    ).write_text(
        '{"approval_id":"apr_test"}',
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    proposal = process_dialogue_message(
        message="归档当前任务然后重新开始",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_ARCHIVE_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert proposal.status == "AWAITING_CONFIRMATION"

    result = process_dialogue_message(
        message="确认",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "CONFIRM"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ARCHIVED"
    assert bundle.is_dir()
    assert list(bundle.iterdir()) == []

    archives = list(
        (
            workspace
            / "archives"
            / "default"
        ).iterdir()
    )

    assert len(archives) == 1

    assert (
        archives[0] / "approval.json"
    ).is_file()


def test_recovery_confirmation_becomes_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    process_dialogue_message(
        message="重新开始这个任务",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_RESET_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    # 用户确认前产生了新的正式证据。
    (
        bundle / "approval.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        ChatDialogueError,
        match="状态在等待确认期间发生了变化",
    ):
        process_dialogue_message(
            message="确认",
            bundle_dir=bundle,
            provider=FakeRecoveryProvider(
                "CONFIRM"
            ),
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=True,
        )

    assert (
        bundle / "approval.json"
    ).is_file()

    assert load_pending_action(bundle) is None


def test_model_can_request_reset_with_free_form_language(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps({
            "status": "NEEDS_INFORMATION",
        }),
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    result = process_dialogue_message(
        message="这个规划搞乱了，我想全部从头来",
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_RESET_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "AWAITING_CONFIRMATION"

    pending = load_pending_action(bundle)

    assert pending is not None
    assert pending.action == "RESET_TASK"


def test_model_can_request_archive_with_free_form_language(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _workspace, bundle = make_workspace(
        tmp_path
    )

    (
        bundle / "approval.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    fake_inspect(monkeypatch)

    result = process_dialogue_message(
        message=(
            "这个任务我还想留着，"
            "但先收起来再开一个干净的"
        ),
        bundle_dir=bundle,
        provider=FakeRecoveryProvider(
            "REQUEST_ARCHIVE_TASK"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "AWAITING_CONFIRMATION"

    pending = load_pending_action(bundle)

    assert pending is not None
    assert pending.action == "ARCHIVE_TASK"
