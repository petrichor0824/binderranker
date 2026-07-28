import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.resume_planning as module
from protein_design_agent.agent.orchestrator import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.resume_planning import (
    ResumePlanningError,
    resume_planning_session,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


class FakeStructuredProvider:
    def __init__(
        self,
        payload: dict,
        *,
        name: str = "fake-provider",
    ) -> None:
        self.payload = payload
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate_json(
        self,
        messages,
    ) -> dict:
        self.calls += 1
        return self.payload


def create_incomplete_bundle(
    tmp_path: Path,
    request: UserRequest,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    plan = build_agent_plan(request)

    assert plan.status == "NEEDS_INFORMATION"

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=plan,
        request_explicit_fields=sorted(
            field_name
            for field_name
            in request.model_fields_set
            if field_name != "raw_text"
        ),
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    (
        bundle
        / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": (
                    "NEEDS_INFORMATION"
                ),
                "provider_name": (
                    "fake-provider"
                ),
                "bundle_directory": (
                    str(bundle)
                ),
                "planning_session": str(
                    bundle
                    / "planning_session.json"
                ),
                "missing_information": (
                    plan.missing_information
                ),
                "scientific_workflow_executed": (
                    False
                ),
                "binderranker_executed": False,
                "remote_backend_used": False,
            }
        ),
        encoding="utf-8",
    )

    return bundle


def test_still_missing_updates_session(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="分析骨架",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": (
                    str(tmp_path / "pdbs")
                )
            },
            "notes": [],
        }
    )

    result = resume_planning_session(
        bundle_dir=bundle,
        supplement_text=(
            f"输入目录是 {tmp_path / 'pdbs'}"
        ),
        provider=provider,
    )

    assert (
        result.status
        == "NEEDS_INFORMATION"
    )

    assert "input_layout" in (
        result.missing_information
    )

    assert (
        result.history_record.is_dir()
    )

    session = module.load_planning_session(
        bundle / "planning_session.json"
    )

    assert session.request.input_dir == (
        tmp_path / "pdbs"
    )

    assert (
        session.plan.status
        == "NEEDS_INFORMATION"
    )


def test_conflicting_confirmed_field_rejected(
    tmp_path: Path,
) -> None:
    original_dir = tmp_path / "original"

    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=original_dir,
        input_layout="existing_chains",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    original_session = (
        bundle / "planning_session.json"
    ).read_bytes()

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": (
                    str(tmp_path / "different")
                )
            }
        }
    )

    with pytest.raises(
        ResumePlanningError,
        match="已经确认",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text=(
                "输入目录改成 different"
            ),
            provider=provider,
        )

    assert (
        bundle / "planning_session.json"
    ).read_bytes() == original_session


def test_provider_must_match_original(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="分析骨架",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": str(
                    tmp_path / "pdbs"
                )
            }
        },
        name="different-provider",
    )

    with pytest.raises(
        ResumePlanningError,
        match="Provider",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text="补充目录",
            provider=provider,
        )


