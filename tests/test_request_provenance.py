import json

from protein_design_agent.agent.orchestrator import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.prompts import (
    user_request_json_schema,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


def contains_default(value) -> bool:
    if isinstance(value, dict):
        if "default" in value:
            return True

        return any(
            contains_default(item)
            for item in value.values()
        )

    if isinstance(value, list):
        return any(
            contains_default(item)
            for item in value
        )

    return False


def test_explicit_fields_survive_json_roundtrip() -> None:
    request = UserRequest.model_validate(
        {
            "raw_text": "分析这个目录",
            "project_name": "demo",
            "input_dir": "/tmp/pdbs",
        }
    )

    explicit_fields = sorted(
        field_name
        for field_name
        in request.model_fields_set
        if field_name != "raw_text"
    )

    session = PlanningSession(
        provider_name="fake",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=explicit_fields,
    )

    restored = PlanningSession.model_validate(
        json.loads(
            session.model_dump_json()
        )
    )

    assert restored.request_explicit_fields == [
        "input_dir",
        "project_name",
    ]

    # UserRequest 本身重载后会看到所有序列化字段，
    # 但 PlanningSession 保存的来源记录不会丢失。
    assert (
        restored.request_explicit_fields
        != sorted(
            field_name
            for field_name
            in restored.request.model_fields_set
            if field_name != "raw_text"
        )
    )


def test_model_schema_contains_no_defaults() -> None:
    schema = user_request_json_schema()

    assert contains_default(schema) is False
