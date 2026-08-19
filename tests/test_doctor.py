from pathlib import Path
from types import SimpleNamespace

import protein_design_agent.agent.doctor as module
from protein_design_agent.agent.doctor import (
    DoctorCheck,
    DoctorReport,
    check_model_profile,
    check_ranker_integrity,
)


def test_report_status_priority(
    tmp_path: Path,
) -> None:
    report = DoctorReport(
        project_root=tmp_path,
        working_directory=tmp_path,
        checks=[
            DoctorCheck(
                name="one",
                status="PASS",
                message="ok",
            ),
            DoctorCheck(
                name="two",
                status="WARN",
                message="warning",
            ),
        ],
    )

    assert report.overall_status() == "WARN"
    assert report.exit_code() == 0

    failed = report.model_copy(
        update={
            "checks": [
                *report.checks,
                DoctorCheck(
                    name="three",
                    status="FAIL",
                    message="failed",
                ),
            ]
        }
    )

    assert failed.overall_status() == "FAIL"
    assert failed.exit_code() == 2


def test_ranker_integrity_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ranker = tmp_path / "ranker.py"
    ranker.write_text(
        "print('ok')\n",
        encoding="utf-8",
    )

    expected = module.sha256_file(
        ranker
    )

    monkeypatch.setattr(
        module,
        "resolve_ranker",
        lambda version: (
            ranker,
            expected,
        ),
    )

    result = check_ranker_integrity(
        version="test"
    )

    assert result.status == "PASS"
    assert expected in str(result.detail)


def test_ranker_integrity_rejects_hash_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ranker = tmp_path / "ranker.py"
    ranker.write_text(
        "changed\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "resolve_ranker",
        lambda version: (
            ranker,
            "0" * 64,
        ),
    )

    result = check_ranker_integrity(
        version="test"
    )

    assert result.status == "FAIL"
    assert "SHA256 不匹配" in result.message


def test_missing_required_api_key_is_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "model.yaml"
    config_path.write_text(
        "profiles: {}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "load_model_provider_config",
        lambda path: object(),
    )

    monkeypatch.setattr(
        module,
        "resolve_provider_profile",
        lambda config, profile_name=None: (
            "demo",
            SimpleNamespace(
                kind="openai_compatible",
                model="demo-model",
                base_url="https://example.invalid",
                require_api_key=True,
                api_key_env="DEMO_API_KEY",
            ),
        ),
    )

    checks = check_model_profile(
        config_path=config_path,
        profile_name=None,
        environment={},
    )

    assert checks[0].status == "PASS"
    assert checks[1].status == "WARN"
    assert (
        "DEMO_API_KEY"
        in str(checks[1].detail)
    )


def test_present_required_api_key_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "model.yaml"
    config_path.write_text(
        "profiles: {}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "load_model_provider_config",
        lambda path: object(),
    )

    monkeypatch.setattr(
        module,
        "resolve_provider_profile",
        lambda config, profile_name=None: (
            "demo",
            SimpleNamespace(
                kind="openai_compatible",
                model="demo-model",
                base_url="https://example.invalid",
                require_api_key=True,
                api_key_env="DEMO_API_KEY",
            ),
        ),
    )

    checks = check_model_profile(
        config_path=config_path,
        profile_name=None,
        environment={
            "DEMO_API_KEY": "secret",
        },
    )

    assert checks[1].status == "PASS"
    assert "secret" not in str(checks[1])

def test_doctor_report_uses_binderranker_identity(
    tmp_path: Path,
) -> None:
    report = DoctorReport(
        project_root=tmp_path,
        working_directory=tmp_path,
        checks=[],
    )

    rendered = module.render_doctor_report(report)

    assert "BinderRanker Doctor" in rendered
    assert "Protein Design Agent Doctor" not in rendered
