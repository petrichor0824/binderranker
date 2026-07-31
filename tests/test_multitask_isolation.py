import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.chat_dialogue as dialogue
from protein_design_agent.agent.chat_dialogue import (
    ChatDialogueError,
    load_pending_action,
    process_dialogue_message,
)
from protein_design_agent.agent.chat_session import (
    ChatTurnResult,
)


class FakeDialogueProvider:
    def __init__(self, intent: str) -> None:
        self.intent = intent

    @property
    def name(self) -> str:
        return "fake-provider"

    def parse_user_request(self, raw_text):
        raise AssertionError(
            "任务隔离测试不应调用请求解析"
        )

    def generate_json(self, messages):
        return {
            "intent": self.intent,
            "reason": "multitask isolation test",
        }


def write_json(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def make_workspace(
    tmp_path: Path,
) -> tuple[Path, Path]:
    workspace = (
        tmp_path / ".protein-design-agent"
    )
    runs = workspace / "runs"
    group_a = runs / "group_a"
    group_b = runs / "group_b"

    group_a.mkdir(parents=True)
    group_b.mkdir()

    write_json(
        workspace / ".pda-workspace.json",
        {
            "schema_version": "0.1",
            "workspace_type": (
                "protein-design-agent"
            ),
        },
    )

    for bundle in (group_a, group_b):
        write_json(
            bundle
            / "agent_prepare_manifest.json",
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
                "project_name": bundle.name,
                "scientific_workflow_executed": (
                    False
                ),
                "binderranker_executed": False,
                "remote_backend_used": False,
            },
        )

    return group_a, group_b


def run_status(bundle_dir: Path):
    bundle = bundle_dir.resolve()

    return SimpleNamespace(
        current_stage="PREPARED",
        project_name=bundle.name,
        analysis_scope_level=(
            "SMOKE_TEST_ONLY"
        ),
        approval_status=(
            "APPROVED"
            if (bundle / "approval.json").is_file()
            else None
        ),
        execution_status=None,
    )


def test_task_approval_and_execution_are_isolated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    group_a, group_b = make_workspace(
        tmp_path
    )

    monkeypatch.setattr(
        dialogue,
        "inspect_run_status",
        run_status,
    )

    monkeypatch.setattr(
        dialogue,
        "inspect_bundle",
        lambda bundle_dir: (
            None,
            run_status(bundle_dir),
        ),
    )

    engine_calls: list[
        tuple[str, Path]
    ] = []

    def fake_engine(**kwargs):
        message = kwargs["message"]
        bundle = Path(
            kwargs["bundle_dir"]
        ).resolve()

        engine_calls.append(
            (message, bundle)
        )

        if message != (
            "批准计划并确认小样本限制"
        ):
            raise AssertionError(
                "未批准任务不应进入确定性执行引擎"
            )

        write_json(
            bundle / "approval.json",
            {
                "schema_version": "0.1",
                "status": "APPROVED",
                "approval_id": "apr_group_a",
                "approved_by": "tester",
            },
        )

        return ChatTurnResult(
            action="APPROVE",
            status="APPROVED",
            message="计划已批准",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        dialogue,
        "process_chat_message",
        fake_engine,
    )

    proposal = process_dialogue_message(
        message="批准当前任务",
        bundle_dir=group_a,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert proposal.status == (
        "AWAITING_CONFIRMATION"
    )

    assert load_pending_action(
        group_a
    ) is not None

    assert load_pending_action(
        group_b
    ) is None

    confirmation = process_dialogue_message(
        message="确认",
        bundle_dir=group_a,
        provider=FakeDialogueProvider(
            "CONFIRM"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert confirmation.status == "APPROVED"
    assert load_pending_action(group_a) is None

    group_a_approval = (
        group_a / "approval.json"
    )

    assert group_a_approval.is_file()
    assert not (
        group_b / "approval.json"
    ).exists()

    approval_before_switch = (
        group_a_approval.read_bytes()
    )
    manifest_before_switch = (
        group_a
        / "agent_prepare_manifest.json"
    ).read_bytes()

    switched = process_dialogue_message(
        message="/task group_b",
        bundle_dir=group_a,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert switched.action == "SWITCH_TASK"
    assert switched.bundle_dir == (
        group_b.resolve()
    )

    assert group_a_approval.read_bytes() == (
        approval_before_switch
    )
    assert (
        group_a
        / "agent_prepare_manifest.json"
    ).read_bytes() == manifest_before_switch

    with pytest.raises(ChatDialogueError):
        process_dialogue_message(
            message="执行当前任务",
            bundle_dir=switched.bundle_dir,
            provider=FakeDialogueProvider(
                "REQUEST_EXECUTION"
            ),
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=True,
        )

    # group_b 没有借用 group_a 的批准。
    assert not (
        group_b / "approval.json"
    ).exists()
    assert load_pending_action(group_b) is None

    # 确定性引擎只接收过 group_a 的批准。
    assert engine_calls == [
        (
            "批准计划并确认小样本限制",
            group_a.resolve(),
        )
    ]

    # group_b 的拒绝不会改变 group_a。
    assert group_a_approval.read_bytes() == (
        approval_before_switch
    )
