import csv
from pathlib import Path

import pytest

from protein_design_agent.agent.scientific_result_validation import (
    REQUIRED_FINITE_SCORE_COLUMNS,
    REQUIRED_SCORED_COLUMNS,
    ScientificResultValidationError,
    validate_scientific_result,
)


def candidate_row(
    *,
    name: str,
    rank: int,
    score: str,
    error: str = "",
) -> dict[str, str]:
    row = {
        column: ""
        for column in REQUIRED_SCORED_COLUMNS
    }
    row.update(
        {
            column: "0.5"
            for column in REQUIRED_FINITE_SCORE_COLUMNS
        }
    )
    row.update(
        {
            "pdb_name": name,
            "filter_level": "BROAD",
            "filter_broad_pass": "YES",
            "filter_medium_pass": "NO",
            "filter_strict_pass": "NO",
            "final_score_v4": score,
            "rank_final_score_v4": str(rank),
            "clash_pairs": "0",
            "error": error,
        }
    )
    return row


def write_outputs(
    tmp_path: Path,
    rows: list[dict[str, str]],
) -> list[Path]:
    prefix = tmp_path / "backbone_rank"
    metrics = Path(f"{prefix}_metrics.csv")
    scored = Path(f"{prefix}_scored.csv")
    ranking = Path(f"{prefix}_ranking.xlsx")
    report = Path(f"{prefix}_report.txt")

    with metrics.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["pdb_name"],
        )
        writer.writeheader()
        writer.writerows(
            {"pdb_name": row["pdb_name"]}
            for row in rows
        )

    with scored.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=sorted(
                REQUIRED_SCORED_COLUMNS
            ),
        )
        writer.writeheader()
        writer.writerows(rows)

    ranking.write_bytes(b"synthetic workbook")
    report.write_text(
        "synthetic report\n",
        encoding="utf-8",
    )

    return [metrics, scored, ranking, report]


def test_zero_valid_candidates_are_rejected(
    tmp_path: Path,
) -> None:
    outputs = write_outputs(
        tmp_path,
        [
            candidate_row(
                name="candidate_1",
                rank=1,
                score="0.9",
                error="No binder residues found",
            )
        ],
    )

    with pytest.raises(
        ScientificResultValidationError,
        match="没有有效候选",
    ):
        validate_scientific_result(outputs)


@pytest.mark.parametrize(
    "non_finite",
    ["NaN", "Inf", "-Inf"],
)
def test_non_finite_scores_are_rejected(
    tmp_path: Path,
    non_finite: str,
) -> None:
    row = candidate_row(
        name="candidate_1",
        rank=1,
        score="0.9",
    )
    row["score_safety"] = non_finite
    outputs = write_outputs(tmp_path, [row])

    with pytest.raises(
        ScientificResultValidationError,
        match="必须是有限数值",
    ):
        validate_scientific_result(outputs)


def test_malformed_ranking_is_rejected(
    tmp_path: Path,
) -> None:
    outputs = write_outputs(
        tmp_path,
        [
            candidate_row(
                name="candidate_1",
                rank=1,
                score="0.9",
            ),
            candidate_row(
                name="candidate_2",
                rank=3,
                score="0.8",
            ),
        ],
    )

    with pytest.raises(
        ScientificResultValidationError,
        match="连续且唯一",
    ):
        validate_scientific_result(outputs)


def test_rank_order_must_match_score_order(
    tmp_path: Path,
) -> None:
    outputs = write_outputs(
        tmp_path,
        [
            candidate_row(
                name="candidate_1",
                rank=1,
                score="0.8",
            ),
            candidate_row(
                name="candidate_2",
                rank=2,
                score="0.9",
            ),
        ],
    )

    with pytest.raises(
        ScientificResultValidationError,
        match="降序关系不一致",
    ):
        validate_scientific_result(outputs)


def test_valid_ranking_result_is_unchanged(
    tmp_path: Path,
) -> None:
    outputs = write_outputs(
        tmp_path,
        [
            candidate_row(
                name="candidate_1",
                rank=1,
                score="0.9",
            ),
            candidate_row(
                name="candidate_2",
                rank=2,
                score="0.8",
            ),
        ],
    )

    validation = validate_scientific_result(
        outputs,
        expected_candidate_count=2,
    )

    assert validation.scientifically_valid is True
    assert validation.candidate_count == 2
    assert validation.valid_candidate_count == 2
    assert validation.invalid_candidate_count == 0
