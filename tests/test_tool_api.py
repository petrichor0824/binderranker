import json
from pathlib import Path

import pytest

from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.tool_api import (
    ToolAPIError,
    get_current_plan,
    get_task_status,
    prepare_task,
    provide_information,
)
from protein_design_agent.agent.planning_session_resume import (
    SupplementExtraction,
    UserRequestPatch,
)
from protein_design_agent.agent.request_evidence import (
    RequestExtraction,
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
                "schema_version": "0.1",
                "status": "NEEDS_INFORMATION",
                "provider_name": "fake-provider",
                "bundle_directory": str(bundle),
                "planning_session": str(
                    bundle / "planning_session.json"
                ),
                "missing_information": (
                    plan.missing_information
                ),
                "scientific_workflow_executed": False,
                "binderranker_executed": False,
                "remote_backend_used": False,
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


def test_provide_information_updates_planning_session(
    tmp_path: Path,
) -> None:
    bundle = create_incomplete_bundle(tmp_path)

    input_dir = tmp_path / "pdbs"
    supplement = f"输入目录是 {input_dir}"

    extraction = SupplementExtraction(
        patch=UserRequestPatch(
            input_dir=input_dir,
        ),
        evidence={
            "input_dir": supplement,
        },
    )

    result = provide_information(
        bundle_dir=bundle,
        supplement_text=supplement,
        extraction=extraction,
    )

    assert result.status == "NEEDS_INFORMATION"

    current = get_current_plan(bundle)

    assert current.available is True
    assert current.plan is not None
    assert (
        current.plan.request.input_dir
        == input_dir
    )
    assert (
        "input_dir"
        in current.request_explicit_fields
    )


def test_provide_information_rejects_forged_evidence_without_mutation(
    tmp_path: Path,
) -> None:
    bundle = create_incomplete_bundle(tmp_path)

    before = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    input_dir = tmp_path / "pdbs"

    extraction = SupplementExtraction(
        patch=UserRequestPatch(
            input_dir=input_dir,
        ),
        evidence={
            "input_dir": (
                f"输入目录是 {input_dir}"
            ),
        },
    )

    with pytest.raises(ToolAPIError):
        provide_information(
            bundle_dir=bundle,
            supplement_text="谢谢",
            extraction=extraction,
        )

    after = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    assert after == before


def test_prepare_task_creates_incomplete_task_from_trusted_extraction(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "new-task"

    raw_text = "binder chain 是 B"

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": raw_text,
        },
    )

    result = prepare_task(
        bundle_dir=bundle,
        raw_text=raw_text,
        extraction=extraction,
        provider_name="unit-test",
    )

    assert result.status == "NEEDS_INFORMATION"
    assert bundle.is_dir()

    current = get_current_plan(bundle)

    assert current.available is True
    assert current.plan is not None
    assert current.plan.request.binder_chain == "B"
    assert current.request_explicit_fields == [
        "binder_chain"
    ]


def test_prepare_task_rejects_forged_initial_evidence_without_bundle(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "new-task"

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": "binder chain 是 B",
        },
    )

    with pytest.raises(ToolAPIError):
        prepare_task(
            bundle_dir=bundle,
            raw_text="帮我分析这些骨架",
            extraction=extraction,
            provider_name="unit-test",
        )

    assert not bundle.exists()


def test_prepare_task_passes_ready_session_to_stable_preparation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import protein_design_agent.agent.tool_api as tool_api_module
    from protein_design_agent.agent.planning_session_prepare import (
        NaturalLanguagePrepareResult,
    )

    bundle = tmp_path / "ready-task"
    input_dir = tmp_path / "pdbs"

    raw_text = (
        f"项目名是 demo，输入目录是 {input_dir}，"
        "数据已经正确分链，binder chain 是 B。"
    )

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            project_name="demo",
            input_dir=input_dir,
            input_layout="existing_chains",
            binder_chain="B",
        ),
        evidence={
            "project_name": raw_text,
            "input_dir": raw_text,
            "input_layout": raw_text,
            "binder_chain": raw_text,
        },
    )

    observed = {}

    def fake_prepare_planning_session(
        *,
        session,
        bundle_dir,
    ):
        observed["session"] = session
        observed["bundle_dir"] = (
            bundle_dir.resolve()
        )

        return NaturalLanguagePrepareResult(
            status="READY_FOR_REVIEW",
            provider_name=session.provider_name,
            bundle_directory=bundle_dir.resolve(),
            planning_session=(
                bundle_dir.resolve()
                / "planning_session.json"
            ),
            prepare_manifest=(
                bundle_dir.resolve()
                / "agent_prepare_manifest.json"
            ),
            project_name=(
                session.request.project_name
            ),
        )

    monkeypatch.setattr(
        tool_api_module,
        "prepare_planning_session",
        fake_prepare_planning_session,
    )

    result = prepare_task(
        bundle_dir=bundle,
        raw_text=raw_text,
        extraction=extraction,
        provider_name="unit-test",
    )

    assert result.status == "READY_FOR_REVIEW"

    session = observed["session"]

    assert session.plan.status == "READY_FOR_REVIEW"
    assert session.provider_name == "unit-test"

    assert set(
        session.request_explicit_fields
    ) == {
        "project_name",
        "input_dir",
        "input_layout",
        "binder_chain",
    }

    assert observed["bundle_dir"] == (
        bundle.resolve()
    )


def test_prepare_task_rejects_nonempty_bundle_without_overwrite(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "existing-task"
    bundle.mkdir()

    important = bundle / "important.txt"
    important.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    before = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    raw_text = "binder chain 是 B"

    extraction = RequestExtraction(
        patch=UserRequestPatch(
            binder_chain="B",
        ),
        evidence={
            "binder_chain": raw_text,
        },
    )

    with pytest.raises(
        ToolAPIError,
        match="已经存在且非空",
    ):
        prepare_task(
            bundle_dir=bundle,
            raw_text=raw_text,
            extraction=extraction,
            provider_name="unit-test",
        )

    after = {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }

    assert after == before
