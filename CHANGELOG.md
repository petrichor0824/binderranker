# Changelog

All notable changes to BinderRanker are documented here.

Historical entries preserve the project names, CLI commands, and terminology
used by the corresponding release.

## Unreleased

### Added

- Added a versioned, machine-readable catalog for all eight public BinderRanker
  Tool operations, with deterministic input/output JSON Schemas, explicit
  side-effect classes, host-local path semantics, and trusted host-field
  declarations for future HTTP, MCP, workflow, and external-Agent adapters.
- Added strict, frozen adapter request models that reject unknown fields and
  exclude provider identity, approval identity, approval confirmation,
  smoke-test acknowledgement, approval notes, and execution confirmation from
  untrusted model-authored arguments.
- Added a host-owned trusted authorization broker and protected Tool runtime.
  Its opaque capabilities require an independent user confirmation, bind one
  action and task plus the reviewed manifest SHA256, expire after five minutes
  by default, and can be consumed atomically only once.
- Added a versioned adapter error envelope with stable request, authorization,
  domain-state, scientific-validity, execution, and internal error codes.
  Successful Tool result models remain unchanged; failure envelopes never
  publish raw exception text, host paths, tracebacks, credentials, capability
  identifiers, subprocess stderr, or validation inputs.
- Added the first concrete external adapter as an optional local MCP server
  using the official `mcp>=2,<3` SDK. It exposes only current-plan, task-status,
  and deterministic dataset-inspection operations over `stdio`.
- Added a workspace-scoped read-only adapter core that accepts managed task
  names instead of paths and projects Tool results into explicit structured
  views without host-local paths, stored free-form request text, or raw warning
  and exception details.
- Added a machine-readable MCP capability resource that explicitly declares
  deferred mutation, approval, execution, and analysis-write operations plus
  the unchanged `SCIENTIFIC_VALIDATION_PENDING` evidence boundary.
- Added a sealed benchmark-bundle contract for v0.5 scientific-validation
  infrastructure, with explicit outcome, baseline, Ranker provenance,
  parameter-selection, blinding, fixed-budget, and target-split declarations.
- Added shared deterministic validation for benchmark SHA256 integrity,
  candidate identity, complete BinderRanker/baseline ranks, finite scores,
  binary outcomes, comparable budgets, and calibration/evaluation target
  isolation. This gate validates benchmark inputs but does not make performance
  or biological claims.
- Added immutable fixed-budget benchmark reports that compare BinderRanker and
  the manifest-declared baseline campaign by campaign and in count-pooled
  summaries, using evaluation rows only.
- Added explicit `AVAILABLE` / `UNAVAILABLE` states for recall and enrichment
  when an individual campaign has no positive outcomes, plus report-level
  retrospective claim boundaries and sealed-input identity checks.
- Added deterministic target-level benchmark sensitivity reports that pool
  repeated campaigns within each target, preserve zero-positive target states,
  summarize cross-target direction and range, and perform leave-one-target-out
  removal analysis without presenting it as a confidence interval.
- Added a strict benchmark-readiness companion checklist bound to the sealed
  manifest and dataset hashes, with declared data freeze, cohort completeness,
  scientific review, analysis plan, evidence limitations, and timezone-aware
  provenance records.
- Added deterministic readiness reports that distinguish real-retrospective
  declarations from synthetic fixtures, expose target/campaign outcome
  structure and method prerequisites, and keep independent verification,
  performance benefit, and formal inference explicitly unestablished.

### Validation

- Added Tool contract regressions for complete inventory, stable serialization,
  side-effect and authorization classification, strict request validation,
  host-field isolation, schema completeness, and existing Tool result-model
  import compatibility.
- Added authorization regressions covering absent confirmation, opaque
  transport, host-fact injection, replay, concurrency, expiry, cross-broker,
  wrong-action, wrong-task, changed-review-resource, and unvalidated-request
  rejection.
- Added adapter-boundary regressions covering strict schema failures, stable
  classifications, unknown operations, authorization failures, scientific
  invalidity, execution failure, unexpected exceptions, information
  sanitization, success-result compatibility, and no blind automatic retry.
- Added read-only adapter and in-memory MCP regressions for tool discovery,
  annotations, workspace/traversal/symlink isolation, path-free projections,
  structured success output, MCP `isError` failures, capability discovery, and
  the absence of approval and execution tools.
- Added a clean installed-Wheel MCP smoke test after installing the optional
  extra, while retaining a base-Wheel smoke assertion that the adapter core is
  importable without the MCP dependency.
- Extended the clean installed-Wheel smoke test to build the Tool API catalog
  and verify that protected authorization fields are absent from its untrusted
  request schemas outside the source checkout.
- Extended the clean installed-Wheel smoke test to import the shared adapter
  error boundary and verify its schema, stable code inventory, sanitized
  unknown-operation response, and non-retryable policy.
- Extended the clean installed-Wheel smoke test to import the v0.5 scientific
  validation package, validate a synthetic sealed benchmark bundle, and
  compute fixed-budget BinderRanker/baseline metrics, target sensitivity, and
  fixture-only readiness boundaries outside the source checkout.

## 0.4.0 - 2026-08-25

BinderRanker v0.4.0 is a scientific-transparency release. It makes empirical
ranking arithmetic, interpretation boundaries, and deterministic analysis
artifacts directly auditable without changing the frozen BinderRanker scoring
or screening algorithm.

