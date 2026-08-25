"""Validate sealed, leakage-aware BinderRanker benchmark bundles."""

from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)


BenchmarkSplit = Literal[
    "CALIBRATION",
    "EVALUATION",
]

EvidenceType = Literal[
    "EXPERIMENTAL",
    "COMPUTATIONAL_PROXY",
]

ParameterSelectionPolicy = Literal[
    "FROZEN_PREDEFINED",
    "CALIBRATION_ONLY",
]

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]

PositiveBudget = Annotated[
    int,
    Field(gt=0),
]

REQUIRED_BENCHMARK_COLUMNS = {
    "campaign_id",
    "target_id",
    "candidate_id",
    "split",
    "binderranker_rank",
    "binderranker_score",
    "baseline_rank",
    "outcome",
}

_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)

_POSITIVE_INTEGER_PATTERN = re.compile(
    r"^[1-9][0-9]*$"
)


class BenchmarkContractError(RuntimeError):
    """The benchmark bundle cannot support trustworthy evaluation."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class BenchmarkDatasetDefinition(_ContractModel):
    """Sealed candidate-level CSV declared by the manifest."""

    file: Path
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )


class BenchmarkOutcomeDefinition(_ContractModel):
    """Meaning and provenance of the binary benchmark outcome."""

    name: Identifier
    description: str = Field(
        min_length=1,
    )
    evidence_type: EvidenceType
    source: str = Field(
        min_length=1,
    )


class BenchmarkBaselineDefinition(_ContractModel):
    """Comparator used for the required baseline ranking."""

    method_id: Identifier
    description: str = Field(
        min_length=1,
    )
    ranking_procedure: str = Field(
        min_length=1,
    )


class BenchmarkRankerProvenance(_ContractModel):
    """Frozen BinderRanker implementation used to generate ranks."""

    ranker_id: Literal["BinderRanker"]
    version: Identifier
    resource_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )


class BenchmarkProtocol(_ContractModel):
    """Declarations needed to interpret a retrospective benchmark."""

    parameter_selection: ParameterSelectionPolicy
    ranking_blinded_to_outcomes: Literal[True]
    baseline_blinded_to_outcomes: Literal[True]
    target_split_unit: Literal["TARGET"]


class BenchmarkManifest(_ContractModel):
    """Auditable definition of one BinderRanker benchmark bundle."""

    schema_version: Literal["0.1"]
    benchmark_id: Identifier
    description: str = Field(
        min_length=1,
    )
    dataset: BenchmarkDatasetDefinition
    outcome: BenchmarkOutcomeDefinition
    baseline: BenchmarkBaselineDefinition
    ranker: BenchmarkRankerProvenance
    protocol: BenchmarkProtocol
    selection_budgets: tuple[
        PositiveBudget,
        ...,
    ] = Field(
        min_length=1,
    )

    @field_validator("selection_budgets")
    @classmethod
    def validate_selection_budgets(
        cls,
        values: tuple[int, ...],
    ) -> tuple[int, ...]:
        if values != tuple(
            sorted(set(values))
        ):
            raise ValueError(
                "selection_budgets must be "
                "strictly increasing and unique"
            )

        return values


class BenchmarkCandidateRecord(_ContractModel):
    """Normalized candidate row admitted by the shared contract."""

    campaign_id: Identifier
    target_id: Identifier
    candidate_id: Identifier
    split: BenchmarkSplit
    binderranker_rank: int = Field(
        ge=1,
    )
    binderranker_score: float
    baseline_rank: int = Field(
        ge=1,
    )
    outcome: Literal[0, 1]


class BenchmarkValidationSummary(_ContractModel):
    """Deterministic facts established by benchmark validation."""

    schema_version: Literal["0.1"] = "0.1"
    scientifically_valid: Literal[True] = True
    benchmark_id: Identifier
    campaign_count: int = Field(
        ge=1,
    )
    target_count: int = Field(
        ge=1,
    )
    candidate_count: int = Field(
        ge=1,
    )
    calibration_campaign_count: int = Field(
        ge=0,
    )
    calibration_target_count: int = Field(
        ge=0,
    )
    evaluation_campaign_count: int = Field(
        ge=1,
    )
    evaluation_target_count: int = Field(
        ge=1,
    )
    evaluation_positive_count: int = Field(
        ge=1,
    )
    evaluation_negative_count: int = Field(
        ge=1,
    )
    selection_budgets: tuple[
        PositiveBudget,
        ...,
    ] = Field(
        min_length=1,
    )
    manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )
    dataset_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
    )


class ValidatedBenchmarkBundle(_ContractModel):
    """Manifest and normalized records behind a trusted benchmark."""

    manifest_path: Path
    dataset_path: Path
    manifest: BenchmarkManifest
    records: tuple[
        BenchmarkCandidateRecord,
        ...,
    ]
    summary: BenchmarkValidationSummary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)
    except OSError as exc:
        raise BenchmarkContractError(
            "无法读取 benchmark 文件以计算 SHA256："
            f"{path}；{exc}"
        ) from exc

    return digest.hexdigest()


def load_benchmark_manifest(
    path: Path,
) -> BenchmarkManifest:
    """Load a strict benchmark manifest without reading its dataset."""
    resolved = Path(path).resolve()

    try:
        raw = yaml.safe_load(
            resolved.read_text(
                encoding="utf-8",
            )
        )
    except OSError as exc:
        raise BenchmarkContractError(
            f"无法读取 benchmark manifest：{resolved}；{exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise BenchmarkContractError(
            "benchmark manifest YAML 格式无效："
            f"{resolved}；{exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise BenchmarkContractError(
            "benchmark manifest 最外层必须是键值对象："
            f"{resolved}"
        )

    try:
        return BenchmarkManifest.model_validate(
            raw
        )
    except ValidationError as exc:
        raise BenchmarkContractError(
            "benchmark manifest 不符合 schema："
            f"{resolved}；{exc}"
        ) from exc


def _resolve_dataset_path(
    *,
    manifest_path: Path,
    declared_path: Path,
) -> Path:
    if declared_path.is_absolute():
        raise BenchmarkContractError(
            "benchmark dataset.file 必须是相对路径"
        )

    bundle_root = manifest_path.parent.resolve()
    resolved = (
        bundle_root
        / declared_path
    ).resolve()

    try:
        resolved.relative_to(
            bundle_root
        )
    except ValueError as exc:
        raise BenchmarkContractError(
            "benchmark dataset.file 不能逃逸 manifest 目录："
            f"{declared_path}"
        ) from exc

    if resolved.suffix.casefold() != ".csv":
        raise BenchmarkContractError(
            "benchmark dataset.file 必须是 CSV 文件："
            f"{declared_path}"
        )

    if not resolved.is_file():
        raise BenchmarkContractError(
            f"benchmark 数据文件不存在：{resolved}"
        )

    if resolved.stat().st_size <= 0:
        raise BenchmarkContractError(
            f"benchmark 数据文件为空：{resolved}"
        )

    return resolved


def _read_candidate_rows(
    path: Path,
) -> list[dict[str, str | None]]:
    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            headers = list(
                reader.fieldnames
                or []
            )

            if not headers:
                raise BenchmarkContractError(
                    "benchmark CSV 缺少表头"
                )

            if len(set(headers)) != len(headers):
                raise BenchmarkContractError(
                    "benchmark CSV 包含重复列名"
                )

            missing = sorted(
                REQUIRED_BENCHMARK_COLUMNS
                - set(headers)
            )
            if missing:
                raise BenchmarkContractError(
                    "benchmark CSV 缺少必需列："
                    f"{missing}"
                )

            rows = list(reader)
    except BenchmarkContractError:
        raise
    except (
        OSError,
        UnicodeError,
        csv.Error,
    ) as exc:
        raise BenchmarkContractError(
            f"无法读取 benchmark CSV：{path}；{exc}"
        ) from exc

    if not rows:
        raise BenchmarkContractError(
            "benchmark CSV 没有候选数据"
        )

    if any(None in row for row in rows):
        raise BenchmarkContractError(
            "benchmark CSV 存在与表头不匹配的数据列"
        )

    return rows


def _identifier(
    raw: str | None,
    *,
    column: str,
    row_number: int,
) -> str:
    value = str(
        raw
        or ""
    ).strip()

    if not _IDENTIFIER_PATTERN.fullmatch(
        value
    ):
        raise BenchmarkContractError(
            f"benchmark CSV 的 {column} 无效；"
            f"数据行={row_number}，值={value!r}"
        )

    return value


def _positive_integer(
    raw: str | None,
    *,
    column: str,
    row_number: int,
) -> int:
    value = str(
        raw
        or ""
    ).strip()

    if not _POSITIVE_INTEGER_PATTERN.fullmatch(
        value
    ):
        raise BenchmarkContractError(
            f"benchmark CSV 的 {column} 必须是正整数；"
            f"数据行={row_number}，值={value!r}"
        )

    return int(value)


def _finite_score(
    raw: str | None,
    *,
    row_number: int,
) -> float:
    value = str(
        raw
        or ""
    ).strip()

    try:
        parsed = float(value)
    except ValueError as exc:
        raise BenchmarkContractError(
            "benchmark CSV 的 binderranker_score "
            "必须是数值；"
            f"数据行={row_number}，值={value!r}"
        ) from exc

    if not math.isfinite(parsed):
        raise BenchmarkContractError(
            "benchmark CSV 的 binderranker_score "
            "必须是有限数值；"
            f"数据行={row_number}，值={value!r}"
        )

    return parsed


def _split(
    raw: str | None,
    *,
    row_number: int,
) -> BenchmarkSplit:
    value = str(
        raw
        or ""
    ).strip().upper()

    if value not in {
        "CALIBRATION",
        "EVALUATION",
    }:
        raise BenchmarkContractError(
            "benchmark CSV 的 split 必须是 "
            "CALIBRATION 或 EVALUATION；"
            f"数据行={row_number}，值={value!r}"
        )

    return cast(
        BenchmarkSplit,
        value,
    )


def _outcome(
    raw: str | None,
    *,
    row_number: int,
) -> Literal[0, 1]:
    value = str(
        raw
        or ""
    ).strip()

    if value not in {
        "0",
        "1",
    }:
        raise BenchmarkContractError(
            "benchmark CSV 的 outcome 必须是 0 或 1；"
            f"数据行={row_number}，值={value!r}"
        )

    return 1 if value == "1" else 0


def _parse_candidate_records(
    rows: list[dict[str, str | None]],
) -> tuple[BenchmarkCandidateRecord, ...]:
    records: list[
        BenchmarkCandidateRecord
    ] = []

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        records.append(
            BenchmarkCandidateRecord(
                campaign_id=_identifier(
                    row.get("campaign_id"),
                    column="campaign_id",
                    row_number=row_number,
                ),
                target_id=_identifier(
                    row.get("target_id"),
                    column="target_id",
                    row_number=row_number,
                ),
                candidate_id=_identifier(
                    row.get("candidate_id"),
                    column="candidate_id",
                    row_number=row_number,
                ),
                split=_split(
                    row.get("split"),
                    row_number=row_number,
                ),
                binderranker_rank=(
                    _positive_integer(
                        row.get(
                            "binderranker_rank"
                        ),
                        column="binderranker_rank",
                        row_number=row_number,
                    )
                ),
                binderranker_score=(
                    _finite_score(
                        row.get(
                            "binderranker_score"
                        ),
                        row_number=row_number,
                    )
                ),
                baseline_rank=(
                    _positive_integer(
                        row.get(
                            "baseline_rank"
                        ),
                        column="baseline_rank",
                        row_number=row_number,
                    )
                ),
                outcome=_outcome(
                    row.get("outcome"),
                    row_number=row_number,
                ),
            )
        )

    return tuple(records)


def _validate_rank_permutation(
    *,
    campaign_id: str,
    rank_name: str,
    ranks: list[int],
) -> None:
    expected = list(
        range(
            1,
            len(ranks) + 1,
        )
    )

    if sorted(ranks) != expected:
        raise BenchmarkContractError(
            f"campaign {campaign_id!r} 的 {rank_name} "
            "必须是从 1 开始的连续唯一排名；"
            f"实际={sorted(ranks)}"
        )


def _validate_records(
    *,
    manifest: BenchmarkManifest,
    records: tuple[
        BenchmarkCandidateRecord,
        ...,
    ],
    manifest_sha256: str,
    dataset_sha256: str,
) -> BenchmarkValidationSummary:
    campaigns: dict[
        str,
        list[BenchmarkCandidateRecord],
    ] = defaultdict(list)
    seen_candidates: set[
        tuple[str, str]
    ] = set()

    for record in records:
        candidate_key = (
            record.campaign_id,
            record.candidate_id,
        )
        if candidate_key in seen_candidates:
            raise BenchmarkContractError(
                "benchmark CSV 包含重复 campaign/candidate："
                f"{candidate_key}"
            )

        seen_candidates.add(
            candidate_key
        )
        campaigns[
            record.campaign_id
        ].append(record)

    target_splits: dict[
        str,
        set[BenchmarkSplit],
    ] = defaultdict(set)

    for campaign_id, campaign_records in campaigns.items():
        target_ids = {
            record.target_id
            for record in campaign_records
        }
        splits = {
            record.split
            for record in campaign_records
        }

        if len(target_ids) != 1 or len(splits) != 1:
            raise BenchmarkContractError(
                f"campaign {campaign_id!r} 必须只属于一个 "
                "target 和一个 split"
            )

        if len(campaign_records) < 2:
            raise BenchmarkContractError(
                f"campaign {campaign_id!r} 至少需要 2 个候选"
            )

        target_id = next(
            iter(target_ids)
        )
        split = next(
            iter(splits)
        )
        target_splits[
            target_id
        ].add(split)

        _validate_rank_permutation(
            campaign_id=campaign_id,
            rank_name="binderranker_rank",
            ranks=[
                record.binderranker_rank
                for record in campaign_records
            ],
        )
        _validate_rank_permutation(
            campaign_id=campaign_id,
            rank_name="baseline_rank",
            ranks=[
                record.baseline_rank
                for record in campaign_records
            ],
        )

        ordered = sorted(
            campaign_records,
            key=lambda record: (
                record.binderranker_rank
            ),
        )
        for previous, current in pairwise(
            ordered
        ):
            if (
                previous.binderranker_score
                < current.binderranker_score
            ):
                raise BenchmarkContractError(
                    f"campaign {campaign_id!r} 的 "
                    "binderranker_rank 与分数降序不一致"
                )

        if (
            max(
                manifest.selection_budgets
            )
            > len(campaign_records)
        ):
            raise BenchmarkContractError(
                f"campaign {campaign_id!r} 的候选数不足以支持 "
                "selection_budgets；"
                f"候选={len(campaign_records)}，"
                f"最大预算={max(manifest.selection_budgets)}"
            )

    leaked_targets = sorted(
        target_id
        for target_id, splits in target_splits.items()
        if len(splits) > 1
    )
    if leaked_targets:
        raise BenchmarkContractError(
            "同一 target 不能同时出现在 CALIBRATION "
            "和 EVALUATION；"
            f"泄漏 targets={leaked_targets}"
        )

    minimum_campaign_size = min(
        len(campaign_records)
        for campaign_records in campaigns.values()
    )
    if (
        min(
            manifest.selection_budgets
        )
        >= minimum_campaign_size
    ):
        raise BenchmarkContractError(
            "selection_budgets 必须至少包含一个小于所有 "
            "campaign 候选数的固定预算"
        )

    calibration_targets = {
        target_id
        for target_id, splits in target_splits.items()
        if splits == {
            "CALIBRATION"
        }
    }
    evaluation_targets = {
        target_id
        for target_id, splits in target_splits.items()
        if splits == {
            "EVALUATION"
        }
    }

    if not evaluation_targets:
        raise BenchmarkContractError(
            "benchmark 至少需要一个 EVALUATION target"
        )

    if (
        manifest.protocol.parameter_selection
        == "CALIBRATION_ONLY"
        and not calibration_targets
    ):
        raise BenchmarkContractError(
            "parameter_selection=CALIBRATION_ONLY 时至少需要"
            "一个 CALIBRATION target"
        )

    evaluation_records = [
        record
        for record in records
        if record.split == "EVALUATION"
    ]
    evaluation_positive_count = sum(
        record.outcome
        for record in evaluation_records
    )
    evaluation_negative_count = (
        len(evaluation_records)
        - evaluation_positive_count
    )

    if evaluation_positive_count < 1:
        raise BenchmarkContractError(
            "EVALUATION split 至少需要一个正 outcome"
        )

    if evaluation_negative_count < 1:
        raise BenchmarkContractError(
            "EVALUATION split 至少需要一个负 outcome"
        )

    calibration_campaigns = {
        record.campaign_id
        for record in records
        if record.split == "CALIBRATION"
    }
    evaluation_campaigns = {
        record.campaign_id
        for record in records
        if record.split == "EVALUATION"
    }

    return BenchmarkValidationSummary(
        benchmark_id=(
            manifest.benchmark_id
        ),
        campaign_count=len(
            campaigns
        ),
        target_count=len(
            target_splits
        ),
        candidate_count=len(
            records
        ),
        calibration_campaign_count=len(
            calibration_campaigns
        ),
        calibration_target_count=len(
            calibration_targets
        ),
        evaluation_campaign_count=len(
            evaluation_campaigns
        ),
        evaluation_target_count=len(
            evaluation_targets
        ),
        evaluation_positive_count=(
            evaluation_positive_count
        ),
        evaluation_negative_count=(
            evaluation_negative_count
        ),
        selection_budgets=(
            manifest.selection_budgets
        ),
        manifest_sha256=(
            manifest_sha256
        ),
        dataset_sha256=(
            dataset_sha256
        ),
    )


def validate_benchmark_bundle(
    manifest_path: Path,
) -> ValidatedBenchmarkBundle:
    """Validate a sealed benchmark without computing performance claims."""
    resolved_manifest = Path(
        manifest_path
    ).resolve()
    manifest = load_benchmark_manifest(
        resolved_manifest
    )
    manifest_sha256 = _sha256_file(
        resolved_manifest
    )
    dataset_path = _resolve_dataset_path(
        manifest_path=resolved_manifest,
        declared_path=manifest.dataset.file,
    )
    dataset_sha256 = _sha256_file(
        dataset_path
    )

    if (
        dataset_sha256
        != manifest.dataset.sha256
    ):
        raise BenchmarkContractError(
            "benchmark dataset SHA256 与 manifest 不一致；"
            f"实际={dataset_sha256}，"
            f"声明={manifest.dataset.sha256}"
        )

    rows = _read_candidate_rows(
        dataset_path
    )
    records = _parse_candidate_records(
        rows
    )
    summary = _validate_records(
        manifest=manifest,
        records=records,
        manifest_sha256=manifest_sha256,
        dataset_sha256=dataset_sha256,
    )
    canonical_records = tuple(
        sorted(
            records,
            key=lambda record: (
                record.split,
                record.target_id,
                record.campaign_id,
                record.binderranker_rank,
                record.candidate_id,
            ),
        )
    )

    return ValidatedBenchmarkBundle(
        manifest_path=resolved_manifest,
        dataset_path=dataset_path,
        manifest=manifest,
        records=canonical_records,
        summary=summary,
    )
