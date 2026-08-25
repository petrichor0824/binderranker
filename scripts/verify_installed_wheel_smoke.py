#!/usr/bin/env python3
"""验证已安装 Wheel 可在仓库外运行内置样例。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import protein_design_agent

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

ranker, _digest = resolve_ranker(
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
    "scientific interpretation modules available)"
)
