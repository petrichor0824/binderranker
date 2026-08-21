from pathlib import Path

from protein_design_agent.agent.onboarding import (
    format_first_chat_guidance,
    task_is_empty,
)


def test_empty_task_is_detected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"

    assert task_is_empty(bundle) is True

    bundle.mkdir()
    assert task_is_empty(bundle) is True

    (bundle / "planning_session.json").write_text(
        "{}",
        encoding="utf-8",
    )
    assert task_is_empty(bundle) is False


def test_created_workspace_explains_no_init_needed() -> None:
    rendered = format_first_chat_guidance(
        task_empty=True,
        model_status="READY",
        uses_default_workspace=True,
        workspace_status="CREATED",
    )

    assert rendered is not None
    assert "Chat 已自动初始化工作空间" in rendered
    assert "无需先运行" in rendered
    assert "binderranker init" in rendered
    assert "分析 data/my_candidates" in rendered
    assert "binderranker extract-sample" in rendered
    assert "不能作为正式候选推荐" in rendered


def test_empty_offline_task_points_to_model_setup() -> None:
    rendered = format_first_chat_guidance(
        task_empty=True,
        model_status="MISSING_CREDENTIAL",
        uses_default_workspace=True,
        workspace_status="REUSED",
    )

    assert rendered is not None
    assert "当前任务尚未开始" in rendered
    assert "不能可靠地把自由文本转换为计划" in rendered
    assert "按上方模型状态指引" in rendered


def test_started_task_does_not_show_first_run_guidance() -> None:
    assert format_first_chat_guidance(
        task_empty=False,
        model_status="READY",
        uses_default_workspace=True,
        workspace_status="REUSED",
    ) is None
