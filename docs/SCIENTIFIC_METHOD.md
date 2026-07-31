# BinderRanker Scientific Method

## Purpose

BinderRanker is an engineering triage method for prioritizing candidate
protein backbones before more expensive downstream work such as sequence
design, complex-structure prediction, molecular simulation, manual review,
and experimental validation.

It does not predict binding affinity, experimental success probability,
folding stability, or biological activity.

## Input and comparison unit

A run evaluates a collection of candidate PDB structures for one defined
target, chain layout, and scoring configuration.

Scores are primarily intended for relative comparison inside the current
candidate batch. Values from unrelated targets or independently normalized
runs must not be treated as directly comparable absolute quality scores.

## Interface geometry

The method evaluates target–binder contact geometry using soft contact
weights, interface coverage, spatial span, continuity, local orientation,
contact-field smoothness, shell sensitivity, and steric-risk indicators.

The detailed semantics of every public metric are documented in
[`METRICS.md`](METRICS.md).

## Morphology-adaptive scoring

BinderRanker represents three complementary interface patterns:

- `score_line`: extended contact patterns;
- `score_plane`: locally planar interface patterns;
- `score_compact`: localized dense contact patches.

Target-dependent morphology weights combine these values into
`morphology_adaptive_score`.

The morphology weights describe which interface mode is emphasized for the
current target. They are not classifications of binder secondary structure
or global protein shape.

## Final ranking score

When region scoring is disabled:

`final_score_v4 = 0.85 × morphology_adaptive_score + 0.10 × score_safety + 0.05 × score_roughness`

When region scoring is enabled:

`final_score_v4 = 0.78 × morphology_adaptive_score + 0.10 × score_safety + 0.05 × score_roughness + 0.07 × score_region`

`score_hotspot` remains a diagnostic quantity rather than an independent
fixed final-score term.

Whether region scoring was actually used must be read from the run metadata;
it must not be inferred only from the presence of region-related columns.

## Layered candidate filters

BinderRanker produces broad, medium, and strict candidate pools.

These pools use quantiles calculated from valid candidates in the current
batch. They are therefore dynamic batch-relative filters, not universal
biophysical cutoffs.

The layers progressively evaluate combinations of:

- effective contact amount;
- target coverage and spatial span;
- back-facing contact risk;
- contact-field variation;
- contact-map jumps and continuity;
- shell sensitivity;
- orientation support;
- safety and clash indicators.

When region filtering is enabled, design-region and undesired-region metrics
can add conditional filtering rules.

A candidate outside the strict pool is not automatically unusable. The pool
failure reasons should be inspected to determine which criteria caused the
exclusion.

## Analysis-scope guardrails

The Agent assigns a scope label from the number of input PDB candidates.

| Candidate count | Scope | Permitted interpretation |
|---:|---|---|
| 1–29 | `SMOKE_TEST_ONLY` | engineering and installation validation only |
| 30–199 | `EXPLORATORY` | exploratory within-batch comparison only |
| 200 or more | `FULL_DATASET_ANALYSIS` | full workflow interpretation is permitted |

These boundaries are safeguards against overinterpretation. They are not
proofs of statistical power or dataset representativeness.

Pool reporting follows the scope policy:

- smoke: public pool counts and memberships are suppressed;
- exploratory: pool counts may be shown but remain exploratory;
- full analysis: counts and leading pool members may be reported.

## Evidence and reproducibility

A completed run records the approved configuration, execution manifest,
critical-file fingerprints, structured Ranker outputs, result summary, and
analysis artifacts.

Model-generated explanation is downstream of deterministic calculation. It
cannot alter Ranker scores, pool membership, execution evidence, or recorded
provenance.

## Scientific limitations

BinderRanker is a prioritization layer, not a replacement for:

- sequence design;
- structure prediction;
- molecular dynamics or free-energy calculations;
- manual structural inspection;
- expression and biochemical validation;
- functional experiments.

High-ranking candidates should be interpreted as candidates that performed
well under the current engineering scoring system and batch context.
