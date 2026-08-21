import json
from pathlib import Path

from protein_design_agent.agent.chat_dialogue import (
    save_pending_action,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.session_recovery import (
    collect_task_recovery_snapshot,
    format_task_recovery_summary,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)


def write_json(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def make_prepared_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    request = UserRequest(
        raw_text=(
            "分析 data/candidates，"
            "binder 是 B 链。"
        ),
        project_name="demo",
        input_dir=Path("data/candidates"),
        input_layout="existing_chains",
        binder_chain="B",
    )
    plan = build_agent_plan(request)
    session = PlanningSession(
        provider_name="test-provider",
        request=request,
        plan=plan,
        request_explicit_fields=[
            "project_name",
            "input_dir",
            "input_layout",
            "binder_chain",
        ],
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    write_json(
        bundle / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )
    write_json(
        bundle
        / "workflow"
        / "workflow_manifest.json",
        {
            "analysis_scope": {
                "level": "EXPLORATORY",
                "pdb_count": 42,
            }
        },
    )

    return bundle


def make_incomplete_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "incomplete"
    bundle.mkdir()

    request = UserRequest(
        raw_text="分析 data/candidates。",
        project_name="incomplete-demo",
        input_dir=Path("data/candidates"),
    )
    plan = build_agent_plan(request)
    session = PlanningSession(
        provider_name="test-provider",
        request=request,
        plan=plan,
        request_explicit_fields=[
            "project_name",
            "input_dir",
        ],
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )
    write_json(
        bundle / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "project_name": "incomplete-demo",
        },
    )

    return bundle


def bundle_contents(
    bundle: Path,
) -> dict[str, bytes]:
    return {
        str(path.relative_to(bundle)): (
            path.read_bytes()
        )
        for path in bundle.rglob("*")
        if path.is_file()
    }


def test_prepared_task_recovers_confirmed_context(
    tmp_path: Path,
) -> None:
    bundle = make_prepared_bundle(tmp_path)

    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="READY",
    )

    assert "恢复上次任务" in rendered
    assert "项目：demo" in rendered
    assert "计划已准备，等待审查和批准" in rendered
    assert (
        f"PDB 目录 {Path('data/candidates')}"
        in rendered
    )
    assert "binder 链 B" in rendered
    assert "分析范围：EXPLORATORY" in rendered
    assert "已记录候选数：42" in rendered
    assert "查看计划" in rendered
    assert "未使用模型记忆" in rendered


def test_incomplete_task_recovers_missing_information(
    tmp_path: Path,
) -> None:
    bundle = make_incomplete_bundle(tmp_path)

    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="READY",
    )

    assert "规划尚未完成，正在等待补充信息" in rendered
    assert "仍需补充：PDB 链布局" in rendered
    assert "直接用自然语言补充" in rendered
    assert "不会自行猜测" in rendered


def test_smoke_scope_boundary_is_restored(
    tmp_path: Path,
) -> None:
    bundle = make_prepared_bundle(tmp_path)
    write_json(
        bundle
        / "workflow"
        / "workflow_manifest.json",
        {
            "analysis_scope": {
                "level": "SMOKE_TEST_ONLY",
                "pdb_count": 5,
            }
        },
    )

    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="READY",
    )

    assert "分析范围：SMOKE_TEST_ONLY" in rendered
    assert "已记录候选数：5" in rendered
    assert "不能作为正式候选推荐" in rendered


def test_pending_action_is_restored_without_execution(
    tmp_path: Path,
) -> None:
    bundle = make_prepared_bundle(tmp_path)
    save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="test approval",
    )

    before = bundle_contents(bundle)
    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="READY",
    )

    assert snapshot.pending_is_current is True
    assert "批准计划（仍有效）" in rendered
    assert "输入“确认”继续" in rendered
    assert "重启 Chat 本身没有执行该操作" in rendered
    assert bundle_contents(bundle) == before


def test_stale_pending_action_is_not_presented_as_valid(
    tmp_path: Path,
) -> None:
    bundle = make_prepared_bundle(tmp_path)
    save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="test approval",
    )

    write_json(
        bundle / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "changed",
        },
    )

    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="READY",
    )

    assert snapshot.pending_is_current is False
    assert "批准计划（已失效或无法验证）" in rendered
    assert "先输入“取消”" in rendered


def test_corrupt_planning_keeps_valid_run_status(
    tmp_path: Path,
) -> None:
    bundle = make_prepared_bundle(tmp_path)
    (
        bundle / "planning_session.json"
    ).write_text(
        "not-json",
        encoding="utf-8",
    )

    snapshot = collect_task_recovery_snapshot(
        bundle
    )
    rendered = format_task_recovery_summary(
        snapshot,
        model_status="OFFLINE",
    )

    assert snapshot.report is not None
    assert snapshot.planning_session is None
    assert "计划已准备，等待审查和批准" in rendered
    assert "规划上下文无法读取" in rendered
    assert "现有文件没有被自动修改" in rendered
