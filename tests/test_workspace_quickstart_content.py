from pathlib import Path

from protein_design_agent.agent.workspace_init import (
    initialize_workspace,
)


def test_generated_quickstart_matches_public_workflow(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    initialize_workspace(workspace)

    content = (
        workspace / "QUICKSTART.md"
    ).read_text(encoding="utf-8")

    required = (
        "protein-design-agent doctor",
        "protein-design-agent extract-sample",
        "protein-design-agent chat",
        "data/3c98_small",
        "binder 是 B 链",
        "查看计划",
        "批准计划并确认小样本限制",
        "确认执行",
        "分析结果",
        "分析并解释结果",
        "状态",
        "不会自动开始执行",
        "不能作为正式候选推荐",
    )

    for value in required:
        assert value in content


def test_generated_quickstart_is_portable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    initialize_workspace(workspace)

    content = (
        workspace / "QUICKSTART.md"
    ).read_text(encoding="utf-8")

    forbidden = (
        "/home/petrichor/",
        "/root/",
        ".venv/bin/python",
        "dist/",
        "sample_data/real/3c98_small",
    )

    for value in forbidden:
        assert value not in content
