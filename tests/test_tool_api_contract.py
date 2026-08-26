import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protein_design_agent.agent.tool_api import (
    CurrentPlanResult as ToolAPICurrentPlanResult,
)
from protein_design_agent.agent.tool_api import (
    TaskStatusResult as ToolAPITaskStatusResult,
)
from protein_design_agent.agent.tool_api_contract import (
    BundleToolRequest,
    CurrentPlanResult,
    ExecuteRankerToolRequest,
    RequestApprovalToolRequest,
    TaskStatusResult,
    ToolAPICatalog,
    get_tool_api_catalog,
)


EXPECTED_TOOLS = (
    "get_current_plan",
    "get_task_status",
    "provide_information",
    "prepare_task",
    "inspect_dataset",
    "request_approval",
    "execute_ranker",
    "analyze_results",
)


def tool_by_name(name: str):
    catalog = get_tool_api_catalog()
    return next(tool for tool in catalog.tools if tool.name == name)


def test_catalog_has_all_eight_public_tools_in_stable_order() -> None:
    catalog = get_tool_api_catalog()

    assert catalog.tool_count == 8
    assert tuple(tool.name for tool in catalog.tools) == EXPECTED_TOOLS

    assert {
        tool.name: tool.side_effect for tool in catalog.tools
    } == {
        "get_current_plan": "READ_ONLY",
        "get_task_status": "READ_ONLY",
        "provide_information": "MUTATING_NON_EXECUTING",
        "prepare_task": "MUTATING_NON_EXECUTING",
        "inspect_dataset": "READ_ONLY",
        "request_approval": "AUTHORIZATION_CHANGING",
        "execute_ranker": "EXECUTING",
        "analyze_results": "APPEND_ONLY_ARTIFACT",
    }


def test_catalog_is_deterministic_and_json_serializable() -> None:
    first = get_tool_api_catalog().model_dump(mode="json")
    second = get_tool_api_catalog().model_dump(mode="json")

    assert first == second
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_adapter_schemas_never_accept_model_supplied_authorization() -> None:
    approval = tool_by_name("request_approval")
    execution = tool_by_name("execute_ranker")

    approval_properties = approval.input_json_schema["properties"]
    execution_properties = execution.input_json_schema["properties"]

    assert set(approval_properties) == {"bundle_dir"}
    assert "execution_confirmed" not in execution_properties
    assert approval.host_injected_fields == (
        "approved_by",
        "approval_confirmed",
        "approval_note",
        "acknowledge_smoke_test",
    )
    assert execution.host_injected_fields == ("execution_confirmed",)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RequestApprovalToolRequest(
            bundle_dir=Path("bundle"),
            approved_by="model",  # type: ignore[call-arg]
            approval_confirmed=True,  # type: ignore[call-arg]
            acknowledge_smoke_test=True,  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecuteRankerToolRequest(
            bundle_dir=Path("bundle"),
            execution_confirmed=True,  # type: ignore[call-arg]
        )


def test_catalog_exposes_authorization_and_scientific_boundaries() -> None:
    catalog = get_tool_api_catalog()

    assert catalog.path_semantics == "HOST_LOCAL_PATH"
    assert catalog.model_supplied_authorization_accepted is False
    assert catalog.authorization_transport == (
        "IN_PROCESS_OPAQUE_CAPABILITY"
    )
    assert catalog.authorization_grant_json_serializable is False
    assert catalog.authorization_grant_single_use is True
    assert catalog.authorization_grant_review_resource_bound is True
    assert catalog.authorization_grant_default_ttl_seconds == 300
    assert catalog.scientific_evidence_status == "SCIENTIFIC_VALIDATION_PENDING"
    assert catalog.performance_claims_established is False

    assert (
        tool_by_name("request_approval").authorization_requirement
        == "TRUSTED_USER_PLAN_APPROVAL"
    )
    assert (
        tool_by_name("execute_ranker").authorization_requirement
        == "TRUSTED_USER_EXECUTION_CONFIRMATION"
    )
    assert tool_by_name("prepare_task").host_injected_fields == (
        "provider_name",
    )
    assert (
        tool_by_name("request_approval").trusted_runtime_entrypoint
        == "TrustedToolRuntime.request_approval"
    )
    assert (
        tool_by_name("execute_ranker").trusted_runtime_entrypoint
        == "TrustedToolRuntime.execute_ranker"
    )


def test_every_operation_exposes_input_and_output_json_schema() -> None:
    catalog = get_tool_api_catalog()

    for tool in catalog.tools:
        assert tool.input_schema_name
        assert tool.output_schema_name
        assert tool.input_json_schema["type"] == "object"
        assert tool.output_json_schema["type"] == "object"


def test_request_models_are_strict_and_frozen() -> None:
    request = BundleToolRequest(bundle_dir=Path("bundle"))

    with pytest.raises(ValidationError, match="Instance is frozen"):
        request.bundle_dir = Path("elsewhere")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BundleToolRequest(
            bundle_dir=Path("bundle"),
            unknown=True,  # type: ignore[call-arg]
        )


def test_catalog_rejects_count_mismatch_and_duplicate_names() -> None:
    catalog = get_tool_api_catalog()

    with pytest.raises(ValidationError, match="tool_count must match"):
        ToolAPICatalog(tool_count=7, tools=catalog.tools)

    duplicated = catalog.tools[:-1] + (catalog.tools[0],)
    with pytest.raises(ValidationError, match="tool names must be unique"):
        ToolAPICatalog(tool_count=8, tools=duplicated)

    unsafe_protected_tool = catalog.tools[5].model_copy(
        update={"trusted_runtime_entrypoint": None}
    )
    unsafe_tools = (
        catalog.tools[:5]
        + (unsafe_protected_tool,)
        + catalog.tools[6:]
    )
    with pytest.raises(
        ValidationError,
        match="trusted runtime entrypoint",
    ):
        ToolAPICatalog(tool_count=8, tools=unsafe_tools)


def test_tool_api_keeps_result_model_import_compatibility() -> None:
    assert ToolAPICurrentPlanResult is CurrentPlanResult
    assert ToolAPITaskStatusResult is TaskStatusResult


def test_contract_documentation_preserves_integration_boundaries() -> None:
    document = Path("docs/TOOL_API_CONTRACT.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    for required in (
        "SCIENTIFIC_VALIDATION_PENDING",
        "performance_claims_established=false",
        "model-authored arguments",
        "request_approval",
        "execute_ranker",
        "host runtime",
        "must not expose",
    ):
        assert required in document

    assert "(docs/TOOL_API_CONTRACT.md)" in readme
