"""Official-SDK MCP server for BinderRanker's read-only Tool adapter."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Generic, TypeAlias, TypeVar

from pydantic import ConfigDict, Field, RootModel

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from protein_design_agent.adapters.read_only import (
    CurrentPlanAdapterResponse,
    DatasetInspectionAdapterResponse,
    ReadOnlyToolAdapter,
    TaskStatusAdapterResponse,
)
from protein_design_agent.agent.tool_adapter_errors import AdapterErrorEnvelope


TaskNameArgument: TypeAlias = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        description=(
            "Name of an existing BinderRanker task under the configured "
            "workspace runs directory. Paths are not accepted."
        ),
    ),
]


MCPOutputT = TypeVar("MCPOutputT")


class _ObjectMCPOutput(RootModel[MCPOutputT], Generic[MCPOutputT]):
    """Keep structured Tool outputs valid on legacy MCP protocol surfaces."""

    model_config = ConfigDict(json_schema_extra={"type": "object"})


class CurrentPlanMCPOutput(_ObjectMCPOutput[CurrentPlanAdapterResponse]):
    """MCP structured output for ``get_current_plan``."""


class TaskStatusMCPOutput(_ObjectMCPOutput[TaskStatusAdapterResponse]):
    """MCP structured output for ``get_task_status``."""


class DatasetInspectionMCPOutput(
    _ObjectMCPOutput[DatasetInspectionAdapterResponse]
):
    """MCP structured output for ``inspect_dataset``."""


_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _binderranker_version() -> str:
    try:
        return version("binderranker")
    except PackageNotFoundError:
        return "0+unknown"


def _call_result(value: object) -> CallToolResult:
    if not hasattr(value, "model_dump"):
        raise TypeError("adapter result must be a Pydantic model")

    payload = value.model_dump(mode="json")
    is_error = isinstance(value, AdapterErrorEnvelope)
    if is_error:
        message = value.error.message
    else:
        operation = payload.get("operation", "read_only_tool")
        message = f"BinderRanker {operation} returned structured evidence."

    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structured_content=payload,
        is_error=is_error,
    )


def create_mcp_server(workspace_dir: Path) -> MCPServer:
    """Build a stdio-ready server bound to one initialized workspace."""

    adapter = ReadOnlyToolAdapter(workspace_dir)
    server = MCPServer(
        "BinderRanker",
        version=_binderranker_version(),
        instructions=(
            "Read-only access to managed BinderRanker task plans, lifecycle "
            "status, and deterministic dataset inspection. This server does "
            "not prepare, approve, execute, or analyze tasks. BinderRanker "
            "scientific performance remains unvalidated pending real data."
        ),
    )

    @server.tool(
        title="Get BinderRanker current plan",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_current_plan(
        task_name: TaskNameArgument,
    ) -> Annotated[CallToolResult, CurrentPlanMCPOutput]:
        """Read the canonical plan for an existing managed task."""

        return _call_result(adapter.get_current_plan(task_name))

    @server.tool(
        title="Get BinderRanker task status",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_task_status(
        task_name: TaskNameArgument,
    ) -> Annotated[CallToolResult, TaskStatusMCPOutput]:
        """Read planning and execution lifecycle state for a managed task."""

        return _call_result(adapter.get_task_status(task_name))

    @server.tool(
        title="Inspect BinderRanker PDB dataset",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def inspect_dataset(
        task_name: TaskNameArgument,
    ) -> Annotated[CallToolResult, DatasetInspectionMCPOutput]:
        """Inspect the dataset recorded by a managed task without modifying it."""

        return _call_result(adapter.inspect_dataset(task_name))

    @server.resource(
        "binderranker://adapter/capabilities",
        title="BinderRanker adapter capabilities",
        description="Read-only safety and capability profile for this server.",
        mime_type="application/json",
    )
    def adapter_capabilities() -> str:
        return adapter.capabilities().model_dump_json()

    return server


def run_mcp_server(workspace_dir: Path) -> None:
    """Run the local server over MCP stdio until the host disconnects."""

    create_mcp_server(workspace_dir).run()


__all__ = [
    "CurrentPlanMCPOutput",
    "DatasetInspectionMCPOutput",
    "TaskStatusMCPOutput",
    "create_mcp_server",
    "run_mcp_server",
]
