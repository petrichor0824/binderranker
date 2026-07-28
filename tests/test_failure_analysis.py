from pathlib import Path

import pytest

from protein_design_agent.agent.failure_analysis import (
    FailureAnalysisError,
    analyze_ranker_failures,
    write_failure_analysis,
)
from protein_design_agent.agent.ranker_result_parser import (
    CandidateResult,
    FilterThreshold,
    RankerResultSummary,
)
from protein_design_agent.agent.result_policy import (
    PoolReportingPolicy,
    PoolReportingView,
)


def build_summary(
    tmp_path: Path,
    *,
    jump_value: float = 0.108,
    broad_reason: str = (
        "high_contact_map_jump_fraction"
    ),
) -> Path:
    policy = PoolReportingPolicy(
        analysis_scope_level=(
            "SMOKE_TEST_ONLY"
        ),
        reporting_mode="SUPPRESSED",
        publish_pool_counts=False,
        pool_labels_reliable=False,
        formal_interpretation_allowed=False,
        formal_candidate_recommendation_allowed=False,
        raw_ranker_outputs_retained=True,
        message="test",
    )

    pool_view = PoolReportingView(
        policy=policy,
        raw_pool_counts={
            "broad": 0,
            "medium": 0,
            "strict": 0,
        },
        public_pool_counts={
            "broad": None,
            "medium": None,
            "strict": None,
        },
        public_pool_status={
            "broad": (
                "NOT_AVAILABLE_SMALL_SAMPLE"
            ),
            "medium": (
                "NOT_AVAILABLE_SMALL_SAMPLE"
            ),
            "strict": (
                "NOT_AVAILABLE_SMALL_SAMPLE"
            ),
        },
    )

    candidate = CandidateResult(
        pdb_name="candidate_1",
        engineering_rank=1,
        final_score_v4=0.6,
        raw_filter_level="FAIL",
        public_filter_level=None,
        public_filter_status=(
            "NOT_AVAILABLE_SMALL_SAMPLE"
        ),
        broad_pass=False,
        medium_pass=False,
        strict_pass=False,
        broad_reasons=[broad_reason],
        medium_reasons=[
            "low_target_effective_coverage"
        ],
        strict_reasons=[
            "low_score_safety"
        ],
        filter_reasons_formally_interpretable=False,
        component_scores={
            "score_safety": 0.44,
        },
        key_metrics={
            "contact_map_jump_fraction": (
                jump_value
            ),
            "target_effective_coverage": 0.4,
        },
        row_error=None,
    )

    summary = RankerResultSummary(
        project_name="failure_test",
        execution_manifest=(
            tmp_path
            / "execution_apr_test.json"
        ),
        analysis_scope={
            "level": "SMOKE_TEST_ONLY",
            "pdb_count": 1,
            (
                "workflow_allows_"
                "formal_interpretation"
            ): False,
            "pool_labels_reliable": False,
            "result_use": (
                "engineering_validation_only"
            ),
        },
        candidate_count=1,
        pool_reporting=pool_view,
        raw_filter_level_counts={
            "FAIL": 1,
        },
        raw_filter_thresholds={
            "broad": {
                (
                    "contact_map_"
                    "jump_fraction"
                ): FilterThreshold(
                    metric=(
                        "contact_map_"
                        "jump_fraction"
                    ),
                    direction="max",
                    value=0.105,
                    quantile=0.95,
                ),
            },
            "medium": {
                (
                    "target_effective_"
                    "coverage"
                ): FilterThreshold(
                    metric=(
                        "target_effective_"
                        "coverage"
                    ),
                    direction="min",
                    value=0.5,
                    quantile=0.4,
                ),
            },
            "strict": {
                "score_safety": (
                    FilterThreshold(
                        metric="score_safety",
                        direction="min",
                        value=0.55,
                        quantile=0.35,
                    )
                ),
            },
        },
        thresholds_formally_interpretable=False,
        candidates_by_engineering_rank=[
            candidate
        ],
        formal_candidate_recommendation_allowed=False,
        result_use=(
            "engineering_validation_only"
        ),
        source_files={
            "metrics_csv": tmp_path / "m.csv",
            "scored_csv": tmp_path / "s.csv",
            "ranking_xlsx": tmp_path / "r.xlsx",
            "report_txt": tmp_path / "r.txt",
        },
    )

    path = tmp_path / "agent_result_summary.json"

    path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return path


def test_failure_gaps_are_calculated(
    tmp_path: Path,
) -> None:
    path = build_summary(tmp_path)

    result = analyze_ranker_failures(
        path
    )

    candidate = (
        result
        .candidates_by_engineering_rank[0]
    )

    assert candidate.failed_gate_count == 3
    assert (
        candidate.unique_failed_metric_count
        == 3
    )

    broad = candidate.failures_by_pool[
        "broad"
    ][0]

    assert broad.metric == (
        "contact_map_jump_fraction"
    )
    assert broad.direction == "max"
    assert broad.actual_value == 0.108
    assert broad.threshold_value == 0.105
    assert broad.failure_gap == pytest.approx(
        0.003
    )
    assert (
        broad.relative_failure_gap
        == pytest.approx(
            0.003 / 0.105
        )
    )
    assert (
        broad.gap_band
        == "ABOVE_1_TO_5_PERCENT"
    )

    medium = candidate.failures_by_pool[
        "medium"
    ][0]

    assert medium.failure_gap == (
        pytest.approx(0.1)
    )
    assert (
        medium.gap_band
        == "ABOVE_15_PERCENT"
    )


def test_smoke_analysis_is_engineering_only(
    tmp_path: Path,
) -> None:
    path = build_summary(tmp_path)

    result = analyze_ranker_failures(
        path
    )

    assert (
        result.interpretation_status
        == "ENGINEERING_DIAGNOSTIC_ONLY"
    )
    assert (
        result
        .formal_candidate_recommendation_allowed
        is False
    )
    assert (
        result
        .thresholds_formally_interpretable
        is False
    )

    assert all(
        failure.interpretation_status
        == "ENGINEERING_DIAGNOSTIC_ONLY"
        for failures in (
            result
            .candidates_by_engineering_rank[0]
            .failures_by_pool
            .values()
        )
        for failure in failures
    )


def test_unknown_reason_is_rejected(
    tmp_path: Path,
) -> None:
    path = build_summary(
        tmp_path,
        broad_reason="unknown_rule",
    )

    with pytest.raises(
        FailureAnalysisError,
        match="无法从失败原因推导",
    ):
        analyze_ranker_failures(path)


def test_inconsistent_recorded_failure_is_rejected(
    tmp_path: Path,
) -> None:
    path = build_summary(
        tmp_path,
        jump_value=0.100,
    )

    with pytest.raises(
        FailureAnalysisError,
        match="数值与报告阈值不一致",
    ):
        analyze_ranker_failures(path)


def test_failure_analysis_file_is_protected(
    tmp_path: Path,
) -> None:
    path = build_summary(tmp_path)

    output = write_failure_analysis(
        result_summary_path=path
    )

    assert output.exists()

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        write_failure_analysis(
            result_summary_path=path
        )
