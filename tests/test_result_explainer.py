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


class SequencedStructuredProvider:
    """按顺序返回多次模型结果。"""

    name = "sequenced-explainer"

    def __init__(
        self,
        payloads: list[dict[str, Any]],
    ) -> None:
        self.payloads = list(payloads)
        self.messages_history = []

    def generate_json(self, messages):
        self.messages_history.append(messages)

        if not self.payloads:
            raise AssertionError(
                "模型调用次数超出测试预期"
            )

        return self.payloads.pop(0)


def test_invalid_explanation_is_repaired_once() -> None:
    invalid_payload = build_valid_payload()
    invalid_payload[
        "cross_candidate_patterns"
    ] = [
        (
            "总分和 morphology_adaptive_score "
            "高度正相关。"
        )
    ]

    repaired_payload = build_valid_payload()

    provider = SequencedStructuredProvider(
        [
            invalid_payload,
            repaired_payload,
        ]
    )

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.status == "EXPLAINED"
    assert len(provider.messages_history) == 2

    repair_messages = (
        provider.messages_history[1]
    )

    assert (
        "没有通过确定性证据校验"
        in repair_messages[-1]["content"]
    )
    assert (
        "不得添加证据中不存在的相关性"
        in repair_messages[-1]["content"]
    )
    assert (
        "真实科学能力边界"
        in repair_messages[-1]["content"]
    )
    assert (
        "候选骨架排序与分层筛选"
        in repair_messages[-1]["content"]
    )
    assert (
        "不能替代"
        in repair_messages[-1]["content"]
    )


@pytest.mark.parametrize(
    "claim",
    [
        (
            "candidate_1 的 final_score_v4 更高，"
            "说明结合亲和力更高。"
        ),
        (
            "candidate_1 的工程排名靠前，"
            "说明结构稳定性更高。"
        ),
        (
            "candidate_1 的结果表明溶解性更好。"
        ),
        (
            "candidate_1 更可能获得实验成功。"
        ),
        (
            "BinderRanker 已经保证 candidate_1 "
            "是优质 binder。"
        ),
        (
            "Protein Design Agent 可以任意拼接"
            "或编辑蛋白结构。"
        ),
        (
            "BinderRanker 可以替代 AlphaFold、"
            "分子模拟和实验验证。"
        ),
    ],
)
def test_capability_overclaims_are_rejected(
    claim: str,
) -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = claim

    provider = FakeStructuredProvider(payload)

    with pytest.raises(
        ResultExplanationError,
        match="科学能力边界",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_explicit_capability_limitations_are_allowed() -> None:
    payload = build_valid_payload()
    statement = (
        "BinderRanker 的排名不能用于判断结合亲和力、"
        "稳定性、溶解性或实验成功概率，"
        "也不能替代 AlphaFold、分子模拟或实验验证。"
    )
    payload["overall_summary"] = statement

    provider = FakeStructuredProvider(payload)

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert (
        record.explanation.overall_summary
        == statement
    )


@pytest.mark.parametrize(
    "claim",
    [
        "BinderRanker 可以预测结合亲和力。",
        "BinderRanker 能够预测蛋白稳定性。",
        "BinderRanker 可用于预测蛋白溶解性。",
        "BinderRanker 可以预测 binding affinity。",
        "candidate_1 的实验成功概率更高。",
        "这些结果证明 candidate_1 一定会结合靶点。",
    ],
)
def test_capability_prediction_overclaims_are_rejected(
    claim: str,
) -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = claim

    provider = FakeStructuredProvider(payload)

    with pytest.raises(
        ResultExplanationError,
        match="科学能力边界",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


@pytest.mark.parametrize(
    "statement",
    [
        "BinderRanker 不能预测结合亲和力。",
        "当前证据无法判断实验成功概率。",
    ],
)
def test_capability_negated_predictions_are_allowed(
    statement: str,
) -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = statement

    provider = FakeStructuredProvider(payload)

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert (
        record.explanation.overall_summary
        == statement
    )


@pytest.mark.parametrize(
    "claim",
    [
        "BinderRanker 预测结合亲和力。",
        "BinderRanker 能预测蛋白稳定性。",
        "BinderRanker 可预测蛋白溶解性。",
        "BinderRanker 用于预测 binding affinity。",
    ],
)
def test_capability_prediction_wording_variants_are_rejected(
    claim: str,
) -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = claim

    provider = FakeStructuredProvider(payload)

    with pytest.raises(
        ResultExplanationError,
        match="科学能力边界",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


@pytest.mark.parametrize(
    "statement",
    [
        "这些结果不能证明 candidate_1 一定会结合靶点。",
        "无法判断实验成功概率是否更高。",
        (
            "虽然 BinderRanker 不能预测结合亲和力，"
            "但可以用于当前候选批次内的工程排序。"
        ),
    ],
)
def test_capability_boundary_safe_wording_is_allowed(
    statement: str,
) -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = statement

    provider = FakeStructuredProvider(payload)

    record = request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert record.explanation.overall_summary == statement


def test_mixed_safe_and_overclaim_sentence_is_rejected() -> None:
    payload = build_valid_payload()
    payload["overall_summary"] = (
        "虽然不能预测结合亲和力，"
        "但 candidate_1 的实验成功概率更高。"
    )

    provider = FakeStructuredProvider(payload)

    with pytest.raises(
        ResultExplanationError,
        match="科学能力边界",
    ):
        request_result_explanation(
            provider=provider,
            evidence=build_evidence(),
            confirm_model_call=True,
        )


def test_result_explainer_prompt_contains_capability_truth() -> None:
    payload = build_valid_payload()
    provider = FakeStructuredProvider(payload)

    request_result_explanation(
        provider=provider,
        evidence=build_evidence(),
        confirm_model_call=True,
    )

    assert provider.messages is not None

    system_message = provider.messages[0]["content"]

    assert "候选骨架排序与分层筛选" in system_message
    assert "结合亲和力预测器" in system_message
    assert "实验成功概率预测器" in system_message
    assert "不能替代" in system_message
