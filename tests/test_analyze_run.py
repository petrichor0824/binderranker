from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.analyze_run as module
from protein_design_agent.agent.analyze_run import (
    AnalyzeRunError,
    run_analyze_run,
)


def make_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    return bundle


def install_fake_deterministic_writers(
    monkeypatch,
) -> None:
    def fake_summary(
        *,
        bundle_dir,
        output_path,
    ):
        output_path.write_text(
            '{"status":"PARSED"}',
            encoding="utf-8",
        )
        return output_path

    def fake_failure(
        *,
        result_summary_path,
        output_path,
    ):
        output_path.write_text(
            '{"status":"ANALYZED"}',
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        module,
        "write_ranker_result_summary",
        fake_summary,
    )

    monkeypatch.setattr(
        module,
        "write_failure_analysis",
        fake_failure,
    )


def test_deterministic_analysis_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = make_bundle(tmp_path)

    install_fake_deterministic_writers(
        monkeypatch
    )

    result = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/test"
        ),
        with_model=False,
    )

    assert result.status == "COMPLETED"
    assert result.with_model is False
    assert result.provider_name is None
    assert result.result_summary_path.is_file()
    assert result.failure_analysis_path.is_file()
    assert result.manifest_path.is_file()

    text = result.manifest_path.read_text(
        encoding="utf-8"
    )

    assert '"status": "COMPLETED"' in text


def test_model_requires_network(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    with pytest.raises(
        AnalyzeRunError,
        match="allow-network",
    ):
        run_analyze_run(
            bundle_dir=bundle,
            analysis_dir=Path(
                "analyses/test"
            ),
            with_model=True,
            model_config_path=config,
            allow_network=False,
        )


def test_model_uses_new_analysis_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = make_bundle(tmp_path)

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    install_fake_deterministic_writers(
        monkeypatch
    )

    captured = {}

    def fake_explain(**kwargs):
        captured.update(kwargs)

        output = kwargs["output_dir"]
        output.mkdir(
            parents=True,
            exist_ok=False,
        )

        evidence = (
            output
            / "agent_explanation_evidence.json"
        )
        explanation = (
            output
            / "agent_explanation.json"
        )
        markdown = (
            output
            / "agent_explanation.md"
        )

        for path in (
            evidence,
            explanation,
            markdown,
        ):
            path.write_text(
                "{}",
                encoding="utf-8",
            )

        return SimpleNamespace(
            provider_name="fake-model",
            evidence_path=evidence,
            explanation_json_path=(
                explanation
            ),
            explanation_markdown_path=(
                markdown
            ),
        )

    monkeypatch.setattr(
        module,
        "run_explain_run",
        fake_explain,
    )

    result = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/test"
        ),
        with_model=True,
        model_config_path=config,
        profile_name="fake",
        allow_network=True,
    )

    assert result.provider_name == "fake-model"

    assert (
        captured["result_summary_path"]
        == result.result_summary_path
    )

    assert (
        captured["failure_analysis_path"]
        == result.failure_analysis_path
    )

    assert (
        result.explanation_markdown_path
        .is_file()
    )


def test_existing_analysis_directory_rejected(
    tmp_path: Path,
) -> None:
    bundle = make_bundle(tmp_path)

    existing = (
        bundle
        / "analyses"
        / "test"
    )
    existing.mkdir(parents=True)

    with pytest.raises(
        AnalyzeRunError,
        match="禁止覆盖",
    ):
        run_analyze_run(
            bundle_dir=bundle,
            analysis_dir=Path(
                "analyses/test"
            ),
            with_model=False,
        )
