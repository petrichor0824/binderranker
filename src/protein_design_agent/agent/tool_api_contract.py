#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Versioned, machine-readable contract for the BinderRanker Tool API.

The contract intentionally separates adapter-visible request fields from the
internal Python function signatures in :mod:`tool_api`.  In particular, user
identity and execution authorization are host-runtime facts and are never
accepted from a model-authored tool request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from protein_design_agent.agent.analyze_run import AnalyzeRunResult
from protein_design_agent.agent.approval import ApprovalRecord
from protein_design_agent.agent.dataset_advisor import DatasetPlanningAdvice
from protein_design_agent.agent.local_executor import CompletedLocalExecution
from protein_design_agent.agent.planning_session_prepare import (
    NaturalLanguagePrepareResult,
)
from protein_design_agent.agent.planning_session_resume import (
    ResumePlanningResult,
    SupplementExtraction,
)
from protein_design_agent.agent.request_evidence import RequestExtraction
from protein_design_agent.agent.tool_api import (
    CurrentPlanResult,
    SealedResultSummaryResult,
    TaskStatusResult,
)
from protein_design_agent.agent.tool_adapter_errors import (
    ADAPTER_ERROR_CODES,
    ADAPTER_ERROR_SCHEMA_VERSION,
    AdapterErrorCode,
    adapter_error_json_schema,
)


TOOL_API_CONTRACT_VERSION = "0.2"
TOOL_API_SCHEMA_VERSION = "0.1"
UNTRUSTED_REQUEST_FORBIDDEN_FIELDS = frozenset(
    {
        "provider_name",
        "approved_by",
        "approval_confirmed",
        "approval_note",
        "acknowledge_smoke_test",
        "execution_confirmed",
    }
)


class _StrictContractModel(BaseModel):
    """Base model for adapter-facing contract values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class BundleToolRequest(_StrictContractModel):
    """Adapter-visible request for a tool scoped to one task bundle."""

    bundle_dir: Path


class ProvideInformationToolRequest(BundleToolRequest):
    """Validated supplemental information supplied by the user."""

    supplement_text: str = Field(min_length=1)
    extraction: SupplementExtraction


class PrepareTaskToolRequest(BundleToolRequest):
    """Validated initial task information supplied by the user."""

    raw_text: str = Field(min_length=1)
    extraction: RequestExtraction


class RequestApprovalToolRequest(BundleToolRequest):
    """Model-visible approval request, without trusted authorization facts."""


class ExecuteRankerToolRequest(BundleToolRequest):
    """Model-visible execution request, without user confirmation fields."""


ToolSideEffect = Literal[
    "READ_ONLY",
    "MUTATING_NON_EXECUTING",
    "AUTHORIZATION_CHANGING",
    "EXECUTING",
    "APPEND_ONLY_ARTIFACT",
]

ToolAuthorizationRequirement = Literal[
    "NONE",
    "TRUSTED_USER_PLAN_APPROVAL",
    "TRUSTED_USER_EXECUTION_CONFIRMATION",
]


class ToolOperationContract(_StrictContractModel):
    """One stable Tool operation and its machine-readable schemas."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    summary: str = Field(min_length=1)
    side_effect: ToolSideEffect
    authorization_requirement: ToolAuthorizationRequirement
    host_injected_fields: tuple[str, ...] = ()
    trusted_runtime_entrypoint: str | None = None

    input_schema_name: str
    output_schema_name: str
    input_json_schema: dict[str, Any]
    output_json_schema: dict[str, Any]


