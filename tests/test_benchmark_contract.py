import csv
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml
from pydantic import ValidationError

from protein_design_agent.scientific_validation import (
    BenchmarkContractError,
    validate_benchmark_bundle,
)


RANKER_SHA256 = (
    "92d6c02f8ca8f500917f5fa61676fe93"
    "a0acdbb59d49f2cac0c7a74a4a553ed7"
)

FIELDNAMES = [
    "campaign_id",
    "target_id",
    "candidate_id",
    "split",
    "binderranker_rank",
    "binderranker_score",
    "baseline_rank",
    "outcome",
]


def valid_rows() -> list[dict[str, Any]]:
    return [
        {
            "campaign_id": "campaign_cal",
            "target_id": "target_cal",
            "candidate_id": "cal_1",
            "split": "CALIBRATION",
            "binderranker_rank": 1,
            "binderranker_score": 0.9,
            "baseline_rank": 2,
            "outcome": 1,
        },
        {
            "campaign_id": "campaign_cal",
            "target_id": "target_cal",
            "candidate_id": "cal_2",
            "split": "CALIBRATION",
            "binderranker_rank": 2,
            "binderranker_score": 0.7,
            "baseline_rank": 1,
            "outcome": 0,
        },
        {
            "campaign_id": "campaign_cal",
            "target_id": "target_cal",
            "candidate_id": "cal_3",
            "split": "CALIBRATION",
            "binderranker_rank": 3,
            "binderranker_score": 0.5,
            "baseline_rank": 3,
            "outcome": 0,
        },
        {
            "campaign_id": "campaign_eval",
            "target_id": "target_eval",
            "candidate_id": "eval_1",
            "split": "EVALUATION",
            "binderranker_rank": 1,
            "binderranker_score": 0.8,
            "baseline_rank": 3,
            "outcome": 0,
        },
        {
            "campaign_id": "campaign_eval",
            "target_id": "target_eval",
            "candidate_id": "eval_2",
            "split": "EVALUATION",
            "binderranker_rank": 2,
            "binderranker_score": 0.6,
            "baseline_rank": 1,
            "outcome": 1,
        },
        {
            "campaign_id": "campaign_eval",
            "target_id": "target_eval",
            "candidate_id": "eval_3",
            "split": "EVALUATION",
            "binderranker_rank": 3,
            "binderranker_score": 0.4,
            "baseline_rank": 2,
            "outcome": 0,
        },
    ]


def base_manifest(
    dataset_sha256: str,
    *,
    dataset_file: str = "candidates.csv",
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "benchmark_id": "retrospective_v1",
        "description": (
            "Synthetic retrospective contract fixture."
        ),
        "dataset": {
            "file": dataset_file,
            "sha256": dataset_sha256,
        },
        "outcome": {
            "name": "downstream_success",
            "description": (
                "Binary downstream validation outcome."
            ),
            "evidence_type": "EXPERIMENTAL",
            "source": "synthetic test fixture",
        },
        "baseline": {
            "method_id": "generation_order",
            "description": (
                "Candidate generation order."
            ),
            "ranking_procedure": (
                "Ascending recorded generation index."
            ),
        },
        "ranker": {
            "ranker_id": "BinderRanker",
            "version": "v0.1-expert",
            "resource_sha256": RANKER_SHA256,
        },
        "protocol": {
            "parameter_selection": (
                "CALIBRATION_ONLY"
            ),
            "ranking_blinded_to_outcomes": True,
            "baseline_blinded_to_outcomes": True,
            "target_split_unit": "TARGET",
        },
        "selection_budgets": [1, 2],
    }


ManifestMutation = Callable[
    [dict[str, Any]],
    None,
]


