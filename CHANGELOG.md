# Changelog

All notable changes to BinderRanker are documented here.

Historical entries preserve the project names, CLI commands, and terminology
used by the corresponding release.

## 0.3.0 - 2026-08-20

BinderRanker v0.3.0 establishes BinderRanker as the public project identity and
turns the ranking workflow into a release-ready, auditable software package.

### Added

- Canonical `binderranker` CLI while retaining `protein-design-agent` as a
  compatibility alias.
- Full Chinese documentation in `README.zh-CN.md`.
- Public scientific-method, metric, result-interpretation, architecture, and
  claim-boundary documentation.
- Deterministic BinderRanker Tool API for preparation, information provision,
  dataset inspection, review, approval, execution, and result analysis.
- Release asset verification for Wheel, sdist, packaged resources, metadata,
  entry points, and SHA256 checksums.
- Cross-platform path-semantics protection that rejects foreign absolute paths
  instead of silently reinterpreting them.
- Improved Doctor onboarding guidance and `plan-mock` documentation.
- Clean handling of stdin EOF in interactive Chat.
- Packaged `3c98_small` installation and end-to-end smoke-test fixture.

### Changed

- Public project identity migrated from Protein Design Agent to BinderRanker.
- BinderRanker is positioned primarily as an interpretable ranking and layered
  screening system for generated protein backbone candidates.
- The Agent is treated as an optional interaction layer rather than the
  scientific core.
- New-user documentation uses the canonical `binderranker` command.
- Release packaging now uses modern SPDX / PEP 639 license metadata.
- CI builds both Wheel and sdist and tests the canonical CLI from a clean
  installation.

### Compatibility

- The Python namespace remains `protein_design_agent`.
- The `protein-design-agent` CLI remains available as a legacy compatibility
  alias.
- Existing `.protein-design-agent` workspace paths remain supported.
- Historical documentation retains terminology used by earlier development
  lines where required for traceability.

### Validation

- The v0.3 engineering validation includes the full regression suite,
  deterministic integrity checks, release-asset auditing, clean-Wheel
  installation, packaged-resource verification, and offline smoke testing.
- Engineering validation does not establish biological predictive accuracy.
- Scientific validation remains a separate downstream activity requiring
  evidence from real design campaigns, structure prediction, enrichment
  analysis, simulation where appropriate, and/or experiment.

### Scientific boundaries

- BinderRanker scores prioritize candidates within a batch.
- A high score is not proof of binding or experimental success.
- BinderRanker does not claim to predict affinity, stability, or solubility.
- BinderRanker does not replace complex-structure prediction, molecular
  simulation, or experimental validation.

## 0.2.0 - 2026-07-31

This release was published under the historical **Protein Design Agent**
project identity. Historical package and CLI terminology is retained here for
traceability.

### Added

- Multi-dataset discovery and evidence-backed dataset grouping.
- Isolated task creation and navigation for grouped design tasks.
- Default Chat workspace initialization and reusable initialized workspaces.
- Packaged `3c98_small` sample extraction and Wheel smoke testing.
- Model readiness reporting, setup guidance, and model-assisted status
  narration.
- Deterministic ranking previews after execution.
- Semantic plan inspection and correction support during pending actions.
- Policy-aware result pools and provenance reporting.
- Scientific-method, metric-reference, and result-interpretation
  documentation.
- Public-command verification for documented CLI workflows.

### Changed

- Improved public positioning and quick-start documentation.
- Included project documentation in the source distribution.
- Made installed-Wheel smoke verification portable.
- Automatically inspected datasets after task intake.
- Separated general questions from planning interactions.
- Preserved deterministic analysis when model-generated explanation was
  unavailable or invalid.

### Reliability and safety

- Added failure evidence to public error guidance.
- Retried invalid model explanations before falling back.
- Kept deterministic analysis authoritative when explanation generation failed.
- Improved isolation between grouped tasks, approvals, and task-specific
  bundle paths.

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
