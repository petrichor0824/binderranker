import math

import pytest

from protein_design_agent.agent.score_decomposition import (
    ScoreDecompositionError,
    canonical_primary_score_formula,
    decompose_primary_score,
    primary_score_weights,
    validate_primary_score_formula,
)


def test_primary_score_weights_without_region() -> None:
    assert primary_score_weights(
        region_score_used=False
    ) == {
        "morphology_adaptive_score": 0.85,
        "score_safety": 0.10,
        "score_roughness": 0.05,
    }


def test_primary_score_weights_with_region() -> None:
    assert primary_score_weights(
        region_score_used=True
    ) == {
        "morphology_adaptive_score": 0.78,
        "score_safety": 0.10,
        "score_roughness": 0.05,
        "score_region": 0.07,
    }


def test_primary_score_formula_matches_ontology() -> None:
    formula = canonical_primary_score_formula(
        region_score_used=False
    )

    assert formula == (
        "0.85*morphology_adaptive_score + "
        "0.10*score_safety + "
        "0.05*score_roughness"
    )
    assert validate_primary_score_formula(
        formula,
        region_score_used=False,
    ) == primary_score_weights(
        region_score_used=False
    )


def test_inconsistent_report_formula_is_rejected() -> None:
    with pytest.raises(
        ScoreDecompositionError,
        match="主分公式与审计指标本体不一致",
    ):
        validate_primary_score_formula(
            (
                "0.80*morphology_adaptive_score + "
                "0.15*score_safety + "
                "0.05*score_roughness"
            ),
            region_score_used=False,
        )


def test_primary_score_is_decomposed() -> None:
    result = decompose_primary_score(
        component_scores={
            "morphology_adaptive_score": 0.8,
            "score_safety": 0.6,
            "score_roughness": 0.4,
        },
        recorded_final_score_v4=0.76,
        region_score_used=False,
    )

    assert result.contributions == {
        "morphology_adaptive_score": (
            pytest.approx(0.68)
        ),
        "score_safety": pytest.approx(0.06),
        "score_roughness": pytest.approx(0.02),
    }
    assert (
        result.reconstructed_final_score_v4
        == pytest.approx(0.76)
    )
    assert result.reconstruction_error == 0.0


@pytest.mark.parametrize(
    "invalid_value",
    [math.nan, math.inf, -math.inf],
)
def test_non_finite_component_is_rejected(
    invalid_value: float,
) -> None:
    with pytest.raises(
        ScoreDecompositionError,
        match="必须是有限数值",
    ):
        decompose_primary_score(
            component_scores={
                "morphology_adaptive_score": (
                    invalid_value
                ),
                "score_safety": 0.6,
                "score_roughness": 0.4,
            },
            recorded_final_score_v4=0.76,
            region_score_used=False,
        )


def test_missing_component_is_rejected() -> None:
    with pytest.raises(
        ScoreDecompositionError,
        match="主分组成指标缺失",
    ):
        decompose_primary_score(
            component_scores={
                "morphology_adaptive_score": 0.8,
                "score_safety": 0.6,
            },
            recorded_final_score_v4=0.76,
            region_score_used=False,
        )


def test_inconsistent_recorded_score_is_rejected() -> None:
    with pytest.raises(
        ScoreDecompositionError,
        match="主分重建与记录值不一致",
    ):
        decompose_primary_score(
            component_scores={
                "morphology_adaptive_score": 0.8,
                "score_safety": 0.6,
                "score_roughness": 0.4,
            },
            recorded_final_score_v4=0.75,
            region_score_used=False,
        )
