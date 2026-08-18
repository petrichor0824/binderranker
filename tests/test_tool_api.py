import json
from pathlib import Path

import pytest

from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.tool_api import (
    get_current_plan,
    get_task_status,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)


def create_incomplete_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    request = UserRequest(
        raw_text="分析骨架",
    )
    plan = build_agent_plan(request)

    assert plan.status == "NEEDS_INFORMATION"

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=plan,
        request_explicit_fields=[],
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    (
        bundle / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": "0.2",
                "status": "NEEDS_INFORMATION",
                "project_name": "demo",
            }
        ),
        encoding="utf-8",
    )

    return bundle


def test_get_task_status_separates_planning_and_run_state(
    tmp_path: Path,
) -> None:
    bundle = create_incomplete_bundle(tmp_path)

    result = get_task_status(bundle)

    assert (
        result.planning_status
        == "NEEDS_INFORMATION"
    )
    assert (
        result.run_status.current_stage
        == "PREPARED"
    )
    assert result.missing_information


def test_get_current_plan_reads_canonical_session(
    tmp_path: Path,
) -> None:
    bundle = create_incomplete_bundle(tmp_path)

    result = get_current_plan(bundle)

    assert result.available is True
    assert result.plan is not None
    assert (
        result.plan.status
        == "NEEDS_INFORMATION"
    )
    assert (
        result.plan.request.raw_text
        == "分析骨架"
    )
    assert result.request_explicit_fields == []


def test_get_current_plan_reports_absence_without_chat_runtime(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = get_current_plan(bundle)

    assert result.available is False
    assert result.plan is None
    assert result.planning_session is None


def test_get_task_status_supports_empty_bundle(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = get_task_status(bundle)

    assert result.planning_status is None
    assert result.missing_information == []
    assert result.run_status.current_stage == "EMPTY"


def test_get_current_plan_wraps_invalid_session(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.tool_api import (
        ToolAPIError,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    (
        bundle / "planning_session.json"
    ).write_text(
        "{not-valid-json",
        encoding="utf-8",
    )

    with pytest.raises(
        ToolAPIError,
        match="无法读取当前规划会话",
    ):
        get_current_plan(bundle)


def test_read_only_tools_do_not_modify_bundle(
    tmp_path: Path,
) -> None:
    bundle = create_incomplete_bundle(tmp_path)

    before = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    get_current_plan(bundle)
    get_task_status(bundle)

    after = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    assert after == before
