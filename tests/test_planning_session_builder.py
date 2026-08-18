from protein_design_agent.agent.planning_session_builder import (
    build_planning_session,
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
