#!/usr/bin/env python3
"""验证已安装 Wheel 可在仓库外运行内置样例。"""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import protein_design_agent
import yaml

from protein_design_agent.agent.metric_documentation import (
    render_metrics_markdown,
)
from protein_design_agent.agent.result_policy import (
    derive_pool_reporting_policy,
)
from protein_design_agent.agent.sample_resources import (
    extract_packaged_sample,
)
from protein_design_agent.agent.scientific_interpretation import (
    build_scientific_interpretation_contract,
)
from protein_design_agent.agent.scientific_result_validation import (
    validate_scientific_result,
)
from protein_design_agent.agent.tool_api_contract import (
    get_tool_api_catalog,
)
from protein_design_agent.agent.tool_adapter_errors import (
    ADAPTER_ERROR_CODES,
    AdapterErrorEnvelope,
    UnknownToolOperationError,
    adapter_error_from_exception,
)
from protein_design_agent.agent.tool_runtime_authorization import (
    DEFAULT_AUTHORIZATION_TTL,
    TrustedAuthorizationBroker,
    TrustedToolRuntime,
)
from protein_design_agent.schemas.project_config import (
    ProjectConfig,
)
from protein_design_agent.scientific_validation import (
    evaluate_fixed_budget_metrics,
    evaluate_target_sensitivity,
    validate_benchmark_bundle,
    validate_benchmark_readiness,
)
from protein_design_agent.tools.normalize_pdb_dataset import (
    normalize_one_pdb,
)
from protein_design_agent.tools.run_binderranker import (
    expected_output_files,
    resolve_ranker,
    validate_ranker_input,
)


root = (
    Path(tempfile.gettempdir())
    / "pda-wheel-smoke"
)
shutil.rmtree(root, ignore_errors=True)

input_dir = root / "input"
normalized_dir = root / "normalized"
results_dir = root / "results"
normalized_dir.mkdir(parents=True)
results_dir.mkdir(parents=True)

sample = extract_packaged_sample(
    destination=input_dir
)
assert len(sample.pdb_files) == 5

project = ProjectConfig.model_validate(
    {
        "project_name": "wheel_smoke",
        "input": {
            "pdb_dir": str(input_dir),
            "layout": "concatenated_single_chain",
            "source_chain": "A",
            "target_residue_count": 132,
            "target_start_residue": 4,
            "normalized_target_chain": "A",
            "normalized_binder_chain": "B",
        },
        "ranking": {
            "region_policy": "off",
            "region_filter": "off",
        },
    }
)

for source in sample.pdb_files:
    normalize_one_pdb(
        source,
        normalized_dir / source.name,
        project,
    )

validate_ranker_input(
    normalized_dir,
    binder_chain="B",
    recursive=False,
    max_files=None,
)

ranker, ranker_digest = resolve_ranker(
    "v0.1-expert"
)
output_prefix = results_dir / "wheel_smoke"

completed = subprocess.run(
    [
        sys.executable,
        str(ranker),
        "--input_dir",
        str(normalized_dir),
        "--output_prefix",
        str(output_prefix),
        "--binder_chain",
        "B",
        "--region_score_mode",
        "off",
        "--region_filter",
        "off",
    ],
    cwd=root,
    text=True,
    capture_output=True,
    check=False,
)

if completed.returncode != 0:
    print(completed.stdout)
    print(completed.stderr, file=sys.stderr)
    raise SystemExit(completed.returncode)

validation = validate_scientific_result(
    tuple(expected_output_files(output_prefix)),
    expected_candidate_count=len(sample.pdb_files),
)

smoke_policy = derive_pool_reporting_policy(
    {
        "level": "SMOKE_TEST_ONLY",
        "pool_labels_reliable": False,
        (
            "workflow_allows_"
            "formal_interpretation"
        ): False,
    }
)
interpretation_contract = (
    build_scientific_interpretation_contract(
        region_score_used=False,
        pool_reporting_policy=smoke_policy,
    )
)
assert len(
    interpretation_contract.metric_semantics
) == 20
assert (
    interpretation_contract
    .threshold_interpretation_mode
    == "SUPPRESSED"
)
assert "### `final_score_v4`" in (
    render_metrics_markdown()
)

