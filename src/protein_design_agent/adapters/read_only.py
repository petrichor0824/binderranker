"""Workspace-scoped, read-only boundary shared by external adapters.

The internal Tool API accepts host-local ``Path`` values.  An external model
must not.  This module therefore accepts only a validated managed task name
and projects successful Tool results into explicit views that contain no host
filesystem paths or stored free-form request text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from protein_design_agent.agent import tool_api
from protein_design_agent.agent.dataset_advisor import DatasetPlanningAdvice
from protein_design_agent.agent.tool_adapter_errors import (
    AdapterErrorEnvelope,
    AdapterSafeError,
    UnknownToolOperationError,
    invoke_adapter_boundary,
)
from protein_design_agent.agent.tool_api import (
    CurrentPlanResult,
    TaskStatusResult,
)
from protein_design_agent.agent.tool_api_contract import (
    TOOL_API_CONTRACT_VERSION,
)
from protein_design_agent.agent.workspace_init import detect_existing_workspace
from protein_design_agent.agent.workspace_tasks import (
    TaskPathError,
    resolve_task_bundle,
    validate_task_name,
)
from protein_design_agent.schemas.agent_models import AgentPlan, UserRequest


READ_ONLY_ADAPTER_SCHEMA_VERSION = "0.1"
READ_ONLY_ADAPTER_OPERATIONS = (
    "get_current_plan",
    "get_task_status",
    "inspect_dataset",
    "get_result_summary",
    "list_tasks",
)
DEFERRED_ADAPTER_OPERATIONS = (
    "provide_information",
    "prepare_task",
    "request_approval",
    "execute_ranker",
    "analyze_results",
)

SafeScientificToken: TypeAlias = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:+|,-]+$",
    ),
]


class _StrictAdapterView(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ManagedTaskRequest(_StrictAdapterView):
    """External request scoped to one task in ``<workspace>/runs``."""

    task_name: str = Field(min_length=1, max_length=64)

    @field_validator("task_name")
    @classmethod
    def validate_managed_name(cls, value: str) -> str:
        try:
            return validate_task_name(value)
        except TaskPathError as exc:
            raise ValueError("invalid managed task name") from exc


class ResultSummaryRequest(ManagedTaskRequest):
    """Bounded external request for sealed deterministic ranking evidence."""

    limit: int = Field(default=20, ge=1, le=100)


class TaskListRequest(_StrictAdapterView):
    """Bounded task-discovery request for the configured workspace."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class ReadOnlyAdapterCapabilities(_StrictAdapterView):
    """Machine-readable safety and capability profile for the adapter."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    adapter_name: Literal["BinderRanker read-only MCP adapter"] = (
        "BinderRanker read-only MCP adapter"
    )
    tool_api_contract_version: Literal["0.3"] = TOOL_API_CONTRACT_VERSION
    transport: Literal["MCP_STDIO"] = "MCP_STDIO"
    request_scope: Literal["BOUND_WORKSPACE_MANAGED_TASKS"] = (
        "BOUND_WORKSPACE_MANAGED_TASKS"
    )
    exposed_operations: tuple[str, ...] = READ_ONLY_ADAPTER_OPERATIONS
    deferred_operations: tuple[str, ...] = DEFERRED_ADAPTER_OPERATIONS
    read_only: Literal[True] = True
    mutating_operations_exposed: Literal[False] = False
    authorization_operations_exposed: Literal[False] = False
    execution_operations_exposed: Literal[False] = False
    host_paths_exposed: Literal[False] = False
    stored_free_text_exposed: Literal[False] = False
    private_stdio_tunnel_compatible: Literal[True] = True
    public_network_listener_exposed: Literal[False] = False
    caller_identity_contract_available: Literal[False] = False
    trusted_human_confirmation_bridge_available: Literal[False] = False
    scientific_evidence_status: Literal[
        "SCIENTIFIC_VALIDATION_PENDING"
    ] = "SCIENTIFIC_VALIDATION_PENDING"
    performance_claims_established: Literal[False] = False


class PlanRequestView(_StrictAdapterView):
    """Scientific request fields safe to expose without local paths or text."""

    task_type: str
    project_name: str | None = None
    input_configured: bool
    input_layout: str | None = None
    binder_chain: SafeScientificToken | None = None
    target_chains: tuple[SafeScientificToken, ...] = ()
    source_chain: SafeScientificToken | None = None
    target_residue_count: int | None = None
    target_start_residue: int
    normalized_target_chain: SafeScientificToken
    normalized_binder_chain: SafeScientificToken
    desired_regions: tuple[SafeScientificToken, ...] = ()
    undesired_regions: tuple[SafeScientificToken, ...] = ()
    hotspots: tuple[SafeScientificToken, ...] = ()
    region_policy: str
    region_filter: str
    requested_top_k: int
    execute_requested: bool


class PlanStepView(_StrictAdapterView):
    """Path-free plan-step state."""

    step_id: SafeScientificToken
    tool_name: SafeScientificToken
    requires_approval: bool
    status: str


class CurrentPlanAdapterResult(_StrictAdapterView):
    """External, path-free view of ``CurrentPlanResult``."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    ok: Literal[True] = True
    operation: Literal["get_current_plan"] = "get_current_plan"
    task_name: str
    available: bool
    request_explicit_fields: tuple[SafeScientificToken, ...] = ()
    planning_status: str | None = None
    missing_information: tuple[SafeScientificToken, ...] = ()
    warning_count: int = Field(default=0, ge=0)
    steps: tuple[PlanStepView, ...] = ()
    request: PlanRequestView | None = None
    config_preview_available: bool = False
    execution_allowed: bool = False


