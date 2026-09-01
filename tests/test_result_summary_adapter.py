import asyncio
import json
from pathlib import Path

from mcp import Client

from protein_design_agent.adapters.mcp_server import create_mcp_server
from protein_design_agent.adapters.read_only import (
    ReadOnlyToolAdapter,
    ResultSummaryAdapterResult,
    TaskListAdapterResult,
)
from protein_design_agent.agent.analysis_artifacts import sha256_file
from protein_design_agent.agent.ranker_result_parser import (
    CandidateResult,
    RankerResultSummary,
)
from protein_design_agent.agent.result_policy import (
    PoolReportingPolicy,
    PoolReportingView,
)
from protein_design_agent.agent.tool_adapter_errors import AdapterErrorEnvelope
from protein_design_agent.agent.tool_api import get_result_summary
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    bundle = workspace / "runs" / "task_a"
    bundle.mkdir(parents=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace, bundle


def build_summary(bundle: Path, execution: Path) -> RankerResultSummary:
    policy = PoolReportingPolicy(
        analysis_scope_level="EXPLORATORY",
        reporting_mode="EXPLORATORY",
        publish_pool_counts=True,
        pool_labels_reliable=False,
        formal_interpretation_allowed=False,
        formal_candidate_recommendation_allowed=False,
        message="deterministic policy text must not be projected",
    )
    pool_reporting = PoolReportingView(
        policy=policy,
        raw_pool_counts={"broad": 1, "medium": 0, "strict": 0},
        public_pool_counts={"broad": 1, "medium": 0, "strict": 0},
        public_pool_status={
            "broad": "EXPLORATORY_ONLY",
            "medium": "EXPLORATORY_ONLY",
            "strict": "EXPLORATORY_ONLY",
        },
    )
    candidates = [
        CandidateResult(
            pdb_name="candidate 1.pdb",
            engineering_rank=1,
            final_score_v4=0.8,
            raw_filter_level="broad",
            public_filter_level="broad",
            public_filter_status="EXPLORATORY_ONLY",
            broad_pass=True,
            medium_pass=False,
            strict_pass=False,
            broad_reasons=[],
            medium_reasons=["low_score_safety"],
            strict_reasons=["low_score_safety"],
            filter_reasons_formally_interpretable=False,
            component_scores={"score_safety": 0.7},
            key_metrics={"clash_pairs": 0.0},
            primary_score_contributions={"score_safety": 0.21},
        ),
        CandidateResult(
            pdb_name="candidate_2.pdb",
            engineering_rank=2,
            final_score_v4=0.7,
            raw_filter_level="FAIL",
            public_filter_level="FAIL",
            public_filter_status="EXPLORATORY_ONLY",
            broad_pass=False,
            medium_pass=False,
            strict_pass=False,
            broad_reasons=["low_score_safety"],
            medium_reasons=["low_score_safety"],
            strict_reasons=["low_score_safety"],
            filter_reasons_formally_interpretable=False,
            component_scores={"score_safety": 0.6},
            key_metrics={"clash_pairs": 1.0},
            primary_score_contributions={"score_safety": 0.18},
        ),
    ]
    return RankerResultSummary(
        project_name=f"private project at {bundle}",
        execution_manifest=execution,
        analysis_scope={
            "level": "EXPLORATORY",
            "pdb_count": 2,
            "workflow_allows_formal_interpretation": False,
            "pool_labels_reliable": False,
            "result_use": "exploratory_batch_comparison",
        },
        candidate_count=2,
        pool_reporting=pool_reporting,
        raw_filter_level_counts={"broad": 1, "FAIL": 1},
        raw_filter_thresholds={"broad": {}, "medium": {}, "strict": {}},
        thresholds_formally_interpretable=False,
        score_decomposition_status="UNAVAILABLE",
        score_decomposition_reason="fixture does not assert decomposition",
        scientific_interpretation_status="UNAVAILABLE",
        scientific_interpretation_reason=(
            "fixture does not assert scientific interpretation"
        ),
        candidate_comparison_status="UNAVAILABLE",
        candidate_comparison_reason="fixture does not assert comparisons",
        candidates_by_engineering_rank=candidates,
        formal_candidate_recommendation_allowed=False,
        result_use="exploratory_batch_comparison",
        source_files={
            "metrics_csv": bundle / "private" / "metrics.csv",
            "scored_csv": bundle / "private" / "scored.csv",
        },
    )


def write_sealed_analysis(bundle: Path) -> tuple[Path, Path]:
    analysis = bundle / "analyses" / "sealed"
    analysis.mkdir(parents=True)
    execution = bundle / "execution_apr_test.json"
    execution.write_text('{"status":"COMPLETED"}', encoding="utf-8")

    summary_path = analysis / "agent_result_summary.json"
    summary_path.write_text(
        build_summary(bundle, execution).model_dump_json(indent=2),
        encoding="utf-8",
    )
    failure_path = analysis / "agent_failure_analysis_v2.json"
    failure_path.write_text('{"status":"ANALYZED"}', encoding="utf-8")
    report_path = analysis / "deterministic_analysis.md"
    report_path.write_text("# Deterministic analysis\n", encoding="utf-8")

    manifest_path = analysis / "analyze_run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.3",
                "status": "COMPLETED",
                "completed_at_utc": "2026-08-31T00:00:00+00:00",
                "result_summary_path": str(summary_path),
                "result_summary_sha256": sha256_file(summary_path),
                "failure_analysis_path": str(failure_path),
                "failure_analysis_sha256": sha256_file(failure_path),
                "deterministic_report_path": str(report_path),
                "deterministic_report_sha256": sha256_file(report_path),
                "execution_manifest_path": str(execution),
                "execution_manifest_sha256": sha256_file(execution),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path, summary_path


def snapshot(bundle: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(bundle): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }


def test_tool_api_reads_only_latest_sealed_result_without_mutation(
    tmp_path: Path,
) -> None:
    _workspace, bundle = make_workspace(tmp_path)
    manifest_path, summary_path = write_sealed_analysis(bundle)
    before = snapshot(bundle)

    result = get_result_summary(bundle)

    assert result.provenance_status == "SEALED_VERIFIED"
    assert result.analysis_manifest == manifest_path.resolve()
    assert result.result_summary_path == summary_path.resolve()
    assert result.result_summary_sha256 == sha256_file(summary_path)
    assert result.summary.candidate_count == 2
    assert snapshot(bundle) == before


def test_adapter_returns_bounded_path_free_ranked_evidence(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    _manifest_path, summary_path = write_sealed_analysis(bundle)

    result = ReadOnlyToolAdapter(workspace).get_result_summary(
        "task_a",
        limit=1,
    )

    assert isinstance(result, ResultSummaryAdapterResult)
    assert result.candidate_count == 2
    assert result.returned_candidate_count == 1
    assert result.truncated is True
    assert result.candidates_by_engineering_rank[0].candidate_id == (
        "candidate 1.pdb"
    )
    assert result.candidates_by_engineering_rank[0].final_score_v4 == 0.8
    assert result.result_summary_sha256 == sha256_file(summary_path)
    encoded = result.model_dump_json()
    assert str(workspace.resolve()) not in encoded
    assert "source_files" not in encoded
    assert "execution_manifest" not in encoded
    assert "private project" not in encoded
    assert "deterministic policy text" not in encoded

    inventory = ReadOnlyToolAdapter(workspace).list_tasks()
    assert isinstance(inventory, TaskListAdapterResult)
    assert inventory.tasks[0].sealed_result_status == "SEALED_VERIFIED"
    assert inventory.tasks[0].candidate_count == 2


def test_adapter_rejects_missing_unsealed_and_tampered_results(
    tmp_path: Path,
) -> None:
    missing_workspace, _missing_bundle = make_workspace(tmp_path / "missing")
    missing = ReadOnlyToolAdapter(missing_workspace).get_result_summary(
        "task_a"
    )
    assert isinstance(missing, AdapterErrorEnvelope)
    assert missing.error.code == "TOOL_REJECTED"

    legacy_workspace, legacy_bundle = make_workspace(tmp_path / "legacy")
    execution = legacy_bundle / "execution.json"
    execution.write_text('{"status":"COMPLETED"}', encoding="utf-8")
    (legacy_bundle / "agent_result_summary.json").write_text(
        build_summary(legacy_bundle, execution).model_dump_json(),
        encoding="utf-8",
    )
    (legacy_bundle / "agent_failure_analysis_v2.json").write_text(
        '{"status":"ANALYZED"}',
        encoding="utf-8",
    )
    legacy = ReadOnlyToolAdapter(legacy_workspace).get_result_summary("task_a")
    assert isinstance(legacy, AdapterErrorEnvelope)
    assert legacy.error.code == "TOOL_REJECTED"

    tampered_workspace, tampered_bundle = make_workspace(tmp_path / "tampered")
    _manifest_path, summary_path = write_sealed_analysis(tampered_bundle)
    summary_path.write_text(
        summary_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    tampered = ReadOnlyToolAdapter(tampered_workspace).get_result_summary(
        "task_a"
    )
    assert isinstance(tampered, AdapterErrorEnvelope)
    assert tampered.error.code == "SCIENTIFIC_RESULT_INVALID"
    assert str(tampered_workspace.resolve()) not in tampered.model_dump_json()

    inventory = ReadOnlyToolAdapter(tampered_workspace).list_tasks()
    assert isinstance(inventory, TaskListAdapterResult)
    assert inventory.tasks[0].sealed_result_status == "INVALID"
    assert inventory.tasks[0].candidate_count is None


def test_adapter_rejects_malformed_but_hash_sealed_result(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    manifest_path, summary_path = write_sealed_analysis(bundle)
    summary_path.write_text('{"status":"PARSED"}', encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["result_summary_sha256"] = sha256_file(summary_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    result = ReadOnlyToolAdapter(workspace).get_result_summary("task_a")

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "SCIENTIFIC_RESULT_INVALID"
    assert str(workspace.resolve()) not in result.model_dump_json()


def test_adapter_rejects_invalid_result_limit_as_published_request_error(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    write_sealed_analysis(bundle)

    result = ReadOnlyToolAdapter(workspace).get_result_summary(
        "task_a",
        limit=0,
    )

    assert isinstance(result, AdapterErrorEnvelope)
    assert result.error.code == "INVALID_REQUEST"
    assert result.error.validation_issues[0].location == "limit"


def test_mcp_returns_sealed_result_summary_with_read_only_annotations(
    tmp_path: Path,
) -> None:
    workspace, bundle = make_workspace(tmp_path)
    write_sealed_analysis(bundle)
    server = create_mcp_server(workspace)

    async def exercise() -> None:
        async with Client(server, mode="legacy") as client:
            tools = await client.list_tools()
            result_tool = next(
                tool for tool in tools.tools if tool.name == "get_result_summary"
            )
            assert result_tool.annotations is not None
            assert result_tool.annotations.read_only_hint is True
            assert result_tool.output_schema["type"] == "object"

            result = await client.call_tool(
                "get_result_summary",
                {"task_name": "task_a", "limit": 1},
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["candidate_count"] == 2
            assert result.structured_content["returned_candidate_count"] == 1
            assert result.structured_content["truncated"] is True
            assert str(workspace.resolve()) not in json.dumps(
                result.structured_content,
                sort_keys=True,
            )

    asyncio.run(exercise())
