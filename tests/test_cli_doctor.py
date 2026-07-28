from pathlib import Path

from typer.testing import CliRunner

import protein_design_agent.agent.doctor as doctor
from protein_design_agent.agent.doctor import (
    DoctorCheck,
    DoctorReport,
)
from protein_design_agent.cli import app


runner = CliRunner()


def test_cli_doctor_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report = DoctorReport(
        project_root=tmp_path,
        working_directory=tmp_path,
        checks=[
            DoctorCheck(
                name="python",
                status="PASS",
                message="Python 正常",
            )
        ],
    )

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda **kwargs: report,
    )

    result = runner.invoke(
        app,
        [
            "doctor",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "[PASS] python" in result.stdout
    assert "总体状态：PASS" in result.stdout


def test_cli_doctor_failure_exit_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report = DoctorReport(
        project_root=tmp_path,
        working_directory=tmp_path,
        checks=[
            DoctorCheck(
                name="ranker",
                status="FAIL",
                message="哈希错误",
            )
        ],
    )

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda **kwargs: report,
    )

    result = runner.invoke(
        app,
        [
            "doctor",
            "--project-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2
    assert "[FAIL] ranker" in result.stdout
    assert "总体状态：FAIL" in result.stdout
