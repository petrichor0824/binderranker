import json
from pathlib import Path

import pytest

from protein_design_agent.agent.task_navigation import (
    TaskNavigationError,
    list_workspace_tasks,
    resolve_task_reference,
)


class FakeSelectionProvider:
    def generate_json(self, messages):
        return {
            "task_name": "group_c",
            "reason": "用户指的是第三个任务",
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
            "workspace_type": (
                "protein-design-agent"
            ),
        }),
        encoding="utf-8",
    )

    for name in (
        "default",
        "group_a",
        "group_b",
        "group_c",
    ):
        bundle = runs / name
        bundle.mkdir()

        (
            bundle
            / "agent_prepare_manifest.json"
        ).write_text(
            json.dumps({
                "status": "NEEDS_INFORMATION",
            }),
            encoding="utf-8",
        )

    return workspace, runs / "default"


def test_lists_arbitrary_number_of_tasks(
    tmp_path: Path,
) -> None:
    _workspace, current = make_workspace(
        tmp_path
    )

    tasks = list_workspace_tasks(current)

    assert [
        task.task_name
        for task in tasks
    ] == [
        "default",
        "group_a",
        "group_b",
        "group_c",
    ]

    assert sum(
        task.is_current
        for task in tasks
    ) == 1


def test_direct_task_name_is_resolved(
    tmp_path: Path,
) -> None:
    _workspace, current = make_workspace(
        tmp_path
    )

    target = resolve_task_reference(
        current_bundle=current,
        message="切换到 group_b",
        provider=None,
    )

    assert target.name == "group_b"


def test_model_can_resolve_indirect_reference(
    tmp_path: Path,
) -> None:
    _workspace, current = make_workspace(
        tmp_path
    )

    target = resolve_task_reference(
        current_bundle=current,
        message="进入第三组",
        provider=FakeSelectionProvider(),
    )

    assert target.name == "group_c"


def test_unknown_task_is_rejected(
    tmp_path: Path,
) -> None:
    _workspace, current = make_workspace(
        tmp_path
    )

    with pytest.raises(
        TaskNavigationError,
    ):
        resolve_task_reference(
            current_bundle=current,
            message="不存在的任务",
            provider=None,
        )
