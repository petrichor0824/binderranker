import json
from pathlib import Path

import pytest

from protein_design_agent.adapters import read_only
from protein_design_agent.adapters.read_only import (
    CurrentPlanAdapterResult,
    DatasetInspectionAdapterResult,
    ReadOnlyAdapterConfigurationError,
    ReadOnlyToolAdapter,
    ResultSummaryAdapterResult,
    TaskListAdapterResult,
    TaskStatusAdapterResult,
)
from protein_design_agent.agent.dataset_advisor import (
    ConditionalDatasetSuggestion,
    DatasetFileEvidence,
    DatasetPlanningAdvice,
)
from protein_design_agent.agent.run_status import (
    AnalysisAttempt,
    RunStatusReport,
)
from protein_design_agent.agent.tool_adapter_errors import AdapterErrorEnvelope
from protein_design_agent.agent.tool_api import CurrentPlanResult, TaskStatusResult
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE
from protein_design_agent.schemas.agent_models import AgentPlan, PlanStep, UserRequest


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    bundle = workspace / "runs" / "task_a"
    bundle.mkdir(parents=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace, bundle


def make_plan(secret_root: Path) -> AgentPlan:
    return AgentPlan(
        status="READY_FOR_REVIEW",
        request=UserRequest(
            raw_text=f"rank structures from {secret_root} token=hidden",
            project_name="project_a",
            input_dir=secret_root / "data",
            input_layout="existing_chains",
            binder_chain="B",
            target_chains=["A"],
        ),
        warnings=[f"private warning at {secret_root}"],
        steps=[
            PlanStep(
                step_id="inspect",
                tool_name="inspect_pdb_dataset",
                description=f"read private files at {secret_root}",
                status="READY",
            )
        ],
        config_preview={"input_dir": str(secret_root / "data")},
    )


def test_current_plan_projection_preserves_scientific_state_without_paths(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "private" / "absolute"
    result = CurrentPlanResult(
        available=True,
        bundle_dir=secret_root / "bundle",
        planning_session=secret_root / "bundle" / "planning_session.json",
        request_explicit_fields=["binder_chain", "input_dir"],
        plan=make_plan(secret_root),
    )

    projected = read_only.project_current_plan(
        task_name="task_a",
        result=result,
    )
    encoded = projected.model_dump_json()

    assert projected.ok is True
    assert projected.planning_status == "READY_FOR_REVIEW"
    assert projected.request is not None
    assert projected.request.input_configured is True
    assert projected.request.binder_chain == "B"
    assert projected.steps[0].tool_name == "inspect_pdb_dataset"
    assert projected.config_preview_available is True
    assert str(secret_root) not in encoded
    assert "token=hidden" not in encoded
    assert "raw_text" not in encoded
    assert '"input_dir":' not in encoded
    assert "description" not in encoded


def test_task_status_projection_omits_artifact_paths_and_warning_text(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "private"
    status = RunStatusReport(
        bundle_dir=secret_root / "bundle",
        project_name="project_a",
        current_stage="ANALYZED",
        approval_status="APPROVED",
        approval_consumed=True,
        candidate_count=4,
        formal_candidate_recommendation_allowed=False,
        thresholds_formally_interpretable=False,
        approval_manifest=secret_root / "approval.json",
        analysis_attempts=[
            AnalysisAttempt(
                manifest_path=secret_root / "analysis.json",
                status="COMPLETED",
            )
        ],
        warnings=[f"host detail at {secret_root}"],
    )
    result = TaskStatusResult(
        bundle_dir=secret_root / "bundle",
        planning_status="READY_FOR_REVIEW",
        run_status=status,
    )

    projected = read_only.project_task_status(
        task_name="task_a",
        result=result,
    )
    encoded = projected.model_dump_json()

    assert projected.current_stage == "ANALYZED"
    assert projected.approval_present is True
    assert projected.analysis_attempt_count == 1
    assert projected.warning_count == 1
    assert str(secret_root) not in encoded
    assert "manifest" not in encoded
    assert "host detail" not in encoded


def test_dataset_projection_keeps_checksums_and_counts_without_paths(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "private"
    advice = DatasetPlanningAdvice(
        created_at_utc="2026-08-26T00:00:00+00:00",
        status="NEEDS_USER_CONFIRMATION",
        input_directory=secret_root / "dataset",
        recursive=False,
        processed_file_count=1,
        valid_file_count=1,
        invalid_file_count=0,
        all_valid_files_are_single_chain=True,
        common_single_chain_id="B",
        chain_count_patterns={"1": 1},
        chain_signature_counts={"B": 1},
        total_residue_count_patterns={"50": 1},
        dataset_warnings=[f"private dataset at {secret_root}"],
        file_evidence=[
            DatasetFileEvidence(
                file_name="candidate_1.pdb",
                file_path=secret_root / "dataset" / "candidate_1.pdb",
                sha256="a" * 64,
                valid=True,
                chain_count=1,
                chain_ids=["B"],
                total_residue_count=50,
                chain_signature="B",
                warnings=[f"warning at {secret_root}"],
            )
        ],
        conditional_suggestion=ConditionalDatasetSuggestion(
            condition=f"private condition at {secret_root}",
            candidate_patch={"input_layout": "concatenated_single_chain"},
            evidence_summary=[f"evidence at {secret_root}"],
        ),
        unresolved_questions=[f"question at {secret_root}"],
        cautions=[f"caution at {secret_root}"],
    )

    projected = read_only.project_dataset_inspection(
        task_name="task_a",
        result=advice,
    )
    encoded = projected.model_dump_json()

    assert projected.file_evidence[0].file_name == "candidate_1.pdb"
    assert projected.file_evidence[0].sha256 == "a" * 64
    assert projected.file_evidence[0].warning_count == 1
    assert projected.conditional_suggestion is not None
    assert projected.conditional_suggestion.candidate_patch == {
        "input_layout": "concatenated_single_chain"
    }
    assert str(secret_root) not in encoded
    assert "file_path" not in encoded
    assert "private condition" not in encoded


def test_adapter_calls_only_tool_api_with_resolved_managed_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    observed: list[Path] = []

    def fake_get_current_plan(bundle_dir: Path) -> CurrentPlanResult:
        observed.append(bundle_dir)
        return CurrentPlanResult(available=False, bundle_dir=bundle_dir)

    monkeypatch.setattr(
        read_only.tool_api,
        "get_current_plan",
        fake_get_current_plan,
    )

    result = ReadOnlyToolAdapter(workspace).get_current_plan("task_a")

    assert isinstance(result, CurrentPlanAdapterResult)
    assert result.available is False
    assert observed == [bundle.resolve()]


def test_adapter_rejects_path_shaped_structured_plan_values_without_leakage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    secret_root = tmp_path / "private" / "absolute"
    plan = make_plan(secret_root)
    plan.request.desired_regions = [str(secret_root)]

    def fake_get_current_plan(bundle_dir: Path) -> CurrentPlanResult:
        return CurrentPlanResult(
            available=True,
            bundle_dir=bundle_dir,
            plan=plan,
        )

    monkeypatch.setattr(
        read_only.tool_api,
        "get_current_plan",
        fake_get_current_plan,
    )

    result = ReadOnlyToolAdapter(workspace).get_current_plan("task_a")

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "INTERNAL_ERROR"
    assert str(secret_root) not in result.model_dump_json()


def test_adapter_rejects_traversal_missing_tasks_and_unpublished_operations(
    tmp_path: Path,
) -> None:
    workspace, _bundle = make_workspace(tmp_path)
    adapter = ReadOnlyToolAdapter(workspace)

    traversal = adapter.get_task_status("../outside")
    missing = adapter.get_task_status("missing")
    protected = adapter.invoke("execute_ranker", task_name="task_a")

    assert isinstance(traversal, AdapterErrorEnvelope)
    assert traversal.error.code == "INVALID_REQUEST"
    assert traversal.error.validation_issues[0].location == "task_name"
    assert isinstance(missing, AdapterErrorEnvelope)
    assert missing.error.code == "TOOL_REJECTED"
    assert isinstance(protected, AdapterErrorEnvelope)
    assert protected.error.code == "UNKNOWN_OPERATION"
    assert protected.operation is None


def test_adapter_rejects_task_symlink_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    adapter = ReadOnlyToolAdapter(workspace)
    original = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == bundle:
            return True
        return original(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    result = adapter.get_current_plan("task_a")

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "TOOL_REJECTED"


def test_adapter_normalizes_resolved_path_escape_as_domain_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _bundle = make_workspace(tmp_path)
    adapter = ReadOnlyToolAdapter(workspace)

    def reject_escape(**_kwargs):
        raise read_only.TaskPathError("private escaped location")

    monkeypatch.setattr(read_only, "resolve_task_bundle", reject_escape)

    result = adapter.get_current_plan("task_a")

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "TOOL_REJECTED"
    assert "private escaped location" not in result.model_dump_json()


def test_adapter_requires_initialized_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "not-managed"
    (workspace / "runs").mkdir(parents=True)

    with pytest.raises(ReadOnlyAdapterConfigurationError):
        ReadOnlyToolAdapter(workspace)


def test_adapter_capability_profile_is_explicit_and_json_safe(
    tmp_path: Path,
) -> None:
    workspace, _bundle = make_workspace(tmp_path)
    capabilities = ReadOnlyToolAdapter(workspace).capabilities()
    payload = capabilities.model_dump(mode="json")

    assert payload["tool_api_contract_version"] == "0.3"
    assert payload["request_scope"] == "BOUND_WORKSPACE_MANAGED_TASKS"
    assert payload["exposed_operations"] == [
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
        "get_result_summary",
        "list_tasks",
    ]
    assert payload["mutating_operations_exposed"] is False
    assert payload["authorization_operations_exposed"] is False
    assert payload["execution_operations_exposed"] is False
    assert payload["host_paths_exposed"] is False
    assert payload["private_stdio_tunnel_compatible"] is True
    assert payload["public_network_listener_exposed"] is False
    assert payload["caller_identity_contract_available"] is False
    assert payload["trusted_human_confirmation_bridge_available"] is False
    assert payload["performance_claims_established"] is False
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_adapter_success_models_are_strict_and_path_free() -> None:
    for model in (
        CurrentPlanAdapterResult,
        TaskStatusAdapterResult,
        DatasetInspectionAdapterResult,
        ResultSummaryAdapterResult,
    ):
        schema = model.model_json_schema(mode="serialization")
        encoded = json.dumps(schema, sort_keys=True)
        assert '"format": "path"' not in encoded
        assert "bundle_dir" not in encoded
        assert "planning_session" not in encoded
        assert "manifest_path" not in encoded
