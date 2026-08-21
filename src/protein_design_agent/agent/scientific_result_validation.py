#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""BinderRanker 原始结果的共享科学语义验证。"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ScientificResultValidationError(RuntimeError):
    """进程可能已结束，但结果不能视为科学有效。"""


class ScientificResultValidation(BaseModel):
    """一次通过共享语义门禁的 BinderRanker 结果。"""

    schema_version: str = "0.1"
    scientifically_valid: Literal[True] = True
    candidate_count: int = Field(ge=1)
    valid_candidate_count: int = Field(ge=1)
    invalid_candidate_count: int = Field(ge=0)
    output_files: dict[str, Path]


REQUIRED_OUTPUT_KEYS = {
    "metrics_csv",
    "scored_csv",
    "ranking_xlsx",
    "report_txt",
}


COMPONENT_SCORE_COLUMNS = (
    "morphology_adaptive_score",
    "score_line",
    "score_plane",
    "score_compact",
    "score_roughness",
    "score_microfit",
    "score_safety",
    "score_region",
    "score_hotspot",
)


KEY_METRIC_COLUMNS = (
    "effective_weight_sum",
    "target_effective_coverage",
    "target_contact_span_norm",
    "backfacing_cb_far_weight_ratio",
    "cb_closer_weight_ratio",
    "binder_field_active_roughness",
    "contact_map_continuity_score",
    "contact_map_jump_fraction",
    "shell_sensitivity_12_vs_8",
    "clash_pairs",
)


REQUIRED_FINITE_SCORE_COLUMNS = (
    "final_score_v4",
    *COMPONENT_SCORE_COLUMNS,
    *KEY_METRIC_COLUMNS,
)


REQUIRED_SCORED_COLUMNS = {
    "pdb_name",
    "filter_level",
    "filter_broad_pass",
    "filter_broad_reasons",
    "filter_medium_pass",
    "filter_medium_reasons",
    "filter_strict_pass",
    "filter_strict_reasons",
    "rank_final_score_v4",
    "error",
    *REQUIRED_FINITE_SCORE_COLUMNS,
}


def _output_key(path: Path) -> str:
    name = path.name

    if name.endswith("_metrics.csv"):
        return "metrics_csv"
    if name.endswith("_scored.csv"):
        return "scored_csv"
    if name.endswith("_ranking.xlsx"):
        return "ranking_xlsx"
    if name.endswith("_report.txt"):
        return "report_txt"

    raise ScientificResultValidationError(
        f"无法识别 BinderRanker 输出文件：{path}"
    )


def identify_result_files(
    output_files: list[Path] | tuple[Path, ...],
) -> dict[str, Path]:
    """识别并验证四类必需输出文件。"""
    identified: dict[str, Path] = {}

    for raw_path in output_files:
        path = Path(raw_path).resolve()
        key = _output_key(path)

        if key in identified:
            raise ScientificResultValidationError(
                f"检测到重复的 BinderRanker 输出类型：{key}"
            )

        if not path.is_file():
            raise ScientificResultValidationError(
                f"BinderRanker 输出文件不存在：{path}"
            )

        if path.stat().st_size <= 0:
            raise ScientificResultValidationError(
                f"BinderRanker 输出文件为空：{path}"
            )

        identified[key] = path

    if set(identified) != REQUIRED_OUTPUT_KEYS:
        missing = sorted(
            REQUIRED_OUTPUT_KEYS - set(identified)
        )
        raise ScientificResultValidationError(
            "BinderRanker 必需输出类型不完整；"
            f"缺少：{missing}"
        )

    return identified


def _read_csv(
    path: Path,
    *,
    description: str,
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])

            if not headers:
                raise ScientificResultValidationError(
                    f"{description} 缺少表头"
                )

            if len(set(headers)) != len(headers):
                raise ScientificResultValidationError(
                    f"{description} 包含重复列名"
                )

            rows = list(reader)

    except (OSError, UnicodeError, csv.Error) as exc:
        raise ScientificResultValidationError(
            f"无法读取 {description}：{exc}"
        ) from exc

    if not rows:
        raise ScientificResultValidationError(
            f"{description} 没有候选数据"
        )

    if any(None in row for row in rows):
        raise ScientificResultValidationError(
            f"{description} 存在与表头不匹配的数据列"
        )

    return headers, rows


def _candidate_identifier(
    row: dict[str, str],
    *,
    row_number: int,
) -> str:
    identifier = str(
        row.get("pdb_name", "") or ""
    ).strip()

    invalid = (
        not identifier
        or identifier in {".", ".."}
        or "/" in identifier
        or "\\" in identifier
        or any(ord(char) < 32 for char in identifier)
    )

    if invalid:
        raise ScientificResultValidationError(
            "scored CSV 包含无效候选标识；"
            f"数据行={row_number}，值={identifier!r}"
        )

    return identifier


def _finite_number(
    row: dict[str, str],
    column: str,
    *,
    candidate: str,
) -> float:
    raw = row.get(column, "")

    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScientificResultValidationError(
            f"候选 {candidate} 的 {column} "
            f"不是有效数值：{raw!r}"
        ) from exc

    if not math.isfinite(value):
        raise ScientificResultValidationError(
            f"候选 {candidate} 的 {column} "
            f"必须是有限数值，实际为 {raw!r}"
        )

    return value


