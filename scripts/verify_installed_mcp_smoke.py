#!/usr/bin/env python3
"""Verify the optional MCP adapter from an installed BinderRanker Wheel."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import protein_design_agent
from mcp import Client

from protein_design_agent.adapters.local_host_validation import (
    verify_local_mcp_host,
)
from protein_design_agent.adapters.mcp_server import create_mcp_server
from protein_design_agent.adapters.tunnel_readiness import (
    assess_private_tunnel_readiness,
)
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
        assert client.server_info is not None
        assert client.server_info.name == "BinderRanker"
        assert client.server_info.version == version("binderranker")
        assert client.instructions is not None
        assert client.instructions.startswith("Read-only access")

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

subprocess_probe = asyncio.run(
    verify_local_mcp_host(
        python_executable=Path(sys.executable),
        workspace=root,
        task_name="smoke_task",
    )
)
assert subprocess_probe["transport"] == "MCP_STDIO_SUBPROCESS"
assert subprocess_probe["server_name"] == "BinderRanker"
assert subprocess_probe["server_version"] == version("binderranker")
assert subprocess_probe["tool_names"] == [
    "get_current_plan",
    "get_task_status",
    "inspect_dataset",
]
assert subprocess_probe["all_tools_read_only"] is True
assert subprocess_probe["protected_tools_absent"] is True
assert subprocess_probe["status_call"] == {
    "ok": True,
    "current_stage": "EMPTY",
}
assert subprocess_probe["closed_failure_call"] == {
    "is_error": True,
    "error_code": "TOOL_REJECTED",
}
assert str(root.resolve()) not in json.dumps(subprocess_probe)

tunnel_readiness = assess_private_tunnel_readiness(root)
assert tunnel_readiness.local_preflight_passed is True
assert tunnel_readiness.status == "READY_FOR_PRIVATE_TUNNEL_CONFIGURATION"
assert tunnel_readiness.public_network_listener_exposed is False
assert tunnel_readiness.protected_operations_exposed is False
assert tunnel_readiness.openai_control_plane_access_verified is False
assert tunnel_readiness.live_tunnel_connection_verified is False

preflight = subprocess.run(
    [
        sys.executable,
        "-m",
        "protein_design_agent.adapters.mcp_entrypoint",
        "--workspace",
        str(root),
        "--check-tunnel-readiness",
    ],
    text=True,
    capture_output=True,
    check=False,
)
assert preflight.returncode == 0, preflight.stderr
preflight_payload = json.loads(preflight.stdout)
assert preflight_payload["local_preflight_passed"] is True
assert preflight_payload["live_tunnel_connection_verified"] is False
assert str(root.resolve()) not in preflight.stdout

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
    "passed the real stdio subprocess contract, returned structured "
    "path-free evidence, preserved stable errors, and passed the local "
    "private-tunnel readiness contract"
)