class ToolAPICatalog(_StrictContractModel):
    """Stable public catalog consumed by HTTP, MCP, and Agent adapters."""

    schema_version: Literal["0.1"] = TOOL_API_SCHEMA_VERSION
    api_name: Literal["BinderRanker Tool API"] = "BinderRanker Tool API"
    contract_version: Literal["0.2"] = TOOL_API_CONTRACT_VERSION

    path_semantics: Literal["HOST_LOCAL_PATH"] = "HOST_LOCAL_PATH"
    scientific_evidence_status: Literal[
        "SCIENTIFIC_VALIDATION_PENDING"
    ] = "SCIENTIFIC_VALIDATION_PENDING"
    performance_claims_established: Literal[False] = False
    model_supplied_authorization_accepted: Literal[False] = False
    authorization_transport: Literal[
        "IN_PROCESS_OPAQUE_CAPABILITY"
    ] = "IN_PROCESS_OPAQUE_CAPABILITY"
    authorization_grant_json_serializable: Literal[False] = False
    authorization_grant_single_use: Literal[True] = True
    authorization_grant_review_resource_bound: Literal[True] = True
    authorization_grant_default_ttl_seconds: Literal[300] = 300
    adapter_error_schema_version: Literal["0.1"] = (
        ADAPTER_ERROR_SCHEMA_VERSION
    )
    adapter_error_schema_name: Literal[
        "AdapterErrorEnvelope"
    ] = "AdapterErrorEnvelope"
    adapter_error_codes: tuple[AdapterErrorCode, ...] = ADAPTER_ERROR_CODES
    adapter_error_internal_details_exposed: Literal[False] = False
    adapter_error_automatic_retry_safe: Literal[False] = False
    adapter_error_json_schema: dict[str, Any] = Field(
        default_factory=adapter_error_json_schema
    )

    tool_count: int = Field(ge=1)
    tools: tuple[ToolOperationContract, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> "ToolAPICatalog":
        """Reject incomplete or ambiguous catalogs."""

        if self.tool_count != len(self.tools):
            raise ValueError("tool_count must match the number of tools")

        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")

        if self.adapter_error_codes != ADAPTER_ERROR_CODES:
            raise ValueError(
                "adapter error codes must match the published profile"
            )

        if self.adapter_error_json_schema.get("type") != "object":
            raise ValueError("adapter error schema must describe an object")

        for tool in self.tools:
            request_fields = set(
                tool.input_json_schema.get("properties", {})
            )
            leaked_fields = request_fields.intersection(
                UNTRUSTED_REQUEST_FORBIDDEN_FIELDS
            )
            if leaked_fields:
                fields = ", ".join(sorted(leaked_fields))
                raise ValueError(
                    f"untrusted request schema exposes host fields: {fields}"
                )

            injected_fields = set(tool.host_injected_fields)
            if injected_fields.intersection(request_fields):
                raise ValueError(
                    "host-injected fields must not appear in the "
                    "untrusted request schema"
                )

            if (
                tool.authorization_requirement != "NONE"
                and (
                    not tool.host_injected_fields
                    or not tool.trusted_runtime_entrypoint
                )
            ):
                raise ValueError(
                    "protected tools must declare host-injected fields "
                    "and a trusted runtime entrypoint"
                )

            if (
                tool.authorization_requirement == "NONE"
                and tool.trusted_runtime_entrypoint is not None
            ):
                raise ValueError(
                    "unprotected tools must not declare a trusted "
                    "authorization entrypoint"
                )

        return self


def _schema(
    model: type[BaseModel],
    *,
    mode: Literal["validation", "serialization"],
) -> dict[str, Any]:
    """Return one JSON Schema without retaining mutable global state."""

    return model.model_json_schema(mode=mode)


def _operation(
    *,
    name: str,
    summary: str,
    side_effect: ToolSideEffect,
    authorization_requirement: ToolAuthorizationRequirement,
    host_injected_fields: tuple[str, ...] = (),
    trusted_runtime_entrypoint: str | None = None,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
) -> ToolOperationContract:
    return ToolOperationContract(
        name=name,
        summary=summary,
        side_effect=side_effect,
        authorization_requirement=authorization_requirement,
        host_injected_fields=host_injected_fields,
        trusted_runtime_entrypoint=trusted_runtime_entrypoint,
        input_schema_name=request_model.__name__,
        output_schema_name=response_model.__name__,
        input_json_schema=_schema(request_model, mode="validation"),
        output_json_schema=_schema(response_model, mode="serialization"),
    )


def get_tool_api_catalog() -> ToolAPICatalog:
    """Build the deterministic v0.2 contract for all nine public tools."""

    tools = (
        _operation(
            name="get_current_plan",
            summary="Read the current canonical planning state.",
            side_effect="READ_ONLY",
            authorization_requirement="NONE",
            request_model=BundleToolRequest,
            response_model=CurrentPlanResult,
        ),
        _operation(
            name="get_task_status",
            summary="Read planning and execution lifecycle status.",
            side_effect="READ_ONLY",
            authorization_requirement="NONE",
            request_model=BundleToolRequest,
            response_model=TaskStatusResult,
        ),
        _operation(
            name="provide_information",
            summary="Append validated user evidence and resume planning.",
            side_effect="MUTATING_NON_EXECUTING",
            authorization_requirement="NONE",
            request_model=ProvideInformationToolRequest,
            response_model=ResumePlanningResult,
        ),
        _operation(
            name="prepare_task",
            summary="Create a task bundle from validated user evidence.",
            side_effect="MUTATING_NON_EXECUTING",
            authorization_requirement="NONE",
            host_injected_fields=("provider_name",),
            request_model=PrepareTaskToolRequest,
            response_model=NaturalLanguagePrepareResult,
        ),
        _operation(
            name="inspect_dataset",
            summary="Inspect the planned PDB dataset without modifying it.",
            side_effect="READ_ONLY",
            authorization_requirement="NONE",
            request_model=BundleToolRequest,
            response_model=DatasetPlanningAdvice,
        ),
        _operation(
            name="request_approval",
            summary="Request a one-use execution approval from the host.",
            side_effect="AUTHORIZATION_CHANGING",
            authorization_requirement="TRUSTED_USER_PLAN_APPROVAL",
            host_injected_fields=(
                "approved_by",
                "approval_confirmed",
                "approval_note",
                "acknowledge_smoke_test",
            ),
            trusted_runtime_entrypoint=(
                "TrustedToolRuntime.request_approval"
            ),
            request_model=RequestApprovalToolRequest,
            response_model=ApprovalRecord,
        ),
        _operation(
            name="execute_ranker",
            summary="Execute an approved BinderRanker task once.",
            side_effect="EXECUTING",
            authorization_requirement="TRUSTED_USER_EXECUTION_CONFIRMATION",
            host_injected_fields=("execution_confirmed",),
            trusted_runtime_entrypoint=(
                "TrustedToolRuntime.execute_ranker"
            ),
            request_model=ExecuteRankerToolRequest,
            response_model=CompletedLocalExecution,
        ),
        _operation(
            name="analyze_results",
            summary="Create a new append-only deterministic analysis artifact.",
            side_effect="APPEND_ONLY_ARTIFACT",
            authorization_requirement="NONE",
            request_model=BundleToolRequest,
            response_model=AnalyzeRunResult,
        ),
        _operation(
            name="get_result_summary",
            summary=(
                "Read the latest integrity-verified deterministic result "
                "summary without modifying task state."
            ),
            side_effect="READ_ONLY",
            authorization_requirement="NONE",
            request_model=BundleToolRequest,
            response_model=SealedResultSummaryResult,
        ),
    )

    return ToolAPICatalog(tool_count=len(tools), tools=tools)


__all__ = [
    "BundleToolRequest",
    "CurrentPlanResult",
    "ExecuteRankerToolRequest",
    "PrepareTaskToolRequest",
    "ProvideInformationToolRequest",
    "RequestApprovalToolRequest",
    "SealedResultSummaryResult",
    "TOOL_API_CONTRACT_VERSION",
    "TOOL_API_SCHEMA_VERSION",
    "UNTRUSTED_REQUEST_FORBIDDEN_FIELDS",
    "TaskStatusResult",
    "ToolAPICatalog",
    "ToolAuthorizationRequirement",
    "ToolOperationContract",
    "ToolSideEffect",
    "get_tool_api_catalog",
]
