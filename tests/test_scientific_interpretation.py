import pytest

from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
)
from protein_design_agent.agent.result_policy import (
    derive_pool_reporting_policy,
)
from protein_design_agent.agent.scientific_interpretation import (
    ScientificInterpretationContract,
    build_scientific_interpretation_contract,
)


def analysis_scope(level: str) -> dict[str, object]:
    formal = level == "FULL_DATASET_ANALYSIS"
    return {
        "level": level,
        "pdb_count": 5000 if formal else 20,
        "pool_labels_reliable": formal,
        "workflow_allows_formal_interpretation": formal,
    }


@pytest.mark.parametrize(
    ("level", "expected_mode"),
    [
        ("SMOKE_TEST_ONLY", "SUPPRESSED"),
        ("EXPLORATORY", "EXPLORATORY"),
        ("FULL_DATASET_ANALYSIS", "STANDARD"),
    ],
)
def test_contract_tracks_result_policy(
    level: str,
    expected_mode: str,
) -> None:
    policy = derive_pool_reporting_policy(
        analysis_scope(level)
    )

    contract = (
        build_scientific_interpretation_contract(
            region_score_used=False,
            pool_reporting_policy=policy,
        )
    )

    assert contract.analysis_scope_level == level
    assert (
        contract.threshold_interpretation_mode
        == expected_mode
    )
    assert set(contract.metric_semantics) == set(
        BASE_METRIC_ONTOLOGY
    )
    assert contract.scores_are_batch_relative is True
    assert (
        contract.cross_batch_score_comparison_allowed
        is False
    )
    assert (
        contract.cross_target_score_comparison_allowed
        is False
    )
    assert (
        contract.dynamic_thresholds_are_batch_relative
        is True
    )


def test_contract_tracks_region_specific_metric_roles() -> None:
    policy = derive_pool_reporting_policy(
        analysis_scope("EXPLORATORY")
    )

    region_off = (
        build_scientific_interpretation_contract(
            region_score_used=False,
            pool_reporting_policy=policy,
        )
    )
    region_on = (
        build_scientific_interpretation_contract(
            region_score_used=True,
            pool_reporting_policy=policy,
        )
    )

    assert (
        region_off.metric_semantics[
            "score_region"
        ].role
        == "diagnostic"
    )
    assert (
        region_on.metric_semantics[
            "score_region"
        ].role
        == "direct_primary_component"
    )
    assert (
        region_on.metric_semantics[
            "score_region"
        ].direct_primary_weight
        == 0.07
    )


def test_contract_rejects_incomplete_metric_ontology() -> None:
    policy = derive_pool_reporting_policy(
        analysis_scope("EXPLORATORY")
    )
    contract = (
        build_scientific_interpretation_contract(
            region_score_used=False,
            pool_reporting_policy=policy,
        )
    )
    payload = contract.model_dump(
        mode="json"
    )
    payload["metric_semantics"].pop(
        "final_score_v4"
    )

    with pytest.raises(
        ValueError,
        match="完整受控指标本体",
    ):
        ScientificInterpretationContract.model_validate(
            payload
        )


def test_contract_rejects_scope_mode_mismatch() -> None:
    policy = derive_pool_reporting_policy(
        analysis_scope("EXPLORATORY")
    )
    contract = (
        build_scientific_interpretation_contract(
            region_score_used=False,
            pool_reporting_policy=policy,
        )
    )
    payload = contract.model_dump(
        mode="json"
    )
    payload["threshold_interpretation_mode"] = (
        "STANDARD"
    )

    with pytest.raises(
        ValueError,
        match="分析级别与阈值模式不一致",
    ):
        ScientificInterpretationContract.model_validate(
            payload
        )


def test_contract_rejects_modified_scientific_boundaries() -> None:
    policy = derive_pool_reporting_policy(
        analysis_scope("EXPLORATORY")
    )
    contract = (
        build_scientific_interpretation_contract(
            region_score_used=False,
            pool_reporting_policy=policy,
        )
    )
    payload = contract.model_dump(
        mode="json"
    )
    payload["prohibited_claims"] = []

    with pytest.raises(
        ValueError,
        match="固定能力边界被修改",
    ):
        ScientificInterpretationContract.model_validate(
            payload
        )
