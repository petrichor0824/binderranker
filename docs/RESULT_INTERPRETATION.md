# Interpreting BinderRanker Results

## Start with the analysis scope

Before interpreting any ranking, check the run scope:

| Scope | Meaning |
|---|---|
| `SMOKE_TEST_ONLY` | engineering validation only; no formal candidate recommendation |
| `EXPLORATORY` | within-batch exploratory comparison only |
| `FULL_DATASET_ANALYSIS` | full workflow interpretation is permitted, but validation is still required |

The scope label limits what may be claimed. It does not measure the quality of
an individual candidate.

## Read the ranking as batch-relative

`final_score_v4` is the primary engineering ranking score.

A higher value means that a candidate performed better under the current
BinderRanker configuration and current batch normalization. It does not mean:

- higher binding affinity;
- greater experimental success probability;
- better folding stability;
- guaranteed interface correctness;
- direct superiority to scores from another target or batch.

Score differences should be interpreted together with component scores,
filter results, and structural inspection.

## Verify the deterministic score decomposition

New result summaries expose `score_decomposition_status` before presenting
candidate-level primary-score contributions.

When the status is `AVAILABLE`, inspect:

- `primary_score_formula`, the formula recorded for the active scoring mode;
- `primary_score_weights`, the audited direct-component weights;
- `primary_score_contributions`, each candidate's weight multiplied by its
  recorded component score;
- `reconstructed_final_score_v4` and
  `primary_score_reconstruction_error`, which verify that the contributions
  reproduce the recorded ranking score.

A result whose recorded score cannot be reconstructed is rejected by the
parser. When the status is `UNAVAILABLE`, the report predates the necessary
formula context or does not contain it; the ranking remains readable, but
BinderRanker does not guess a decomposition.

These contributions explain arithmetic inside the ranking formula. They are
not causal attributions, free-energy components, or evidence that a metric has
the same importance across targets or candidate batches.

## Read the deterministic analysis report

`binderranker analyze-run` writes
`binderranker_deterministic_analysis.md` alongside the authoritative JSON
summary and failure analysis. The Markdown report is generated without a
language model and does not recompute scores, ranks, filters, or thresholds.
It presents only evidence that has already passed the structured parsers and
cross-artifact consistency checks.

The report follows the analysis-scope policy:

- `SMOKE_TEST_ONLY` keeps public screening status but suppresses numerical
  dynamic-threshold and gap details because a tiny batch does not support
  stable interpretation;
- `EXPLORATORY` may show failed gates and numerical threshold gaps as
  within-batch exploratory evidence;
- `FULL_DATASET_ANALYSIS` may show the same deterministic evidence under the
  full-workflow interpretation policy, while still requiring downstream
  validation.

The report path and SHA256 digest are recorded in the completed analysis
manifest. Editing the report after completion causes provenance verification
to fail. Analysis manifests created before this report was introduced remain
readable as legacy artifacts.

## Use the sealed scientific-interpretation contract

Current deterministic result summaries include a machine-readable
`scientific_interpretation_contract`. It binds the controlled metric ontology
to the run's recorded scoring mode and analysis-scope policy. The contract
records:

- every exposed metric's direction, role, definition, permitted
  interpretations, prohibited interpretations, and suggested checks;
- that scores and ranks are empirical, batch-relative engineering evidence;
- that cross-batch and cross-target score comparison is not allowed without
  calibration;
- that dynamic thresholds are batch-relative rather than universal cutoffs;
- the current threshold interpretation mode;
- prohibited scientific claims and required downstream validation.

The deterministic Markdown report and optional evidence-bound explanation
validate and reuse this contract. A modified contract that no longer matches
the shared metric ontology or result policy is rejected. Older summaries remain
readable with `scientific_interpretation_status=UNAVAILABLE`; BinderRanker does
not invent missing run-bound interpretation evidence.

## Check artifact schema compatibility

Result summaries declare the evidence generation they contain. BinderRanker
supports result-summary schemas `0.1`, `0.2`, `0.3`, and `0.4`:

- `0.1` is the v0.3.1 result-summary contract;
- `0.2` adds deterministic primary-score decomposition;
- `0.3` adds adjacent-rank arithmetic comparisons;
- `0.4` adds the sealed scientific-interpretation contract.

Older generations remain readable and expose later evidence as explicitly
`UNAVAILABLE`. A summary claiming a newer known generation must contain all
fields introduced by that generation; missing fields are treated as artifact
damage rather than silently replaced with defaults. Unknown future schema
versions are rejected so an older BinderRanker installation cannot
misinterpret newer evidence.

Completed analysis manifests follow the same rule for their known `0.1`
through `0.3` generations. Current `0.3` manifests must include the sealed
deterministic-report path and digest. All loaded summary scores, component
values, metrics, weights, and thresholds must be finite; NaN and infinity are
invalid even when they arrive through an explicit or legacy artifact path.

