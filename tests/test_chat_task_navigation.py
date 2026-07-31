import json
from pathlib import Path

from protein_design_agent.agent.chat_dialogue import (
    process_dialogue_message,
)


def make_navigation_workspace(
    tmp_path: Path,
) -> tuple[Path, Path]:
    workspace = tmp_path / ".protein-design-agent"
    runs = workspace / "runs"
    current = runs / "default"
    target = runs / "group_b"

    current.mkdir(parents=True)
    target.mkdir()

    (
        workspace / ".pda-workspace.json"
    ).write_text(
        json.dumps({
            "schema_version": "0.1",
            "workspace_type": (
                "protein-design-agent"
            ),
        }),
        encoding="utf-8",
    )

    return current, target


def test_offline_task_switch_shortcut(
    tmp_path: Path,
) -> None:
    current, target = make_navigation_workspace(
        tmp_path
    )

    pending = (
        current
        / "chat"
        / "pending_action.json"
    )
    pending.parent.mkdir()
    pending.write_text(
        "{}",
        encoding="utf-8",
    )

    result = process_dialogue_message(
        message="/task group_b",
        bundle_dir=current,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "SWITCH_TASK"
    assert result.bundle_dir == target.resolve()

    # 切换不应删除或消费原任务的待确认动作。
    assert pending.is_file()


def test_offline_task_list_shortcut(
    tmp_path: Path,
) -> None:
    current, _target = (
        make_navigation_workspace(tmp_path)
    )

    result = process_dialogue_message(
        message="/tasks",
        bundle_dir=current,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "LIST_TASKS"
    assert "default" in result.message
    assert "group_b" in result.message