def write_bundle(
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
    mutate_manifest: ManifestMutation | None = None,
    dataset_file: str = "candidates.csv",
) -> tuple[Path, Path]:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    dataset_path = (
        bundle_dir
        / dataset_file
    )
    dataset_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with dataset_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDNAMES,
        )
        writer.writeheader()
        writer.writerows(
            rows
            if rows is not None
            else valid_rows()
        )

    dataset_sha256 = hashlib.sha256(
        dataset_path.read_bytes()
    ).hexdigest()
    manifest = base_manifest(
        dataset_sha256,
        dataset_file=dataset_file,
    )

    if mutate_manifest is not None:
        mutate_manifest(manifest)

    manifest_path = (
        bundle_dir
        / "benchmark.yaml"
    )
    manifest_path.write_text(
        yaml.safe_dump(
            manifest,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return manifest_path, dataset_path


def reseal_dataset(
    manifest_path: Path,
    dataset_path: Path,
) -> None:
    manifest = yaml.safe_load(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    manifest["dataset"]["sha256"] = (
        hashlib.sha256(
            dataset_path.read_bytes()
        ).hexdigest()
    )
    manifest_path.write_text(
        yaml.safe_dump(
            manifest,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_valid_benchmark_bundle_is_normalized(
    tmp_path: Path,
) -> None:
    rows = list(
        reversed(
            valid_rows()
        )
    )
    manifest_path, dataset_path = write_bundle(
        tmp_path,
        rows=rows,
    )

    bundle = validate_benchmark_bundle(
        manifest_path
    )

    assert bundle.dataset_path == dataset_path.resolve()
    assert bundle.summary.scientifically_valid is True
    assert bundle.summary.benchmark_id == (
        "retrospective_v1"
    )
    assert bundle.summary.campaign_count == 2
    assert bundle.summary.target_count == 2
    assert bundle.summary.candidate_count == 6
    assert bundle.summary.calibration_target_count == 1
    assert bundle.summary.evaluation_target_count == 1
    assert bundle.summary.evaluation_positive_count == 1
    assert bundle.summary.evaluation_negative_count == 2
    assert bundle.summary.selection_budgets == (1, 2)
    assert bundle.summary.manifest_sha256 == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert [
        record.candidate_id
        for record in bundle.records
    ] == [
        "cal_1",
        "cal_2",
        "cal_3",
        "eval_1",
        "eval_2",
        "eval_3",
    ]

    with pytest.raises(
        ValidationError,
        match="frozen_instance",
    ):
        bundle.records[0].outcome = 0


def test_dataset_sha256_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    manifest_path, dataset_path = write_bundle(
        tmp_path
    )
    dataset_path.write_text(
        dataset_path.read_text(
            encoding="utf-8"
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        BenchmarkContractError,
        match="SHA256",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_dataset_path_cannot_escape_bundle(
    tmp_path: Path,
) -> None:
    manifest_path, _dataset_path = write_bundle(
        tmp_path,
        dataset_file="../outside.csv",
    )

    with pytest.raises(
        BenchmarkContractError,
        match="不能逃逸",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


@pytest.mark.parametrize(
    "non_finite",
    ["NaN", "Inf", "-Inf"],
)
def test_non_finite_binderranker_score_is_rejected(
    tmp_path: Path,
    non_finite: str,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[3]["binderranker_score"] = non_finite
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="必须是有限数值",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_incomplete_rank_permutation_is_rejected(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[5]["binderranker_rank"] = 4
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="连续唯一排名",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_incomplete_baseline_rank_permutation_is_rejected(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[5]["baseline_rank"] = 4
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="baseline_rank.*连续唯一排名",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_score_order_must_match_binderranker_rank(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[4]["binderranker_score"] = 0.95
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="分数降序不一致",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_duplicate_campaign_candidate_is_rejected(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[1]["candidate_id"] = "cal_1"
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="重复 campaign/candidate",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_target_split_leakage_is_rejected(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    for row in rows[3:]:
        row["target_id"] = "target_cal"
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="同一 target",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_campaign_cannot_mix_targets(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[5]["target_id"] = "target_other"
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="只属于一个 target",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_outcome_must_be_binary(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    rows[4]["outcome"] = 2
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="outcome 必须是 0 或 1",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_evaluation_requires_both_outcome_classes(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    for row in rows[3:]:
        row["outcome"] = 1
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="至少需要一个负 outcome",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_evaluation_requires_positive_outcome(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()
    )
    for row in rows[3:]:
        row["outcome"] = 0
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="至少需要一个正 outcome",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_fixed_budget_must_fit_every_campaign(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest[
            "selection_budgets"
        ] = [1, 4]

    manifest_path, _ = write_bundle(
        tmp_path,
        mutate_manifest=mutate,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="候选数不足",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_budget_must_include_selective_comparison(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest[
            "selection_budgets"
        ] = [3]

    manifest_path, _ = write_bundle(
        tmp_path,
        mutate_manifest=mutate,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="小于所有 campaign 候选数",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_calibration_only_policy_requires_calibration_target(
    tmp_path: Path,
) -> None:
    rows = deepcopy(
        valid_rows()[3:]
    )
    manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="至少需要一个 CALIBRATION target",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_frozen_predefined_policy_allows_evaluation_only(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest["protocol"][
            "parameter_selection"
        ] = "FROZEN_PREDEFINED"

    manifest_path, _ = write_bundle(
        tmp_path,
        rows=deepcopy(
            valid_rows()[3:]
        ),
        mutate_manifest=mutate,
    )

    bundle = validate_benchmark_bundle(
        manifest_path
    )

    assert bundle.summary.calibration_target_count == 0
    assert bundle.summary.evaluation_target_count == 1


def test_outcome_blinding_must_be_explicit(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest["protocol"][
            "ranking_blinded_to_outcomes"
        ] = False

    manifest_path, _ = write_bundle(
        tmp_path,
        mutate_manifest=mutate,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="ranking_blinded_to_outcomes",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_unsorted_selection_budgets_are_rejected(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest[
            "selection_budgets"
        ] = [2, 1]

    manifest_path, _ = write_bundle(
        tmp_path,
        mutate_manifest=mutate,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="strictly increasing",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_missing_required_csv_column_is_rejected(
    tmp_path: Path,
) -> None:
    manifest_path, dataset_path = write_bundle(
        tmp_path
    )
    lines = dataset_path.read_text(
        encoding="utf-8"
    ).splitlines()
    lines[0] = lines[0].replace(
        ",outcome",
        "",
    )
    dataset_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    reseal_dataset(
        manifest_path,
        dataset_path,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="缺少必需列.*outcome",
    ):
        validate_benchmark_bundle(
            manifest_path
        )


def test_unknown_manifest_field_is_rejected(
    tmp_path: Path,
) -> None:
    def mutate(
        manifest: dict[str, Any],
    ) -> None:
        manifest["unreviewed_claim"] = True

    manifest_path, _ = write_bundle(
        tmp_path,
        mutate_manifest=mutate,
    )

    with pytest.raises(
        BenchmarkContractError,
        match="unreviewed_claim",
    ):
        validate_benchmark_bundle(
            manifest_path
        )
