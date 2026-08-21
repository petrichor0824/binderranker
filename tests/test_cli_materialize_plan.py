from pathlib import Path

from typer.testing import CliRunner

import protein_design_agent.cli as cli_module
from protein_design_agent.agent.plan_materializer import (
    PlanMaterializationError,
)


runner = CliRunner()


def write_session(tmp_path: Path) -> Path:
    session = tmp_path / "session.json"
    session.write_text(
        "{}",
        encoding="utf-8",
    )
    return session


def test_materialize_plan_hides_raw_value_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = write_session(tmp_path)

    def failing_materialize(**kwargs):
        raise ValueError(
            "PRIVATE_MATERIALIZATION_DETAIL"
        )

    monkeypatch.setattr(
        cli_module,
        "materialize_planning_session",
        failing_materialize,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "materialize-plan",
            "--session",
            str(session),
            "--output-config",
            str(tmp_path / "project.yaml"),
        ],
    )

    assert result.exit_code == 2

    assert (
        "当前操作没有完成"
        in result.output
    )
    assert (
        "计划落地未完成"
        in result.output
    )
    assert (
        "不执行 BinderRanker"
        in result.output
    )

    assert (
        "PRIVATE_MATERIALIZATION_DETAIL"
        not in result.output
    )
    assert "ValueError" not in result.output


def test_materialize_plan_preserves_safe_business_fact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = write_session(tmp_path)

    def failing_materialize(**kwargs):
        raise PlanMaterializationError(
            "INTERNAL_MATERIALIZATION_STATE",
            public_message=(
                "只有 READY_FOR_REVIEW 计划"
                "可以落地为正式项目配置。"
            ),
        )

    monkeypatch.setattr(
        cli_module,
        "materialize_planning_session",
        failing_materialize,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "materialize-plan",
            "--session",
            str(session),
            "--output-config",
            str(tmp_path / "project.yaml"),
        ],
    )

    assert result.exit_code == 2

    assert (
        "只有准备完整并可供审核的计划"
        "才能落地为正式项目配置"
        in result.output
    )
    assert "READY_FOR_REVIEW" not in result.output

    assert (
        "INTERNAL_MATERIALIZATION_STATE"
        not in result.output
    )


def test_materialize_plan_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = write_session(tmp_path)

    def failing_materialize(**kwargs):
        raise OSError(
            "PRIVATE_MATERIALIZATION_IO_DETAIL"
        )

    monkeypatch.setattr(
        cli_module,
        "materialize_planning_session",
        failing_materialize,
    )

    result = runner.invoke(
        cli_module.app,
        [
            "materialize-plan",
            "--session",
            str(session),
            "--output-config",
            str(tmp_path / "project.yaml"),
        ],
    )

    assert result.exit_code == 2

    assert (
        "计划落地未完成"
        in result.output
    )
    assert (
        "不运行科学工作流"
        in result.output
    )

    assert (
        "PRIVATE_MATERIALIZATION_IO_DETAIL"
        not in result.output
    )
    assert "OSError" not in result.output
