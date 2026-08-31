"""Real-subprocess validation for local MCP Host interoperability."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters


EXPECTED_LOCAL_HOST_TOOLS = (
    "get_current_plan",
    "get_task_status",
    "inspect_dataset",
    "get_result_summary",
)
PROTECTED_TOOLS = {
    "provide_information",
    "prepare_task",
    "request_approval",
    "execute_ranker",
    "analyze_results",
}
CAPABILITY_RESOURCE = "binderranker://adapter/capabilities"


def _server_field(value: object | None, name: str) -> str | None:
    field = getattr(value, name, None)
    return field if isinstance(field, str) else None


def _installed_version() -> str:
    try:
        return version("binderranker")
    except PackageNotFoundError:
        return "0+unknown"


def _contains_text(value: object, needle: str) -> bool:
    if isinstance(value, str):
        return needle.casefold() in value.casefold()
    if isinstance(value, dict):
        return any(
            _contains_text(key, needle) or _contains_text(item, needle)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_text(item, needle) for item in value)
    return False


async def verify_local_mcp_host(
    *,
    python_executable: Path,
    workspace: Path,
    task_name: str,
) -> dict[str, Any]:
    """Exercise the same subprocess boundary used by a local Codex Host."""

    command_path = python_executable.absolute()
    resolved_command_path = python_executable.resolve()
    workspace_path = workspace.resolve()
    sensitive_values = tuple(
        dict.fromkeys(
            (
                str(workspace_path),
                str(command_path),
                str(resolved_command_path),
            )
        )
    )
    parameters = StdioServerParameters(
        command=str(command_path),
        args=[
            "-m",
            "protein_design_agent.adapters.mcp_entrypoint",
            "--workspace",
            str(workspace_path),
        ],
    )

    async with Client(
        parameters,
        read_timeout_seconds=30,
        mode="legacy",
    ) as client:
        server_name = _server_field(client.server_info, "name")
        server_version = _server_field(client.server_info, "version")
        if server_name != "BinderRanker":
            raise RuntimeError("unexpected MCP server identity")
        if server_version != _installed_version():
            raise RuntimeError("unexpected MCP server version")
        if not client.instructions or not client.instructions.startswith(
            "Read-only access"
        ):
            raise RuntimeError("read-only MCP server instructions missing")

        page = await client.list_tools()
        tool_names = tuple(tool.name for tool in page.tools)
        if tool_names != EXPECTED_LOCAL_HOST_TOOLS:
            raise RuntimeError("unexpected MCP Tool surface")

        all_tools_read_only = all(
            tool.annotations is not None
            and tool.annotations.read_only_hint is True
            and tool.annotations.destructive_hint is False
            for tool in page.tools
        )
        if not all_tools_read_only:
            raise RuntimeError("MCP Tool annotations are not read-only")

        status = await client.call_tool(
            "get_task_status",
            {"task_name": task_name},
        )
        if status.is_error or status.structured_content is None:
            raise RuntimeError("read-only task status call failed")
        if status.structured_content.get("ok") is not True:
            raise RuntimeError("task status response is not successful")
        if status.structured_content.get("current_stage") != "EMPTY":
            raise RuntimeError("probe task is not empty")

        rejected = await client.call_tool(
            "inspect_dataset",
            {"task_name": task_name},
        )
        if not rejected.is_error or rejected.structured_content is None:
            raise RuntimeError("empty dataset inspection did not fail closed")
        rejected_code = rejected.structured_content.get("error", {}).get(
            "code"
        )
        if rejected_code != "TOOL_REJECTED":
            raise RuntimeError("unexpected fail-closed error code")

        result_rejected = await client.call_tool(
            "get_result_summary",
            {"task_name": task_name, "limit": 5},
        )
        if (
            not result_rejected.is_error
            or result_rejected.structured_content is None
        ):
            raise RuntimeError("missing result summary did not fail closed")
        result_rejected_code = (
            result_rejected.structured_content.get("error", {}).get("code")
        )
        if result_rejected_code != "TOOL_REJECTED":
            raise RuntimeError("unexpected result-summary error code")

        resources = await client.list_resources()
        resource_uris = tuple(str(item.uri) for item in resources.resources)
        if resource_uris != (CAPABILITY_RESOURCE,):
            raise RuntimeError("unexpected MCP resource surface")

        capability_result = await client.read_resource(CAPABILITY_RESOURCE)
        if len(capability_result.contents) != 1:
            raise RuntimeError("capability resource is malformed")
        capability_text = getattr(capability_result.contents[0], "text", None)
        if not isinstance(capability_text, str):
            raise RuntimeError("capability resource is not JSON text")
        capabilities = json.loads(capability_text)
        expected_capabilities = {
            "read_only": True,
            "execution_operations_exposed": False,
            "host_paths_exposed": False,
            "scientific_evidence_status": "SCIENTIFIC_VALIDATION_PENDING",
        }
        actual_capabilities = {
            key: capabilities.get(key) for key in expected_capabilities
        }
        if actual_capabilities != expected_capabilities:
            raise RuntimeError("unexpected MCP capability boundary")

        raw_responses = (
            status.structured_content,
            rejected.structured_content,
            result_rejected.structured_content,
            capabilities,
        )
        if any(
            _contains_text(raw_responses, sensitive)
            for sensitive in sensitive_values
        ):
            raise RuntimeError("host path leaked from MCP response")

        report: dict[str, Any] = {
            "schema_version": "0.1",
            "host_contract": "GENERIC_LOCAL_MCP_HOST",
            "transport": "MCP_STDIO_SUBPROCESS",
            "client_mode": "legacy",
            "protocol_version": client.protocol_version,
            "server_name": server_name,
            "server_version": server_version,
            "server_instructions_received": True,
            "tool_names": list(tool_names),
            "all_tools_read_only": all_tools_read_only,
            "protected_tools_absent": not bool(
                PROTECTED_TOOLS.intersection(tool_names)
            ),
            "status_call": {
                "ok": status.structured_content.get("ok"),
                "current_stage": status.structured_content.get(
                    "current_stage"
                ),
            },
            "closed_failure_call": {
                "is_error": rejected.is_error,
                "error_code": rejected_code,
            },
            "result_summary_closed_failure_call": {
                "is_error": result_rejected.is_error,
                "error_code": result_rejected_code,
            },
            "capability_resource": {
                "read_only": capabilities.get("read_only"),
                "execution_operations_exposed": capabilities.get(
                    "execution_operations_exposed"
                ),
                "host_paths_exposed": capabilities.get(
                    "host_paths_exposed"
                ),
                "scientific_evidence_status": capabilities.get(
                    "scientific_evidence_status"
                ),
            },
            "host_paths_exposed": False,
        }

    encoded = json.dumps(report, sort_keys=True)
    if any(
        _contains_text(encoded, sensitive)
        for sensitive in sensitive_values
    ):
        raise RuntimeError("host path leaked into validation report")
    return report


__all__ = [
    "CAPABILITY_RESOURCE",
    "EXPECTED_LOCAL_HOST_TOOLS",
    "verify_local_mcp_host",
]