def _error_is_empty(value: str | None) -> bool:
    normalized = str(value or "").strip().casefold()
    return normalized in {"", "nan", "none", "null"}


def _validate_scored_rows(
    rows: list[dict[str, str]],
    *,
    expected_candidate_count: int | None,
) -> tuple[list[str], list[float]]:
    identifiers = [
        _candidate_identifier(
            row,
            row_number=index,
        )
        for index, row in enumerate(rows, start=2)
    ]

    if len(set(identifiers)) != len(identifiers):
        raise ScientificResultValidationError(
            "scored CSV 包含重复候选标识"
        )

    if (
        expected_candidate_count is not None
        and len(rows) != expected_candidate_count
    ):
        raise ScientificResultValidationError(
            "scored CSV 候选数量与预期不一致："
            f"实际={len(rows)}，预期={expected_candidate_count}"
        )

    valid_indices = [
        index
        for index, row in enumerate(rows)
        if _error_is_empty(row.get("error"))
    ]

    if not valid_indices:
        raise ScientificResultValidationError(
            "BinderRanker 进程已结束，但没有有效候选；"
            f"有效候选=0，总候选={len(rows)}"
        )

    if len(valid_indices) != len(rows):
        failures = [
            {
                "pdb_name": identifiers[index],
                "error": str(rows[index].get("error", "")).strip(),
            }
            for index in range(len(rows))
            if index not in valid_indices
        ]
        raise ScientificResultValidationError(
            "BinderRanker 结果包含候选级计算失败，"
            "不能将整次执行标为科学成功；"
            f"失败候选={failures[:10]}"
        )

    ranks: list[int] = []
    scores: list[float] = []

    for row, candidate in zip(rows, identifiers, strict=True):
        for column in (
            "filter_broad_pass",
            "filter_medium_pass",
            "filter_strict_pass",
        ):
            flag = str(row.get(column, "")).strip().upper()
            if flag not in {"YES", "NO"}:
                raise ScientificResultValidationError(
                    f"候选 {candidate} 的 {column} "
                    f"必须是 YES 或 NO，实际为 {flag!r}"
                )

        if not str(row.get("filter_level", "")).strip():
            raise ScientificResultValidationError(
                f"候选 {candidate} 缺少 filter_level"
            )

        score_values = {
            column: _finite_number(
                row,
                column,
                candidate=candidate,
            )
            for column in REQUIRED_FINITE_SCORE_COLUMNS
        }

        raw_rank = _finite_number(
            row,
            "rank_final_score_v4",
            candidate=candidate,
        )

        if not raw_rank.is_integer() or raw_rank < 1:
            raise ScientificResultValidationError(
                f"候选 {candidate} 的 rank_final_score_v4 "
                f"必须是正整数，实际为 {raw_rank!r}"
            )

        ranks.append(int(raw_rank))
        scores.append(score_values["final_score_v4"])

    expected_ranks = list(range(1, len(rows) + 1))
    if sorted(ranks) != expected_ranks:
        raise ScientificResultValidationError(
            "rank_final_score_v4 必须形成连续且唯一的 1..N 排名；"
            f"实际为 {sorted(ranks)}"
        )

    ranked_scores = [
        score
        for _rank, score in sorted(
            zip(ranks, scores, strict=True)
        )
    ]
    if any(
        earlier < later
        for earlier, later in zip(
            ranked_scores,
            ranked_scores[1:],
            strict=False,
        )
    ):
        raise ScientificResultValidationError(
            "rank_final_score_v4 与 final_score_v4 的降序关系不一致"
        )

    return identifiers, scores


def validate_scientific_result(
    output_files: list[Path] | tuple[Path, ...],
    *,
    expected_candidate_count: int | None = None,
) -> ScientificResultValidation:
    """验证一次运行是否可以被视为科学成功。"""
    files = identify_result_files(output_files)

    scored_headers, scored_rows = _read_csv(
        files["scored_csv"],
        description="scored CSV",
    )
    missing_columns = sorted(
        REQUIRED_SCORED_COLUMNS - set(scored_headers)
    )
    if missing_columns:
        raise ScientificResultValidationError(
            "scored CSV 缺少必需列："
            f"{missing_columns}"
        )

    identifiers, _scores = _validate_scored_rows(
        scored_rows,
        expected_candidate_count=expected_candidate_count,
    )

    metrics_headers, metrics_rows = _read_csv(
        files["metrics_csv"],
        description="metrics CSV",
    )
    if "pdb_name" not in metrics_headers:
        raise ScientificResultValidationError(
            "metrics CSV 缺少必需列：['pdb_name']"
        )

    metrics_identifiers = [
        _candidate_identifier(
            row,
            row_number=index,
        )
        for index, row in enumerate(metrics_rows, start=2)
    ]
    if metrics_identifiers != identifiers:
        raise ScientificResultValidationError(
            "metrics CSV 与 scored CSV 的候选标识或顺序不一致"
        )

    return ScientificResultValidation(
        candidate_count=len(scored_rows),
        valid_candidate_count=len(scored_rows),
        invalid_candidate_count=0,
        output_files=files,
    )
