# Protein Design Agent

A safety-oriented, configuration-driven agent for protein-design dataset inspection, BinderRanker planning, controlled execution, and auditable result explanation.

Current release: **0.1.0 Public Beta**

## What this project does

Protein Design Agent turns a natural-language protein-design request into a structured and reviewable workflow:

1. inspect a PDB dataset;
2. normalize target and binder chains;
3. validate project configuration;
4. generate a deterministic BinderRanker plan;
5. freeze configuration and critical-file hashes during approval;
6. execute an approved plan once;
7. parse and analyze Ranker outputs;
8. generate a controlled, evidence-bound explanation.

The language model is used for natural-language understanding and constrained explanation. It does not directly generate arbitrary shell commands for automatic execution.

## Core safety model

The workflow separates planning, approval, execution, analysis, and explanation.

- Planning does not execute BinderRanker.
- Approval does not execute BinderRanker.
- Approval freezes configuration and critical-file fingerprints.
- Approved bundles cannot be silently edited before execution.
- One approval can be consumed only once.
- Local execution uses a fixed argument list with `shell=False`.
- Deterministic evidence remains authoritative over model-generated prose.
- API keys are never written into generated model YAML files.
- `doctor` and `init` do not access the network.

## Analysis-scope guardrails

Dataset size determines the permitted interpretation scope:

| Candidate count | Scope | Intended use |
|---:|---|---|
| fewer than 30 | `SMOKE_TEST_ONLY` | engineering validation only |
| 30–199 | `EXPLORATORY` | exploratory comparison |
| 200 or more | `FULL_DATASET_ANALYSIS` | full dataset analysis |

These boundaries are engineering guardrails, not universal statistical laws.

For `SMOKE_TEST_ONLY` runs:

- formal candidate recommendations are disabled;
- broad, medium, and strict reporting pools are suppressed;
- threshold-based pass/fail interpretation is disabled;
- only small-sample engineering observations are permitted.

## Requirements

- Python 3.10 or newer
- Linux, WSL2, or another environment capable of running the scientific dependencies
- an OpenAI-compatible model endpoint is optional for natural-language parsing and controlled explanation
- deterministic planning and validation do not require a model API key

## Development installation

Clone the repository, enter the project directory, and create a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

Verify the installation:

    protein-design-agent doctor

Run the test suite:

    pytest -q

## Create a user workspace

Create a portable workspace outside the source repository:

    protein-design-agent init \
      --destination ~/protein-design-workspace

Enter it:

    cd ~/protein-design-workspace

The generated structure is:

    protein-design-workspace/
    ├── configs/
    │   └── models/
    │       └── deepseek.local.yaml
    ├── data/
    ├── runs/
    ├── .env.example
    ├── .gitignore
    └── QUICKSTART.md

Existing managed files are never overwritten.

## Configure DeepSeek

The generated profile uses an OpenAI-compatible DeepSeek endpoint.

Set the API key in the current shell:

    export DEEPSEEK_API_KEY="your-api-key"

Do not place the real key in YAML, Git, screenshots, logs, or shared run bundles.

Validate the model profile without contacting the network:

    protein-design-agent validate-model-config \
      --config configs/models/deepseek.local.yaml \
      --profile deepseek_flash

Run the full local environment diagnosis:

    protein-design-agent doctor \
      --model-config configs/models/deepseek.local.yaml \
      --profile deepseek_flash

`doctor` reports only whether the environment variable exists. It never displays the key value.

## Start the conversational workflow

View the currently supported options:

    protein-design-agent chat --help

The conversational controller may:

- ask for missing target/binder information;
- inspect input PDB files in read-only mode;
- propose dataset-derived parameters;
- require explicit confirmation before adopting file-derived advice;
- answer safety questions deterministically;
- prepare an auditable run bundle;
- request explicit confirmation before high-risk actions.

## Deterministic CLI lifecycle

The public CLI contains commands for each workflow stage:

| Command | Purpose |
|---|---|
| `init` | create a portable workspace |
| `doctor` | diagnose installation and workspace state |
| `validate-model-config` | validate a model provider profile without network access |
| `plan` | convert a structured request into a deterministic plan |
| `plan-mock` | test planning with the mock provider |
| `materialize-plan` | write a validated plan into a run bundle |
| `prepare-session` | create a resumable planning session |
| `prepare` | inspect, normalize, validate, and prepare a reviewable run |
| `approve-run` | freeze configuration and critical-file fingerprints |
| `execute-run` | consume a valid one-time approval and execute locally |
| `run-status` | report the current lifecycle state without modification |
| `analyze-run` | parse outputs and build deterministic evidence |
| `explain-run` | generate an evidence-bound model explanation |
| `chat` | operate the natural-language controller |

Use `<command> --help` for the exact options supported by the installed version.

## Frozen BinderRanker

Version `v0.1-expert` is distributed as an immutable package resource.

Expected SHA256:

    92d6c02f8ca8f500917f5fa61676fe93a0acdbb59d49f2cac0c7a74a4a553ed7

The digest is checked before planning or execution. A mismatch stops the workflow.

The repository-level `algorithms/` copy remains the human-auditable source. The package-level resource is included in the wheel so that installed releases do not depend on the source repository path.

## Example data

The repository includes a five-candidate real PDB dataset:

    sample_data/real/3c98_small/

It is intentionally a smoke-test dataset. Results from this dataset must not be presented as formal screening conclusions or final design recommendations.

## Run bundles and auditability

Run bundles preserve stage-specific manifests and evidence, including:

- structured user request;
- explicit-field provenance;
- dataset inspection evidence;
- normalized input fingerprints;
- generated workflow plan;
- approval digest;
- execution manifest;
- output fingerprints;
- deterministic analysis;
- controlled explanation evidence.

Completed or consumed bundles should be treated as immutable audit records.

## Current limitations

Version 0.1.0 currently focuses on a tested local BinderRanker workflow.

Not yet included:

- graphical user interface;
- web service;
- cluster execution backend;
- plugin marketplace;
- database or account system;
- universal support for arbitrary protein-design tools;
- formal experimental validation of every Ranker metric.

## Development status

The deterministic scientific and safety core is frozen for the 0.1 release line. Public Beta work focuses on packaging, documentation, clean-environment installation, and continuous integration.

## License

Copyright 2026 the Protein Design Agent contributors.

Licensed under the Apache License, Version 2.0. See `LICENSE`.