tool_catalog = get_tool_api_catalog()
assert tool_catalog.tool_count == 8
assert tool_catalog.model_supplied_authorization_accepted is False
assert tool_catalog.scientific_evidence_status == "SCIENTIFIC_VALIDATION_PENDING"
assert tool_catalog.authorization_transport == "IN_PROCESS_OPAQUE_CAPABILITY"
assert tool_catalog.authorization_grant_json_serializable is False
assert tool_catalog.authorization_grant_single_use is True
assert tool_catalog.authorization_grant_review_resource_bound is True
assert tool_catalog.adapter_error_codes == ADAPTER_ERROR_CODES
assert tool_catalog.adapter_error_internal_details_exposed is False
assert tool_catalog.adapter_error_automatic_retry_safe is False
assert tool_catalog.adapter_error_json_schema["type"] == "object"

adapter_error = adapter_error_from_exception(
    operation="not_published",
    error=UnknownToolOperationError("not_published"),
)
assert isinstance(adapter_error, AdapterErrorEnvelope)
assert adapter_error.error.code == "UNKNOWN_OPERATION"
assert adapter_error.error.retryable is False

tool_contracts = {
    tool.name: tool for tool in tool_catalog.tools
}
approval_properties = tool_contracts[
    "request_approval"
].input_json_schema["properties"]
execution_properties = tool_contracts[
    "execute_ranker"
].input_json_schema["properties"]
assert set(approval_properties) == {"bundle_dir"}
assert "execution_confirmed" not in execution_properties
assert tool_contracts["request_approval"].trusted_runtime_entrypoint == (
    "TrustedToolRuntime.request_approval"
)
assert tool_contracts["execute_ranker"].trusted_runtime_entrypoint == (
    "TrustedToolRuntime.execute_ranker"
)
assert DEFAULT_AUTHORIZATION_TTL.total_seconds() == 300
trusted_runtime = TrustedToolRuntime(
    TrustedAuthorizationBroker()
)
assert isinstance(trusted_runtime, TrustedToolRuntime)

benchmark_dir = root / "benchmark"
benchmark_dir.mkdir()
benchmark_csv = benchmark_dir / "candidates.csv"
benchmark_rows = [
    {
        "campaign_id": "smoke_cal",
        "target_id": "target_cal",
        "candidate_id": "cal_1",
        "split": "CALIBRATION",
        "binderranker_rank": 1,
        "binderranker_score": 0.9,
        "baseline_rank": 2,
        "outcome": 1,
    },
    {
        "campaign_id": "smoke_cal",
        "target_id": "target_cal",
        "candidate_id": "cal_2",
        "split": "CALIBRATION",
        "binderranker_rank": 2,
        "binderranker_score": 0.8,
        "baseline_rank": 1,
        "outcome": 0,
    },
    {
        "campaign_id": "smoke_eval",
        "target_id": "target_eval",
        "candidate_id": "eval_1",
        "split": "EVALUATION",
        "binderranker_rank": 1,
        "binderranker_score": 0.7,
        "baseline_rank": 2,
        "outcome": 1,
    },
    {
        "campaign_id": "smoke_eval",
        "target_id": "target_eval",
        "candidate_id": "eval_2",
        "split": "EVALUATION",
        "binderranker_rank": 2,
        "binderranker_score": 0.6,
        "baseline_rank": 1,
        "outcome": 0,
    },
]
benchmark_columns = list(
    benchmark_rows[0]
)

with benchmark_csv.open(
    "w",
    encoding="utf-8",
    newline="",
) as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=benchmark_columns,
    )
    writer.writeheader()
    writer.writerows(
        benchmark_rows
    )

