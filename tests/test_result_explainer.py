from pathlib import Path
from typing import Any

import pytest

from protein_design_agent.agent.result_explainer import (
    ResultExplanationError,
    request_result_explanation,
    write_explanation_artifacts,
)


class FakeStructuredProvider:
    """测试用假模型，不联网、不产生费用。"""

    name = "fake-explainer"

    def __init__(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.payload = payload
        self.messages = None

    def generate_json(
        self,
        messages,
    ) -> dict[str, Any]:
        self.messages = messages
        return self.payload


def build_evidence() -> dict[str, Any]:
    """构造一份最小可信证据包。"""
    return {
        "evidence_schema_version": "0.1",
        "project_name": "demo",
        "analysis_scope_level": (
            "SMOKE_TEST_ONLY"
        ),
        "candidate_count": 1,
        (
            "formal_candidate_"
            "recommendation_allowed"
        ): False,
        "result_use": (
            "engineering_validation_only"
        ),
        "pool_reporting": {
            "reporting_mode": "SUPPRESSED",
            "public_pool_counts": {
                "broad": None,
                "medium": None,
                "strict": None,
            },
        },
        "report_context": {
            "run_config": {
                "region_score_mode": "off",
                "region_score_used": "False",
                "region_filter": "off",
            },
            "score_formulas": {
                "final_score_v4": (
                    "primary ranking score"
                ),
            },
        },
        "metric_roles": {
            "morphology_adaptive_score": (
                "primary_score_direct_component"
            ),
            "score_safety": (
                "primary_score_direct_component"
            ),
            "score_roughness": (
                "primary_score_direct_component"
            ),
            "score_region": (
                "diagnostic_or_conditional_component"
            ),
            "score_hotspot": (
                "diagnostic_component"
            ),
        },
        "candidates": [
            {
                "pdb_name": "candidate_1",
                "engineering_rank": 1,
                "final_score_v4": 0.6,
                "public_filter_level": None,
                "public_filter_status": (
                    "NOT_AVAILABLE_SMALL_SAMPLE"
                ),
                "component_scores": {
                    (
                        "morphology_"
                        "adaptive_score"
                    ): 0.7,
                    "score_safety": 0.5,
                    "score_roughness": 0.6,
                    "score_region": 0.9,
                    "score_hotspot": 0.8,
                },
                "key_metrics": {
                    (
                        "contact_map_"
                        "jump_fraction"
                    ): 0.1,
                    (
                        "contact_map_"
                        "continuity_score"
                    ): 0.45,
                },
                "failed_gate_count": 2,
                "unique_failed_metric_count": 1,
                "unique_failed_metrics": [
                    (
                        "contact_map_"
                        "jump_fraction"
                    )
                ],
                "closest_failed_gate": None,
                (
                    "largest_relative_"
                    "failed_gate"
                ): None,
            }
        ],
        "safety_contract": {
            "numbers_are_authoritative": True,
            (
                "candidate_order_is_"
                "authoritative"
            ): True,
            (
                "pool_policy_is_"
                "authoritative"
            ): True,
        },
        "_source_result_summary": (
            "/tmp/result.json"
        ),
        "_source_failure_analysis": (
            "/tmp/failure.json"
        ),
    }


def build_valid_payload() -> dict[str, Any]:
    """构造符合 Schema 的模型输出。"""
    return {
        "schema_version": "0.1",
        "project_name": "demo",
        "analysis_scope_level": (
            "SMOKE_TEST_ONLY"
        ),
        (
            "formal_candidate_"
            "recommendation_allowed"
        ): False,
        "overall_summary": (
            "当前结果只能用于工程观察，"
            "不能形成正式候选推荐。"
        ),
        "batch_limitations": [
            "候选数量过少，动态阈值不稳定。"
        ],
        "cross_candidate_patterns": [
            "当前只有一个候选，"
            "不能形成可靠的跨候选模式。"
        ],
        "candidates": [
            {
                "pdb_name": "candidate_1",
                "engineering_rank": 1,
                "headline": (
                    "整体形态较好，"
                    "局部接触连续性仍需检查"
                ),
                "interpretation": (
                    "该候选在整体形态适配方面"
                    "表现较好，但局部界面接触"
                    "仍需结合结构进行检查。"
                ),
                "score_filter_relationship": (
                    "综合分和动态过滤门槛描述"
                    "的是不同层面的特征，"
                    "高综合分不代表所有门槛"
                    "均能通过。"
                ),
                "strengths": [
                    {
                        "metric_key": (
                            "morphology_"
                            "adaptive_score"
                        ),
                        "explanation": (
                            "支持整体形态与目标表面"
                            "具有一定适配性。"
                        ),
                    }
                ],
                "limitations": [
                    {
                        "metric_key": (
                            "contact_map_"
                            "jump_fraction"
                        ),
                        "explanation": (
                            "提示界面接触可能存在"
                            "局部跳跃或不连续。"
                        ),
                    }
                ],
                "next_structural_checks": [
                    (
                        "在 PyMOL 中检查接触残基"
                        "是否形成连续界面。"
                    )
                ],
            }
        ],
        "next_dataset_requirements": [
            (
                "使用更大规模候选集合，"
                "重新评估动态分位数阈值。"
            )
        ],
    }


def test_valid_model_explanation() -> None:
    provider = FakeStructuredProvider(
        build_valid_payload()
    )

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.status == "EXPLAINED"
    assert record.provider_name == (
        "fake-explainer"
    )
    assert (
        record.explanation
        .candidates[0]
        .pdb_name
        == "candidate_1"
    )
    assert provider.messages is not None


def test_model_cannot_change_candidate() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "pdb_name"
    ] = "invented_candidate"

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="候选顺序或名称",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_model_cannot_use_unknown_metric() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "strengths"
    ][0]["metric_key"] = (
        "invented_metric"
    )

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="不存在的指标",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_model_call_requires_confirmation() -> None:
    provider = FakeStructuredProvider(
        build_valid_payload()
    )

    with pytest.raises(
        ValueError,
        match="显式设置",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=False,
        )


