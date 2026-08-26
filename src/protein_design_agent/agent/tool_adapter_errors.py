#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Stable, framework-independent error boundary for Tool adapters.

The internal exception chain remains available to the trusted host for
diagnostics.  External callers receive only the deterministic envelope defined
here; exception text, host paths, exception types, and tracebacks are never
copied into it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from protein_design_agent.agent.scientific_result_validation import (
    ScientificResultValidationError,
)


ADAPTER_ERROR_SCHEMA_VERSION = "0.1"

AdapterErrorCode = Literal[
    "INVALID_REQUEST",
    "UNKNOWN_OPERATION",
    "AUTHORIZATION_REQUIRED",
    "AUTHORIZATION_REJECTED",
    "TOOL_REJECTED",
    "SCIENTIFIC_RESULT_INVALID",
    "EXECUTION_FAILED",
    "INTERNAL_ERROR",
]

AdapterErrorCategory = Literal[
    "REQUEST",
    "AUTHORIZATION",
    "DOMAIN_STATE",
    "SCIENTIFIC_VALIDITY",
    "EXECUTION",
    "INTERNAL",
]

AdapterRecoveryAction = Literal[
    "CORRECT_REQUEST",
    "SELECT_PUBLISHED_OPERATION",
    "OBTAIN_TRUSTED_AUTHORIZATION",
    "REAUTHORIZE",
    "REVIEW_TASK_STATE",
    "REVIEW_SCIENTIFIC_OUTPUT",
    "INSPECT_EXECUTION_EVIDENCE",
    "CONTACT_OPERATOR",
]

ADAPTER_ERROR_CODES: tuple[AdapterErrorCode, ...] = (
    "INVALID_REQUEST",
    "UNKNOWN_OPERATION",
    "AUTHORIZATION_REQUIRED",
    "AUTHORIZATION_REJECTED",
    "TOOL_REJECTED",
    "SCIENTIFIC_RESULT_INVALID",
    "EXECUTION_FAILED",
    "INTERNAL_ERROR",
)


@dataclass(frozen=True, slots=True)
class _ErrorProfile:
    category: AdapterErrorCategory
    message: str
    recovery_action: AdapterRecoveryAction


_ERROR_PROFILES: dict[AdapterErrorCode, _ErrorProfile] = {
    "INVALID_REQUEST": _ErrorProfile(
        category="REQUEST",
        message="The Tool request does not match the published schema.",
        recovery_action="CORRECT_REQUEST",
    ),
    "UNKNOWN_OPERATION": _ErrorProfile(
        category="REQUEST",
        message="The requested Tool operation is not published.",
        recovery_action="SELECT_PUBLISHED_OPERATION",
    ),
    "AUTHORIZATION_REQUIRED": _ErrorProfile(
        category="AUTHORIZATION",
        message="This operation requires trusted user authorization.",
        recovery_action="OBTAIN_TRUSTED_AUTHORIZATION",
    ),
    "AUTHORIZATION_REJECTED": _ErrorProfile(
        category="AUTHORIZATION",
        message="The trusted authorization was rejected or is no longer valid.",
        recovery_action="REAUTHORIZE",
    ),
    "TOOL_REJECTED": _ErrorProfile(
        category="DOMAIN_STATE",
        message="BinderRanker rejected the operation in its current state.",
        recovery_action="REVIEW_TASK_STATE",
    ),
    "SCIENTIFIC_RESULT_INVALID": _ErrorProfile(
        category="SCIENTIFIC_VALIDITY",
        message=(
            "Execution did not produce a scientifically valid "
            "BinderRanker result."
        ),
        recovery_action="REVIEW_SCIENTIFIC_OUTPUT",
    ),
    "EXECUTION_FAILED": _ErrorProfile(
        category="EXECUTION",
        message="BinderRanker execution did not complete successfully.",
        recovery_action="INSPECT_EXECUTION_EVIDENCE",
    ),
    "INTERNAL_ERROR": _ErrorProfile(
        category="INTERNAL",
        message="The adapter could not complete the Tool operation.",
        recovery_action="CONTACT_OPERATOR",
    ),
}


class AdapterSafeError(RuntimeError):
    """Internal exception carrying a stable adapter classification.

    ``str(error)`` intentionally retains the original internal message for
    trusted diagnostics.  The adapter mapper publishes only the code's fixed
    public profile and never publishes this message.
    """

    def __init__(
        self,
        message: str,
        *,
        adapter_error_code: AdapterErrorCode = "TOOL_REJECTED",
    ) -> None:
        super().__init__(message)

        if adapter_error_code not in _ERROR_PROFILES:
            raise ValueError("unsupported adapter error code")

        self.adapter_error_code = adapter_error_code


class UnknownToolOperationError(AdapterSafeError):
    """An adapter requested a name outside the published Tool catalog."""

    def __init__(self, operation: object) -> None:
        super().__init__(
            f"unknown Tool operation: {operation!r}",
            adapter_error_code="UNKNOWN_OPERATION",
        )


class _StrictAdapterModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class AdapterValidationIssue(_StrictAdapterModel):
    """Non-sensitive location and type for one request validation error."""

    location: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=128)


