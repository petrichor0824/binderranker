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
from protein_design_agent.schemas.project_config import (
    ProjectConfig,
)
from protein_design_agent.scientific_validation import (
    evaluate_fixed_budget_metrics,
    evaluate_target_sensitivity,
    validate_benchmark_bundle,
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
    "benchmark contract, fixed-budget metrics, and target sensitivity "
    "validated)"
)