def test_artifacts_written_and_protected(
    tmp_path: Path,
) -> None:
    evidence = build_evidence()

    provider = FakeStructuredProvider(
        build_valid_payload()
    )

    record = request_result_explanation(
        provider=provider,
        evidence=evidence,
        confirm_model_call=True,
    )

    paths = write_explanation_artifacts(
        output_dir=tmp_path,
        evidence=evidence,
        record=record,
    )

    assert paths["evidence"].exists()
    assert paths["json"].exists()
    assert paths["markdown"].exists()

    markdown = paths[
        "markdown"
    ].read_text(
        encoding="utf-8"
    )

    assert "SMOKE_TEST_ONLY" in markdown
    assert "candidate_1" in markdown
    assert (
        "morphology_adaptive_score"
        in markdown
    )

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        write_explanation_artifacts(
            output_dir=tmp_path,
            evidence=evidence,
            record=record,
        )


def test_failed_metric_cannot_be_strength() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "strengths"
    ][0]["metric_key"] = (
        "contact_map_jump_fraction"
    )

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="错误地列为候选优势",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_model_cannot_describe_threshold_direction() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "interpretation"
    ] = "该指标高于阈值，需要检查。"

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="自行描述了阈值方向",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_forbidden_candidate_priority_is_rejected() -> None:
    payload = build_valid_payload()

    payload[
        "next_dataset_requirements"
    ] = [
        "建议优先验证该候选。"
    ]

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="候选优先级建议",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )



def test_integer_candidate_count_is_allowed() -> None:
    """普通整数描述不应导致整次解释失败。"""
    payload = build_valid_payload()

    payload["overall_summary"] = (
        "本次共有5个候选，"
        "结果仅用于工程观察。"
    )

    provider = FakeStructuredProvider(
        payload
    )

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.status == "EXPLAINED"


def test_precise_decimal_in_narrative_is_allowed() -> None:
    """
    自由文本复述小数不应使整个任务失败。

    精确数值仍以确定性证据和渲染器为准。
    """
    payload = build_valid_payload()

    payload["overall_summary"] = (
        "模型观察到某项记录值为0.614103，"
        "但该数值以确定性证据为准。"
    )

    provider = FakeStructuredProvider(
        payload
    )

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.status == "EXPLAINED"

def test_percentage_in_narrative_is_allowed() -> None:
    """
    百分比不再作为整次任务失败的条件。

    阈值方向越权仍由其他校验负责。
    """
    payload = build_valid_payload()

    payload["overall_summary"] = (
        "自由文本中出现14%的描述，"
        "不应造成结构化解释失败。"
    )

    provider = FakeStructuredProvider(
        payload
    )

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.status == "EXPLAINED"

def test_ontology_forbids_compact_fold_claim() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "limitations"
    ][0]["explanation"] = (
        "说明整个蛋白折叠松散并存在内部空腔。"
    )

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="指标本体明确禁止",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_ontology_forbids_ramachandran_claim() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "strengths"
    ][0]["explanation"] = (
        "说明Ramachandran构象合理。"
    )

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="指标本体明确禁止",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_diagnostic_metric_cannot_claim_primary_score() -> None:
    payload = build_valid_payload()

    payload["candidates"][0][
        "strengths"
    ][0] = {
        "metric_key": "score_region",
        "explanation": (
            "该指标直接拉高最终分。"
        ),
    }

    current_evidence = build_evidence()

    current_evidence["metric_semantics"] = {
        "score_region": {
            "role": "diagnostic",
        }
    }

    provider = FakeStructuredProvider(
        payload
    )

    with pytest.raises(
        ResultExplanationError,
        match="非主分指标",
    ):
        request_result_explanation(
            provider=provider,
            evidence=current_evidence,
            confirm_model_call=True,
        )
