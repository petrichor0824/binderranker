from protein_design_agent.agent.planning_session_builder import (
    build_planning_session,
    build_planning_session_from_extraction,
)
from protein_design_agent.agent.request_evidence import (
    RequestEvidenceError,
    RequestExtraction,
    UserRequestPatch,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


def test_build_planning_session_uses_deterministic_plan() -> None:
    request = UserRequest(
        raw_text="分析这些骨架",
    )

    session = build_planning_session(
        request=request,
        provider_name="unit-test",
    )

    assert session.provider_name == "unit-test"
    assert session.request == request
    assert (
        session.plan.status
        == "NEEDS_INFORMATION"
    )


def test_build_planning_session_records_explicit_fields() -> None:
    request = UserRequest(
        raw_text="binder chain 是 B",
        binder_chain="B",
    )

    session = build_planning_session(
        request=request,
        provider_name="unit-test",
    )

    assert (
        session.request_explicit_fields
        == ["binder_chain"]
    )


def test_raw_text_is_not_an_explicit_request_field() -> None:
    request = UserRequest(
        raw_text="分析这些骨架",
    )

    session = build_planning_session(
        request=request,
        provider_name="unit-test",
    )

    assert (
        "raw_text"
        not in session.request_explicit_fields
    )


def test_build_planning_session_from_extraction_validates_user_evidence() -> None:
    raw_text = "binder chain 是 B"

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": raw_text,
        },
    )

    session = build_planning_session_from_extraction(
        raw_text=raw_text,
        extraction=extraction,
        provider_name="unit-test",
    )

    assert session.request.raw_text == raw_text
    assert session.request.binder_chain == "B"
    assert (
        session.request_explicit_fields
        == ["binder_chain"]
    )
    assert (
        session.plan.status
        == "NEEDS_INFORMATION"
    )


def test_build_planning_session_from_extraction_rejects_forged_field() -> None:
    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": "binder chain 是 B",
        },
    )

    try:
        build_planning_session_from_extraction(
            raw_text="帮我分析这些骨架",
            extraction=extraction,
            provider_name="unit-test",
        )
    except RequestEvidenceError:
        pass
    else:
        raise AssertionError(
            "伪造的字段 evidence 必须被拒绝"
        )