class TaskStatusAdapterResult(_StrictAdapterView):
    """External lifecycle state without local artifact paths or warning text."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    ok: Literal[True] = True
    operation: Literal["get_task_status"] = "get_task_status"
    task_name: str
    project_name: str
    planning_status: str | None = None
    missing_information: tuple[str, ...] = ()
    current_stage: str
    prepare_status: str | None = None
    approval_status: str | None = None
    execution_status: str | None = None
    analysis_status: str | None = None
    explanation_status: str | None = None
    analysis_scope_level: str | None = None
    approval_present: bool
    approval_consumed: bool | None = None
    candidate_count: int | None = Field(default=None, ge=0)
    formal_candidate_recommendation_allowed: bool | None = None
    thresholds_formally_interpretable: bool | None = None
    analysis_attempt_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)


class DatasetFileEvidenceView(_StrictAdapterView):
    """Per-file scientific evidence without a host-local file path."""

    file_name: str
    sha256: str
    valid: bool
    chain_count: int = Field(ge=0)
    chain_ids: tuple[str, ...] = ()
    total_residue_count: int = Field(ge=0)
    chain_signature: str | None = None
    warning_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)


class DatasetSuggestionView(_StrictAdapterView):
    """Conditional parameter patch without free-form evidence text."""

    candidate_patch: dict[str, str]
    evidence_item_count: int = Field(default=0, ge=0)


class DatasetInspectionAdapterResult(_StrictAdapterView):
    """External, path-free view of deterministic dataset inspection."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    ok: Literal[True] = True
    operation: Literal["inspect_dataset"] = "inspect_dataset"
    task_name: str
    evidence_created_at_utc: str
    status: str
    recursive: bool
    processed_file_count: int = Field(ge=0)
    valid_file_count: int = Field(ge=0)
    invalid_file_count: int = Field(ge=0)
    all_valid_files_are_single_chain: bool
    common_single_chain_id: str | None = None
    chain_count_patterns: dict[str, int] = Field(default_factory=dict)
    chain_signature_counts: dict[str, int] = Field(default_factory=dict)
    total_residue_count_patterns: dict[str, int] = Field(default_factory=dict)
    dataset_warning_count: int = Field(default=0, ge=0)
    file_evidence: tuple[DatasetFileEvidenceView, ...] = ()
    conditional_suggestion: DatasetSuggestionView | None = None
    unresolved_question_count: int = Field(default=0, ge=0)
    caution_count: int = Field(default=0, ge=0)


