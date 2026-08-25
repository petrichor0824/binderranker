# BinderRanker

[简体中文](README.zh-CN.md)

**Interpretable Ranking and Layered Screening for Generated Protein Backbone Candidates**

BinderRanker prioritizes generated protein backbone candidates before more
expensive downstream sequence design, structure / complex prediction,
molecular simulation, manual review, and experimental validation.

It addresses a practical intermediate question:

> After generating many candidate backbones, which ones are worth carrying
> forward?

    RFdiffusion / other backbone generators
                    ↓
          candidate backbone PDBs
                    ↓
               BinderRanker
                    ↓
       interpretable multi-metric ranking
          + layered screening
          + failure analysis
                    ↓
          prioritized candidates
                    ↓
    ProteinMPNN / complex prediction / MD / experiments

BinderRanker does not generate backbone candidates itself; it prioritizes an
existing candidate PDB set.

BinderRanker is a **prioritization layer**. A high score or strict-layer pass
is not biological proof.

Current release line: **v0.4.0 — scientific transparency**.

---

## Why BinderRanker?

Backbone generators can produce many plausible candidates, while downstream
evaluation is comparatively expensive. Running every candidate through
sequence design, complex prediction, simulation, manual inspection, or
experiments is often inefficient.

BinderRanker provides a deterministic and auditable way to reduce that search
space. It ranks candidates within the current batch, applies progressively
stricter screening layers, and records the evidence that helped or hurt each
candidate.

The goal is not to declare a universal "best binder", but to identify more
defensible candidates for further investigation under the current target,
dataset, and scoring configuration.

---

## Scientific Method

A BinderRanker run evaluates candidate PDB structures for one defined target,
chain layout, and scoring configuration.

The ranking uses structural evidence including:

- target–binder contact amount and coverage;
- spatial contact span and local orientation;
- contact-field smoothness and contact-map continuity;
- shell sensitivity and steric-risk / clash indicators;
- optional design-region evidence and hotspot diagnostics.

Scores are intended primarily for **relative comparison inside the current
candidate batch**. Scores from unrelated targets or independently normalized
runs should not be treated as directly comparable absolute quality values.

### Morphology-adaptive ranking

BinderRanker combines three complementary interface patterns:

- `score_line` — extended contact patterns;
- `score_plane` — locally planar interface patterns;
- `score_compact` — localized dense contact patches.

Target-dependent morphology weights combine these into
`morphology_adaptive_score`.

When region scoring is disabled:

    final_score_v4 =
        0.85 × morphology_adaptive_score
      + 0.10 × score_safety
      + 0.05 × score_roughness

When region scoring is enabled, the final-score formula additionally includes
`score_region`. `score_hotspot` remains diagnostic rather than an independent
fixed final-score term.

Full definitions: [`SCIENTIFIC_METHOD.md`](docs/SCIENTIFIC_METHOD.md) and
[`METRICS.md`](docs/METRICS.md).

---

## Layered Screening

BinderRanker produces three progressively selective screening layers:

| Layer | Purpose |
|---|---|
| Broad | permissive screening |
| Medium | stronger multi-metric filtering |
| Strict | most selective configured screening |

The layers use quantiles from valid candidates in the current batch. They are
therefore **dynamic, batch-relative filters**, not universal biophysical
thresholds or biological categories.

A candidate outside the strict layer is not automatically unusable.
Failed criteria and threshold gaps should be inspected to understand why it
was filtered.

---

## Outputs and Interpretability

Depending on the run and permitted analysis scope, BinderRanker can expose:

- candidate ranking and component scores;
- broad / medium / strict screening results;
- strengths, weaknesses, failed gates, and threshold gaps;
- deterministic result summaries with a sealed scientific-interpretation
  contract;
- a human-readable deterministic analysis report with adjacent-rank score
  differences;
- configuration, execution, and file provenance;
- optional evidence-bound model explanations.

Deterministic calculations remain authoritative. Model-generated prose cannot
change scores, screening membership, execution evidence, or provenance.

See [`RESULT_INTERPRETATION.md`](docs/RESULT_INTERPRETATION.md).

---

## Analysis-Scope Guardrails

| Candidate count | Scope | Permitted interpretation |
|---:|---|---|
| 1–29 | `SMOKE_TEST_ONLY` | engineering / installation validation only |
| 30–199 | `EXPLORATORY` | exploratory within-batch comparison |
| 200+ | `FULL_DATASET_ANALYSIS` | full workflow interpretation permitted |

These are safeguards against overinterpretation, not proofs of statistical
power or dataset representativeness.

The packaged five-PDB example is an **engineering smoke test**, not scientific
validation of biological predictive performance.

---

## Quick Start

### Requirements

- Python 3.10+
- Linux, WSL2, or another environment capable of running the scientific
  dependencies
- an OpenAI-compatible model endpoint only for optional Agent features or
  model-generated explanations

The deterministic ranking and analysis workflow does not inherently require a
model API key.

### Install

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install ./binderranker-0.4.0-py3-none-any.whl

Verify:

    binderranker --help
    binderranker doctor

### Create a workspace and smoke-test dataset

    binderranker init --destination ~/binderranker-workspace
    cd ~/binderranker-workspace
    binderranker extract-sample --destination data/3c98_small
    binderranker doctor

The packaged sample contains five candidate PDBs and is intended only for
packaging, installation, and end-to-end smoke testing.

### Development installation

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
    python -m pytest -q

---