## Compare adjacent ranks arithmetically

When primary-score decomposition is available, the result summary and
deterministic report compare each adjacent rank pair. For rank 1 versus rank
2, for example, BinderRanker subtracts rank 2 from rank 1 for every recorded
direct-primary contribution.

The comparison records:

- the recorded `final_score_v4` difference;
- each direct-primary contribution difference;
- the sum of those contribution differences;
- the reconstruction error between the two values;
- the largest positive and largest negative contribution differences, when
  present.

A positive contribution difference supports the higher-ranked candidate's
recorded score advantage. A negative difference is an arithmetic offset: the
higher-ranked candidate received less from that term but overcame it through
other terms. These statements describe the recorded empirical ranking formula
only. They are not causal explanations, energetic decompositions, or evidence
of a biological mechanism.

Only adjacent ranks are compared by default. This keeps the evidence linear in
the candidate count and makes each local rank separation directly auditable.
A single-candidate run is marked `NOT_APPLICABLE`; legacy or insufficient
formula evidence is marked `UNAVAILABLE` without inferred comparisons.

## Understand strengths and weaknesses

The compact result preview reports the strongest and weakest normalized
component scores for each leading candidate.

These component values are direction-normalized:

- higher displayed values indicate better component performance;
- lower displayed values indicate a potential relative weakness.

A component described as a weakness is not necessarily an absolute failure.
It means that the component is relatively weak within the current scoring
context.

The main component groups are:

- morphology-adaptive interface geometry;
- extended-interface mode;
- planar-interface mode;
- compact-contact mode;
- contact-field smoothness and continuity;
- local microgeometry;
- geometric safety;
- optional design-region support;
- hotspot-neighborhood diagnostics.

Detailed definitions and prohibited interpretations are provided in
[`METRICS.md`](METRICS.md).

## Distinguish score rank from filter level

Candidates are ranked by `final_score_v4`, while broad, medium, and strict
filters evaluate additional geometric conditions.

Therefore:

- a high-scoring candidate may still fail a strict filter;
- a candidate may pass a pool without having the highest total score;
- filter failure does not automatically make a candidate unusable;
- strict-pool membership does not guarantee experimental success.

Always inspect the recorded filter reasons to identify the actual limiting
metrics.

## Interpret broad, medium, and strict pools

The pools are nested levels of batch-relative screening:

- **broad** removes clearer geometric outliers;
- **medium** applies more selective coverage, continuity, orientation, and
  risk requirements;
- **strict** applies the strongest combined requirements.

Thresholds are calculated from quantiles of valid candidates in the current
batch. They are not universal physical cutoffs.

Pool reporting also depends on analysis scope:

- `SMOKE_TEST_ONLY`: pool counts and memberships are hidden;
- `EXPLORATORY`: pool counts may be shown, but remain exploratory;
- `FULL_DATASET_ANALYSIS`: pool counts and leading members may be reported.

## Region and hotspot interpretation

Check the run metadata before interpreting region-related fields.

When `region_score_used` is false:

- `score_region` is diagnostic;
- it does not directly raise or lower `final_score_v4`.

When `region_score_used` is true:

- `score_region` contributes 0.07 to the final-score formula;
- morphology contribution changes from 0.85 to 0.78.

`score_hotspot` remains diagnostic and is not an independent fixed
final-score term.

Region filtering is a separate setting from region scoring. A run may contain
region diagnostics without using them in the final score or filter rules.

## Investigate why a candidate was dragged down

For a high-ranked candidate that failed a stricter pool:

1. read `filter_medium_reasons` or `filter_strict_reasons`;
2. identify the exact metric and threshold involved;
3. check whether the issue reflects contact amount, coverage, span,
   orientation, continuity, shell sensitivity, safety, clash, or region
   targeting;
4. inspect the PDB interface visually;
5. compare the same metric across nearby-ranked candidates.

Do not infer a biological mechanism from a metric name alone.

## Use provenance before explanation

The deterministic result summary records execution and output fingerprints.
Use these identifiers to verify that the ranking, analysis, and explanation
belong to the same approved run.

Model-generated explanation is optional. If explanation is unavailable or
fails validation, the deterministic ranking and analysis remain valid.

## Recommended downstream use

BinderRanker results are best used to allocate downstream resources:

1. retain a diverse set of high-ranked and filter-supported candidates;
2. inspect their interfaces structurally;
3. perform sequence design;
4. run complex-structure prediction;
5. apply simulation or energetic analysis where appropriate;
6. validate experimentally.

Avoid selecting candidates from total score alone. Preserve diversity across
interface modes and investigate candidates whose strengths and weaknesses
suggest complementary design hypotheses.
