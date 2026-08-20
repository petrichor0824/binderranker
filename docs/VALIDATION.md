# BinderRanker Validation

BinderRanker separates software and workflow validation from scientific
validation.

A successful software test, installation smoke test, or BinderRanker score
does not by itself establish biological predictive accuracy.

## 1. Engineering validation

The v0.3 release line is validated at several deterministic boundaries.

### Regression tests

The current v0.3 repository baseline is recorded in
[`V0.3_ROADMAP.md`](V0.3_ROADMAP.md).

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

## 4. Claims not established by v0.3 engineering validation

The v0.3 engineering validation does not establish that:

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
