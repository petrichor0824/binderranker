import pytest

from protein_design_agent.agent.request_evidence import (
    RequestExtraction,
    RequestEvidenceError,
    UserRequestPatch,
    validate_request_evidence,
)


def test_valid_request_evidence_is_accepted() -> None:
    text = "binder chain 是 B"

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": text,
        },
    )

    validate_request_evidence(
        extraction=extraction,
        evidence_text=text,
    )


def test_forged_request_evidence_is_rejected() -> None:
    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": "binder chain 是 B",
        },
    )

    with pytest.raises(RequestEvidenceError):
        validate_request_evidence(
            extraction=extraction,
            evidence_text="帮我分析这些骨架",
        )


def test_unmentioned_patch_field_requires_evidence() -> None:
    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={},
    )

    with pytest.raises(RequestEvidenceError):
        validate_request_evidence(
            extraction=extraction,
            evidence_text="binder chain 是 B",
        )
