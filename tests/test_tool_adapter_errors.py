import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protein_design_agent.agent.scientific_result_validation import (
    ScientificResultValidationError,
)
from protein_design_agent.agent.local_executor import LocalExecutionError
from protein_design_agent.agent import tool_api
from protein_design_agent.agent.tool_adapter_errors import (
    ADAPTER_ERROR_CODES,
    AdapterErrorDetail,
    AdapterErrorEnvelope,
    AdapterSafeError,
    UnknownToolOperationError,
    adapter_error_from_exception,
    adapter_error_json_schema,
    invoke_adapter_boundary,
)
from protein_design_agent.agent.tool_api import ToolAPIError
from protein_design_agent.agent.tool_api_contract import BundleToolRequest
from protein_design_agent.agent.tool_runtime_authorization import (
    RuntimeAuthorizationError,
)


def capture_error(call):
    try:
        call()
    except Exception as error:
        return error

    raise AssertionError("expected an exception")


def test_invalid_request_exposes_only_location_and_error_type() -> None:
    secret_path = "C:/private/workspace/hidden-bundle"
    secret_field = "token_super_secret_value"
    error = capture_error(
        lambda: BundleToolRequest.model_validate(
            {
                "bundle_dir": secret_path,
                secret_field: True,
            }
        )
    )
    assert isinstance(error, ValidationError)

    envelope = adapter_error_from_exception(
        operation="execute_ranker",
        error=error,
    )
    payload = envelope.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == "0.1"
    assert payload["ok"] is False
    assert payload["operation"] == "execute_ranker"
    assert payload["error"] == {
        "code": "INVALID_REQUEST",
        "category": "REQUEST",
        "message": "The Tool request does not match the published schema.",
        "retryable": False,
        "recovery_action": "CORRECT_REQUEST",
        "validation_issue_count": 1,
        "validation_issues": [
            {
                "location": "$",
                "code": "extra_forbidden",
            }
        ],
    }
    assert secret_path not in encoded
    assert secret_field not in encoded
    assert "Extra inputs are not permitted" not in encoded


def test_known_request_root_location_remains_actionable() -> None:
    error = capture_error(
        lambda: BundleToolRequest.model_validate({})
    )
    assert isinstance(error, ValidationError)

    envelope = adapter_error_from_exception(
        operation="get_task_status",
        error=error,
    )

    assert envelope.error.validation_issues[0].location == "bundle_dir"


def test_unknown_operation_has_stable_non_retryable_profile() -> None:
    envelope = adapter_error_from_exception(
        operation="delete_everything",
        error=UnknownToolOperationError("delete_everything"),
    )

    assert envelope.operation is None
    assert envelope.error.code == "UNKNOWN_OPERATION"
    assert envelope.error.category == "REQUEST"
    assert envelope.error.retryable is False
    assert envelope.error.recovery_action == "SELECT_PUBLISHED_OPERATION"


def test_invalid_operation_name_is_not_reflected() -> None:
    envelope = adapter_error_from_exception(
        operation="../../secret token",
        error=UnknownToolOperationError("../../secret token"),
    )

    assert envelope.operation is None
    assert "secret token" not in envelope.model_dump_json()


def test_trusted_authorization_failures_have_stable_codes() -> None:
    rejected = adapter_error_from_exception(
        operation="execute_ranker",
        error=RuntimeAuthorizationError(
            "opaque capability rta_secret was already consumed"
        ),
    )
    required = adapter_error_from_exception(
        operation="request_approval",
        error=RuntimeAuthorizationError(
            "host confirmation was absent",
            adapter_error_code="AUTHORIZATION_REQUIRED",
        ),
    )

    assert rejected.error.code == "AUTHORIZATION_REJECTED"
    assert rejected.error.recovery_action == "REAUTHORIZE"
    assert "rta_secret" not in rejected.model_dump_json()
    assert required.error.code == "AUTHORIZATION_REQUIRED"
    assert required.error.recovery_action == "OBTAIN_TRUSTED_AUTHORIZATION"


def test_tool_rejection_does_not_publish_internal_message_or_path() -> None:
    internal_message = (
        "task failed at C:/host/private/bundle; token=super-secret"
    )
    envelope = adapter_error_from_exception(
        operation="get_task_status",
        error=ToolAPIError(internal_message),
    )
    encoded = envelope.model_dump_json()

    assert envelope.error.code == "TOOL_REJECTED"
    assert envelope.error.category == "DOMAIN_STATE"
    assert internal_message not in encoded
    assert "super-secret" not in encoded
    assert "C:/host" not in encoded


