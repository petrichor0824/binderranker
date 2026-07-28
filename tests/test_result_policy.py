import pytest

from protein_design_agent.agent.result_policy import (
    build_pool_reporting_view,
    derive_pool_reporting_policy,
)


def scope(
    level: str,
    *,
    reliable: bool,
    formal: bool,
) -> dict:
    return {
        "level": level,
        "pdb_count": 5,
        "pool_labels_reliable": reliable,
        (
            "workflow_allows_"
            "formal_interpretation"
        ): formal,
    }


def test_smoke_test_suppresses_public_pool_counts() -> None:
    analysis_scope = scope(
        "SMOKE_TEST_ONLY",
        reliable=False,
        formal=False,
    )

    view = build_pool_reporting_view(
        analysis_scope=analysis_scope,
        raw_pool_counts={
            "broad": 1,
            "medium": 1,
            "strict": 0,
        },
    )

    assert (
        view.policy.reporting_mode
        == "SUPPRESSED"
    )
    assert (
        view.policy.publish_pool_counts
        is False
    )
    assert (
        view.policy
        .formal_candidate_recommendation_allowed
        is False
    )

    # 原始值仍保留，便于复现和调试。
    assert view.raw_pool_counts == {
        "broad": 1,
        "medium": 1,
        "strict": 0,
    }

    # 用户报告不能展示这些数值。
    assert view.public_pool_counts == {
        "broad": None,
        "medium": None,
        "strict": None,
    }

    assert view.public_pool_status == {
        "broad": "NOT_AVAILABLE_SMALL_SAMPLE",
        "medium": "NOT_AVAILABLE_SMALL_SAMPLE",
        "strict": "NOT_AVAILABLE_SMALL_SAMPLE",
    }


def test_exploratory_counts_are_marked_unreliable() -> None:
    analysis_scope = scope(
        "EXPLORATORY",
        reliable=False,
        formal=False,
    )

    view = build_pool_reporting_view(
        analysis_scope=analysis_scope,
        raw_pool_counts={
            "broad": 12,
            "medium": 6,
            "strict": 2,
        },
    )

    assert (
        view.policy.reporting_mode
        == "EXPLORATORY"
    )
    assert (
        view.policy.publish_pool_counts
        is True
    )
    assert (
        view.policy.pool_labels_reliable
        is False
    )
    assert (
        view.policy
        .formal_candidate_recommendation_allowed
        is False
    )

    assert view.public_pool_counts == {
        "broad": 12,
        "medium": 6,
        "strict": 2,
    }

    assert set(
        view.public_pool_status.values()
    ) == {"EXPLORATORY_ONLY"}


def test_full_dataset_counts_are_reportable() -> None:
    analysis_scope = scope(
        "FULL_DATASET_ANALYSIS",
        reliable=True,
        formal=True,
    )

    view = build_pool_reporting_view(
        analysis_scope=analysis_scope,
        raw_pool_counts={
            "broad": 80,
            "medium": 35,
            "strict": 10,
        },
    )

    assert (
        view.policy.reporting_mode
        == "STANDARD"
    )
    assert (
        view.policy.publish_pool_counts
        is True
    )
    assert (
        view.policy.pool_labels_reliable
        is True
    )
    assert (
        view.policy
        .formal_candidate_recommendation_allowed
        is True
    )

    assert view.public_pool_counts == {
        "broad": 80,
        "medium": 35,
        "strict": 10,
    }

    assert set(
        view.public_pool_status.values()
    ) == {"REPORTABLE"}


def test_inconsistent_scope_is_rejected() -> None:
    analysis_scope = scope(
        "SMOKE_TEST_ONLY",
        reliable=True,
        formal=False,
    )

    with pytest.raises(
        ValueError,
        match="相矛盾",
    ):
        derive_pool_reporting_policy(
            analysis_scope
        )


def test_negative_pool_count_is_rejected() -> None:
    analysis_scope = scope(
        "FULL_DATASET_ANALYSIS",
        reliable=True,
        formal=True,
    )

    with pytest.raises(
        ValueError,
        match="大于等于 0",
    ):
        build_pool_reporting_view(
            analysis_scope=analysis_scope,
            raw_pool_counts={
                "broad": 10,
                "medium": -1,
                "strict": 2,
            },
        )
