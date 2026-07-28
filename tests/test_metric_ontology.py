import pytest

from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
    ontology_for_run,
    select_metric_semantics,
)


EXPECTED_METRICS = {
    "final_score_v4",
    "morphology_adaptive_score",
    "score_line",
    "score_plane",
    "score_compact",
    "score_roughness",
    "score_microfit",
    "score_safety",
    "score_region",
    "score_hotspot",
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
}


def test_ontology_covers_explainer_metrics() -> None:
    assert EXPECTED_METRICS <= set(
        BASE_METRIC_ONTOLOGY
    )


def test_region_off_primary_weights() -> None:
    ontology = ontology_for_run(
        region_score_used=False
    )

    assert (
        ontology[
            "morphology_adaptive_score"
        ].direct_primary_weight
        == 0.85
    )
    assert (
        ontology["score_safety"]
        .direct_primary_weight
        == 0.10
    )
    assert (
        ontology["score_roughness"]
        .direct_primary_weight
        == 0.05
    )
    assert (
        ontology["score_region"].role
        == "diagnostic"
    )
    assert (
        ontology["score_region"]
        .direct_primary_weight
        is None
    )


def test_region_on_primary_weights() -> None:
    ontology = ontology_for_run(
        region_score_used=True
    )

    assert (
        ontology[
            "morphology_adaptive_score"
        ].direct_primary_weight
        == 0.78
    )
    assert (
        ontology["score_region"].role
        == "direct_primary_component"
    )
    assert (
        ontology["score_region"]
        .direct_primary_weight
        == 0.07
    )


def test_misleading_names_are_constrained() -> None:
    ontology = ontology_for_run(
        region_score_used=False
    )

    roughness = ontology[
        "score_roughness"
    ]

    assert "平滑" in roughness.definition
    assert any(
        "真实分子表面粗糙度" in text
        for text in (
            roughness
            .forbidden_interpretations
        )
    )

    microfit = ontology[
        "score_microfit"
    ]

    assert any(
        "二面角" in text
        for text in (
            microfit
            .forbidden_interpretations
        )
    )

    safety = ontology[
        "score_safety"
    ]

    assert any(
        "生物安全" in text
        for text in (
            safety
            .forbidden_interpretations
        )
    )


def test_unknown_metric_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="指标本体缺少",
    ):
        select_metric_semantics(
            metric_keys={
                "final_score_v4",
                "invented_metric",
            },
            region_score_used=False,
        )
