import asyncio
import json
from importlib.metadata import version
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import TextContent

from protein_design_agent.adapters.mcp_server import create_mcp_server
from protein_design_agent.adapters.mcp_entrypoint import main as mcp_main
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "runs" / "task_a").mkdir(parents=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace


def test_mcp_server_exposes_only_read_only_workspace_scoped_tools(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(make_workspace(tmp_path))

    async def exercise() -> None:
        async with Client(server) as client:
            assert client.server_info is not None
            assert client.server_info.name == "BinderRanker"
            assert client.server_info.version == version("binderranker")
            assert client.instructions is not None
            assert client.instructions.startswith("Read-only access")

            page = await client.list_tools()
            assert [tool.name for tool in page.tools] == [
                "get_current_plan",
                "get_task_status",
                "inspect_dataset",
            ]

            for tool in page.tools:
                assert set(tool.input_schema["properties"]) == {"task_name"}
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is False
                assert tool.output_schema is not None

            assert "execute_ranker" not in {tool.name for tool in page.tools}
            assert "request_approval" not in {tool.name for tool in page.tools}

    asyncio.run(exercise())


def test_mcp_success_and_failure_use_structured_non_sensitive_results(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    server = create_mcp_server(workspace)

    async def exercise() -> None:
        async with Client(server) as client:
            success = await client.call_tool(
                "get_task_status",
                {"task_name": "task_a"},
            )
            assert success.is_error is False
            assert success.structured_content is not None
            assert success.structured_content["ok"] is True
            assert success.structured_content["operation"] == "get_task_status"
            assert success.structured_content["current_stage"] == "EMPTY"
            assert str(workspace.resolve()) not in json.dumps(
                success.structured_content,
                sort_keys=True,
            )

            failure = await client.call_tool(
                "inspect_dataset",
                {"task_name": "task_a"},
            )
            assert failure.is_error is True
            assert failure.structured_content is not None
            assert failure.structured_content["ok"] is False
            assert failure.structured_content["error"]["code"] == "TOOL_REJECTED"
            assert str(workspace.resolve()) not in json.dumps(
                failure.structured_content,
                sort_keys=True,
            )
            assert len(failure.content) == 1
            assert isinstance(failure.content[0], TextContent)
            assert "planning_session.json" not in failure.content[0].text

    asyncio.run(exercise())


def test_mcp_capability_resource_declares_deferred_execution(
    tmp_path: Path,
) -> None:
    server = create_mcp_server(make_workspace(tmp_path))

    async def exercise() -> None:
        async with Client(server) as client:
            resources = await client.list_resources()
            assert [str(item.uri) for item in resources.resources] == [
                "binderranker://adapter/capabilities"
            ]

            result = await client.read_resource(
                "binderranker://adapter/capabilities"
            )
            assert len(result.contents) == 1
            payload = json.loads(result.contents[0].text)
            assert payload["read_only"] is True
            assert payload["execution_operations_exposed"] is False
            assert "execute_ranker" in payload["deferred_operations"]
            assert payload["scientific_evidence_status"] == (
                "SCIENTIFIC_VALIDATION_PENDING"
            )

    asyncio.run(exercise())


def test_mcp_documentation_preserves_scope_and_remote_boundary() -> None:
    document = Path("docs/integrations/MCP.md").read_text(encoding="utf-8")
    security = Path(
        "docs/integrations/REMOTE_MCP_SECURITY.md"
    ).read_text(encoding="utf-8")
    codex_local = Path(
        "docs/integrations/CODEX_LOCAL_MCP.md"
    ).read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh = Path("README.zh-CN.md").read_text(encoding="utf-8")

    for required in (
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
        "task_name",
        "local `stdio` only",
        "--check-tunnel-readiness",
        "Secure MCP Tunnel",
        "SCIENTIFIC_VALIDATION_PENDING",
        "Do not expose this local server directly",
    ):
        assert required in document

    assert "docs/integrations/MCP.md" in readme
    assert "docs/integrations/MCP.md" in readme_zh
    assert "docs/integrations/REMOTE_MCP_SECURITY.md" in readme
    assert "docs/integrations/REMOTE_MCP_SECURITY.md" in readme_zh
    assert "docs/integrations/CODEX_LOCAL_MCP.md" in readme
    assert "docs/integrations/CODEX_LOCAL_MCP.md" in readme_zh

    for required in (
        "outbound-only",
        "single trust domain",
        "Do not add a public HTTP listener",
        "MCP_SDK_NOT_INSTALLED",
        "openai_control_plane_access_verified",
        "live_tunnel_connection_verified",
        "approval cannot create BinderRanker's",
    ):
        assert required in security

    for required in (
        "requires no",
        "OpenAI API key",
        "stdio subprocess",
        "enabled_tools",
        'default_tools_approval_mode = "writes"',
        "SCIENTIFIC_VALIDATION_PENDING",
        "Remote Secure MCP Tunnel acceptance remains",
    ):
        assert required in codex_local


def test_mcp_entrypoint_reports_invalid_workspace_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        mcp_main(["--workspace", str(tmp_path)])

    assert raised.value.code == 2
    stderr = capsys.readouterr().err
    assert "configuration error" in stderr
    assert "Traceback" not in stderr
