from protein_design_agent.agent.capability_truth import (
    CAPABILITY_TRUTH_PROMPT,
    DETERMINISTIC_CAPABILITY_ANSWER,
    find_capability_overclaim,
)


def test_current_capability_identity_is_binderranker() -> None:
    assert CAPABILITY_TRUTH_PROMPT.startswith(
        "BinderRanker 是针对当前 target 和候选批次的"
    )
    assert (
        "历史名称 Protein Design Agent"
        in CAPABILITY_TRUTH_PROMPT
    )

    assert "BinderRanker 不提供任意蛋白结构" in (
        DETERMINISTIC_CAPABILITY_ANSWER
    )
    assert "Protein Design Agent 不提供" not in (
        DETERMINISTIC_CAPABILITY_ANSWER
    )


def test_legacy_brand_overclaim_is_still_rejected() -> None:
    claim = (
        "Protein Design Agent 可以预测结合亲和力。"
    )

    assert find_capability_overclaim(claim) is not None
