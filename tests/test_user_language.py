from protein_design_agent.agent.user_language import (
    format_user_progress,
    lifecycle_state_label,
    pending_action_label,
    plan_step_status_label,
    translate_internal_terms,
    user_scope,
    user_status,
)


def test_known_states_are_translated() -> None:
    assert user_status(
        "READY_FOR_REVIEW",
        area="prepare",
    ) == "计划已准备，等待审核"
    assert user_status(
        "APPROVED",
        area="stage",
    ) == "计划已批准，尚未执行"
    assert user_scope(
        "SMOKE_TEST_ONLY"
    ).startswith("工程冒烟测试")
    assert user_status(
        "MATERIALIZED",
        area="prepare",
    ) == "项目配置已生成"
    assert plan_step_status_label("READY") == (
        "可以开始"
    )


def test_unknown_internal_values_are_not_exposed() -> None:
    secret_status = "PRIVATE_FUTURE_STATUS"

    rendered = user_status(
        secret_status,
        area="execution",
    )

    assert secret_status not in rendered
    assert "内部审计记录" in rendered


def test_progress_uses_plain_language() -> None:
    rendered = "\n".join(
        format_user_progress(
            {
                "current_stage": "ANALYZED",
                "prepare_status": (
                    "READY_FOR_REVIEW"
                ),
                "approval_status": "APPROVED",
                "execution_status": "COMPLETED",
                "analysis_status": "COMPLETED",
                "explanation_status": "UNAVAILABLE",
            },
            include_explanation=True,
        )
    )

    assert "总体：确定性结果分析已完成" in rendered
    assert "模型解释：暂不可用" in rendered
    assert "READY_FOR_REVIEW" not in rendered
    assert "COMPLETED" not in rendered


def test_public_terms_and_action_labels_are_stable() -> None:
    translated = translate_internal_terms(
        "当前为 READY_FOR_REVIEW，等待 APPROVED。"
    )

    assert "READY_FOR_REVIEW" not in translated
    assert "APPROVED" not in translated
    assert pending_action_label("EXECUTE") == (
        "运行 BinderRanker"
    )
    assert lifecycle_state_label("INCOMPLETE") == (
        "尚未完成的任务"
    )