def test_scientific_invalidity_wins_over_outer_tool_wrapper() -> None:
    def fail() -> None:
        try:
            raise ScientificResultValidationError(
                "NaN score in C:/host/private/results.csv"
            )
        except ScientificResultValidationError as error:
            raise ToolAPIError("analysis failed") from error

    error = capture_error(fail)
    envelope = adapter_error_from_exception(
        operation="analyze_results",
        error=error,
    )

    assert envelope.error.code == "SCIENTIFIC_RESULT_INVALID"
    assert envelope.error.category == "SCIENTIFIC_VALIDITY"
    assert envelope.error.recovery_action == "REVIEW_SCIENTIFIC_OUTPUT"
    assert "NaN" not in envelope.model_dump_json()


def test_execution_failure_is_distinct_from_domain_rejection() -> None:
    envelope = adapter_error_from_exception(
        operation="execute_ranker",
        error=ToolAPIError(
            "subprocess stderr contains host details",
            adapter_error_code="EXECUTION_FAILED",
        ),
    )

    assert envelope.error.code == "EXECUTION_FAILED"
    assert envelope.error.category == "EXECUTION"
    assert envelope.error.recovery_action == "INSPECT_EXECUTION_EVIDENCE"


def test_actual_tool_execution_failure_uses_execution_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "approval.json").write_text("{}", encoding="utf-8")

    def fail_execution(**_kwargs):
        raise LocalExecutionError(
            "stderr at C:/host/private with token=secret",
            execution_manifest=bundle / "execution.json",
            public_message="Execution did not complete.",
        )

    monkeypatch.setattr(
        tool_api,
        "execute_approved_binderranker",
        fail_execution,
    )

    result = invoke_adapter_boundary(
        operation="execute_ranker",
        call=lambda: tool_api.execute_ranker(
            bundle_dir=bundle,
            execution_confirmed=True,
        ),
    )

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "EXECUTION_FAILED"
    assert "token=secret" not in result.model_dump_json()


def test_unexpected_exception_is_generic_and_non_sensitive() -> None:
    error = RuntimeError(
        "database password secret-value at C:/host/private"
    )
    envelope = adapter_error_from_exception(
        operation="inspect_dataset",
        error=error,
    )
    encoded = envelope.model_dump_json()

    assert envelope.error.code == "INTERNAL_ERROR"
    assert envelope.error.category == "INTERNAL"
    assert envelope.error.recovery_action == "CONTACT_OPERATOR"
    assert envelope.error.retryable is False
    assert "RuntimeError" not in encoded
    assert "secret-value" not in encoded
    assert "C:/host" not in encoded


def test_boundary_preserves_success_result_without_wrapping() -> None:
    expected = object()

    result = invoke_adapter_boundary(
        operation="get_current_plan",
        call=lambda: expected,
    )

    assert result is expected


def test_boundary_normalizes_exception_but_not_base_exception() -> None:
    error_result = invoke_adapter_boundary(
        operation="inspect_dataset",
        call=lambda: (_ for _ in ()).throw(
            AdapterSafeError("private diagnostic")
        ),
    )

    assert isinstance(error_result, AdapterErrorEnvelope)
    assert error_result.error.code == "TOOL_REJECTED"

    with pytest.raises(SystemExit):
        invoke_adapter_boundary(
            operation="inspect_dataset",
            call=lambda: (_ for _ in ()).throw(SystemExit(2)),
        )


def test_error_models_are_strict_frozen_and_profile_consistent() -> None:
    envelope = adapter_error_from_exception(
        operation="inspect_dataset",
        error=RuntimeError("hidden"),
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        envelope.operation = "get_task_status"

    with pytest.raises(ValidationError, match="stable code"):
        AdapterErrorDetail(
            code="INTERNAL_ERROR",
            category="REQUEST",
            message="The adapter could not complete the Tool operation.",
            recovery_action="CONTACT_OPERATOR",
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        AdapterErrorEnvelope(
            error=envelope.error,
            traceback="hidden",  # type: ignore[call-arg]
        )


def test_error_schema_and_codes_are_deterministic() -> None:
    first = adapter_error_json_schema()
    second = adapter_error_json_schema()

    assert first == second
    assert first["type"] == "object"
    assert len(ADAPTER_ERROR_CODES) == len(set(ADAPTER_ERROR_CODES))
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_tool_api_error_keeps_runtime_error_compatibility() -> None:
    error = ToolAPIError("existing caller message")

    assert isinstance(error, RuntimeError)
    assert str(error) == "existing caller message"
    assert error.adapter_error_code == "TOOL_REJECTED"


def test_error_documentation_preserves_adapter_boundary() -> None:
    document = Path("docs/TOOL_API_CONTRACT.md").read_text(encoding="utf-8")

    for required in (
        "AdapterErrorEnvelope",
        "SCIENTIFIC_RESULT_INVALID",
        "INTERNAL_ERROR",
        "retryable",
        "must not automatically replay",
        "raw exception text",
        "host filesystem paths",
        "Successful Tool results",
        "operation-specific Pydantic models",
    ):
        assert required in document
