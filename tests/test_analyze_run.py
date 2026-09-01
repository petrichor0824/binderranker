from pathlib import Path
import json
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

    def fake_report(
        *,
        result_summary_path,
        failure_analysis_path,
        output_path,
    ):
        assert result_summary_path.is_file()
        assert failure_analysis_path.is_file()
        output_path.write_text(
            "# Deterministic analysis\n",
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

    monkeypatch.setattr(
        module,
        "write_deterministic_analysis_report",
        fake_report,
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
    assert result.deterministic_report_path.is_file()
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


def test_model_failure_preserves_deterministic_analysis(
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

    def fail_explanation(**kwargs):
        raise RuntimeError(
            "model explanation unavailable"
        )

    monkeypatch.setattr(
        module,
        "run_explain_run",
        fail_explanation,
    )

    result = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/model_fallback"
        ),
        with_model=True,
        model_config_path=config,
        profile_name="fake",
        allow_network=True,
    )

    assert result.status == "COMPLETED"
    assert result.explanation_status == (
        "UNAVAILABLE"
    )
    assert result.explanation_error_type == (
        "RuntimeError"
    )
    assert (
        "model explanation unavailable"
        in result.explanation_error_message
    )

    assert result.result_summary_path.is_file()
    assert result.failure_analysis_path.is_file()
    assert result.deterministic_report_path.is_file()

    assert (
        result.explanation_evidence_path
        is None
    )
    assert (
        result.explanation_json_path
        is None
    )
    assert (
        result.explanation_markdown_path
        is None
    )

    manifest = result.manifest_path.read_text(
        encoding="utf-8"
    )

    assert '"status": "COMPLETED"' in manifest
    assert (
        '"explanation_status": "UNAVAILABLE"'
        in manifest
    )


def test_completed_analysis_manifest_is_sealed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import hashlib
    import json

    bundle = make_bundle(tmp_path)

    install_fake_deterministic_writers(
        monkeypatch
    )

    result = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/sealed"
        ),
        with_model=False,
    )

    manifest = json.loads(
        result.manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == "0.3"
    assert manifest["status"] == "COMPLETED"

    completed_at = manifest.get(
        "completed_at_utc"
    )
    assert isinstance(completed_at, str)
    assert completed_at

    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    assert (
        manifest["result_summary_sha256"]
        == sha256_file(
            result.result_summary_path
        )
    )

    assert (
        manifest["failure_analysis_sha256"]
        == sha256_file(
            result.failure_analysis_path
        )
    )

    assert (
        manifest["deterministic_report_sha256"]
        == sha256_file(
            result.deterministic_report_path
        )
    )

    execution = Path(
        manifest["execution_manifest_path"]
    ).resolve()

    assert execution.is_file()

    assert (
        manifest["execution_manifest_sha256"]
        == sha256_file(execution)
    )


def test_next_analysis_directory_starts_from_first_slot(
    tmp_path: Path,
) -> None:
    result = module.next_analysis_directory(
        bundle_dir=tmp_path,
        prefix="tool_deterministic",
    )

    assert result == (
        Path("analyses")
        / "tool_deterministic_0001"
    )

    assert not (
        tmp_path
        / result
    ).exists()


def test_next_analysis_directory_never_reuses_existing_attempt(
    tmp_path: Path,
) -> None:
    analyses = tmp_path / "analyses"
    analyses.mkdir()

    (
        analyses
        / "tool_deterministic_0001"
    ).mkdir()

    (
        analyses
        / "tool_deterministic_0002"
    ).mkdir()

    result = module.next_analysis_directory(
        bundle_dir=tmp_path,
        prefix="tool_deterministic",
    )

    assert result == (
        Path("analyses")
        / "tool_deterministic_0003"
    )


def test_analyze_run_does_not_eagerly_import_model_explainer() -> None:
    import ast

    source = Path(
        module.__file__
    ).read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    eager_model_imports = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            == "protein_design_agent.agent.explain_run"
        )
    ]

    assert eager_model_imports == []
