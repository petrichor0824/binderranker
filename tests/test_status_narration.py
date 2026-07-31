from types import SimpleNamespace

from protein_design_agent.agent.status_narration import (
    build_status_facts,
    deterministic_summary,
    format_status_narration,
    model_summary,
)


def analyzed_report():
    return SimpleNamespace(
        project_name="demo",
        current_stage="ANALYZED",
        prepare_status="READY_FOR_REVIEW",
        approval_status="APPROVED",
        execution_status="COMPLETED",
        analysis_status="COMPLETED",
        explanation_status="UNAVAILABLE",
        analysis_scope_level="EXPLORATORY",
        candidate_count=50,
        formal_candidate_recommendation_allowed=False,
        approval_consumed=True,
    )


class CorrectProvider:
    name = "test"

    def generate_json(self, messages):
        return {
            "current_stage": "ANALYZED",
            "execution_status": "COMPLETED",
            "analysis_status": "COMPLETED",
            "explanation_status": "UNAVAILABLE",
            "plain_language_summary": (
                "排名和确定性分析已经完成，"
                "只有模型解释暂时不可用。"
            ),
        }


class WrongProvider:
    name = "wrong"

    def generate_json(self, messages):
        return {
            "current_stage": "EXPLAINED",
            "execution_status": "COMPLETED",
            "analysis_status": "COMPLETED",
            "explanation_status": "EXPLAINED",
            "plain_language_summary": (
                "所有步骤都已完成。"
            ),
        }


def test_unavailable_keeps_valid_results() -> None:
    facts = build_status_facts(
        analyzed_report()
    )
    rendered = deterministic_summary(facts)

    assert "确定性分析都已完成" in rendered
    assert "仍然有效" in rendered
    assert "只有大模型解释步骤不可用" in rendered


def test_correct_model_can_rephrase_status() -> None:
    facts = build_status_facts(
        analyzed_report()
    )

    rendered = model_summary(
        provider=CorrectProvider(),
        facts=facts,
        fallback_summary="fallback",
        allow_model=True,
    )

    assert "只有模型解释暂时不可用" in rendered


def test_model_cannot_change_status() -> None:
    facts = build_status_facts(
        analyzed_report()
    )

    rendered = model_summary(
        provider=WrongProvider(),
        facts=facts,
        fallback_summary="安全兜底",
        allow_model=True,
    )

    assert rendered == "安全兜底"


def test_full_status_message_preserves_raw_facts(
    tmp_path,
    monkeypatch,
) -> None:
    import protein_design_agent.agent.status_narration as module

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: analyzed_report(),
    )

    rendered = format_status_narration(
        bundle_dir=tmp_path,
        provider=CorrectProvider(),
        allow_model=True,
    )

    assert "通俗说明：" in rendered
    assert "仍然有效的产物：" in rendered
    assert "不需要重跑 BinderRanker" in rendered
    assert "当前阶段：ANALYZED" in rendered
    assert (
        "COMPLETED / COMPLETED / UNAVAILABLE"
        in rendered
    )
