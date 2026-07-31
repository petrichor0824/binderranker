from types import SimpleNamespace

from protein_design_agent.agent.chat_session import (
    format_component_strengths,
    format_execution_result_preview,
)


def make_candidate():
    return SimpleNamespace(
        pdb_name="candidate_001",
        engineering_rank=1,
        final_score_v4=0.812345,
        public_filter_level="MEDIUM",
        public_filter_status="REPORTABLE",
        filter_reasons_formally_interpretable=True,
        strict_reasons=[
            "contact_map_jump_fraction 超过阈值",
        ],
        medium_reasons=[],
        broad_reasons=[],
        component_scores={
            "score_line": 0.91,
            "score_safety": 0.82,
            "score_plane": 0.44,
        },
    )


def test_component_strengths_use_highest_scores() -> None:
    rendered = format_component_strengths(
        {
            "score_plane": 0.44,
            "score_safety": 0.82,
            "score_line": 0.91,
        }
    )

    assert rendered == (
        "线性界面适配 0.910、"
        "几何安全性 0.820"
    )


def test_execution_preview_includes_strength_and_drag() -> None:
    summary = SimpleNamespace(
        candidates_by_engineering_rank=[
            make_candidate()
        ],
        candidate_count=1,
        analysis_scope={
            "level": "EXPLORATORY",
        },
        formal_candidate_recommendation_allowed=False,
    )

    rendered = format_execution_result_preview(
        summary
    )

    assert "candidate_001" in rendered
    assert "总分 0.8123" in rendered
    assert "过滤 MEDIUM" in rendered

    assert (
        "主要优势（高分组件） "
        "线性界面适配 0.910、"
        "几何安全性 0.820"
    ) in rendered

    assert (
        "主要拖累 "
        "contact_map_jump_fraction 超过阈值"
    ) in rendered

    assert (
        "不允许把该排序作为正式候选推荐"
        in rendered
    )


def test_empty_component_scores_are_explicit() -> None:
    assert (
        format_component_strengths({})
        == "未提供"
    )
