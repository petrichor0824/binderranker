#!/usr/bin/env python3
"""Verify the optional MCP adapter from an installed BinderRanker Wheel."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import protein_design_agent
from mcp import Client

from protein_design_agent.adapters.mcp_server import create_mcp_server
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


root = Path(tempfile.gettempdir()) / "binderranker-mcp-wheel-smoke"
shutil.rmtree(root, ignore_errors=True)
bundle = root / "runs" / "smoke_task"
bundle.mkdir(parents=True)
(root / ".pda-workspace.json").write_text(
    WORKSPACE_MARKER_TEMPLATE,
    encoding="utf-8",
)


async def verify() -> None:
    server = create_mcp_server(root)
    async with Client(server) as client:
        page = await client.list_tools()
        names = [tool.name for tool in page.tools]
        assert names == [
            "get_current_plan",
            "get_task_status",
            "inspect_dataset",
        ]
        assert all(
            tool.annotations is not None
            and tool.annotations.read_only_hint is True
            for tool in page.tools
        )

        status = await client.call_tool(
            "get_task_status",
            {"task_name": "smoke_task"},
        )
        assert status.is_error is False
        assert status.structured_content is not None
        assert status.structured_content["current_stage"] == "EMPTY"
        assert str(root.resolve()) not in json.dumps(status.structured_content)

        rejected = await client.call_tool(
            "inspect_dataset",
            {"task_name": "smoke_task"},
        )
        assert rejected.is_error is True
        assert rejected.structured_content is not None
        assert rejected.structured_content["error"]["code"] == "TOOL_REJECTED"

        resources = await client.list_resources()
        assert [str(item.uri) for item in resources.resources] == [
            "binderranker://adapter/capabilities"
        ]


asyncio.run(verify())

package_path = Path(protein_design_agent.__file__).resolve()
repository_root = Path(__file__).resolve().parents[1]
environment_root = Path(__import__("sys").prefix).resolve()

assert not package_path.is_relative_to(repository_root), (
    f"package imported from repository: {package_path}"
)
assert package_path.is_relative_to(environment_root), (
    f"package not imported from active environment: {package_path}"
)

print(
    "PASS: installed BinderRanker MCP extra exposed three read-only tools, "
    "returned structured path-free evidence, and preserved stable errors"
)
