# BinderRanker Validation

BinderRanker separates software and workflow validation from scientific
validation.

A successful software test, installation smoke test, or BinderRanker score
does not by itself establish biological predictive accuracy.

## 1. Engineering validation

The v0.4 release line is validated at several deterministic boundaries.

### Regression tests

The current release baseline and completed scientific-transparency work are
recorded in
[`POST_V0_3_EXECUTION_ROADMAP.md`](POST_V0_3_EXECUTION_ROADMAP.md).

The full regression suite is run with:

    python -m pytest -q

The suite covers deterministic planning, dataset inspection, workflow
preparation, approval and execution integrity, result parsing, public error
boundaries, CLI behavior, packaged resources, path semantics, and related
release-facing behavior.

### Release asset validation

BinderRanker release engineering builds both:

- a Python Wheel;
- a source distribution (`sdist`).

The release asset verifier checks:

- distribution name and version;
- sdist `CITATION.cff` version agreement with package metadata;
- package summary;
- Python version requirement;
- SPDX license metadata;
- canonical and legacy console entry points;
- packaged LICENSE;
- packaged README;
- the frozen BinderRanker implementation;
- the internal BinderRanker SHA256 manifest;
- five packaged `3c98_small` smoke-test PDB files;
- release `SHA256SUMS.txt`;
- checksum integrity;
- basename-only checksum entries without local `dist/` prefixes.

Run the verifier with:

    python scripts/verify_release_assets.py dist

The verifier is designed to fail when an artifact is modified or when the
release checksum manifest contains invalid paths.

### Clean-Wheel validation

Release candidates are also installed into a new virtual environment outside
the source checkout.

The clean installation verifies that:

- `binderranker` is installed and reports the distribution version;
- the legacy `protein-design-agent` CLI alias remains available for
  compatibility;
- the Python package is imported from the installed environment rather than
  the repository;
- the packaged frozen BinderRanker can be located and integrity-checked;
- the packaged five-PDB smoke-test dataset can be extracted;
- BinderRanker can complete the packaged smoke test outside the repository;
- the v0.4 metric-documentation and scientific-interpretation modules import
  from the installed Wheel and build the complete 20-metric contract;
- the v0.5 scientific-validation package imports from the installed Wheel,
  validates a synthetic SHA256-sealed benchmark bundle outside the checkout,
  computes its evaluation-only fixed-budget BinderRanker/baseline report, and
  builds target-level removal-sensitivity and fixture-only readiness reports;
- the versioned Tool API catalog imports from the installed Wheel, describes
  all eight operations, and keeps provider identity and protected approval or
  execution facts out of untrusted request schemas;
- the trusted Tool runtime imports from the installed Wheel and declares its
  opaque, SHA256-bound, short-lived, atomically single-use authorization
  transport for protected operations;
- offline Chat initializes safely without a model credential;
- compatibility workspace initialization remains functional;
- Doctor can inspect the installed environment.

The packaged execution smoke test can be reproduced from a clean installed
environment with:

    python scripts/verify_installed_wheel_smoke.py

## 2. Smoke-test scope

The packaged `3c98_small` dataset contains five PDB candidates.

It exists for:

- installation validation;
- packaging validation;
- deterministic workflow validation;
- end-to-end smoke testing.

It is not large enough to support formal screening conclusions or scientific
claims about BinderRanker's predictive performance.

BinderRanker analysis scopes therefore distinguish small engineering smoke
tests from larger exploratory or full screening tasks.

See:

- [`SCIENTIFIC_METHOD.md`](SCIENTIFIC_METHOD.md)
- [`RESULT_INTERPRETATION.md`](RESULT_INTERPRETATION.md)

## 3. Scientific validation

Scientific validation is separate from engineering validation.

Evidence that can contribute to scientific validation includes:

- retrospective evaluation on real design campaigns;
- comparison with downstream complex-structure prediction;
- enrichment analysis;
- comparison of prioritized and non-prioritized candidates;
- molecular simulation where scientifically appropriate;
- prospective experimental validation.

BinderRanker should be evaluated as a ranking and triage method within a
defined candidate batch, not as a standalone predictor of affinity,
stability, solubility, or experimental success.

### v0.5 benchmark intake gate

Post-v0.4 development includes a framework-independent benchmark input
contract. The gate validates a SHA256-sealed manifest/CSV bundle before any
performance metric is computed. It requires explicit outcome evidence type,
baseline procedure, BinderRanker provenance, fixed selection budgets,
parameter-selection policy, and outcome-blinding declarations.

The validator rejects incomplete ranks, non-finite scores, non-binary outcomes,
duplicate candidates, campaign inconsistencies, budgets that cannot be compared
across candidate pools, and any target shared by `CALIBRATION` and
`EVALUATION`.

Validated records are immutable and canonically ordered. The validation
summary records separate SHA256 values for the manifest and candidate CSV so
later metric artifacts can identify the exact admitted benchmark contract.

This is engineering validation of scientific benchmark inputs. It does not
establish enrichment, generalization, biological causality, or predictive
accuracy. See [`BENCHMARK_CONTRACT.md`](BENCHMARK_CONTRACT.md).

The downstream fixed-budget evaluator revalidates the sealed bundle before
use, excludes all calibration rows, computes campaign and pooled BinderRanker
and baseline metrics side by side, and represents zero-positive campaign
recall/enrichment as explicitly unavailable. Its immutable report is bound to
the manifest and dataset hashes and marks generalization and causality as not
established. See [`BENCHMARK_METRICS.md`](BENCHMARK_METRICS.md).

The target-sensitivity layer groups repeated evaluation campaigns by target,
reports equal-target distributions, and recomputes the macro target estimate
after removing each defined target once. Zero-positive targets remain explicit
for recall/enrichment, and fewer than two defined targets produces an
unavailable removal range. The range is deterministic sensitivity evidence,
not a confidence interval or significance test. See
[`BENCHMARK_SENSITIVITY.md`](BENCHMARK_SENSITIVITY.md).

The readiness layer requires a strict companion YAML record bound to the exact
manifest and dataset hashes. It records declared data-freeze provenance,
candidate-cohort completeness, outcome/baseline/leakage review, a predeclared
analysis-plan identifier, and evidence limitations. The resulting report
distinguishes `SYNTHETIC_FIXTURE` from `REAL_RETROSPECTIVE`, counts the outcome
structure at target and campaign levels, and exposes only the mathematical
prerequisites required by the implemented descriptive sensitivity methods.

`READY_FOR_SCIENTIFIC_REVIEW` does not mean independently verified, adequately
powered, representative, or performance-positive. The software validates the
structure and hash binding of declarations; an independent reviewer must
verify their truth and choose any justified formal inference method. See
[`BENCHMARK_READINESS.md`](BENCHMARK_READINESS.md).

## 4. Claims not established by v0.4 engineering validation

The v0.4 engineering validation does not establish that:

- a high BinderRanker score guarantees binding;
- a high-ranked backbone will succeed experimentally;
- BinderRanker predicts binding affinity;
- BinderRanker predicts protein stability or solubility;
- BinderRanker replaces AlphaFold or other complex-structure prediction;
- BinderRanker replaces molecular simulation;
- BinderRanker replaces experimental validation.

The validated software claim is narrower:

> BinderRanker provides a deterministic, interpretable, auditable workflow for
> ranking and layered screening of generated protein backbone candidates before
> more expensive downstream evaluation.

## 5. Real-provider smoke testing

Model-assisted features require a configured provider, valid credentials, and
explicit network authorization.

Real-provider smoke testing is a manual release-candidate check rather than a
mandatory offline CI requirement, because CI must not depend on private API
credentials.

Deterministic BinderRanker functionality remains available without a model.
