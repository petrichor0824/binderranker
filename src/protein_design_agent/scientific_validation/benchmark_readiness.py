"""Validate benchmark provenance declarations and report structural readiness."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from protein_design_agent.scientific_validation.benchmark_contract import (
    Identifier,
    ValidatedBenchmarkBundle,
)
from protein_design_agent.scientific_validation.benchmark_sensitivity import (
    TargetSensitivityError,
    evaluate_target_sensitivity,
)


BenchmarkDataKind = Literal[
    "REAL_RETROSPECTIVE",
    "SYNTHETIC_FIXTURE",
]

ReadinessWarning = Literal[
    "DECLARATIONS_NOT_INDEPENDENTLY_VERIFIED",
    "SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE",
    "SINGLE_EVALUATION_TARGET",
    "FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS",
    "NO_TARGET_WITH_BOTH_OUTCOME_CLASSES",
    "IDENTICAL_RANKINGS_ALL_CAMPAIGNS",
    "COMPUTATIONAL_PROXY_NOT_EXPERIMENTAL_EVIDENCE",
    "FORMAL_INFERENCE_NOT_ESTABLISHED",
]

NonEmptyText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=4096,
    ),
]

RecordIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
    ),
]


class BenchmarkReadinessError(RuntimeError):
    """A benchmark readiness declaration cannot be trusted structurally."""


class _ReadinessModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class BenchmarkDataFreezeDeclaration(_ReadinessModel):
    """Declared identity and extraction history of the frozen dataset."""

    frozen_at: AwareDatetime
    source_system: NonEmptyText
    extraction_procedure: NonEmptyText
    immutable_record_id: RecordIdentifier


class BenchmarkCohortDeclaration(_ReadinessModel):
    """Declared construction rules for the candidate cohort."""

    inclusion_criteria: NonEmptyText
    exclusion_criteria: NonEmptyText
    candidate_universe_complete: Literal[True]
    missing_outcome_policy: NonEmptyText


class BenchmarkReviewDeclaration(_ReadinessModel):
    """Declared scientific review actions bound to an analysis plan."""

    outcome_definition_reviewed: Literal[True]
    baseline_procedure_reviewed: Literal[True]
    leakage_reviewed: Literal[True]
    analysis_plan_id: Identifier
    reviewer_role: NonEmptyText
    review_record_id: RecordIdentifier
    reviewed_at: AwareDatetime


class BenchmarkReadinessChecklist(_ReadinessModel):
    """Strict companion record bound to one exact benchmark bundle."""

    schema_version: Literal["0.1"]
    benchmark_id: Identifier
    manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    dataset_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    data_kind: BenchmarkDataKind
    data_freeze: BenchmarkDataFreezeDeclaration
    cohort: BenchmarkCohortDeclaration
    review: BenchmarkReviewDeclaration
    evidence_limitations: tuple[
        NonEmptyText,
        ...,
    ] = Field(
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_review_timing(self) -> BenchmarkReadinessChecklist:
        if self.review.reviewed_at < self.data_freeze.frozen_at:
            raise ValueError(
                "review.reviewed_at cannot precede data_freeze.frozen_at"
            )
        if len(set(self.evidence_limitations)) != len(
            self.evidence_limitations
        ):
            raise ValueError("evidence_limitations must be unique")
        return self


class StructuralReadinessState(_ReadinessModel):
    """Availability of a method implied only by benchmark structure."""

    status: Literal[
        "AVAILABLE",
        "UNAVAILABLE",
    ]
    reason: Literal[
        "SINGLE_EVALUATION_TARGET",
        "FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS",
    ] | None = None

    @model_validator(mode="after")
    def validate_state(self) -> StructuralReadinessState:
        if self.status == "AVAILABLE" and self.reason is not None:
            raise ValueError("available readiness cannot have a reason")
        if self.status == "UNAVAILABLE" and self.reason is None:
            raise ValueError("unavailable readiness requires a reason")
        return self


class BenchmarkReadinessReport(_ReadinessModel):
    """Deterministic facts and boundaries for scientific review intake."""

    schema_version: Literal["0.1"] = "0.1"
    benchmark_id: Identifier
    manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    dataset_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    checklist_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    data_kind: BenchmarkDataKind
    outcome_evidence_type: Literal[
        "EXPERIMENTAL",
        "COMPUTATIONAL_PROXY",
    ]
    engineering_readiness_status: Literal["READY"] = "READY"
    scientific_review_status: Literal[
        "FIXTURE_ONLY",
        "READY_FOR_SCIENTIFIC_REVIEW",
    ]
    claim_scope: Literal["READINESS_METADATA_ONLY"] = (
        "READINESS_METADATA_ONLY"
    )
    declarations_structurally_valid: Literal[True] = True
    declaration_truth_independently_verified: Literal[False] = False
    formal_inference_established: Literal[False] = False
    performance_benefit_established: Literal[False] = False
    analysis_plan_id: Identifier
    review_record_id: RecordIdentifier
    immutable_record_id: RecordIdentifier
    frozen_at: AwareDatetime
    reviewed_at: AwareDatetime
    evaluation_target_count: int = Field(ge=1)
    evaluation_campaign_count: int = Field(ge=1)
    evaluation_candidate_count: int = Field(ge=2)
    evaluation_positive_count: int = Field(ge=1)
    evaluation_negative_count: int = Field(ge=1)
    targets_with_both_outcome_classes: int = Field(ge=0)
    positive_only_target_count: int = Field(ge=0)
    negative_only_target_count: int = Field(ge=0)
    campaigns_with_both_outcome_classes: int = Field(ge=0)
    positive_only_campaign_count: int = Field(ge=0)
    negative_only_campaign_count: int = Field(ge=0)
    minimum_campaigns_per_target: int = Field(ge=1)
    maximum_campaigns_per_target: int = Field(ge=1)
    minimum_candidates_per_campaign: int = Field(ge=2)
    maximum_candidates_per_campaign: int = Field(ge=2)
    rankings_identical_all_campaigns: bool
    target_removal_sensitivity: StructuralReadinessState
    positive_denominator_target_sensitivity: StructuralReadinessState
    warnings: tuple[ReadinessWarning, ...]

    @model_validator(mode="after")
    def validate_internal_consistency(self) -> BenchmarkReadinessReport:
        if (
            self.targets_with_both_outcome_classes
            + self.positive_only_target_count
            + self.negative_only_target_count
            != self.evaluation_target_count
        ):
            raise ValueError("target outcome counts do not sum to target total")
        if (
            self.campaigns_with_both_outcome_classes
            + self.positive_only_campaign_count
            + self.negative_only_campaign_count
            != self.evaluation_campaign_count
        ):
            raise ValueError(
                "campaign outcome counts do not sum to campaign total"
            )
        if self.minimum_campaigns_per_target > self.maximum_campaigns_per_target:
            raise ValueError("campaign-per-target range is invalid")
        if (
            self.minimum_candidates_per_campaign
            > self.maximum_candidates_per_campaign
        ):
            raise ValueError("candidate-per-campaign range is invalid")
        expected_status = (
            "FIXTURE_ONLY"
            if self.data_kind == "SYNTHETIC_FIXTURE"
            else "READY_FOR_SCIENTIFIC_REVIEW"
        )
        if self.scientific_review_status != expected_status:
            raise ValueError("scientific review status disagrees with data kind")
        expected_target_state = (
            StructuralReadinessState(status="AVAILABLE")
            if self.evaluation_target_count >= 2
            else StructuralReadinessState(
                status="UNAVAILABLE",
                reason="SINGLE_EVALUATION_TARGET",
            )
        )
        if self.target_removal_sensitivity != expected_target_state:
            raise ValueError(
                "target-removal readiness disagrees with target count"
            )
        positive_target_count = (
            self.targets_with_both_outcome_classes
            + self.positive_only_target_count
        )
        expected_positive_state = (
            StructuralReadinessState(status="AVAILABLE")
            if positive_target_count >= 2
            else StructuralReadinessState(
                status="UNAVAILABLE",
                reason="FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS",
            )
        )
        if (
            self.positive_denominator_target_sensitivity
            != expected_positive_state
        ):
            raise ValueError(
                "positive-denominator readiness disagrees with target counts"
            )
        expected_warnings = {
            "DECLARATIONS_NOT_INDEPENDENTLY_VERIFIED",
            "FORMAL_INFERENCE_NOT_ESTABLISHED",
        }
        if self.data_kind == "SYNTHETIC_FIXTURE":
            expected_warnings.add("SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE")
        if self.evaluation_target_count == 1:
            expected_warnings.add("SINGLE_EVALUATION_TARGET")
        if positive_target_count < 2:
            expected_warnings.add("FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS")
        if self.targets_with_both_outcome_classes == 0:
            expected_warnings.add("NO_TARGET_WITH_BOTH_OUTCOME_CLASSES")
        if self.rankings_identical_all_campaigns:
            expected_warnings.add("IDENTICAL_RANKINGS_ALL_CAMPAIGNS")
        if self.outcome_evidence_type == "COMPUTATIONAL_PROXY":
            expected_warnings.add(
                "COMPUTATIONAL_PROXY_NOT_EXPERIMENTAL_EVIDENCE"
            )
        warning_set = set(self.warnings)
        if warning_set != expected_warnings:
            raise ValueError("warnings disagree with deterministic report facts")
        if len(warning_set) != len(self.warnings):
            raise ValueError("warnings must be unique")
        return self


def _load_benchmark_readiness_checklist(
    path: Path,
) -> tuple[BenchmarkReadinessChecklist, str]:
    resolved = Path(path).resolve()
    if resolved.suffix.casefold() not in {".yaml", ".yml"}:
        raise BenchmarkReadinessError(
            "benchmark readiness checklist 必须是 YAML 文件"
        )
    try:
        encoded = resolved.read_bytes()
    except OSError as exc:
        raise BenchmarkReadinessError(
            f"无法读取 benchmark readiness checklist：{resolved}；{exc}"
        ) from exc
    try:
        raw = yaml.safe_load(encoded.decode("utf-8"))
    except UnicodeError as exc:
        raise BenchmarkReadinessError(
            f"benchmark readiness checklist 不是有效 UTF-8：{resolved}；{exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise BenchmarkReadinessError(
            f"benchmark readiness checklist YAML 格式无效：{resolved}；{exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise BenchmarkReadinessError(
            "benchmark readiness checklist 最外层必须是键值对象"
        )
    try:
        checklist = BenchmarkReadinessChecklist.model_validate(raw)
    except ValidationError as exc:
        raise BenchmarkReadinessError(
            "benchmark readiness checklist 不符合 schema："
            f"{resolved}；{exc}"
        ) from exc
    return checklist, hashlib.sha256(encoded).hexdigest()


def load_benchmark_readiness_checklist(
    path: Path,
) -> BenchmarkReadinessChecklist:
    """Load one strict YAML readiness checklist."""
    checklist, _ = _load_benchmark_readiness_checklist(path)
    return checklist


def _outcome_class_counts(
    groups: dict[str, list[int]],
) -> tuple[int, int, int]:
    both = 0
    positive_only = 0
    negative_only = 0
    for outcomes in groups.values():
        classes = set(outcomes)
        if classes == {0, 1}:
            both += 1
        elif classes == {1}:
            positive_only += 1
        else:
            negative_only += 1
    return both, positive_only, negative_only


def validate_benchmark_readiness(
    bundle: ValidatedBenchmarkBundle,
    checklist_path: Path,
) -> BenchmarkReadinessReport:
    """Bind review declarations to a current bundle and report readiness facts."""
    try:
        sensitivity = evaluate_target_sensitivity(bundle)
    except TargetSensitivityError as exc:
        raise BenchmarkReadinessError(
            "benchmark readiness requires a current validated benchmark bundle"
        ) from exc

    checklist, checklist_sha256 = _load_benchmark_readiness_checklist(
        checklist_path
    )
    expected_bindings = {
        "benchmark_id": sensitivity.benchmark_id,
        "manifest_sha256": sensitivity.manifest_sha256,
        "dataset_sha256": sensitivity.dataset_sha256,
    }
    actual_bindings = {
        "benchmark_id": checklist.benchmark_id,
        "manifest_sha256": checklist.manifest_sha256,
        "dataset_sha256": checklist.dataset_sha256,
    }
    if actual_bindings != expected_bindings:
        raise BenchmarkReadinessError(
            "benchmark readiness checklist does not match the current sealed "
            f"bundle; expected={expected_bindings}, actual={actual_bindings}"
        )

    evaluation_records = tuple(
        record for record in bundle.records if record.split == "EVALUATION"
    )
    target_outcomes: dict[str, list[int]] = defaultdict(list)
    campaign_outcomes: dict[str, list[int]] = defaultdict(list)
    target_campaigns: dict[str, set[str]] = defaultdict(set)
    campaign_candidate_counts: dict[str, int] = defaultdict(int)
    rankings_identical = True
    for record in evaluation_records:
        target_outcomes[record.target_id].append(record.outcome)
        campaign_outcomes[record.campaign_id].append(record.outcome)
        target_campaigns[record.target_id].add(record.campaign_id)
        campaign_candidate_counts[record.campaign_id] += 1
        if record.binderranker_rank != record.baseline_rank:
            rankings_identical = False

    target_both, target_positive_only, target_negative_only = (
        _outcome_class_counts(target_outcomes)
    )
    campaign_both, campaign_positive_only, campaign_negative_only = (
        _outcome_class_counts(campaign_outcomes)
    )
    targets_with_positive_outcomes = target_both + target_positive_only

    warnings: list[ReadinessWarning] = [
        "DECLARATIONS_NOT_INDEPENDENTLY_VERIFIED",
    ]
    if checklist.data_kind == "SYNTHETIC_FIXTURE":
        warnings.append("SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE")
    if sensitivity.evaluation_target_count == 1:
        warnings.append("SINGLE_EVALUATION_TARGET")
    if targets_with_positive_outcomes < 2:
        warnings.append("FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS")
    if target_both == 0:
        warnings.append("NO_TARGET_WITH_BOTH_OUTCOME_CLASSES")
    if rankings_identical:
        warnings.append("IDENTICAL_RANKINGS_ALL_CAMPAIGNS")
    if sensitivity.outcome_evidence_type == "COMPUTATIONAL_PROXY":
        warnings.append("COMPUTATIONAL_PROXY_NOT_EXPERIMENTAL_EVIDENCE")
    warnings.append("FORMAL_INFERENCE_NOT_ESTABLISHED")

    campaigns_per_target = tuple(
        len(campaigns) for campaigns in target_campaigns.values()
    )
    candidates_per_campaign = tuple(campaign_candidate_counts.values())
    target_removal_state = (
        StructuralReadinessState(status="AVAILABLE")
        if sensitivity.evaluation_target_count >= 2
        else StructuralReadinessState(
            status="UNAVAILABLE",
            reason="SINGLE_EVALUATION_TARGET",
        )
    )
    positive_denominator_state = (
        StructuralReadinessState(status="AVAILABLE")
        if targets_with_positive_outcomes >= 2
        else StructuralReadinessState(
            status="UNAVAILABLE",
            reason="FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS",
        )
    )

    return BenchmarkReadinessReport(
        benchmark_id=checklist.benchmark_id,
        manifest_sha256=checklist.manifest_sha256,
        dataset_sha256=checklist.dataset_sha256,
        checklist_sha256=checklist_sha256,
        data_kind=checklist.data_kind,
        outcome_evidence_type=sensitivity.outcome_evidence_type,
        scientific_review_status=(
            "FIXTURE_ONLY"
            if checklist.data_kind == "SYNTHETIC_FIXTURE"
            else "READY_FOR_SCIENTIFIC_REVIEW"
        ),
        analysis_plan_id=checklist.review.analysis_plan_id,
        review_record_id=checklist.review.review_record_id,
        immutable_record_id=checklist.data_freeze.immutable_record_id,
        frozen_at=checklist.data_freeze.frozen_at,
        reviewed_at=checklist.review.reviewed_at,
        evaluation_target_count=sensitivity.evaluation_target_count,
        evaluation_campaign_count=sensitivity.evaluation_campaign_count,
        evaluation_candidate_count=len(evaluation_records),
        evaluation_positive_count=sum(
            record.outcome for record in evaluation_records
        ),
        evaluation_negative_count=sum(
            1 - record.outcome for record in evaluation_records
        ),
        targets_with_both_outcome_classes=target_both,
        positive_only_target_count=target_positive_only,
        negative_only_target_count=target_negative_only,
        campaigns_with_both_outcome_classes=campaign_both,
        positive_only_campaign_count=campaign_positive_only,
        negative_only_campaign_count=campaign_negative_only,
        minimum_campaigns_per_target=min(campaigns_per_target),
        maximum_campaigns_per_target=max(campaigns_per_target),
        minimum_candidates_per_campaign=min(candidates_per_campaign),
        maximum_candidates_per_campaign=max(candidates_per_campaign),
        rankings_identical_all_campaigns=rankings_identical,
        target_removal_sensitivity=target_removal_state,
        positive_denominator_target_sensitivity=positive_denominator_state,
        warnings=tuple(warnings),
    )
