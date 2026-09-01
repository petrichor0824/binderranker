import json
from pathlib import Path

import pytest

from protein_design_agent.agent.analysis_artifacts import (
    AnalysisArtifactError,
    resolve_analysis_artifacts,
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


def make_analysis(
    bundle: Path,
    name: str,
    *,
    status: str = "COMPLETED",
    completed_at_utc: str | None = None,
) -> tuple[Path, Path, Path]:
    analysis = (
        bundle
        / "analyses"
        / name
    )
    analysis.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    payload = {
        "schema_version": "0.1",
        "status": status,
        "bundle_dir": str(bundle),
        "analysis_dir": str(analysis),
        "with_model": False,
        "result_summary_path": str(summary),
        "failure_analysis_path": str(failure),
    }

    if completed_at_utc is not None:
        payload["completed_at_utc"] = (
            completed_at_utc
        )

    write_json(
        manifest,
        payload,
    )

    return manifest, summary, failure


def test_explicit_paths_have_priority(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    summary = bundle / "explicit_summary.json"
    failure = bundle / "explicit_failure.json"

    summary.write_text(
        "{}",
        encoding="utf-8",
    )
    failure.write_text(
        "{}",
        encoding="utf-8",
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
        result_summary_path=summary,
        failure_analysis_path=failure,
    )

    assert artifacts.source == "EXPLICIT"
    assert artifacts.analysis_manifest_path is None
    assert artifacts.result_summary_path == (
        summary.resolve()
    )
    assert artifacts.failure_analysis_path == (
        failure.resolve()
    )


def test_explicit_paths_must_be_a_pair(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    summary = bundle / "summary.json"
    summary.write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(
        AnalysisArtifactError,
        match="必须同时提供",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
            result_summary_path=summary,
            failure_analysis_path=None,
        )


def test_latest_completed_analysis_is_selected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    old_manifest, _, _ = make_analysis(
        bundle,
        "old",
        completed_at_utc=(
            "2026-08-07T01:00:00Z"
        ),
    )

    new_manifest, new_summary, new_failure = (
        make_analysis(
            bundle,
            "new",
            completed_at_utc=(
                "2026-08-07T02:00:00Z"
            ),
        )
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
    )

    assert artifacts.source == "ANALYSIS_MANIFEST"
    assert artifacts.analysis_manifest_path == (
        new_manifest.resolve()
    )
    assert artifacts.analysis_manifest_path != (
        old_manifest.resolve()
    )
    assert artifacts.result_summary_path == (
        new_summary.resolve()
    )
    assert artifacts.failure_analysis_path == (
        new_failure.resolve()
    )


def test_unknown_completed_manifest_schema_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    manifest, _, _ = make_analysis(
        bundle,
        "future",
    )
    payload = json.loads(
        manifest.read_text(encoding="utf-8")
    )
    payload["schema_version"] = "0.4"
    write_json(manifest, payload)

    with pytest.raises(
        AnalysisArtifactError,
        match="不支持的 schema_version",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )


def test_current_manifest_requires_report_integrity_fields(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    manifest, _, _ = make_analysis(
        bundle,
        "partial_current",
    )
    payload = json.loads(
        manifest.read_text(encoding="utf-8")
    )
    payload["schema_version"] = "0.3"
    write_json(manifest, payload)

    with pytest.raises(
        AnalysisArtifactError,
        match="schema 0.3.*完整性字段",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )


def test_running_analysis_is_not_selected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    completed_manifest, summary, failure = (
        make_analysis(
            bundle,
            "completed",
            status="COMPLETED",
            completed_at_utc=(
                "2026-08-07T01:00:00Z"
            ),
        )
    )

    make_analysis(
        bundle,
        "running",
        status="RUNNING",
        completed_at_utc=(
            "2026-08-07T03:00:00Z"
        ),
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
    )

    assert artifacts.analysis_manifest_path == (
        completed_manifest.resolve()
    )
    assert artifacts.result_summary_path == (
        summary.resolve()
    )
    assert artifacts.failure_analysis_path == (
        failure.resolve()
    )


def test_manifest_missing_artifact_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, _summary, failure = make_analysis(
        bundle,
        "broken",
        completed_at_utc=(
            "2026-08-07T01:00:00Z"
        ),
    )

    failure.unlink()

    with pytest.raises(
        AnalysisArtifactError,
        match="不存在",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )

    assert manifest.is_file()


def test_manifest_cannot_reference_outside_bundle(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, _failure = make_analysis(
        bundle,
        "unsafe",
        completed_at_utc=(
            "2026-08-07T01:00:00Z"
        ),
    )

    outside = tmp_path / "outside.json"
    outside.write_text(
        "{}",
        encoding="utf-8",
    )

    payload = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )
    payload["failure_analysis_path"] = str(
        outside
    )

    write_json(
        manifest,
        payload,
    )

    with pytest.raises(
        AnalysisArtifactError,
        match="Bundle 外",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )

    assert summary.is_file()


def test_legacy_root_layout_remains_supported(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    summary = (
        bundle
        / "agent_result_summary.json"
    )
    failure = (
        bundle
        / "agent_failure_analysis_v2.json"
    )

    summary.write_text(
        "{}",
        encoding="utf-8",
    )
    failure.write_text(
        "{}",
        encoding="utf-8",
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
    )

    assert artifacts.source == "LEGACY_ROOT"
    assert artifacts.analysis_manifest_path is None
    assert artifacts.result_summary_path == (
        summary.resolve()
    )
    assert artifacts.failure_analysis_path == (
        failure.resolve()
    )


def sha256_for_test(
    path: Path,
) -> str:
    import hashlib

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def seal_test_analysis(
    *,
    bundle: Path,
    manifest: Path,
    summary: Path,
    failure: Path,
    deterministic_report: Path | None = None,
) -> Path:
    execution = (
        bundle / "execution_apr_test.json"
    )
    execution.write_text(
        '{"status":"COMPLETED"}',
        encoding="utf-8",
    )

    write_json(
        summary,
        {
            "status": "PARSED",
            "execution_manifest": str(
                execution
            ),
        },
    )

    payload = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )

    payload.update(
        {
            "completed_at_utc": (
                "2026-08-07T02:00:00+00:00"
            ),
            "result_summary_sha256": (
                sha256_for_test(summary)
            ),
            "failure_analysis_sha256": (
                sha256_for_test(failure)
            ),
            "execution_manifest_path": str(
                execution
            ),
            "execution_manifest_sha256": (
                sha256_for_test(execution)
            ),
        }
    )

    if deterministic_report is not None:
        payload.update(
            {
                "deterministic_report_path": str(
                    deterministic_report
                ),
                "deterministic_report_sha256": (
                    sha256_for_test(
                        deterministic_report
                    )
                ),
            }
        )

    write_json(
        manifest,
        payload,
    )

    return execution


def test_sealed_analysis_is_verified(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, failure = make_analysis(
        bundle,
        "sealed",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )

    seal_test_analysis(
        bundle=bundle,
        manifest=manifest,
        summary=summary,
        failure=failure,
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
    )

    assert artifacts.provenance_status == (
        "SEALED_VERIFIED"
    )


def test_sealed_analysis_rejects_tampered_summary(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, failure = make_analysis(
        bundle,
        "sealed",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )

    seal_test_analysis(
        bundle=bundle,
        manifest=manifest,
        summary=summary,
        failure=failure,
    )

    summary.write_text(
        '{"status":"TAMPERED"}',
        encoding="utf-8",
    )

    with pytest.raises(
        AnalysisArtifactError,
        match="SHA256 不匹配",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )


def test_sealed_deterministic_report_is_verified(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, failure = make_analysis(
        bundle,
        "sealed_report",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )
    report = (
        manifest.parent
        / "binderranker_deterministic_analysis.md"
    )
    report.write_text(
        "# Deterministic analysis\n",
        encoding="utf-8",
    )

    seal_test_analysis(
        bundle=bundle,
        manifest=manifest,
        summary=summary,
        failure=failure,
        deterministic_report=report,
    )

    artifacts = resolve_analysis_artifacts(
        bundle_dir=bundle,
    )

    assert artifacts.provenance_status == (
        "SEALED_VERIFIED"
    )
    assert artifacts.deterministic_report_path == (
        report.resolve()
    )


def test_sealed_analysis_rejects_tampered_report(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, failure = make_analysis(
        bundle,
        "tampered_report",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )
    report = manifest.parent / "report.md"
    report.write_text(
        "original\n",
        encoding="utf-8",
    )

    seal_test_analysis(
        bundle=bundle,
        manifest=manifest,
        summary=summary,
        failure=failure,
        deterministic_report=report,
    )
    report.write_text(
        "tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(
        AnalysisArtifactError,
        match="SHA256 不匹配",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )


def test_partial_provenance_seal_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, summary, _failure = make_analysis(
        bundle,
        "partial",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )

    payload = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )

    payload["result_summary_sha256"] = (
        sha256_for_test(summary)
    )

    write_json(
        manifest,
        payload,
    )

    with pytest.raises(
        AnalysisArtifactError,
        match="provenance seal 不完整",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )


def test_report_only_provenance_seal_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    manifest, _summary, _failure = make_analysis(
        bundle,
        "report_only",
        completed_at_utc=(
            "2026-08-07T02:00:00+00:00"
        ),
    )
    report = manifest.parent / "report.md"
    report.write_text(
        "report\n",
        encoding="utf-8",
    )
    payload = json.loads(
        manifest.read_text(encoding="utf-8")
    )
    payload.update(
        {
            "deterministic_report_path": str(report),
            "deterministic_report_sha256": (
                sha256_for_test(report)
            ),
        }
    )
    write_json(manifest, payload)

    with pytest.raises(
        AnalysisArtifactError,
        match="缺少基础 provenance seal",
    ):
        resolve_analysis_artifacts(
            bundle_dir=bundle,
        )