class RankedCandidateAdapterView(_StrictAdapterView):
    """Path-free evidence for one candidate in sealed engineering-rank order."""

    candidate_id: str = Field(min_length=1, max_length=255)
    engineering_rank: int = Field(ge=1)
    final_score_v4: float
    public_filter_level: SafeScientificToken | None = None
    public_filter_status: SafeScientificToken
    broad_pass: bool
    medium_pass: bool
    strict_pass: bool
    broad_reasons: tuple[SafeScientificToken, ...] = ()
    medium_reasons: tuple[SafeScientificToken, ...] = ()
    strict_reasons: tuple[SafeScientificToken, ...] = ()
    component_scores: dict[SafeScientificToken, float]
    key_metrics: dict[SafeScientificToken, float]
    primary_score_contributions: dict[SafeScientificToken, float]

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_identifier(cls, value: str) -> str:
        invalid = (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(char) < 32 for char in value)
        )
        if invalid:
            raise ValueError("candidate identifier is not path-safe")
        return value


class ResultSummaryAdapterResult(_StrictAdapterView):
    """Bounded external view of one sealed deterministic result summary."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    ok: Literal[True] = True
    operation: Literal["get_result_summary"] = "get_result_summary"
    task_name: str
    provenance_status: Literal["SEALED_VERIFIED"] = "SEALED_VERIFIED"
    result_summary_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_summary_schema_version: SafeScientificToken
    analysis_scope_level: SafeScientificToken
    reporting_mode: SafeScientificToken
    result_use: SafeScientificToken
    candidate_count: int = Field(ge=1)
    returned_candidate_count: int = Field(ge=1)
    truncated: bool
    formal_candidate_recommendation_allowed: bool
    thresholds_formally_interpretable: bool
    score_decomposition_status: SafeScientificToken
    scientific_interpretation_status: SafeScientificToken
    candidate_comparison_status: SafeScientificToken
    public_pool_counts: dict[SafeScientificToken, int | None]
    public_pool_status: dict[SafeScientificToken, SafeScientificToken]
    primary_score_formula: str | None = Field(default=None, max_length=512)
    primary_score_weights: dict[SafeScientificToken, float]
    candidates_by_engineering_rank: tuple[RankedCandidateAdapterView, ...]


class TaskDiscoveryAdapterItem(_StrictAdapterView):
    """Path-free lifecycle and sealed-result availability for one task."""

    task_name: str = Field(min_length=1, max_length=64)
    lifecycle_status: Literal["AVAILABLE", "INVALID"]
    current_stage: SafeScientificToken | None = None
    sealed_result_status: Literal[
        "SEALED_VERIFIED",
        "NOT_AVAILABLE",
        "INVALID",
    ]
    candidate_count: int | None = Field(default=None, ge=1)

    @field_validator("task_name")
    @classmethod
    def validate_discovered_name(cls, value: str) -> str:
        try:
            return validate_task_name(value)
        except TaskPathError as exc:
            raise ValueError("invalid discovered task name") from exc


class TaskListAdapterResult(_StrictAdapterView):
    """Bounded path-free inventory for the configured workspace."""

    schema_version: Literal["0.1"] = READ_ONLY_ADAPTER_SCHEMA_VERSION
    ok: Literal[True] = True
    operation: Literal["list_tasks"] = "list_tasks"
    total_task_count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    returned_task_count: int = Field(ge=0)
    truncated: bool
    next_offset: int | None = Field(default=None, ge=0)
    tasks: tuple[TaskDiscoveryAdapterItem, ...]


CurrentPlanAdapterResponse: TypeAlias = (
    CurrentPlanAdapterResult | AdapterErrorEnvelope
)
TaskStatusAdapterResponse: TypeAlias = (
    TaskStatusAdapterResult | AdapterErrorEnvelope
)
DatasetInspectionAdapterResponse: TypeAlias = (
    DatasetInspectionAdapterResult | AdapterErrorEnvelope
)
ResultSummaryAdapterResponse: TypeAlias = (
    ResultSummaryAdapterResult | AdapterErrorEnvelope
)
TaskListAdapterResponse: TypeAlias = (
    TaskListAdapterResult | AdapterErrorEnvelope
)


class ReadOnlyAdapterConfigurationError(RuntimeError):
    """The adapter was started without a valid managed workspace."""


class AdapterProjectionError(RuntimeError):
    """Stored Tool output could not be projected through the safe view."""


def _request_view(request: UserRequest) -> PlanRequestView:
    return PlanRequestView(
        task_type=request.task_type,
        project_name=request.project_name,
        input_configured=request.input_dir is not None,
        input_layout=request.input_layout,
        binder_chain=request.binder_chain,
        target_chains=tuple(request.target_chains),
        source_chain=request.source_chain,
        target_residue_count=request.target_residue_count,
        target_start_residue=request.target_start_residue,
        normalized_target_chain=request.normalized_target_chain,
        normalized_binder_chain=request.normalized_binder_chain,
        desired_regions=tuple(request.desired_regions),
        undesired_regions=tuple(request.undesired_regions),
        hotspots=tuple(request.hotspots),
        region_policy=request.region_policy,
        region_filter=request.region_filter,
        requested_top_k=request.requested_top_k,
        execute_requested=request.execute_requested,
    )


def _plan_fields(plan: AgentPlan | None) -> dict[str, Any]:
    if plan is None:
        return {}

    return {
        "planning_status": plan.status,
        "missing_information": tuple(plan.missing_information),
        "warning_count": len(plan.warnings),
        "steps": tuple(
            PlanStepView(
                step_id=step.step_id,
                tool_name=step.tool_name,
                requires_approval=step.requires_approval,
                status=step.status,
            )
            for step in plan.steps
        ),
        "request": _request_view(plan.request),
        "config_preview_available": plan.config_preview is not None,
        "execution_allowed": plan.execution_allowed,
    }


def project_current_plan(
    *,
    task_name: str,
    result: CurrentPlanResult,
) -> CurrentPlanAdapterResult:
    return CurrentPlanAdapterResult(
        task_name=task_name,
        available=result.available,
        request_explicit_fields=tuple(result.request_explicit_fields),
        **_plan_fields(result.plan),
    )


def project_task_status(
    *,
    task_name: str,
    result: TaskStatusResult,
) -> TaskStatusAdapterResult:
    status = result.run_status
    return TaskStatusAdapterResult(
        task_name=task_name,
        project_name=status.project_name,
        planning_status=result.planning_status,
        missing_information=tuple(result.missing_information),
        current_stage=status.current_stage,
        prepare_status=status.prepare_status,
        approval_status=status.approval_status,
        execution_status=status.execution_status,
        analysis_status=status.analysis_status,
        explanation_status=status.explanation_status,
        analysis_scope_level=status.analysis_scope_level,
        approval_present=status.approval_manifest is not None,
        approval_consumed=status.approval_consumed,
        candidate_count=status.candidate_count,
        formal_candidate_recommendation_allowed=(
            status.formal_candidate_recommendation_allowed
        ),
        thresholds_formally_interpretable=(
            status.thresholds_formally_interpretable
        ),
        analysis_attempt_count=len(status.analysis_attempts),
        warning_count=len(status.warnings),
    )


def project_dataset_inspection(
    *,
    task_name: str,
    result: DatasetPlanningAdvice,
) -> DatasetInspectionAdapterResult:
    suggestion = result.conditional_suggestion
    return DatasetInspectionAdapterResult(
        task_name=task_name,
        evidence_created_at_utc=result.created_at_utc,
        status=result.status,
        recursive=result.recursive,
        processed_file_count=result.processed_file_count,
        valid_file_count=result.valid_file_count,
        invalid_file_count=result.invalid_file_count,
        all_valid_files_are_single_chain=(
            result.all_valid_files_are_single_chain
        ),
        common_single_chain_id=result.common_single_chain_id,
        chain_count_patterns=dict(result.chain_count_patterns),
        chain_signature_counts=dict(result.chain_signature_counts),
        total_residue_count_patterns=dict(
            result.total_residue_count_patterns
        ),
        dataset_warning_count=len(result.dataset_warnings),
        file_evidence=tuple(
            DatasetFileEvidenceView(
                file_name=evidence.file_name,
                sha256=evidence.sha256,
                valid=evidence.valid,
                chain_count=evidence.chain_count,
                chain_ids=tuple(evidence.chain_ids),
                total_residue_count=evidence.total_residue_count,
                chain_signature=evidence.chain_signature,
                warning_count=len(evidence.warnings),
                error_count=len(evidence.errors),
            )
            for evidence in result.file_evidence
        ),
        conditional_suggestion=(
            DatasetSuggestionView(
                candidate_patch=dict(suggestion.candidate_patch),
                evidence_item_count=len(suggestion.evidence_summary),
            )
            if suggestion is not None
            else None
        ),
        unresolved_question_count=len(result.unresolved_questions),
        caution_count=len(result.cautions),
    )


def project_result_summary(
    *,
    task_name: str,
    result: tool_api.SealedResultSummaryResult,
    limit: int,
) -> ResultSummaryAdapterResult:
    summary = result.summary
    selected = summary.candidates_by_engineering_rank[:limit]
    policy = summary.pool_reporting.policy
    return ResultSummaryAdapterResult(
        task_name=task_name,
        result_summary_sha256=result.result_summary_sha256,
        source_summary_schema_version=summary.schema_version,
        analysis_scope_level=policy.analysis_scope_level,
        reporting_mode=policy.reporting_mode,
        result_use=summary.result_use,
        candidate_count=summary.candidate_count,
        returned_candidate_count=len(selected),
        truncated=len(selected) < summary.candidate_count,
        formal_candidate_recommendation_allowed=(
            summary.formal_candidate_recommendation_allowed
        ),
        thresholds_formally_interpretable=(
            summary.thresholds_formally_interpretable
        ),
        score_decomposition_status=summary.score_decomposition_status,
        scientific_interpretation_status=(
            summary.scientific_interpretation_status
        ),
        candidate_comparison_status=summary.candidate_comparison_status,
        public_pool_counts=dict(summary.pool_reporting.public_pool_counts),
        public_pool_status=dict(summary.pool_reporting.public_pool_status),
        primary_score_formula=summary.primary_score_formula,
        primary_score_weights=dict(summary.primary_score_weights),
        candidates_by_engineering_rank=tuple(
            RankedCandidateAdapterView(
                candidate_id=candidate.pdb_name,
                engineering_rank=candidate.engineering_rank,
                final_score_v4=candidate.final_score_v4,
                public_filter_level=candidate.public_filter_level,
                public_filter_status=candidate.public_filter_status,
                broad_pass=candidate.broad_pass,
                medium_pass=candidate.medium_pass,
                strict_pass=candidate.strict_pass,
                broad_reasons=tuple(candidate.broad_reasons),
                medium_reasons=tuple(candidate.medium_reasons),
                strict_reasons=tuple(candidate.strict_reasons),
                component_scores=dict(candidate.component_scores),
                key_metrics=dict(candidate.key_metrics),
                primary_score_contributions=dict(
                    candidate.primary_score_contributions
                ),
            )
            for candidate in selected
        ),
    )


def project_task_list(
    result: tool_api.WorkspaceTaskDiscoveryResult,
) -> TaskListAdapterResult:
    return TaskListAdapterResult(
        total_task_count=result.total_task_count,
        offset=result.offset,
        limit=result.limit,
        returned_task_count=result.returned_task_count,
        truncated=result.truncated,
        next_offset=result.next_offset,
        tasks=tuple(
            TaskDiscoveryAdapterItem(
                task_name=item.task_name,
                lifecycle_status=item.lifecycle_status,
                current_stage=item.current_stage,
                sealed_result_status=item.sealed_result_status,
                candidate_count=item.candidate_count,
            )
            for item in result.tasks
        ),
    )


class ReadOnlyToolAdapter:
    """Invoke safe read-only Tool operations within one managed workspace."""

    def __init__(self, workspace_dir: Path) -> None:
        workspace = workspace_dir.expanduser().resolve()
        if detect_existing_workspace(workspace) is None:
            raise ReadOnlyAdapterConfigurationError(
                "the MCP workspace must be initialized by BinderRanker"
            )

        runs_root = workspace / "runs"
        if runs_root.is_symlink() or not runs_root.is_dir():
            raise ReadOnlyAdapterConfigurationError(
                "the managed runs directory is missing or unsafe"
            )
        if runs_root.resolve().parent != workspace:
            raise ReadOnlyAdapterConfigurationError(
                "the managed runs directory escapes the workspace"
            )

        self._workspace = workspace

    @property
    def workspace(self) -> Path:
        """Canonical host path retained only inside the adapter process."""

        return self._workspace

    def capabilities(self) -> ReadOnlyAdapterCapabilities:
        return ReadOnlyAdapterCapabilities()

    def list_tasks(
        self,
        *,
        offset: object = 0,
        limit: object = 20,
    ) -> TaskListAdapterResponse:
        return invoke_adapter_boundary(
            operation="list_tasks",
            call=lambda: self._list_tasks(offset=offset, limit=limit),
        )

    def _list_tasks(
        self,
        *,
        offset: object,
        limit: object,
    ) -> TaskListAdapterResult:
        request = TaskListRequest.model_validate(
            {"offset": offset, "limit": limit}
        )
        result = tool_api.list_tasks(
            self._workspace,
            offset=request.offset,
            limit=request.limit,
        )
        try:
            return project_task_list(result)
        except ValidationError as exc:
            raise AdapterProjectionError(
                "task inventory contains unsafe external-view fields"
            ) from exc

    def _bundle_for(self, request: ManagedTaskRequest) -> Path:
        raw_bundle = self._workspace / "runs" / request.task_name
        if raw_bundle.is_symlink():
            raise AdapterSafeError("managed task bundle is a symbolic link")

        try:
            bundle = resolve_task_bundle(
                workspace_dir=self._workspace,
                task_name=request.task_name,
            )
        except TaskPathError as exc:
            raise AdapterSafeError("managed task path is unsafe") from exc
        if not bundle.is_dir():
            raise AdapterSafeError("managed task bundle does not exist")

        return bundle

    def _validated_bundle(self, task_name: object) -> tuple[str, Path]:
        request = ManagedTaskRequest.model_validate({"task_name": task_name})
        return request.task_name, self._bundle_for(request)

    def get_current_plan(self, task_name: object) -> CurrentPlanAdapterResponse:
        return invoke_adapter_boundary(
            operation="get_current_plan",
            call=lambda: self._get_current_plan(task_name),
        )

    def _get_current_plan(self, task_name: object) -> CurrentPlanAdapterResult:
        valid_name, bundle = self._validated_bundle(task_name)
        result = tool_api.get_current_plan(bundle)
        try:
            return project_current_plan(task_name=valid_name, result=result)
        except ValidationError as exc:
            raise AdapterProjectionError(
                "current plan contains unsafe external-view fields"
            ) from exc

    def get_task_status(self, task_name: object) -> TaskStatusAdapterResponse:
        return invoke_adapter_boundary(
            operation="get_task_status",
            call=lambda: self._get_task_status(task_name),
        )

    def _get_task_status(self, task_name: object) -> TaskStatusAdapterResult:
        valid_name, bundle = self._validated_bundle(task_name)
        result = tool_api.get_task_status(bundle)
        try:
            return project_task_status(task_name=valid_name, result=result)
        except ValidationError as exc:
            raise AdapterProjectionError(
                "task status contains unsafe external-view fields"
            ) from exc

    def inspect_dataset(
        self,
        task_name: object,
    ) -> DatasetInspectionAdapterResponse:
        return invoke_adapter_boundary(
            operation="inspect_dataset",
            call=lambda: self._inspect_dataset(task_name),
        )

    def _inspect_dataset(
        self,
        task_name: object,
    ) -> DatasetInspectionAdapterResult:
        valid_name, bundle = self._validated_bundle(task_name)
        result = tool_api.inspect_dataset(bundle_dir=bundle)
        try:
            return project_dataset_inspection(task_name=valid_name, result=result)
        except ValidationError as exc:
            raise AdapterProjectionError(
                "dataset evidence contains unsafe external-view fields"
            ) from exc

    def get_result_summary(
        self,
        task_name: object,
        *,
        limit: object = 20,
    ) -> ResultSummaryAdapterResponse:
        return invoke_adapter_boundary(
            operation="get_result_summary",
            call=lambda: self._get_result_summary(task_name, limit=limit),
        )

    def _get_result_summary(
        self,
        task_name: object,
        *,
        limit: object,
    ) -> ResultSummaryAdapterResult:
        request = ResultSummaryRequest.model_validate(
            {"task_name": task_name, "limit": limit}
        )
        bundle = self._bundle_for(request)
        result = tool_api.get_result_summary(bundle)
        try:
            return project_result_summary(
                task_name=request.task_name,
                result=result,
                limit=request.limit,
            )
        except ValidationError as exc:
            raise AdapterProjectionError(
                "result summary contains unsafe external-view fields"
            ) from exc

    def invoke(
        self,
        operation: object,
        *,
        task_name: object = None,
        offset: object = 0,
        limit: object = 20,
    ) -> BaseModel:
        """Dispatch a published read-only operation without dynamic imports."""

        if operation == "list_tasks":
            return self.list_tasks(offset=offset, limit=limit)
        if operation == "get_current_plan":
            return self.get_current_plan(task_name)
        if operation == "get_task_status":
            return self.get_task_status(task_name)
        if operation == "inspect_dataset":
            return self.inspect_dataset(task_name)
        if operation == "get_result_summary":
            return self.get_result_summary(task_name, limit=limit)

        error = UnknownToolOperationError(operation)
        result = invoke_adapter_boundary(
            operation=operation,
            call=lambda: (_ for _ in ()).throw(error),
        )
        if not isinstance(result, AdapterErrorEnvelope):
            raise AssertionError("unknown operation must produce an error")
        return result


__all__ = [
    "CurrentPlanAdapterResponse",
    "CurrentPlanAdapterResult",
    "AdapterProjectionError",
    "DatasetInspectionAdapterResponse",
    "DatasetInspectionAdapterResult",
    "DEFERRED_ADAPTER_OPERATIONS",
    "ManagedTaskRequest",
    "PlanRequestView",
    "RankedCandidateAdapterView",
    "READ_ONLY_ADAPTER_OPERATIONS",
    "READ_ONLY_ADAPTER_SCHEMA_VERSION",
    "ReadOnlyAdapterCapabilities",
    "ReadOnlyAdapterConfigurationError",
    "ReadOnlyToolAdapter",
    "ResultSummaryAdapterResponse",
    "ResultSummaryAdapterResult",
    "ResultSummaryRequest",
    "TaskDiscoveryAdapterItem",
    "TaskListAdapterResponse",
    "TaskListAdapterResult",
    "TaskListRequest",
    "TaskStatusAdapterResponse",
    "TaskStatusAdapterResult",
    "project_current_plan",
    "project_dataset_inspection",
    "project_result_summary",
    "project_task_list",
    "project_task_status",
]
