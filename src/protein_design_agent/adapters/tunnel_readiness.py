"""Deterministic local readiness contract for private MCP tunneling.

The report deliberately covers only facts BinderRanker can verify locally.
OpenAI organization permissions, tunnel creation, runtime authentication, and
live connectivity remain external control-plane facts and are never inferred.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from protein_design_agent.adapters.read_only import (
    DEFERRED_ADAPTER_OPERATIONS,
    READ_ONLY_ADAPTER_OPERATIONS,
    ReadOnlyAdapterConfigurationError,
    ReadOnlyToolAdapter,
)


TUNNEL_READINESS_SCHEMA_VERSION = "0.1"
TunnelReadinessBlocker = Literal[
    "WORKSPACE_INVALID_OR_UNSAFE",
    "MCP_SDK_NOT_INSTALLED",
    "MCP_SDK_VERSION_UNSUPPORTED",
]


class PrivateTunnelReadinessReport(BaseModel):
    """Path-free local preflight for a private stdio tunnel deployment."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    schema_version: Literal["0.1"] = TUNNEL_READINESS_SCHEMA_VERSION
    provider: Literal["OPENAI_SECURE_MCP_TUNNEL"] = (
        "OPENAI_SECURE_MCP_TUNNEL"
    )
    status: Literal[
        "READY_FOR_PRIVATE_TUNNEL_CONFIGURATION",
        "BLOCKED",
    ]
    local_preflight_passed: bool
    workspace_valid: bool
    mcp_sdk_installed: bool
    mcp_sdk_version: str | None = None
    mcp_sdk_version_supported: bool
    local_transport: Literal["MCP_STDIO"] = "MCP_STDIO"
    tunnel_target_mode: Literal["STDIO_COMMAND"] = "STDIO_COMMAND"
    public_network_listener_exposed: Literal[False] = False
    inbound_firewall_port_required: Literal[False] = False
    workspace_scope: Literal["SINGLE_WORKSPACE_PER_PROCESS"] = (
        "SINGLE_WORKSPACE_PER_PROCESS"
    )
    tenant_scope: Literal["SINGLE_TRUST_DOMAIN"] = "SINGLE_TRUST_DOMAIN"
    exposed_operations: tuple[str, ...] = READ_ONLY_ADAPTER_OPERATIONS
    deferred_operations: tuple[str, ...] = DEFERRED_ADAPTER_OPERATIONS
    read_only: Literal[True] = True
    protected_operations_exposed: Literal[False] = False
    caller_identity_contract_available: Literal[False] = False
    trusted_human_confirmation_bridge_available: Literal[False] = False
    openai_control_plane_access_verified: Literal[False] = False
    live_tunnel_connection_verified: Literal[False] = False
    scientific_evidence_status: Literal[
        "SCIENTIFIC_VALIDATION_PENDING"
    ] = "SCIENTIFIC_VALIDATION_PENDING"
    blocking_reasons: tuple[TunnelReadinessBlocker, ...] = ()


def installed_mcp_version() -> str | None:
    """Return installed official MCP SDK version without importing the SDK."""

    try:
        return version("mcp")
    except PackageNotFoundError:
        return None


def is_supported_mcp_version(value: str | None) -> bool:
    """BinderRanker's optional dependency contract currently accepts v2."""

    if value is None:
        return False

    major, separator, _remainder = value.partition(".")
    return bool(separator) and major == "2"


def assess_private_tunnel_readiness(
    workspace_dir: Path,
) -> PrivateTunnelReadinessReport:
    """Assess locally provable prerequisites without contacting OpenAI."""

    workspace_valid = True
    try:
        ReadOnlyToolAdapter(workspace_dir)
    except ReadOnlyAdapterConfigurationError:
        workspace_valid = False

    sdk_version = installed_mcp_version()
    sdk_installed = sdk_version is not None
    sdk_supported = is_supported_mcp_version(sdk_version)

    blockers: list[TunnelReadinessBlocker] = []
    if not workspace_valid:
        blockers.append("WORKSPACE_INVALID_OR_UNSAFE")
    if not sdk_installed:
        blockers.append("MCP_SDK_NOT_INSTALLED")
    elif not sdk_supported:
        blockers.append("MCP_SDK_VERSION_UNSUPPORTED")

    passed = not blockers
    return PrivateTunnelReadinessReport(
        status=(
            "READY_FOR_PRIVATE_TUNNEL_CONFIGURATION"
            if passed
            else "BLOCKED"
        ),
        local_preflight_passed=passed,
        workspace_valid=workspace_valid,
        mcp_sdk_installed=sdk_installed,
        mcp_sdk_version=sdk_version,
        mcp_sdk_version_supported=sdk_supported,
        blocking_reasons=tuple(blockers),
    )


__all__ = [
    "PrivateTunnelReadinessReport",
    "TUNNEL_READINESS_SCHEMA_VERSION",
    "TunnelReadinessBlocker",
    "assess_private_tunnel_readiness",
    "installed_mcp_version",
    "is_supported_mcp_version",
]