## BinderRanker Agent

**BinderRanker Agent is an optional interaction layer, not the scientific
ranking algorithm.**

It can assist with natural-language task preparation, guided workflow use, and
evidence-bound result explanation. BinderRanker Core remains responsible for
deterministic preparation, approval, execution guards, provenance, and result
analysis.

Start it with:

    binderranker chat

Validate a configured model profile without making a network request:

    binderranker validate-model-config \
      --config configs/models/deepseek.local.yaml \
      --profile deepseek_flash

API keys should be supplied through configured environment variables, not
stored in YAML, Git history, logs, screenshots, or shared run bundles.

---

## Deterministic Workflow

BinderRanker separates preparation, review, approval, execution, and analysis.

Key properties:

- preparation and approval do not execute the ranker;
- approval freezes reviewed configuration and critical-file fingerprints;
- approved bundles cannot be silently edited before execution;
- one approval can be consumed only once;
- local execution uses fixed argument lists rather than model-written shell;
- deterministic evidence remains authoritative over generated prose.

Common commands:

| Command | Purpose |
|---|---|
| `prepare` | inspect, normalize, validate, and prepare a run |
| `approve-run` | freeze reviewed configuration and critical files |
| `execute-run` | consume a valid approval and run BinderRanker |
| `analyze-run` | build deterministic result evidence |
| `run-status` | inspect lifecycle state |
| `chat` | use BinderRanker Agent |

Use `binderranker <command> --help` for exact options.

---

## Reproducibility and Provenance

Run bundles preserve structured task information, dataset inspection evidence,
normalized-input fingerprints, workflow plans, approval records, execution
manifests, output fingerprints, and deterministic analysis artifacts.

Completed or consumed bundles should be treated as immutable audit records.

The packaged BinderRanker Engine is distributed as a frozen resource and
verified before planning or execution.

---

## Scientific Scope and Limitations

BinderRanker must **not** be interpreted as directly predicting:

- experimental binding success or binding affinity;
- thermodynamic / folding stability or solubility;
- universal binder quality or experimental success probability.

It does not replace backbone generation, sequence design, structure / complex
prediction, molecular dynamics, manual structural inspection, or experimental
validation.

Preferred interpretations include **higher-ranked backbone**, **prioritized
candidate**, and **candidate worth further investigation**.

Claims such as *best binder*, *highest-affinity candidate*, *guaranteed
binder*, or *validated hit* require independent downstream evidence.

---

## Architecture

    Direct CLI / Python ─────────┐
    Built-in Agent (optional) ───┼──> BinderRanker Tool API
    External Agents (optional) ──┘              ↓
                                      BinderRanker Core
                                                ↓
                                      BinderRanker Engine

- **Engine** — scientific ranking and layered screening.
- **Core** — deterministic workflow, safety, provenance, parsing, and analysis.
- **Tool API** — stable controlled interface for direct use and integrations.
- **Agent** — optional conversational interaction.

BinderRanker remains the same scientific capability regardless of the access
path. Agent interfaces improve accessibility and integration; they do not own
or redefine scientific behavior.

The internal Python namespace remains `protein_design_agent` for backward
compatibility. It is an implementation detail, not the public project
identity.

---

## Validation Status

Engineering validation includes regression tests, execution-integrity checks,
resource verification, provenance checks, installation tests, and smoke-test
workflows. These establish software and workflow correctness; they do **not**
establish biological predictive accuracy.

Scientific validation requires separate downstream evidence such as
retrospective design-campaign comparison, complex-prediction evaluation,
enrichment analysis, or prospective experimental validation.

---

## Documentation

- [Scientific method](docs/SCIENTIFIC_METHOD.md)
- [Metric reference](docs/METRICS.md)
- [Result interpretation](docs/RESULT_INTERPRETATION.md)
- [Validation](docs/VALIDATION.md)
- [Public identity and claim policy](docs/PUBLIC_IDENTITY.md)
- [v0.3 architecture](docs/V0.3_ARCHITECTURE.md)
- [Architecture evolution and development principles](docs/ARCHITECTURE_EVOLUTION.md)
- [Post-v0.3 execution roadmap](docs/POST_V0_3_EXECUTION_ROADMAP.md)
- [Historical v0.3 roadmap](docs/V0.3_ROADMAP.md)
- [Improvement backlog](docs/IMPROVEMENT_BACKLOG.md)

Historical v0.2 planning documentation is retained for traceability.

---

## Roadmap

Future work prioritizes scientific ranking and screening, reproducibility and
validation, stable Tool/API interfaces, and then optional external-Agent
compatibility. Agent framework expansion is not an independent product goal.

See [`docs/POST_V0_3_EXECUTION_ROADMAP.md`](docs/POST_V0_3_EXECUTION_ROADMAP.md)
and
[`docs/IMPROVEMENT_BACKLOG.md`](docs/IMPROVEMENT_BACKLOG.md).

---

## Citation, Contributions, and License

Contribution guidelines are available in [`CONTRIBUTING.md`](CONTRIBUTING.md).

Machine-readable citation metadata is provided in
[`CITATION.cff`](CITATION.cff). GitHub's **Cite this repository** feature can
use this metadata directly.

Primary software author:

- **Zheng Hu**
- ORCID: [0009-0006-7368-613X](https://orcid.org/0009-0006-7368-613X)

When reporting results, cite the specific BinderRanker software version used in
the analysis.

Copyright 2026 BinderRanker contributors.

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
