# BinderRanker Target-Level Benchmark Sensitivity

> Status: v0.5 development contract, report schema `0.1`

This document defines a deterministic target-level heterogeneity and removal
sensitivity analysis for BinderRanker fixed-budget benchmark results. It is a
precondition for reviewing real retrospective campaigns; synthetic fixtures
are packaging and arithmetic tests only.

The analysis does not establish statistical significance, confidence-interval
coverage, cross-target generalization, causality, affinity, or experimental
success for a new candidate.

## 1. Input and analysis unit

`evaluate_target_sensitivity()` accepts the same `ValidatedBenchmarkBundle` as
the fixed-budget evaluator. It recomputes the Phase 2 report through the sealed
input gate before sensitivity analysis, so a changed manifest, changed CSV, or
stale bundle is rejected.

Only `EVALUATION` rows enter the report. `CALIBRATION` rows remain excluded.
The analysis unit is `TARGET`, matching the benchmark leakage-control unit.
When a target contains multiple campaigns, campaign counts are pooled within
that target before cross-target summaries are computed.

This prevents a target with many recorded campaigns from silently becoming
many independent targets. Cross-target summaries then give each target one
value per metric and fixed budget.

## 2. Target-level deltas

For each target and fixed budget, the report records:

- BinderRanker and baseline selected-hit counts;
- hits-per-campaign delta;
- precision delta;
- recall delta;
- enrichment-factor delta;
- successful-campaign count and success-rate delta.

All deltas are BinderRanker minus the manifest-declared baseline. A positive
delta is only an arithmetic direction in this retrospective dataset; it is not
a probability of biological success or proof of mechanism.

If every campaign for a target has zero positive outcomes, target recall and
enrichment have no valid denominator. Their values are explicitly:

```json
{
  "status": "UNAVAILABLE",
  "value": null,
  "reason": "NO_POSITIVE_OUTCOMES_IN_TARGET"
}
```

Undefined target values are counted as excluded from that metric's macro
summary. They are never replaced with zero, infinity, or a favorable default.

## 3. Equal-target descriptive summary

For every metric and budget, `TargetMetricSummary` records:

- total, defined, and excluded target counts;
- the equal-target arithmetic mean;
- target minimum, median, and maximum;
- counts of positive, near-zero, and negative target directions.

Direction classification treats absolute values at or below `1e-12` as zero.
The complete target rows remain in the report so every summary can be audited.

The macro target mean deliberately differs from a candidate-count-pooled
estimate: it gives each target equal weight after within-target campaign
aggregation. Both views may be useful, but neither should be substituted for
the other without explanation.

## 4. Leave-one-target-out sensitivity

The `LEAVE_ONE_TARGET_OUT` procedure removes each target with a defined metric
once, recomputes the equal-target mean from the remaining targets, and reports:

- the minimum removal estimate;
- the maximum removal estimate;
- the maximum absolute shift from the full equal-target mean.

At least two targets with a defined metric are required. Otherwise the range
is `UNAVAILABLE` with reason
`FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC`.

This is a deterministic removal-sensitivity range, **not a confidence
interval**. It has no nominal coverage level and is not a hypothesis test. A
range that stays above or below zero does not, by itself, establish statistical
significance or generalization.

## 5. Report claim boundary

`TargetSensitivityReport` is immutable, rejects NaN and infinity, and binds to
the benchmark manifest/CSV SHA256 values and frozen Ranker provenance inherited
from the fixed-budget report. It records:

- `analysis_unit=TARGET`;
- `analysis_method=LEAVE_ONE_TARGET_OUT`;
- `claim_scope=DESCRIPTIVE_TARGET_SENSITIVITY_ONLY`;
- `not_confidence_interval=true`;
- `statistical_significance_established=false`;
- `generalization_established=false`;
- `causality_established=false`.

## 6. Python entry point

```python
from pathlib import Path

from protein_design_agent.scientific_validation import (
    evaluate_target_sensitivity,
    validate_benchmark_bundle,
)

bundle = validate_benchmark_bundle(
    Path("retrospective_benchmark/benchmark.yaml")
)
report = evaluate_target_sensitivity(bundle)
```

Formal uncertainty intervals or hypothesis tests require an adequately sized,
independently reviewed real benchmark and a predeclared analysis plan. They are
not inferred automatically from this descriptive sensitivity report.
