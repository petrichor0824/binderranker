# BinderRanker Fixed-Budget Benchmark Metrics

> Status: v0.5 development contract, report schema `0.1`

This document defines the deterministic comparison computed after a benchmark
bundle passes the sealed input contract. It compares BinderRanker with the
manifest-declared baseline under the same fixed downstream selection budgets.

The report is descriptive retrospective evidence. This report
does not by itself establish generalization, causality, biological mechanism,
affinity, or experimental success for a new target.

## 1. Evaluation boundary

`evaluate_fixed_budget_metrics()` accepts a `ValidatedBenchmarkBundle`. Before
computing anything, it revalidates the manifest and CSV and requires the
in-memory bundle to match the current sealed files exactly. A changed dataset,
changed manifest, stale summary, or forged summary is rejected.

Only rows whose split is `EVALUATION` enter reported metrics. `CALIBRATION`
rows are always excluded. Selection budgets come from the sealed manifest and
are applied independently within every evaluation campaign.

BinderRanker selection uses ascending `binderranker_rank`. Baseline selection
uses ascending `baseline_rank`. Outcomes, scores, or extra CSV columns are not
used to alter either ranking.

## 2. Campaign-level definitions

For one campaign with `N` candidates, `P` positive outcomes, and fixed budget
`k`, let `H(k)` be the positive outcomes among the first `k` candidates under
the evaluated ranking.

| Metric | Definition |
| --- | --- |
| `hits_at_k` | `H(k)` |
| `precision_at_k` | `H(k) / k` |
| `recall_at_k` | `H(k) / P` |
| `enrichment_factor_at_k` | `(H(k) / k) / (P / N)` |
| `success_at_k` | `H(k) > 0` |

Every campaign/budget row contains BinderRanker and baseline results side by
side, followed by the arithmetic BinderRanker-minus-baseline deltas. Selected
candidate identifiers are retained so the counts remain auditable.

### Explicit undefined states

When a campaign has no positive outcomes (`P = 0`), recall and enrichment
factor have no valid denominator. They are represented as:

```json
{
  "status": "UNAVAILABLE",
  "value": null,
  "reason": "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN"
}
```

Their deltas are also `UNAVAILABLE`. They are never replaced by zero, one, an
infinite value, or an optimistic default. Precision and `success_at_k` remain
defined because their denominators do not depend on `P`.

## 3. Pooled definitions

Pooled metrics first select exactly `k` candidates inside every evaluation
campaign, then sum the resulting counts. They do not create one global ranking
across targets.

For `C` campaigns, the pooled selected count is `k * C`. Pooled precision,
recall, and enrichment factor are computed from total selected hits, total
selected candidates, total positive outcomes, and total candidates. The report
also records:

- successful campaign count and success rate at each budget;
- campaigns with no positive outcomes;
- BinderRanker-minus-baseline count and rate deltas.

The sealed input contract requires at least one positive and one negative
evaluation outcome overall, so pooled recall and pooled enrichment factor are
defined. Campaign-level undefined states remain visible and are not erased by
pooling.

## 4. Report contract

`FixedBudgetBenchmarkReport` is immutable, rejects NaN and infinity, and binds
the result to:

- benchmark ID;
- manifest and dataset SHA256 values;
- outcome evidence type;
- baseline method ID;
- BinderRanker version and frozen-resource SHA256;
- fixed selection budgets.

It records `calibration_excluded=true`,
`claim_scope=DESCRIPTIVE_RETROSPECTIVE_ONLY`,
`generalization_established=false`, and `causality_established=false`.

## 5. Python entry point

```python
from pathlib import Path

from protein_design_agent.scientific_validation import (
    evaluate_fixed_budget_metrics,
    validate_benchmark_bundle,
)

bundle = validate_benchmark_bundle(
    Path("retrospective_benchmark/benchmark.yaml")
)
report = evaluate_fixed_budget_metrics(bundle)
```

This phase does not tune BinderRanker, change the frozen ranking algorithm,
estimate uncertainty, run hypothesis tests, or claim a real-world advantage.
Confidence intervals, target-level resampling, sensitivity analysis, and any
empirical interpretation require an adequately powered real benchmark and a
separate scientific review.
