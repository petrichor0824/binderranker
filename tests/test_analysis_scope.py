import pytest

from protein_design_agent.tools.analysis_scope import (
    classify_analysis_scope,
)


@pytest.mark.parametrize(
    ("pdb_count", "expected_level"),
    [
        (1, "SMOKE_TEST_ONLY"),
        (5, "SMOKE_TEST_ONLY"),
        (29, "SMOKE_TEST_ONLY"),
        (30, "EXPLORATORY"),
        (199, "EXPLORATORY"),
        (200, "FULL_DATASET_ANALYSIS"),
    ],
)
def test_analysis_scope_boundaries(
    pdb_count: int,
    expected_level: str,
) -> None:
    result = classify_analysis_scope(pdb_count)

    assert result["pdb_count"] == pdb_count
    assert result["level"] == expected_level


def test_small_dataset_cannot_be_formally_interpreted() -> None:
    result = classify_analysis_scope(5)

    assert (
        result["workflow_allows_formal_interpretation"]
        is False
    )
    assert result["pool_labels_reliable"] is False
    assert result["result_use"] == (
        "engineering_validation_only"
    )


def test_full_dataset_still_contains_caveat() -> None:
    result = classify_analysis_scope(5000)

    assert (
        result["workflow_allows_formal_interpretation"]
        is True
    )
    assert "不自动证明" in result["message"]


def test_zero_pdb_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="必须大于 0",
    ):
        classify_analysis_scope(0)
