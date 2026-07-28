import pytest

from protein_design_agent.agent.result_explainer import (
    ResultExplanationError,
    validate_generated_claim_boundaries,
)


def smoke_evidence() -> dict:
    return {
        "analysis_scope_level": (
            "SMOKE_TEST_ONLY"
        ),
        "threshold_analysis_mode": (
            "DISABLED_SMALL_SAMPLE"
        ),
    }


def test_rejects_claim_that_hidden_thresholds_are_unset() -> None:
    explanation = {
        "overall_summary": (
            "本批次未设置动态过滤门槛。"
        )
    }

    with pytest.raises(
        ResultExplanationError,
        match="未设置或未启用",
    ):
        validate_generated_claim_boundaries(
            explanation=explanation,
            evidence=smoke_evidence(),
        )


def test_allows_accurate_threshold_suppression_wording() -> None:
    explanation = {
        "overall_summary": (
            "小样本下动态阈值不展示、"
            "不解释，也不用于正式候选判断。"
        )
    }

    validate_generated_claim_boundaries(
        explanation=explanation,
        evidence=smoke_evidence(),
    )


def test_rejects_mandatory_region_score_claim() -> None:
    explanation = {
        "next_steps": [
            (
                "若进入正式筛选阶段，"
                "需启用区域分数。"
            )
        ]
    }

    with pytest.raises(
        ResultExplanationError,
        match="必须启用区域分数",
    ):
        validate_generated_claim_boundaries(
            explanation=explanation,
            evidence=smoke_evidence(),
        )


def test_allows_statement_that_region_score_is_optional() -> None:
    explanation = {
        "next_steps": [
            (
                "正式筛选并不要求启用区域分数；"
                "是否启用取决于任务设计。"
            )
        ]
    }

    validate_generated_claim_boundaries(
        explanation=explanation,
        evidence=smoke_evidence(),
    )


def test_rejects_correlation_claim_without_statistics() -> None:
    explanation = {
        "cross_candidate_patterns": [
            (
                "总分和 morphology_adaptive_score "
                "高度正相关。"
            )
        ]
    }

    with pytest.raises(
        ResultExplanationError,
        match="没有提供相关性统计",
    ):
        validate_generated_claim_boundaries(
            explanation=explanation,
            evidence=smoke_evidence(),
        )


def test_allows_descriptive_small_sample_observation() -> None:
    explanation = {
        "cross_candidate_patterns": [
            (
                "在本次 5 个候选中，"
                "总分较高的两个候选同时具有较高的 "
                "morphology_adaptive_score。"
            )
        ]
    }

    validate_generated_claim_boundaries(
        explanation=explanation,
        evidence=smoke_evidence(),
    )


def test_allows_correlation_when_evidence_contains_statistic() -> None:
    evidence = smoke_evidence()
    evidence["deterministic_statistics"] = {
        "spearman_correlation": 0.9,
    }

    explanation = {
        "cross_candidate_patterns": [
            (
                "确定性 Spearman 统计显示两者"
                "具有正相关关系。"
            )
        ]
    }

    validate_generated_claim_boundaries(
        explanation=explanation,
        evidence=evidence,
    )
