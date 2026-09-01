#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Deterministic parsing of BinderRanker report context.

This module owns the shared, model-independent interpretation of run
configuration flags and score-formula descriptions written by the frozen
Ranker. It reads evidence only; it does not evaluate formulas or alter scores.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RankerReportContextError(RuntimeError):
    """The Ranker report context cannot be interpreted safely."""


class RankerReportContext(BaseModel):
    """Validated configuration and formula evidence from a Ranker report."""

    schema_version: str = "0.1"
    run_config: dict[str, str] = Field(
        default_factory=dict
    )
    score_formulas: dict[str, str] = Field(
        default_factory=dict
    )


REPORT_CONFIG_RE = re.compile(
    r"^\s*"
    r"(binder_chain|desired_regions|"
    r"undesired_regions|hotspot_regions|"
    r"hotspot_expand_radius|"
    r"region_score_mode|region_score_used|"
    r"region_filter)"
    r"\s*=\s*(.*?)\s*$"
)

REPORT_FORMULA_RE = re.compile(
    r"^\s*"
    r"(final_score_v4_original|"
    r"final_score_v4_region|"
    r"final_score_v4)"
    r"\s*=\s*(.*?)\s*$"
)


def parse_boolean_flag(
    value: Any,
    *,
    field_name: str,
) -> bool:
    """Strictly parse a boolean value recorded by the Ranker."""

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()

    if normalized in {
        "true",
        "1",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "false",
        "0",
        "no",
        "off",
    }:
        return False

    raise RankerReportContextError(
        f"无法解析布尔配置 {field_name}："
        f"{value!r}"
    )


def parse_ranker_report_context(
    report_path: Path,
    *,
    require_final_formula: bool = True,
) -> RankerReportContext:
    """Read run configuration and score formulas from ``report.txt``."""

    report_path = report_path.resolve()

    if not report_path.exists():
        raise RankerReportContextError(
            f"Ranker 报告不存在：{report_path}"
        )

    try:
        lines = report_path.read_text(
            encoding="utf-8",
            errors="strict",
        ).splitlines()
    except (OSError, UnicodeError) as exc:
        raise RankerReportContextError(
            f"Ranker 报告无法读取：{report_path}"
        ) from exc

    run_config: dict[str, str] = {}
    score_formulas: dict[str, str] = {}

    for line in lines:
        config_match = REPORT_CONFIG_RE.match(
            line
        )
        if config_match:
            run_config[config_match.group(1)] = (
                config_match.group(2)
            )
            continue

        formula_match = REPORT_FORMULA_RE.match(
            line
        )
        if formula_match:
            score_formulas[
                formula_match.group(1)
            ] = formula_match.group(2)

    if (
        require_final_formula
        and "final_score_v4" not in score_formulas
    ):
        raise RankerReportContextError(
            "无法从 Ranker 报告找到 "
            "final_score_v4 说明"
        )

    return RankerReportContext(
        run_config=run_config,
        score_formulas=score_formulas,
    )
