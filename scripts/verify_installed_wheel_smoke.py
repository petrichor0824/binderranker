#!/usr/bin/env python3
"""验证已安装 Wheel 可在仓库外运行内置样例。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import protein_design_agent

from protein_design_agent.agent.sample_resources import (
    extract_packaged_sample,
)
from protein_design_agent.tools.run_binderranker import (
    resolve_ranker,
)


root = Path("/tmp/pda-wheel-smoke")
shutil.rmtree(root, ignore_errors=True)

input_dir = root / "input"
results_dir = root / "results"
results_dir.mkdir(parents=True)

sample = extract_packaged_sample(
    destination=input_dir
)
assert len(sample.pdb_files) == 5

ranker, _digest = resolve_ranker(
    "v0.1-expert"
)
output_prefix = results_dir / "wheel_smoke"

completed = subprocess.run(
    [
        sys.executable,
        str(ranker),
        "--input_dir",
        str(input_dir),
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

for suffix in (
    "metrics.csv",
    "scored.csv",
    "ranking.xlsx",
    "report.txt",
):
    output = Path(f"{output_prefix}_{suffix}")
    assert output.is_file(), output
    assert output.stat().st_size > 0

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
    "and completed BinderRanker outside repository"
)