### Added

- Added a shared, model-independent primary-score decomposition layer that
  exposes audited weights, per-candidate weighted contributions, reconstructed
  scores, and reconstruction errors in deterministic result summaries.
- Added explicit `AVAILABLE` / `UNAVAILABLE` decomposition semantics so legacy
  reports remain readable without inferring missing scientific evidence.
- Added a deterministic, human-readable Markdown analysis report that combines
  validated rankings, public screening status, score contributions, and
  policy-permitted failed-gate evidence without requiring a model or network.
- Added SHA256 sealing and artifact resolution for the deterministic report,
  while preserving support for analysis manifests created before the report
  existed.
- Added shared adjacent-candidate score comparisons that reconstruct each
  recorded rank gap from direct-primary contribution deltas and identify the
  largest positive and negative arithmetic terms.
- Added a sealed scientific-interpretation contract that exposes run-specific
  metric direction and role, batch-relative score and threshold boundaries,
  prohibited claims, and required downstream validation.

### Changed

- Aligned active architecture and roadmap documentation around BinderRanker as
  a scientific ranking and screening capability; Agent interfaces are now
  consistently documented as optional access and integration layers.
- Optional model explanations now reuse the same deterministic report-context
  and score-decomposition logic as offline result analysis.
- `SMOKE_TEST_ONLY` reports now suppress unstable dynamic-threshold details;
  exploratory and full-dataset reports retain numerical gap evidence with
  explicit batch-relative interpretation boundaries.
- Deterministic Markdown reports now explain adjacent rank differences without
  presenting contribution deltas as causal, energetic, or biological effects.
- Deterministic reports and optional evidence-bound explanations now validate
  and reuse the interpretation contract stored in the result summary.
- Result-summary and completed-analysis loaders now accept only documented
  artifact schema generations, preserve known legacy generations, and reject
  unknown or incomplete current-generation artifacts.

### Fixed

- Derived result-summary loading now rejects NaN and infinity in candidate
  scores, component scores, key metrics, primary-score weights, and dynamic
  thresholds, including explicit and legacy analysis paths.

### Validation

- The clean installed-Wheel smoke test now imports the metric-documentation and
  scientific-interpretation modules, builds the 20-metric run contract, and
  verifies that these v0.4 modules do not depend on a source checkout.
- Release-asset verification now requires the sdist citation version to match
  the Wheel/sdist package metadata.

## 0.3.1 - 2026-08-21

BinderRanker v0.3.1 is a stabilization release that strengthens scientific
result semantics, installed-package verification, cross-platform reliability,
and first-workflow usability without changing the frozen scoring algorithm.

### Added

- A shared scientific-result validator for candidate identity, required output
  schema, finite scores, and rank/score consistency.
- State-aware first-workflow guidance for empty Chat tasks, including explicit
  automatic-workspace initialization status, real-data intake, and the
  packaged engineering smoke path.
- Platform-specific secure API Key setup guidance for Windows PowerShell and
  POSIX shells.
- Windows / Python 3.12 CI coverage for the full regression suite and Doctor.
- Read-only Chat startup recovery summaries reconstructed from deterministic
  Bundle state, explicit planning provenance, and pending confirmations.
- A deterministic user-language layer for task stages, component statuses,
  analysis scopes, pending actions, and task lifecycle states.
- Regression coverage for zero-valid-candidate runs, missing binder chains,
  non-finite scores, malformed ranking output, and unchanged valid rankings.

### Changed

- Local execution now distinguishes a zero process exit code from scientific
  success and records semantic validation evidence before `COMPLETED`.
- Installed-Wheel smoke verification now normalizes the packaged concatenated
  sample and requires five scientifically valid candidates instead of only
  checking that output files exist.
- Public CLI and Chat error/status views now present plain-language progress
  while keeping internal state-machine values in deterministic records and
  model context.
- Error fallbacks use the recorded task stage to recommend one safe next step.
- Confirmation prompts now use one compact format, accept explicit “继续”
  language, and avoid repeating the full proposal after status or help queries.
- Approval and execution remain separate confirmations; deterministic result
  analysis remains read-only and does not gain an extra confirmation step.

### Fixed

- Result parsing and downstream analysis reject `NaN`, positive infinity,
  negative infinity, malformed rankings, and candidate-level computation
  failures rather than silently accepting them as successful output.
- Published Bundle metadata now relocates JSON-escaped Windows staging paths
  as well as native and POSIX path forms.
- Generated workspace guidance now includes secure instructions for both
  Windows and POSIX users.
- CLI help payload examples and analysis-manifest tests are portable across
  Windows and POSIX path semantics.
- Public error facts preserve their business meaning without displaying
  internal state constants such as `READY_FOR_REVIEW`.
- Frozen Ranker resources retain LF line endings on Windows checkouts, keeping
  their audited SHA256 values stable across platforms.
- CLI entry points switch redirected standard streams to UTF-8 before emitting
  localized output, including on legacy Windows code pages.

### Validation

- The full regression suite, clean Wheel/sdist build, release-asset checksum
  verification, clean-environment Wheel installation, and installed-package
  five-candidate scientific smoke test are required release gates.
- Platform-dependent POSIX path and symlink-containment tests remain covered by
  the Linux CI matrix when the local Windows environment intentionally skips
  them.

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