class AdapterErrorDetail(_StrictAdapterModel):
    """Stable failure classification shared by every future adapter."""

    code: AdapterErrorCode
    category: AdapterErrorCategory
    message: str = Field(min_length=1)
    retryable: Literal[False] = False
    recovery_action: AdapterRecoveryAction
    validation_issue_count: int = Field(default=0, ge=0)
    validation_issues: tuple[AdapterValidationIssue, ...] = ()

    @model_validator(mode="after")
    def validate_profile(self) -> "AdapterErrorDetail":
        profile = _ERROR_PROFILES[self.code]

        if self.category != profile.category:
            raise ValueError("error category must match the stable code")
        if self.message != profile.message:
            raise ValueError("error message must match the stable code")
        if self.recovery_action != profile.recovery_action:
            raise ValueError("recovery action must match the stable code")
        if self.validation_issue_count < len(self.validation_issues):
            raise ValueError(
                "validation_issue_count cannot be smaller than details"
            )
        if self.code != "INVALID_REQUEST" and (
            self.validation_issue_count or self.validation_issues
        ):
            raise ValueError(
                "validation issues are allowed only for INVALID_REQUEST"
            )

        return self


class AdapterErrorEnvelope(_StrictAdapterModel):
    """Versioned JSON-safe failure output for Tool adapters."""

    schema_version: Literal["0.1"] = ADAPTER_ERROR_SCHEMA_VERSION
    ok: Literal[False] = False
    operation: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    error: AdapterErrorDetail


_SAFE_OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_VALIDATION_ISSUES = 32
_PUBLISHED_REQUEST_ROOT_FIELDS = frozenset(
    {
        "bundle_dir",
        "extraction",
        "raw_text",
        "supplement_text",
    }
)
_ResultT = TypeVar("_ResultT")


def _safe_operation(operation: object) -> str | None:
    if not isinstance(operation, str):
        return None

    clean = operation.strip()
    if not _SAFE_OPERATION_PATTERN.fullmatch(clean):
        return None

    return clean


def _exception_chain(error: Exception) -> Iterator[Exception]:
    """Walk a bounded, cycle-safe cause/context chain."""

    current: BaseException | None = error
    seen: set[int] = set()

    for _index in range(32):
        if current is None or id(current) in seen:
            return
        seen.add(id(current))

        if isinstance(current, Exception):
            yield current

        current = current.__cause__ or current.__context__


def _validation_issues(
    error: ValidationError,
) -> tuple[int, tuple[AdapterValidationIssue, ...]]:
    raw_issues = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    issues: list[AdapterValidationIssue] = []

    for raw_issue in raw_issues[:_MAX_VALIDATION_ISSUES]:
        raw_location = raw_issue.get("loc", ())
        root_location = (
            str(raw_location[0])
            if raw_location
            else ""
        )
        location = (
            root_location
            if root_location in _PUBLISHED_REQUEST_ROOT_FIELDS
            else "$"
        )
        issues.append(
            AdapterValidationIssue(
                location=location,
                code=str(
                    raw_issue.get("type", "validation_error")
                )[:128],
            )
        )

    return len(raw_issues), tuple(issues)


def _classified_code(error: Exception) -> AdapterErrorCode:
    chain = tuple(_exception_chain(error))

    if any(
        isinstance(item, ScientificResultValidationError)
        for item in chain
    ):
        return "SCIENTIFIC_RESULT_INVALID"

    for item in chain:
        if isinstance(item, AdapterSafeError):
            return item.adapter_error_code

    return "INTERNAL_ERROR"


def adapter_error_from_exception(
    *,
    operation: object,
    error: Exception,
) -> AdapterErrorEnvelope:
    """Convert one failure into a deterministic, non-sensitive envelope."""

    if not isinstance(error, Exception):
        raise TypeError("error must be an Exception")

    issue_count = 0
    issues: tuple[AdapterValidationIssue, ...] = ()

    if isinstance(error, ValidationError):
        code: AdapterErrorCode = "INVALID_REQUEST"
        issue_count, issues = _validation_issues(error)
    else:
        code = _classified_code(error)

    profile = _ERROR_PROFILES[code]
    return AdapterErrorEnvelope(
        operation=(
            None
            if code == "UNKNOWN_OPERATION"
            else _safe_operation(operation)
        ),
        error=AdapterErrorDetail(
            code=code,
            category=profile.category,
            message=profile.message,
            retryable=False,
            recovery_action=profile.recovery_action,
            validation_issue_count=issue_count,
            validation_issues=issues,
        ),
    )


def invoke_adapter_boundary(
    *,
    operation: object,
    call: Callable[[], _ResultT],
) -> _ResultT | AdapterErrorEnvelope:
    """Preserve successful Tool results and normalize ordinary failures."""

    if not callable(call):
        raise TypeError("call must be callable")

    try:
        return call()
    except Exception as error:
        return adapter_error_from_exception(
            operation=operation,
            error=error,
        )


def adapter_error_json_schema() -> dict[str, Any]:
    """Return a fresh serialization schema for the shared error envelope."""

    return AdapterErrorEnvelope.model_json_schema(mode="serialization")


__all__ = [
    "ADAPTER_ERROR_CODES",
    "ADAPTER_ERROR_SCHEMA_VERSION",
    "AdapterErrorCategory",
    "AdapterErrorCode",
    "AdapterErrorDetail",
    "AdapterErrorEnvelope",
    "AdapterRecoveryAction",
    "AdapterSafeError",
    "AdapterValidationIssue",
    "UnknownToolOperationError",
    "adapter_error_from_exception",
    "adapter_error_json_schema",
    "invoke_adapter_boundary",
]
