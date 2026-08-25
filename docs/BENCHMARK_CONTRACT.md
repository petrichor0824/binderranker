# BinderRanker Benchmark Contract

> Status: v0.5 development contract, schema `0.1`

This contract defines which retrospective candidate data may enter a
BinderRanker benchmark. It is an input-integrity and leakage-control gate. It
does not by itself establish that BinderRanker improves downstream outcomes.

## 1. Scientific boundary

A benchmark bundle that passes this contract establishes that:

- the manifest and candidate table are identified by SHA256;
- the outcome and baseline are explicitly defined;
- the BinderRanker implementation is identified by version and resource hash;
- candidate rankings are complete and internally consistent;
- fixed selection budgets are comparable across campaigns;
- calibration and evaluation targets do not overlap;
- both positive and negative outcomes exist in the evaluation split.

Passing the contract does **not** establish enrichment, generalization,
biological causality, affinity prediction, or experimental success. Those
claims require separately reviewed benchmark results and appropriate
downstream evidence.

## 2. Bundle layout

A benchmark bundle contains a YAML manifest and one candidate-level CSV in the
same directory tree:

```text
retrospective_benchmark/
├── benchmark.yaml
└── candidates.csv
```

`dataset.file` must be a relative path that remains inside the manifest
directory. The manifest records the lowercase SHA256 of the exact CSV bytes.
Absolute paths and paths that escape the bundle are rejected.

## 3. Manifest schema `0.1`

```yaml
schema_version: "0.1"
benchmark_id: campaign_series_2026
description: Retrospective evaluation on fixed historical candidate batches.

dataset:
  file: candidates.csv
  sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

outcome:
  name: downstream_success
  description: Binary outcome from the declared downstream validation stage.
  evidence_type: EXPERIMENTAL
  source: Laboratory campaign registry export 2026-08-01

baseline:
  method_id: generation_order
  description: Candidate order before BinderRanker prioritization.
  ranking_procedure: Ascending immutable generation index within each campaign.

ranker:
  ranker_id: BinderRanker
  version: v0.1-expert
  resource_sha256: 92d6c02f8ca8f500917f5fa61676fe93a0acdbb59d49f2cac0c7a74a4a553ed7

protocol:
  parameter_selection: CALIBRATION_ONLY
  ranking_blinded_to_outcomes: true
  baseline_blinded_to_outcomes: true
  target_split_unit: TARGET

selection_budgets: [5, 10, 20]
```

Manifest keys are strict. Unknown keys and unsupported schema versions are
rejected instead of being silently ignored.

### Outcome evidence type

`outcome.evidence_type` must be one of:

- `EXPERIMENTAL` — an observed experimental outcome;
- `COMPUTATIONAL_PROXY` — a declared downstream computational measurement.

A computational proxy must not be described as experimental validation.

### Parameter-selection policy

`protocol.parameter_selection` must be one of:

- `FROZEN_PREDEFINED` — all evaluated parameters were fixed before examining
  benchmark outcomes;
- `CALIBRATION_ONLY` — any parameter choice used calibration targets only, and
  the bundle must contain at least one calibration target.

The manifest must explicitly declare that BinderRanker and baseline rankings
were blinded to outcomes. The validator can enforce the declaration and split
structure; independent provenance review is still required to verify the
historical process behind that declaration.

## 4. Candidate CSV

The CSV requires these columns:

| Column | Meaning |
| --- | --- |
| `campaign_id` | Candidate batch identifier. |
| `target_id` | Biological target used as the leakage-control unit. |
| `candidate_id` | Candidate identifier, unique within a campaign. |
| `split` | `CALIBRATION` or `EVALUATION`. |
| `binderranker_rank` | Complete one-based BinderRanker rank. |
| `binderranker_score` | Finite BinderRanker score used for that rank. |
| `baseline_rank` | Complete one-based comparator rank. |
| `outcome` | Binary downstream outcome: `1` positive, `0` negative. |

Additional provenance columns may be retained. Schema `0.1` ignores them for
validation and performance computation; downstream code must not silently
reinterpret an extra column as a scientific outcome.

Example:

```csv
campaign_id,target_id,candidate_id,split,binderranker_rank,binderranker_score,baseline_rank,outcome
campaign_01,target_A,candidate_001,CALIBRATION,1,0.812,4,1
campaign_01,target_A,candidate_002,CALIBRATION,2,0.774,1,0
campaign_02,target_B,candidate_101,EVALUATION,1,0.803,3,0
campaign_02,target_B,candidate_102,EVALUATION,2,0.765,1,1
```

## 5. Deterministic validation rules

The shared validator rejects a bundle when any of these conditions occurs:

1. The manifest or CSV is missing, empty, malformed, or outside the bundle.
2. The CSV SHA256 differs from the manifest.
3. Required identifiers are invalid or a campaign/candidate pair is repeated.
4. A campaign mixes targets or split roles.
5. A target appears in both `CALIBRATION` and `EVALUATION`.
6. BinderRanker or baseline ranks are not the complete permutation `1..N`.
7. BinderRanker scores are non-finite or disagree with recorded rank order.
8. Outcomes are not exactly binary.
9. A fixed selection budget exceeds any campaign candidate count.
10. No budget performs a selective comparison below the full campaign size.
11. The evaluation split lacks either a positive or a negative outcome.
12. `CALIBRATION_ONLY` is declared without a calibration target.

Rows are returned as immutable models in a deterministic canonical order after
validation. The validation summary records both the manifest SHA256 and the CSV
SHA256 so downstream metric artifacts can bind to the exact admitted contract.

## 6. Python entry point

```python
from pathlib import Path

from protein_design_agent.scientific_validation import (
    validate_benchmark_bundle,
)

bundle = validate_benchmark_bundle(
    Path("retrospective_benchmark/benchmark.yaml")
)

print(bundle.summary)
```

This entry point does not execute BinderRanker, tune parameters, compute
enrichment, or create performance claims. It only admits or rejects benchmark
inputs and returns normalized deterministic records.

## 7. Downstream fixed-budget phase

The v0.5 fixed-budget metric layer computes only from a revalidated
`ValidatedBenchmarkBundle`. Evaluation metrics exclude calibration rows,
report BinderRanker and baseline results side by side, preserve undefined
metric states explicitly, and avoid turning a retrospective association into a
causal or generalizable biological claim. See
[`BENCHMARK_METRICS.md`](BENCHMARK_METRICS.md).
