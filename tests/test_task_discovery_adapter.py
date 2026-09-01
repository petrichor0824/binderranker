import asyncio
import json
from pathlib import Path

from mcp import Client

from protein_design_agent.adapters.mcp_server import create_mcp_server
from protein_design_agent.adapters.read_only import (
    ReadOnlyToolAdapter,
    TaskListAdapterResult,
)
from protein_design_agent.agent import tool_api
from protein_design_agent.agent.tool_adapter_errors import AdapterErrorEnvelope
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


def make_workspace(tmp_path: Path, *task_names: str) -> Path:
    workspace = tmp_path / "workspace"
    for task_name in task_names:
        (workspace / "runs" / task_name).mkdir(parents=True)
    (workspace / "runs").mkdir(parents=True, exist_ok=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace


def snapshot_tree(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    directories = tuple(
        sorted(
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_dir()
        )
    )
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    return directories, files


def test_tool_api_lists_tasks_deterministically_without_mutation(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path, "beta", "Alpha", "第一组")
    (workspace / "runs" / ".hidden").mkdir()
    (workspace / "runs" / "not_a_task.txt").write_text(
        "ignored",
        encoding="utf-8",
    )
    before = snapshot_tree(workspace)

    result = tool_api.list_tasks(workspace, offset=1, limit=1)

    assert result.total_task_count == 3
    assert result.returned_task_count == 1
    assert result.truncated is True
    assert result.next_offset == 2
    assert [item.task_name for item in result.tasks] == ["beta"]
    assert result.tasks[0].lifecycle_status == "AVAILABLE"
    assert result.tasks[0].current_stage == "EMPTY"
    assert result.tasks[0].sealed_result_status == "NOT_AVAILABLE"
    assert snapshot_tree(workspace) == before


def test_adapter_task_inventory_is_bounded_and_path_free(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path, "task_a", "task_b", "task_c")

    result = ReadOnlyToolAdapter(workspace).list_tasks(offset=0, limit=2)

    assert isinstance(result, TaskListAdapterResult)
    assert result.total_task_count == 3
    assert result.returned_task_count == 2
    assert result.next_offset == 2
    assert [item.task_name for item in result.tasks] == ["task_a", "task_b"]
    encoded = result.model_dump_json()
    assert str(workspace.resolve()) not in encoded
    assert "workspace_dir" not in encoded
    assert "bundle_dir" not in encoded


def test_task_inventory_isolates_malformed_task_state(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path, "bad_task", "good_task")
    (workspace / "runs" / "bad_task" / "agent_prepare_manifest.json").write_text(
        "not-json",
        encoding="utf-8",
    )

    result = ReadOnlyToolAdapter(workspace).list_tasks()

    assert isinstance(result, TaskListAdapterResult)
    by_name = {item.task_name: item for item in result.tasks}
    assert by_name["bad_task"].lifecycle_status == "INVALID"
    assert by_name["bad_task"].current_stage is None
    assert by_name["bad_task"].sealed_result_status == "NOT_AVAILABLE"
    assert by_name["good_task"].lifecycle_status == "AVAILABLE"
    assert by_name["good_task"].current_stage == "EMPTY"


def test_task_inventory_rejects_invalid_pagination_with_stable_error(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path, "task_a")
    adapter = ReadOnlyToolAdapter(workspace)

    invalid_offset = adapter.list_tasks(offset=-1)
    invalid_limit = adapter.invoke("list_tasks", limit=101)

    assert isinstance(invalid_offset, AdapterErrorEnvelope)
    assert invalid_offset.error.code == "INVALID_REQUEST"
    assert invalid_offset.error.validation_issues[0].location == "offset"
    assert isinstance(invalid_limit, AdapterErrorEnvelope)
    assert invalid_limit.error.code == "INVALID_REQUEST"
    assert invalid_limit.error.validation_issues[0].location == "limit"


def test_mcp_task_discovery_requires_no_preselected_task_name(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path, "task_a")
    server = create_mcp_server(workspace)

    async def exercise() -> None:
        async with Client(server, mode="legacy") as client:
            result = await client.call_tool(
                "list_tasks",
                {"offset": 0, "limit": 20},
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["operation"] == "list_tasks"
            assert result.structured_content["tasks"][0]["task_name"] == (
                "task_a"
            )
            assert str(workspace.resolve()) not in json.dumps(
                result.structured_content,
                sort_keys=True,
            )

    asyncio.run(exercise())
