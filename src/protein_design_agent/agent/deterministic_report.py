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
from protein_design_agent.agent.scientific_interpretation import (
    build_scientific_interpretation_contract,
)
from protein_design_agent.agent.score_decomposition import (
    AdjacentCandidateScoreComparison,
    PrimaryScoreContributionDelta,
    ScoreDecompositionError,
    build_adjacent_primary_score_comparisons,
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

    interpretation_contract = (
        summary.scientific_interpretation_contract
    )
    interpretation_status = (
        summary.scientific_interpretation_status
    )

    if interpretation_status == "AVAILABLE":
        if (
            interpretation_contract is None
            or summary.score_decomposition_status
            != "AVAILABLE"
            or summary.region_score_used is None
            or summary.scientific_interpretation_reason
            is not None
        ):
            raise DeterministicReportError(
                "科学解释状态与运行证据不一致"
            )

        expected_contract = (
            build_scientific_interpretation_contract(
                region_score_used=(
                    summary.region_score_used
                ),
                pool_reporting_policy=(
                    summary.pool_reporting.policy
                ),
            )
        )

        if interpretation_contract != expected_contract:
            raise DeterministicReportError(
                "科学解释契约与共享本体或结果策略不一致"
            )

    elif interpretation_contract is not None:
        raise DeterministicReportError(
            "科学解释不可用时不得包含契约"
        )

    elif not summary.scientific_interpretation_reason:
        raise DeterministicReportError(
            "不可用的科学解释契约必须记录原因"
        )

    comparisons = (
        summary
        .adjacent_candidate_score_comparisons
    )
    comparison_status = (
        summary.candidate_comparison_status
    )

    if comparison_status == "AVAILABLE":
        if (
            summary.score_decomposition_status
            != "AVAILABLE"
            or summary.candidate_count < 2
            or len(comparisons)
            != summary.candidate_count - 1
            or summary.candidate_comparison_reason
            is not None
        ):
            raise DeterministicReportError(
                "候选比较状态与分数分解或候选数不一致"
            )

        try:
            expected_comparisons = (
                build_adjacent_primary_score_comparisons(
                    summary
                    .candidates_by_engineering_rank
                )
            )
        except ScoreDecompositionError as exc:
            raise DeterministicReportError(
                "候选比较证据无法通过共享算术验证"
            ) from exc

        if comparisons != expected_comparisons:
            raise DeterministicReportError(
                "候选比较证据与共享算术结果不一致"
            )

    elif comparisons:
        raise DeterministicReportError(
            "候选比较不可用时不得包含比较记录"
        )

    elif (
        comparison_status == "NOT_APPLICABLE"
        and (
            summary.candidate_count != 1
            or summary.score_decomposition_status
            != "AVAILABLE"
        )
    ):
        raise DeterministicReportError(
            "候选比较仅在单候选时可标记为不适用"
        )

    elif not summary.candidate_comparison_reason:
        raise DeterministicReportError(
            "不可用或不适用的候选比较必须记录原因"
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


def format_metric_direction(value: str) -> str:
    """Render one controlled metric direction."""
    return {
        "higher_better": "higher is better within this batch",
        "lower_better": "lower is better within this batch",
        "context_dependent": "context dependent",
    }[value]


def format_metric_role(value: str) -> str:
    """Render one controlled metric role."""
    return {
        "primary_score": "primary score",
        "direct_primary_component": (
            "direct primary component"
        ),
        "indirect_primary_component": (
            "indirect primary component"
        ),
        "diagnostic": "diagnostic",
        "raw_metric": "raw metric",
    }[value]


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


def format_signed_number(value: float) -> str:
    """Render a signed arithmetic difference."""
    return f"{float(value):+.6g}"


def format_contribution_delta(
    delta: PrimaryScoreContributionDelta,
) -> str:
    """Render one direct-primary contribution difference."""
    return (
        f"{delta.metric_key}="
        f"{format_signed_number(delta.delta)}"
    )


def format_largest_delta(
    delta: PrimaryScoreContributionDelta | None,
) -> str:
    """Render an optional leading arithmetic difference."""
    if delta is None:
        return "none"

    return format_contribution_delta(delta)


def format_comparison_pair(
    comparison: AdjacentCandidateScoreComparison,
) -> str:
    """Render the ordered candidate names and ranks for one comparison."""
    return (
        f"#{comparison.higher_rank} "
        f"{comparison.higher_ranked_candidate} → "
        f"#{comparison.lower_rank} "
        f"{comparison.lower_ranked_candidate}"
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
        "## Scientific interpretation contract",
        "",
    ]

    interpretation_contract = (
        summary.scientific_interpretation_contract
    )

    if interpretation_contract is None:
        reason = (
            summary.scientific_interpretation_reason
            or "No sealed scientific-interpretation contract was recorded."
        )
        lines.extend(
            [
                "- Contract status: `UNAVAILABLE`",
                f"- Reason: {markdown_cell(reason)}",
            ]
        )
    else:
        threshold_policy = markdown_cell(
            interpretation_contract
            .threshold_interpretation
        )
        lines.extend(
            [
                "- Ranking scope: "
                f"`{interpretation_contract.ranking_scope}`",
                "- Scores are empirical and batch-relative: `true`",
                "- Cross-batch score comparison allowed: `false`",
                "- Cross-target score comparison allowed: `false`",
                "- Dynamic thresholds are batch-relative: `true`",
                "- Threshold interpretation mode: "
                f"`{interpretation_contract.threshold_interpretation_mode}`",
                "- Threshold policy: "
                f"{threshold_policy}",
                "- Empirical weights are universal biophysical "
                "parameters: `false`",
                "",
                "Known limitations:",
                "",
            ]
        )

        for limitation in (
            interpretation_contract
            .known_limitations
        ):
            lines.append(f"- {limitation}")

        lines.extend(
            [
                "",
                "Prohibited conclusions:",
                "",
            ]
        )

        for claim in (
            interpretation_contract
            .prohibited_claims
        ):
            lines.append(f"- {claim}")

        lines.extend(
            [
                "",
                "Controlled metric direction and run-specific role:",
                "",
                "| Metric | Label | Direction | Role | Direct weight |",
                "|---|---|---|---|---:|",
            ]
        )

        for metric_key, semantics in (
            interpretation_contract
            .metric_semantics.items()
        ):
            direct_weight = (
                "—"
                if semantics.direct_primary_weight
                is None
                else format_number(
                    semantics
                    .direct_primary_weight
                )
            )
            direction = format_metric_direction(
                semantics.direction
            )
            role = format_metric_role(
                semantics.role
            )
            lines.append(
                "| "
                f"`{markdown_cell(metric_key)}` | "
                f"{markdown_cell(semantics.label_zh)} | "
                f"{markdown_cell(direction)} | "
                f"{markdown_cell(role)} | "
                f"{direct_weight} |"
            )

    lines.extend(
        [
            "",
            "## Primary-score evidence",
            "",
        ]
    )

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
            "## Adjacent rank differences",
            "",
            "Each row subtracts the lower-ranked candidate from the "
            "adjacent higher-ranked candidate. Positive contribution "
            "deltas support the recorded score difference; negative "
            "deltas are arithmetic offsets. They are not causal or "
            "biophysical explanations.",
            "",
        ]
    )

    if summary.candidate_comparison_status == "AVAILABLE":
        visible_comparisons = (
            summary
            .adjacent_candidate_score_comparisons[
                :max(len(candidates) - 1, 0)
            ]
        )

        if visible_comparisons:
            lines.extend(
                [
                    "| Adjacent pair | Recorded score delta | "
                    "Largest positive contribution delta | "
                    "Largest negative contribution delta | "
                    "All contribution deltas | Reconstruction error |",
                    "|---|---:|---|---|---|---:|",
                ]
            )

            for comparison in visible_comparisons:
                all_deltas = "; ".join(
                    format_contribution_delta(
                        item
                    )
                    for item in (
                        comparison
                        .contribution_deltas
                    )
                )
                positive_delta = format_largest_delta(
                    comparison
                    .largest_positive_contribution_delta
                )
                negative_delta = format_largest_delta(
                    comparison
                    .largest_negative_contribution_delta
                )
                lines.append(
                    "| "
                    f"{markdown_cell(format_comparison_pair(comparison))} | "
                    f"{format_number(comparison.recorded_score_delta)} | "
                    f"{markdown_cell(positive_delta)} | "
                    f"{markdown_cell(negative_delta)} | "
                    f"{markdown_cell(all_deltas)} | "
                    f"{format_number(comparison.reconstruction_error)} |"
                )
        else:
            lines.append(
                "The candidate display limit leaves no adjacent pair "
                "visible in this report."
            )

        hidden_comparisons = (
            len(
                summary
                .adjacent_candidate_score_comparisons
            )
            - len(visible_comparisons)
        )
        if hidden_comparisons > 0:
            lines.extend(
                [
                    "",
                    f"{hidden_comparisons} additional adjacent comparisons "
                    "remain available in the authoritative result-summary "
                    "JSON.",
                ]
            )
    else:
        reason = (
            summary.candidate_comparison_reason
            or "No validated candidate-comparison evidence was recorded."
        )
        lines.extend(
            [
                "- Comparison status: "
                f"`{summary.candidate_comparison_status}`",
                f"- Reason: {markdown_cell(reason)}",
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
        ]
    )

    if interpretation_contract is None:
        lines.append(
            "Use structural inspection, sequence design, complex-structure "
            "prediction, appropriate simulation or energetic analysis, and "
            "experimental validation before making biological claims."
        )
    else:
        for requirement in (
            interpretation_contract
            .required_downstream_validation
        ):
            lines.append(f"- {requirement}")

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