def test_ready_session_is_promoted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = UserRequest(
        raw_text="分析已有分链数据",
        project_name="demo",
        input_dir=tmp_path / "pdbs",
        input_layout="existing_chains",
        binder_chain=None,
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "binder_chain": "B"
            }
        }
    )

    def fake_prepare_agent_run(
        *,
        session_path,
        bundle_dir,
        runner=None,
    ):
        bundle_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        session_copy = (
            bundle_dir
            / "planning_session.json"
        )
        session_copy.write_bytes(
            session_path.read_bytes()
        )

        project_config = (
            bundle_dir / "project.yaml"
        )
        project_config.write_text(
            "project_name: demo\n",
            encoding="utf-8",
        )

        provenance = (
            bundle_dir
            / "project.provenance.json"
        )
        provenance.write_text(
            "{}",
            encoding="utf-8",
        )

        workflow_directory = (
            bundle_dir / "workflow"
        )
        workflow_directory.mkdir()

        workflow_manifest = (
            workflow_directory
            / "workflow_manifest.json"
        )
        workflow_manifest.write_text(
            '{"status":"READY_FOR_REVIEW"}',
            encoding="utf-8",
        )

        prepare_manifest = (
            bundle_dir
            / "agent_prepare_manifest.json"
        )
        prepare_manifest.write_text(
            json.dumps(
                {
                    "status": (
                        "READY_FOR_REVIEW"
                    ),
                    "project_name": "demo",
                }
            ),
            encoding="utf-8",
        )

        return SimpleNamespace(
            project_name="demo",
            provider_name="fake-provider",
            bundle_directory=bundle_dir,
            session_copy=session_copy,
            project_config=project_config,
            project_provenance=provenance,
            workflow_directory=(
                workflow_directory
            ),
            workflow_manifest=(
                workflow_manifest
            ),
            stdout_log=(
                bundle_dir
                / "logs"
                / "stdout.log"
            ),
            stderr_log=(
                bundle_dir
                / "logs"
                / "stderr.log"
            ),
            prepare_manifest=(
                prepare_manifest
            ),
            scientific_workflow_executed=True,
            binderranker_executed=False,
            remote_backend_used=False,
        )

    monkeypatch.setattr(
        module,
        "prepare_agent_run",
        fake_prepare_agent_run,
    )

    result = resume_planning_session(
        bundle_dir=bundle,
        supplement_text="binder 链是 B",
        provider=provider,
    )

    assert (
        result.status
        == "READY_FOR_REVIEW"
    )

    assert (
        result.prepare_manifest.is_file()
    )

    assert (
        result.history_record.is_dir()
    )

    session = module.load_planning_session(
        bundle / "planning_session.json"
    )

    assert session.request.binder_chain == "B"
    assert (
        session.plan.status
        == "READY_FOR_REVIEW"
    )


def test_prepare_failure_restores_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=tmp_path / "pdbs",
        input_layout="existing_chains",
        binder_chain=None,
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    original_session = (
        bundle / "planning_session.json"
    ).read_bytes()

    original_manifest = (
        bundle
        / "agent_prepare_manifest.json"
    ).read_bytes()

    provider = FakeStructuredProvider(
        {
            "patch": {
                "binder_chain": "B"
            }
        }
    )

    def failing_prepare(
        *,
        session_path,
        bundle_dir,
        runner=None,
    ):
        bundle_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        (
            bundle_dir / "partial.txt"
        ).write_text(
            "partial",
            encoding="utf-8",
        )

        raise RuntimeError(
            "simulated prepare failure"
        )

    monkeypatch.setattr(
        module,
        "prepare_agent_run",
        failing_prepare,
    )

    with pytest.raises(
        ResumePlanningError,
        match="原不完整任务已恢复",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text="binder 链是 B",
            provider=provider,
        )

    assert (
        bundle / "planning_session.json"
    ).read_bytes() == original_session

    assert (
        bundle
        / "agent_prepare_manifest.json"
    ).read_bytes() == original_manifest

    assert not (
        bundle / "partial.txt"
    ).exists()


def test_system_default_can_be_overridden() -> None:
    from protein_design_agent.agent.resume_planning import (
        UserRequestPatch,
        merge_request_patch,
    )

    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=Path("/tmp/pdbs"),
        input_layout="existing_chains",
        binder_chain=None,
    )

    # target_start_residue=1 来自系统默认，
    # 不在旧 Provider 的显式字段集合中。
    merged, accepted = merge_request_patch(
        old_request=request,
        old_missing_information=[
            "binder_chain",
        ],
        old_explicit_fields={
            "input_dir",
            "input_layout",
        },
        patch=UserRequestPatch(
            binder_chain="B",
            target_start_residue=4,
        ),
        supplement_text=(
            "binder 链是 B，"
            "target 从第 4 号残基开始"
        ),
    )

    assert merged.binder_chain == "B"
    assert merged.target_start_residue == 4

    assert set(accepted) == {
        "binder_chain",
        "target_start_residue",
    }
