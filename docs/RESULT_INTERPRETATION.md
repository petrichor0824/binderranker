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
