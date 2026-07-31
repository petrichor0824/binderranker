from types import SimpleNamespace

from protein_design_agent.agent.chat_session import (
    format_pool_summary,
    format_result_provenance,
)


def candidate(
    name: str,
    rank: int,
    *,
    broad: bool,
    medium: bool,
    strict: bool,
):
    return SimpleNamespace(
        pdb_name=name,
        engineering_rank=rank,
        broad_pass=broad,
        medium_pass=medium,
        strict_pass=strict,
    )


def pool_summary(mode: str):
    return SimpleNamespace(
        pool_reporting=SimpleNamespace(
            policy=SimpleNamespace(
                reporting_mode=mode,
            ),
            public_pool_counts={
                "broad": 3,
                "medium": 2,
                "strict": 1,
            },
        ),
        candidates_by_engineering_rank=[
            candidate(
                "candidate_1",
                1,
                broad=True,
                medium=True,
                strict=True,
            ),
            candidate(
                "candidate_2",
                2,
                broad=True,
                medium=True,
                strict=False,
            ),
            candidate(
                "candidate_3",
                3,
                broad=True,
                medium=False,
                strict=False,
            ),
        ],
    )


def test_smoke_pool_members_are_hidden() -> None:
    rendered = format_pool_summary(
        pool_summary("SUPPRESSED")
    )

    assert "发布政策隐藏" in rendered
    assert "candidate_1" not in rendered
    assert "3 个" not in rendered


def test_exploratory_only_shows_counts() -> None:
    rendered = format_pool_summary(
        pool_summary("EXPLORATORY")
    )

    assert "宽松：3 个" in rendered
    assert "中等：2 个" in rendered
    assert "严格：1 个" in rendered
    assert "批内探索结果" in rendered
    assert "candidate_1" not in rendered


def test_standard_shows_ranked_members() -> None:
    rendered = format_pool_summary(
        pool_summary("STANDARD")
    )

    assert "candidate_1" in rendered
    assert "candidate_2" in rendered
    assert "candidate_3" in rendered


def test_result_provenance_uses_verified_hash() -> None:
    summary = SimpleNamespace(
        result_provenance=SimpleNamespace(
            execution_manifest=SimpleNamespace(
                sha256="a" * 64,
            ),
            verified_output_files={
                "metrics_csv": object(),
                "scored_csv": object(),
                "ranking_xlsx": object(),
                "report_txt": object(),
            },
        )
    )

    rendered = format_result_provenance(summary)

    assert "a" * 64 in rendered
    assert "已验证原始输出 4 个" in rendered