benchmark_sha256 = hashlib.sha256(
    benchmark_csv.read_bytes()
).hexdigest()
benchmark_manifest = {
    "schema_version": "0.1",
    "benchmark_id": "wheel_smoke",
    "description": (
        "Installed-Wheel benchmark contract smoke."
    ),
    "dataset": {
        "file": benchmark_csv.name,
        "sha256": benchmark_sha256,
    },
    "outcome": {
        "name": "synthetic_outcome",
        "description": (
            "Synthetic binary outcome for packaging only."
        ),
        "evidence_type": "COMPUTATIONAL_PROXY",
        "source": "installed-Wheel smoke fixture",
    },
    "baseline": {
        "method_id": "fixture_order",
        "description": "Synthetic comparator.",
        "ranking_procedure": (
            "Fixed fixture order."
        ),
    },
    "ranker": {
        "ranker_id": "BinderRanker",
        "version": "v0.1-expert",
        "resource_sha256": ranker_digest,
    },
    "protocol": {
        "parameter_selection": "CALIBRATION_ONLY",
        "ranking_blinded_to_outcomes": True,
        "baseline_blinded_to_outcomes": True,
        "target_split_unit": "TARGET",
    },
    "selection_budgets": [1],
}
benchmark_manifest_path = (
    benchmark_dir
    / "benchmark.yaml"
)
benchmark_manifest_path.write_text(
    yaml.safe_dump(
        benchmark_manifest,
        sort_keys=False,
    ),
    encoding="utf-8",
)
benchmark_validation = (
    validate_benchmark_bundle(
        benchmark_manifest_path
    )
)
assert (
    benchmark_validation
    .summary
    .candidate_count
    == 4
)
benchmark_report = evaluate_fixed_budget_metrics(
    benchmark_validation
)
assert benchmark_report.calibration_excluded is True
assert benchmark_report.evaluation_campaign_count == 1
assert benchmark_report.evaluation_candidate_count == 2
assert benchmark_report.pooled_comparisons[0].binderranker.hits_at_k == 1
assert benchmark_report.pooled_comparisons[0].baseline.hits_at_k == 0
benchmark_sensitivity = evaluate_target_sensitivity(
    benchmark_validation
)
assert benchmark_sensitivity.analysis_unit == "TARGET"
assert benchmark_sensitivity.evaluation_target_count == 1
assert all(
    item.leave_one_target_out.status == "UNAVAILABLE"
    for item in benchmark_sensitivity.metric_summaries
)
benchmark_readiness_path = benchmark_dir / "readiness.yaml"
benchmark_readiness_path.write_text(
    yaml.safe_dump(
        {
            "schema_version": "0.1",
            "benchmark_id": benchmark_validation.summary.benchmark_id,
            "manifest_sha256": benchmark_validation.summary.manifest_sha256,
            "dataset_sha256": benchmark_validation.summary.dataset_sha256,
            "data_kind": "SYNTHETIC_FIXTURE",
            "data_freeze": {
                "frozen_at": "2026-08-01T09:00:00+08:00",
                "source_system": "Installed-Wheel smoke fixture.",
                "extraction_procedure": "Generated deterministically in smoke.",
                "immutable_record_id": "wheel-smoke-fixture-v1",
            },
            "cohort": {
                "inclusion_criteria": "All generated smoke rows.",
                "exclusion_criteria": "No exclusions.",
                "candidate_universe_complete": True,
                "missing_outcome_policy": "No missing outcomes in fixture.",
            },
            "review": {
                "outcome_definition_reviewed": True,
                "baseline_procedure_reviewed": True,
                "leakage_reviewed": True,
                "analysis_plan_id": "wheel-smoke-plan-v1",
                "reviewer_role": "Packaging test",
                "review_record_id": "wheel-smoke-review-v1",
                "reviewed_at": "2026-08-02T09:00:00+08:00",
            },
            "evidence_limitations": [
                "Synthetic packaging fixture is not empirical evidence.",
            ],
        },
        sort_keys=False,
    ),
    encoding="utf-8",
)
benchmark_readiness = validate_benchmark_readiness(
    benchmark_validation,
    benchmark_readiness_path,
)
assert benchmark_readiness.engineering_readiness_status == "READY"
assert benchmark_readiness.scientific_review_status == "FIXTURE_ONLY"
assert benchmark_readiness.formal_inference_established is False
assert (
    "SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE"
    in benchmark_readiness.warnings
)

package_path = Path(
    protein_design_agent.__file__
).resolve()
repository_root = Path(__file__).resolve().parents[1]
environment_root = Path(sys.prefix).resolve()

assert not package_path.is_relative_to(repository_root), (
    f"package imported from repository: {package_path}"
)
assert package_path.is_relative_to(environment_root), (
    f"package not imported from active environment: "
    f"{package_path}; sys.prefix={environment_root}"
)

print(
    "PASS: installed Wheel extracted five PDBs "
    "and produced a scientifically valid BinderRanker "
    f"result outside repository "
    f"({validation.valid_candidate_count} valid candidates; "
    "scientific interpretation modules available; "
    "versioned Tool API contract validated; "
    "benchmark contract, fixed-budget metrics, target sensitivity, and "
    "readiness boundaries "
    "validated)"
)
