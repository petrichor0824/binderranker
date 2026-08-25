# BinderRanker Benchmark Readiness and Provenance Review

> Status: v0.5 development contract, checklist/report schema `0.1`

This layer binds provenance and review declarations to one exact sealed
benchmark and reports whether its structure can enter scientific review. It
does not verify that a declaration is historically true and does not turn a
retrospective dataset into evidence of BinderRanker performance.

## 1. Two different readiness questions

`validate_benchmark_readiness()` keeps these states separate:

- `engineering_readiness_status=READY` means the strict checklist is valid,
  matches the current manifest/CSV hashes, and the sealed bundle still passes
  the Phase 1–3 validation chain;
- `scientific_review_status=READY_FOR_SCIENTIFIC_REVIEW` means data declared as
  `REAL_RETROSPECTIVE` can be handed to an independent scientific reviewer;
- `scientific_review_status=FIXTURE_ONLY` means data declared as
  `SYNTHETIC_FIXTURE` remain packaging or arithmetic test material only.

Neither status means that BinderRanker improves enrichment, predicts binding,
generalizes to new targets, or causes experimental success. Every report uses
`claim_scope=READINESS_METADATA_ONLY`,
`declaration_truth_independently_verified=false`,
`formal_inference_established=false`, and
`performance_benefit_established=false`.

The validator confirms that required declarations exist and agree with the
sealed artifacts. An independent reviewer must verify the source records,
extraction history, cohort definition, blinding history, outcome definition,
baseline procedure, and analysis plan outside the software.

## 2. Companion checklist

Keep the checklist beside the sealed benchmark bundle:

```text
retrospective_benchmark/
├── benchmark.yaml
├── candidates.csv
└── readiness.yaml
```

Copy and complete this schema:

```yaml
schema_version: "0.1"
benchmark_id: campaign_series_2026
manifest_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
dataset_sha256: fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
data_kind: REAL_RETROSPECTIVE

data_freeze:
  frozen_at: 2026-08-01T09:00:00+08:00
  source_system: Immutable laboratory campaign registry export.
  extraction_procedure: Predeclared query with no manual row edits.
  immutable_record_id: registry-export-2026-08-01

cohort:
  inclusion_criteria: All generated candidates in the declared campaigns.
  exclusion_criteria: No post-ranking candidate exclusions.
  candidate_universe_complete: true
  missing_outcome_policy: Preserve missing outcomes outside the admitted table.

review:
  outcome_definition_reviewed: true
  baseline_procedure_reviewed: true
  leakage_reviewed: true
  analysis_plan_id: retrospective-analysis-v1
  reviewer_role: Independent scientific reviewer
  review_record_id: review-record-001
  reviewed_at: 2026-08-02T09:00:00+08:00

evidence_limitations:
  - Retrospective association does not establish causality.
  - Target coverage may not represent future design campaigns.
```

`benchmark_id`, `manifest_sha256`, and `dataset_sha256` must match the current
validated bundle exactly. The checklist bytes receive a separate SHA256 in the
report. Timestamps must include a UTC offset, and review cannot predate the
declared data freeze. Unknown fields, false required review declarations,
duplicate limitations, and unsupported schema versions are rejected.

`candidate_universe_complete: true` is a declaration that the candidate set
was not selectively filtered after ranking. The software cannot independently
prove that declaration from the CSV alone.

## 3. Structural facts and warnings

The report deterministically counts:

- evaluation targets, campaigns, candidates, positive outcomes, and negative
  outcomes;
- targets and campaigns containing both outcome classes, positive outcomes
  only, or negative outcomes only;
- minimum and maximum campaigns per target;
- minimum and maximum candidates per campaign;
- whether BinderRanker and baseline ranks are identical in every evaluation
  campaign.

It also exposes explicit method prerequisites:

- target-removal sensitivity is structurally `AVAILABLE` with at least two
  evaluation targets;
- positive-denominator target sensitivity is structurally `AVAILABLE` with at
  least two evaluation targets containing positive outcomes.

These are mathematical prerequisites for the implemented descriptive method,
not claims that a sample is large, representative, powered, or suitable for
formal inference. The software intentionally does not invent a universal
threshold such as “N targets is enough.” Sample-size justification belongs in
the predeclared analysis plan and independent scientific review.

Warnings include `SYNTHETIC_FIXTURE_NOT_EMPIRICAL_EVIDENCE`,
`COMPUTATIONAL_PROXY_NOT_EXPERIMENTAL_EVIDENCE`,
`SINGLE_EVALUATION_TARGET`,
`FEWER_THAN_TWO_POSITIVE_OUTCOME_TARGETS`,
`NO_TARGET_WITH_BOTH_OUTCOME_CLASSES`, and
`IDENTICAL_RANKINGS_ALL_CAMPAIGNS` when applicable. Every report also includes
`DECLARATIONS_NOT_INDEPENDENTLY_VERIFIED` and
`FORMAL_INFERENCE_NOT_ESTABLISHED`.

## 4. Python entry point

```python
from pathlib import Path

from protein_design_agent.scientific_validation import (
    validate_benchmark_bundle,
    validate_benchmark_readiness,
)

bundle = validate_benchmark_bundle(
    Path("retrospective_benchmark/benchmark.yaml")
)
report = validate_benchmark_readiness(
    bundle,
    Path("retrospective_benchmark/readiness.yaml"),
)
```

The readiness function reruns the target-sensitivity entry point first, which
in turn revalidates fixed-budget metrics and the sealed input contract. A stale
manifest, changed CSV, forged bundle summary, or mismatched checklist is
rejected before a readiness report is produced.

## 5. What remains outside software validation

For real retrospective data, `READY_FOR_SCIENTIFIC_REVIEW` is the beginning of
scientific review, not its conclusion. Remaining work includes source-record
inspection, analysis-plan review, assessment of missingness and selection
bias, target representativeness, appropriate uncertainty methods, and
interpretation of the actual benchmark results. Prospective experimental
validation remains a separate evidence tier.
