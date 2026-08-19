# Changelog

All notable changes to BinderRanker are documented here.

Historical entries preserve the project names, CLI commands, and terminology
used by the corresponding release.

## 0.1.0 - 2026-07-28

First public beta release.

Historical note: this release predates the BinderRanker public rebranding, so
its original CLI commands are retained below for traceability.

### Added

- Natural-language planning with deterministic structured requests.
- Resumable conversational planning sessions.
- Read-only PDB dataset inspection and auditable parameter advice.
- Target and binder chain normalization.
- Deterministic BinderRanker workflow preparation.
- Integrity-bound human approval.
- One-time approved local execution with shell disabled.
- Read-only run lifecycle status reporting.
- Deterministic result parsing and failure analysis.
- Evidence-bound model explanations.
- Small-sample interpretation guardrails.
- Safe workspace initialization through `protein-design-agent init`.
- Read-only environment diagnosis through `protein-design-agent doctor`.
- DeepSeek OpenAI-compatible provider configuration.
- Frozen BinderRanker v0.1-expert packaged with SHA256 verification.
- Python 3.10, 3.11, and 3.12 continuous integration.
- Clean wheel installation and packaged-resource CI checks.

### Safety boundaries

- Planning does not execute BinderRanker.
- Approval does not execute BinderRanker.
- Approved files and configuration are integrity-bound.
- An approval can be consumed only once.
- The model cannot directly execute arbitrary shell commands.
- Smoke-test datasets cannot produce formal design recommendations.
- Deterministic evidence remains authoritative over generated prose.

### Current limitations

- Local execution only.
- No graphical or web interface.
- No cluster execution backend.
- No plugin marketplace or database.
- BinderRanker metrics still require broader experimental validation.
