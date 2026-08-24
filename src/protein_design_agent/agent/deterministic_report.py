#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Human-readable, model-independent BinderRanker analysis report.

The report is a deterministic view over the validated result summary and
failure-gap analysis. It does not recompute metrics, thresholds, rankings, or
screening decisions.
"""

from __future__ import annotations

from pathlib import Path

from protein_design_agent.agent.failure_analysis import (
    CandidateFailureAnalysis,
    FailureAnalysisSummary,
    FailedGateGap,
    load_result_summary,
)
from protein_design_agent.agent.ranker_result_parser import (
    CandidateResult,
    RankerResultSummary,
)


REPORT_CANDIDATE_LIMIT = 20


class DeterministicReportError(RuntimeError):
    """The deterministic report cannot be produced safely."""


def load_failure_analysis(
    path: Path,
) -> FailureAnalysisSummary:
    """Read and validate a deterministic failure analysis."""
    path = path.resolve()

    if not path.is_file():
        raise DeterministicReportError(
            f"失败分析不存在：{path}"
        )

    try:
        return (
            FailureAnalysisSummary
            .model_validate_json(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )
    except Exception as exc:
        raise DeterministicReportError(
            f"无法验证失败分析：{path}"
        ) from exc


def validate_report_inputs(
    *,
    summary: RankerResultSummary,
    failure: FailureAnalysisSummary,
) -> None:
    """Require both deterministic artifacts to describe the same run."""
    if summary.project_name != failure.project_name:
        raise DeterministicReportError(
            "结果摘要和失败分析的项目名不一致"
        )

    if summary.candidate_count != failure.candidate_count:
        raise DeterministicReportError(
            "结果摘要和失败分析的候选数不一致"
        )

    if (
        len(summary.candidates_by_engineering_rank)
        != summary.candidate_count
        or len(failure.candidates_by_engineering_rank)
        != failure.candidate_count
    ):
        raise DeterministicReportError(
            "候选列表长度与声明的候选数不一致"
        )

    scope_level = str(
        summary.analysis_scope.get(
            "level",
            "",
        )
    )
    if scope_level != failure.analysis_scope_level:
        raise DeterministicReportError(
            "结果摘要和失败分析的分析级别不一致"
        )

    expected_interpretation = {
        "SMOKE_TEST_ONLY": (
            "ENGINEERING_DIAGNOSTIC_ONLY"
        ),
        "EXPLORATORY": "EXPLORATORY_ONLY",
        "FULL_DATASET_ANALYSIS": (
            "FORMAL_ANALYSIS_ALLOWED"
        ),
    }.get(scope_level)
    if (
        expected_interpretation is None
        or failure.interpretation_status
        != expected_interpretation
    ):
        raise DeterministicReportError(
            "失败分析的解释状态与分析级别不一致"
        )

    if (
        summary.formal_candidate_recommendation_allowed
        != failure.formal_candidate_recommendation_allowed
        or summary.thresholds_formally_interpretable
        != failure.thresholds_formally_interpretable
    ):
        raise DeterministicReportError(
            "结果摘要和失败分析的解释权限不一致"
        )

    summary_candidates = [
        (item.engineering_rank, item.pdb_name)
        for item in (
            summary
            .candidates_by_engineering_rank
        )
    ]
    failure_candidates = [
        (item.engineering_rank, item.pdb_name)
        for item in (
            failure
            .candidates_by_engineering_rank
        )
    ]
    if summary_candidates != failure_candidates:
        raise DeterministicReportError(
            "结果摘要和失败分析的候选顺序不一致"
        )

    if summary.score_decomposition_status == "AVAILABLE":
        if (
            not summary.primary_score_formula
            or not summary.primary_score_weights
            or any(
                not item.primary_score_contributions
                or item.reconstructed_final_score_v4
                is None
                or item.primary_score_reconstruction_error
                is None
                for item in (
                    summary
                    .candidates_by_engineering_rank
                )
            )
        ):
            raise DeterministicReportError(
                "结果摘要声明分数分解可用，"
                "但缺少完整的分解证据"
            )


def markdown_cell(value: object) -> str:
    """Escape one compact Markdown table cell."""
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def format_number(value: float) -> str:
    """Render deterministic evidence without false decimal precision."""
    return f"{float(value):.6g}"


def format_contributions(
    candidate: CandidateResult,
) -> str:
    """Render direct primary-score arithmetic contributions."""
    if not candidate.primary_score_contributions:
        return "不可用"

    return "; ".join(
        f"{metric}={format_number(value)}"
        for metric, value in (
            candidate
            .primary_score_contributions
            .items()
        )
    )


def format_failed_gate(
    gate: FailedGateGap | None,
) -> str:
    """Render one validated failed-gate fact."""
    if gate is None:
        return "无记录失败门槛"

    operator = (
        "<"
        if gate.direction == "min"
        else ">"
    )
    relative = (
        "仅绝对差距"
        if gate.relative_failure_gap is None
        else (
            f"相对差距 "
            f"{gate.relative_failure_gap:.2%}"
        )
    )
    return (
        f"{gate.metric} ({gate.pool}): "
        f"{format_number(gate.actual_value)} "
        f"{operator} "
        f"{format_number(gate.threshold_value)}, "
        f"差距 {format_number(gate.failure_gap)}, "
        f"{relative}, {gate.gap_band}"
    )


def candidate_filter_display(
    candidate: CandidateResult,
) -> str:
    """Respect the result-policy public filter view."""
    return (
        candidate.public_filter_level
        or candidate.public_filter_status
    )


def failure_by_name(
    failure: FailureAnalysisSummary,
) -> dict[str, CandidateFailureAnalysis]:
    """Index the already-validated candidate failure analyses."""
    return {
        item.pdb_name: item
        for item in (
            failure
            .candidates_by_engineering_rank
        )
    }


def build_deterministic_analysis_markdown(
    *,
    summary: RankerResultSummary,
    failure: FailureAnalysisSummary,
    candidate_limit: int = REPORT_CANDIDATE_LIMIT,
) -> str:
    """Build a deterministic, policy-aware Markdown analysis report."""
    if candidate_limit < 1:
        raise ValueError(
            "candidate_limit 必须至少为 1"
        )

    validate_report_inputs(
        summary=summary,
        failure=failure,
    )

    scope_level = failure.analysis_scope_level
    smoke_only = (
        failure.interpretation_status
        == "ENGINEERING_DIAGNOSTIC_ONLY"
    )
    candidates = (
        summary
        .candidates_by_engineering_rank[
            :candidate_limit
        ]
    )
    failures = failure_by_name(failure)

    lines = [
        "# BinderRanker Deterministic Analysis",
        "",
        "This report was generated without a language model.",
        "All scores, ranks, filters, and threshold gaps come from "
        "validated deterministic artifacts.",
        "",
        "## Analysis scope",
        "",
        f"- Project: `{markdown_cell(summary.project_name)}`",
        f"- Scope: `{scope_level}`",
        f"- Candidate count: `{summary.candidate_count}`",
        "- Interpretation status: "
        f"`{failure.interpretation_status}`",
        "- Formal candidate recommendation allowed: "
        f"`{str(summary.formal_candidate_recommendation_allowed).lower()}`",
        "",
        "BinderRanker provides batch-relative engineering ranking and "
        "layered screening. This report does not establish binding "
        "affinity, stability, solubility, or experimental success.",
        "",
        "## Primary-score evidence",
        "",
    ]

    if summary.score_decomposition_status == "AVAILABLE":
        lines.extend(
            [
                f"- Formula: `{summary.primary_score_formula}`",
                "- Weights: "
                + "; ".join(
                    f"`{key}={format_number(value)}`"
                    for key, value in (
                        summary
                        .primary_score_weights
                        .items()
                    )
                ),
                "- Candidate contribution values below are arithmetic "
                "terms in the recorded formula, not causal or energetic "
                "attributions.",
            ]
        )
    else:
        reason = (
            summary.score_decomposition_reason
            or "No validated decomposition evidence was recorded."
        )
        lines.extend(
            [
                "- Decomposition status: `UNAVAILABLE`",
                f"- Reason: {markdown_cell(reason)}",
            ]
        )

    lines.extend(
        [
            "",
            "## Candidate overview",
            "",
            "| Rank | Candidate | final_score_v4 | Public filter view | "
            "Primary-score contributions | Closest failed gate |",
            "|---:|---|---:|---|---|---|",
        ]
    )

    for candidate in candidates:
        failure_item = failures[
            candidate.pdb_name
        ]
        if smoke_only:
            gate_display = (
                "Suppressed: small-sample dynamic thresholds "
                "are not stable for interpretation"
            )
        else:
            gate_display = format_failed_gate(
                failure_item.closest_failed_gate
            )

        lines.append(
            "| "
            f"{candidate.engineering_rank} | "
            f"{markdown_cell(candidate.pdb_name)} | "
            f"{format_number(candidate.final_score_v4)} | "
            f"{markdown_cell(candidate_filter_display(candidate))} | "
            f"{markdown_cell(format_contributions(candidate))} | "
            f"{markdown_cell(gate_display)} |"
        )

    omitted = summary.candidate_count - len(
        candidates
    )
    if omitted > 0:
        lines.extend(
            [
                "",
                f"The table shows the first {len(candidates)} candidates; "
                f"{omitted} additional candidates remain available in the "
                "authoritative JSON artifacts.",
            ]
        )

    lines.extend(
        [
            "",
            "## Threshold-gap interpretation",
            "",
        ]
    )

    if smoke_only:
        lines.append(
            "Threshold values and gap details are intentionally suppressed "
            "for `SMOKE_TEST_ONLY`; the underlying JSON is retained for "
            "engineering audit, not scientific interpretation."
        )
    else:
        lines.extend(
            [
                "The closest failed gate is selected by relative distance "
                "to the batch-derived threshold. It identifies a numerical "
                "screening bottleneck, not a biological mechanism.",
                "",
                "Gap bands are transparent engineering labels:",
                "",
            ]
        )
        for key, definition in (
            failure.gap_band_definition.items()
        ):
            lines.append(
                f"- `{key}`: {definition}"
            )

    lines.extend(
        [
            "",
            "## Required downstream work",
            "",
            "Use structural inspection, sequence design, complex-structure "
            "prediction, appropriate simulation or energetic analysis, and "
            "experimental validation before making biological claims.",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def write_deterministic_analysis_report(
    *,
    result_summary_path: Path,
    failure_analysis_path: Path,
    output_path: Path,
) -> Path:
    """Write and verify a non-overwriting deterministic Markdown report."""
    result_summary_path = (
        result_summary_path.resolve()
    )
    failure_analysis_path = (
        failure_analysis_path.resolve()
    )
    output_path = output_path.resolve()

    if output_path.exists():
        raise ValueError(
            "确定性分析报告已经存在，禁止覆盖："
            f"{output_path}"
        )

    summary = load_result_summary(
        result_summary_path
    )
    failure = load_failure_analysis(
        failure_analysis_path
    )

    if (
        failure.source_result_summary.resolve()
        != result_summary_path
    ):
        raise DeterministicReportError(
            "失败分析引用的结果摘要与输入不一致"
        )

    content = build_deterministic_analysis_markdown(
        summary=summary,
        failure=failure,
    )
    output_path.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )

    if output_path.read_text(
        encoding="utf-8"
    ) != content:
        output_path.unlink(
            missing_ok=True
        )
        raise DeterministicReportError(
            "确定性分析报告写入前后不一致，"
            "已删除不可靠文件"
        )

    return output_path
