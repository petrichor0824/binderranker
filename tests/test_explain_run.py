from pathlib import Path

import pytest

import protein_design_agent.agent.explain_run as module
from protein_design_agent.agent.explain_run import (
    ExplainRunError,
    run_explain_run,
)


class FakeStructuredProvider:
    @property
    def name(self) -> str:
        return "fake-structured"

    def generate_json(
        self,
        messages,
    ):
        return {}


def prepare_inputs(
    tmp_path: Path,
) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    (
        bundle
        / "agent_result_summary.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    (
        bundle
        / "agent_failure_analysis_v2.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    return bundle, config


def test_network_permission_is_required(
    tmp_path: Path,
) -> None:
    bundle, config = prepare_inputs(
        tmp_path
    )

    with pytest.raises(
        ExplainRunError,
        match="allow-network",
    ):
        run_explain_run(
            bundle_dir=bundle,
            model_config_path=config,
            profile_name=None,
            output_dir=Path(
                "explanations/test"
            ),
            allow_network=False,
        )


def test_required_result_files_are_checked(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    with pytest.raises(
        ExplainRunError,
        match="缺少必要输入",
    ):
        run_explain_run(
            bundle_dir=bundle,
            model_config_path=config,
            profile_name=None,
            output_dir=Path(
                "explanations/test"
            ),
            allow_network=True,
        )


def test_relative_output_is_inside_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle, config = prepare_inputs(
        tmp_path
    )

    provider = FakeStructuredProvider()

    monkeypatch.setattr(
        module,
        "load_model_provider_config",
        lambda path: object(),
    )

    monkeypatch.setattr(
        module,
        "build_request_parser_provider",
        lambda config, profile_name=None: (
            provider
        ),
    )

    captured = {}

    def fake_explain_ranker_results(
        *,
        provider,
        result_summary_path,
        failure_analysis_path,
        output_dir,
        confirm_model_call,
    ):
        captured["provider"] = provider
        captured["output_dir"] = output_dir
        captured["confirm"] = (
            confirm_model_call
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        for filename in (
            "agent_explanation_evidence.json",
            "agent_explanation.json",
            "agent_explanation.md",
        ):
            (
                output_dir
                / filename
            ).write_text(
                "{}",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        module,
        "explain_ranker_results",
        fake_explain_ranker_results,
    )

    result = run_explain_run(
        bundle_dir=bundle,
        model_config_path=config,
        profile_name="fake",
        output_dir=Path(
            "explanations/test"
        ),
        allow_network=True,
    )

    expected_output = (
        bundle
        / "explanations"
        / "test"
    ).resolve()

    assert result.status == "EXPLAINED"
    assert result.output_dir == expected_output
    assert captured["output_dir"] == (
        expected_output
    )
    assert captured["confirm"] is True
    assert (
        result.explanation_markdown_path
        .is_file()
    )


def test_existing_outputs_are_not_overwritten(
    tmp_path: Path,
) -> None:
    bundle, config = prepare_inputs(
        tmp_path
    )

    output = (
        bundle
        / "explanations"
        / "test"
    )

    output.mkdir(
        parents=True
    )

    (
        output
        / "agent_explanation.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        ExplainRunError,
        match="禁止覆盖",
    ):
        run_explain_run(
            bundle_dir=bundle,
            model_config_path=config,
            profile_name=None,
            output_dir=Path(
                "explanations/test"
            ),
            allow_network=True,
        )


def test_standalone_explain_discovers_completed_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    analysis = (
        bundle
        / "analyses"
        / "analysis_v1"
    )
    analysis.mkdir(parents=True)

    summary = (
        analysis
        / "agent_result_summary.json"
    )
    failure = (
        analysis
        / "agent_failure_analysis_v2.json"
    )
    manifest = (
        analysis
        / "analyze_run_manifest.json"
    )

    summary.write_text(
        '{"status":"PARSED"}',
        encoding="utf-8",
    )
    failure.write_text(
        '{"status":"ANALYZED"}',
        encoding="utf-8",
    )
    manifest.write_text(
        (
            "{\n"
            '  "schema_version": "0.1",\n'
            '  "status": "COMPLETED",\n'
            f'  "bundle_dir": "{bundle}",\n'
            f'  "analysis_dir": "{analysis}",\n'
            '  "with_model": false,\n'
            f'  "result_summary_path": "{summary}",\n'
            f'  "failure_analysis_path": "{failure}"\n'
            "}\n"
        ),
        encoding="utf-8",
    )

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    provider = FakeStructuredProvider()

    monkeypatch.setattr(
        module,
        "load_model_provider_config",
        lambda path: object(),
    )
    monkeypatch.setattr(
        module,
        "build_request_parser_provider",
        lambda config, profile_name=None: (
            provider
        ),
    )

    captured = {}

    def fake_explain_ranker_results(
        *,
        provider,
        result_summary_path,
        failure_analysis_path,
        output_dir,
        confirm_model_call,
    ):
        captured["summary"] = (
            result_summary_path
        )
        captured["failure"] = (
            failure_analysis_path
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        for filename in (
            "agent_explanation_evidence.json",
            "agent_explanation.json",
            "agent_explanation.md",
        ):
            (
                output_dir
                / filename
            ).write_text(
                "{}",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        module,
        "explain_ranker_results",
        fake_explain_ranker_results,
    )

    result = run_explain_run(
        bundle_dir=bundle,
        model_config_path=config,
        profile_name=None,
        output_dir=Path(
            "explanations/standalone"
        ),
        allow_network=True,
    )

    assert captured["summary"] == (
        summary.resolve()
    )
    assert captured["failure"] == (
        failure.resolve()
    )

    assert result.result_summary_path == (
        summary.resolve()
    )
    assert result.failure_analysis_path == (
        failure.resolve()
    )

    assert result.analysis_manifest_path == (
        manifest.resolve()
    )
    assert result.analysis_artifact_source == (
        "ANALYSIS_MANIFEST"
    )


def test_standalone_explain_rejects_tampered_sealed_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json

    import protein_design_agent.agent.analyze_run as analyze_module
    from protein_design_agent.agent.analyze_run import (
        run_analyze_run,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    config = tmp_path / "models.yaml"
    config.write_text(
        "profiles: {}",
        encoding="utf-8",
    )

    def fake_summary(
        *,
        bundle_dir,
        output_path,
    ):
        execution = (
            bundle_dir
            / "execution_apr_test.json"
        )
        execution.write_text(
            '{"status":"COMPLETED"}',
            encoding="utf-8",
        )

        output_path.write_text(
            json.dumps(
                {
                    "status": "PARSED",
                    "execution_manifest": str(
                        execution
                    ),
                }
            ),
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
        analyze_module,
        "write_ranker_result_summary",
        fake_summary,
    )
    monkeypatch.setattr(
        analyze_module,
        "write_failure_analysis",
        fake_failure,
    )

    analyzed = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/sealed"
        ),
        with_model=False,
    )

    analyzed.result_summary_path.write_text(
        '{"status":"TAMPERED"}',
        encoding="utf-8",
    )

    with pytest.raises(
        ExplainRunError,
        match="SHA256 不匹配",
    ):
        run_explain_run(
            bundle_dir=bundle,
            model_config_path=config,
            profile_name=None,
            output_dir=Path(
                "explanations/tampered"
            ),
            allow_network=True,
        )
