# BinderRanker Post-v0.3 Execution Roadmap

> Status: living implementation roadmap
>
> Primary branch at roadmap creation: `feat/v0.3-stabilization`
>
> Read first: `ARCHITECTURE_EVOLUTION.md`
> Detailed deferred items remain tracked in `IMPROVEMENT_BACKLOG.md`.

---

## 1. Purpose

This roadmap converts BinderRanker's post-v0.3 architectural direction into an execution plan suitable for long-running Codex-assisted development.

It is intentionally stricter than a feature list.

Each phase defines:

- objective;
- rationale;
- scope;
- non-goals;
- likely code areas;
- required tests;
- acceptance criteria;
- stop/review conditions.

Codex may update completion status and add discovered issues, but must not silently change the architectural principles defined in `ARCHITECTURE_EVOLUTION.md`.

The governing principle is:

> BinderRanker is a scientific ranking and screening capability. Agent
> interfaces are optional interaction layers used to improve accessibility and
> integration, not the core product.

After v0.3.1, workstreams are prioritized in this order:

1. scientific ranking and screening capability;
2. reproducibility and validation;
3. stable Tool/API interfaces;
4. external Agent ecosystem compatibility.

The numbered workstreams below describe bounded bodies of work and their
dependencies; their numeric labels do not override this priority order.
Generic chatbot capabilities, general-purpose Agent infrastructure, and
memory/personality/planning expansion are not roadmap goals unless they
directly improve BinderRanker usability.

---

## 2. Current repository baseline

The active release-cut branch represents BinderRanker v0.4.0 after completing
the scientific-transparency implementation and artifact-contract stabilization.

### Current product facts

- package: `binderranker`
- current release-cut version: `0.4.0`
- Python: `>=3.10`
- canonical CLI: `binderranker`
- compatibility CLI: `protein-design-agent`
- Python namespace: `protein_design_agent`
- no `pydantic-ai` dependency is currently present
- `pydantic` v2 is present
- BinderRanker Agent remains optional
- deterministic ranking and analysis do not inherently require a model API

### Current integration seam

`src/protein_design_agent/agent/tool_api.py` already exposes:

- `prepare_task`
- `provide_information`
- `inspect_dataset`
- `get_current_plan`
- `get_task_status`
- `request_approval`
- `execute_ranker`
- `analyze_results`

This is the starting point for external Agent compatibility.

### Current CI baseline

The repository CI currently includes:

- Ubuntu / Python 3.10
- Ubuntu / Python 3.11
- Ubuntu / Python 3.12
- Windows / Python 3.12
- package build
- release-asset verification
- clean-wheel installation
- CLI entry-point checks
- frozen Ranker verification
- installed-wheel smoke workflow
- clean workspace initialization / Doctor checks

The stabilization branch has also added Windows line-ending and UTF-8 output hardening.

---

## 3. Versioning policy

Do not create patch/minor versions merely to reflect every internal phase.

Use SemVer intent:

### v0.3.1 — stabilization patch

Only compatible fixes to the already released v0.3 contract:

- release reliability;
- cross-platform behavior;
- clean-install correctness;
- user-facing error recovery;
- critical built-in Agent closed-loop fixes;
- semantic smoke-test correctness;
- provider failure recovery where it is clearly a bug.

Do not put a major Agent redesign or new ecosystem adapter into v0.3.1.

### v0.4.0 — scientific capability and interface hardening

The first minor release after stabilization should prioritize scientific
capability, reproducibility/validation, and stable Tool/API contracts.

The supported access modes may be documented and tested without making Agent
integration the product identity or a release gate:

1. offline deterministic use;
2. built-in reference Agent;
3. optional external-Agent interoperability through the same Tool API.

An external adapter is included only when the higher-priority scientific and
interface work is ready and a current ecosystem review justifies it. MCP is a
candidate, not a predetermined architecture direction.

### v0.5.0 — scientific validation / benchmark infrastructure

Focus on evidence that the ranking method enriches useful downstream candidates.

### v0.6+ — broader adapters/integrations

Additional external Agent adapters, downstream result ingestion, or scientific workflow integrations after interfaces are stable.

### v0.9 — pre-1.0 hardening

Stable schemas, reproducibility review, documentation consolidation, deprecation cleanup, validation maturity.

### v1.0

A stable scientific software contract with documented interfaces, reproducibility, validation evidence, and release discipline.

---

# Phase 0 — Reconcile the actual repository before further large changes

## Objective

Establish a trustworthy snapshot of the current code after recent stabilization/CI work.

## Required actions

Codex must inspect, not assume:

- `README.md`
- `README.zh-CN.md`
- `CHANGELOG.md`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `docs/PUBLIC_IDENTITY.md`
- `docs/SCIENTIFIC_METHOD.md`
- `docs/METRICS.md`
- `docs/RESULT_INTERPRETATION.md`
- `docs/V0.3_ARCHITECTURE.md`
- `docs/V0.3_ROADMAP.md`
- `docs/V0.3_STABILIZATION_PLAN.md`
- `docs/IMPROVEMENT_BACKLOG.md`
- `src/protein_design_agent/agent/tool_api.py`
- built-in Chat/session modules
- approval/execution/provenance modules
- relevant tests
- release verification scripts.

## Architecture audit classification

Classify relevant components as:

- `KEEP`
- `KEEP / EXTRACT`
- `REFERENCE-ONLY`
- `REPLACE ONLY IF JUSTIFIED`
- `DEPRECATE AFTER PARITY`
- `DEFER`

The audit must explicitly answer:

1. Which modules are scientific Engine logic?
2. Which modules are deterministic Core/domain safety?
3. Which modules are stable Tool API/application services?
4. Which modules are generic Harness-like infrastructure?
5. Which modules are built-in reference Agent UX?
6. Which current docs contradict the new three-mode strategy?
7. Which tests represent domain invariants vs legacy implementation details?

## No-code gate

Do not begin broad implementation until this audit is written.

Small CI-only emergency fixes are exempt only if clearly isolated.

## Acceptance criteria

- repository state documented;
- contradictions identified;
- no speculative rewrite proposed;
- owner can review the audit independently.

---

# Phase 1 — Finish v0.3.1 stabilization

## Objective

Make the released v0.3 contract reliable across supported environments without expanding architectural scope.

## Workstream 1A — CI root-cause closure

### Requirements

For every remaining failing CI job:

- identify the first real failing step;
- retrieve complete failure evidence;
- distinguish primary vs secondary failure;
- classify as application/test/package/cross-platform/CI/external;
- reproduce locally when feasible;
- add regression coverage for the behavior category;
- avoid runner-specific business-logic special cases.

### Specific existing cross-platform fixes to preserve

- frozen Ranker resources must retain stable LF byte representation for hash verification;
- redirected public CLI output must remain UTF-8 safe on legacy Windows code pages.

Do not repeatedly rewrite those areas unless current failure evidence proves they remain faulty.

### Acceptance

CI fully green across all configured jobs.

---

## Workstream 1B — semantic installed-wheel smoke correctness

Verify whether the current installed-wheel smoke test can falsely pass when the Ranker processes zero valid candidates.

Required invariant:

> A release smoke test must prove semantically meaningful processing, not merely that output files were created.

Investigate:

- requested chain absent from all candidates;
- zero valid candidates;
- non-finite candidate scores;
- malformed/empty ranking output.

If confirmed:

- make the scientific execution boundary fail clearly for invalid all-candidate cases where appropriate;
- make installed-wheel smoke assert expected candidate count and finite outputs;
- where fixture behavior is stable, assert a known semantic relation/rank without overfitting to incidental file formatting.

Do not introduce a special case for the sample by filename.

---

## Workstream 1C — model-provider empty-content recovery

Observed real-user failure class:

- provider returns HTTP success;
- reasoning/output budget is consumed;
- formal answer content is empty/unusable.

Required behavior:

- detect empty/invalid structured result;
- use bounded retry/repair if safe;
- expose actionable public error if still unavailable;
- preserve deterministic results;
- never mark deterministic analysis as failed merely because optional model explanation failed.

Keep this change compatible and provider-agnostic where possible.

---

## Workstream 1D — built-in Agent closed-loop stabilization only

The current stabilization branch already improves:

- first workflow;
- workspace guidance;
- recovery summary;
- error translation;
- compact confirmations.

Finish only defects that prevent a simple closed loop.

Do not implement:

- universal memory;
- multi-agent orchestration;
- scheduler;
- generic sandbox;
- complex general planner;
- broad new intent taxonomy.

### Built-in Agent acceptance scenario

A clean user should be able to:

1. install package;
2. enter Chat;
3. understand whether workspace was initialized;
4. use packaged smoke data or provide real PDB input;
5. inspect data;
6. provide missing target information;
7. review plan;
8. approve;
9. explicitly confirm execution;
10. execute Ranker;
11. run deterministic analysis;
12. receive optional model explanation when available;
13. resume task state after restart.

Scientific and authorization boundaries must remain intact.

---

## Workstream 1E — provenance/public-source cleanup

Audit frozen scientific script headers and public source attribution.

If an old source file contains text such as an AI system being listed as the human code author, replace it with accurate provenance/acknowledgement language without rewriting scientific history or removing required attribution.

Do not alter frozen scientific bytes without following the resource checksum/versioning policy.

---

## v0.3.1 release gate

Required:

- `git diff --check`
- `python -m pytest -q`
- configured Linux/Windows CI green
- package build succeeds
- release verifier passes
- clean-wheel smoke passes semantically
- no scientific scoring semantics changed unless separately reviewed
- CHANGELOG updated
- fresh user acceptance test repeated.

---

# Workstream 2 — Formalize the scientific product and access contract

Target: v0.4.0 foundation.

## Objective

Make BinderRanker's scientific product contract primary and its direct,
built-in, and external access modes explicit in code boundaries, tests, and
docs. The access modes are not three products and must not duplicate the
scientific implementation.

## Mode A contract — Offline deterministic

Requirements:

- no model/API/network requirement;
- direct CLI and/or Python path;
- all ranking/analysis operations deterministic;
- machine-readable result artifacts;
- documented HPC/batch suitability;
- importing offline functionality must not eagerly import Agent/provider runtime.

Tests:

- install without model credentials;
- execute deterministic smoke path;
- verify no model call;
- verify scientific result artifacts.

## Mode B contract — Built-in reference Agent

Requirements:

- supported;
- simple natural-language closed loop;
- optional model API;
- built-in Agent uses the same domain services/Tool API where practical;
- no second scientific execution implementation;
- no expansion into general Harness scope.

Tests:

- representative end-to-end dialogue acceptance;
- deterministic evidence parity;
- authorization boundary tests;
- model failure fallback tests.

## Mode C contract — External Agent

Requirements:

- thin adapter;
- same Tool API;
- no duplicate ranking logic;
- explicit capability metadata;
- stable structured inputs/outputs;
- trusted authorization boundary for mutating tools.

Tests:

- adapter calls known Tool API operations;
- model cannot self-approve;
- external path preserves same domain state/provenance invariants.

---

# Workstream 3 — Harden the Tool API for stable consumption

## Objective

Turn the existing framework-independent Tool API into an intentionally versioned integration surface.

## 3A — Tool inventory and classification

Each Tool must be classified by side effects:

### Read-only

Examples:

- `get_current_plan`
- `get_task_status`
- `inspect_dataset`
- deterministic result reads/analysis where no task state is mutated beyond append-only artifacts.

### Mutating but non-executing

Examples:

- `prepare_task`
- `provide_information`

### Authorization-changing

- `request_approval`

### Executing

- `execute_ranker`

This classification should be machine-readable or centrally defined if useful.

## 3B — Stable schemas

Review all public Tool inputs/outputs for:

- schema version;
- JSON serializability;
- Path representation;
- error taxonomy;
- human-readable vs machine-readable fields;
- backward compatibility;
- no leakage of internal exception text/secrets.

Avoid exposing internal implementation classes merely because they are convenient today.

## 3C — Observation vs planning advice

The current `inspect_dataset` returns `DatasetPlanningAdvice`, which mixes verified observation with conditional advice.

Evaluate splitting:

```text
DatasetObservation
        ↓
planning advice
```

Do this only if it materially improves external Tool contracts.

Do not break the v0.3 built-in path casually.

## 3D — Trusted authorization injection

This is a blocker before external Agents can call mutating/execution tools.

The model must not be allowed to set:

- `approval_confirmed=True`
- `execution_confirmed=True`

based solely on its own tool arguments.

Design a trusted runtime context/token/capability mechanism so:

```text
model requests action
        ↓
host runtime obtains real user confirmation
        ↓
trusted authorization context
        ↓
BinderRanker Tool API
```

BinderRanker Core retains the final domain guard.

## Acceptance criteria

- Tool contracts documented;
- read/write/execution classes explicit;
- authorization cannot be forged by model output;
- JSON adapter tests pass;
- built-in workflow regression remains green.

---

# Workstream 4 — Deliberately cap and simplify the built-in Agent

## Objective

Preserve existing investment while minimizing future Harness maintenance.

This is optional interaction-layer maintenance, not a product milestone. Do
not schedule it ahead of scientific capability, reproducibility/validation, or
required Tool/API work.

## Required decision

Perform a cost/benefit review of the current handwritten runtime.

Two acceptable outcomes:

### Outcome A — keep legacy reference runtime

Use if:

- current behavior is stable;
- maintenance burden is tolerable;
- no major new Agent features are required.

Then:

- freeze generic runtime features;
- fix only critical issues;
- route more domain operations through stable services where low-risk;
- document it as the built-in reference Agent.

### Outcome B — small parity-preserving framework migration

Use Pydantic AI or another mature framework only if it demonstrably:

- removes substantial generic runtime code;
- reduces provider/tool-loop maintenance;
- preserves behavior;
- does not expand product scope.

Do not migrate merely because a framework is fashionable.

## Explicit non-goals

- no general-purpose memory platform;
- no generic scheduler;
- no multi-agent framework;
- no competing plugin ecosystem;
- no universal permission framework;
- no broad autonomous protein-design claims.

## Acceptance

Built-in Agent remains a supported simple closed loop with a documented maintenance boundary.

---

# Workstream 5 — Implement the first external Agent adapter

## Objective

Prove that BinderRanker can be used through a mature external Agent without duplicating domain logic.

This workstream follows the scientific, reproducibility, and Tool/API
priorities. It is not required to establish BinderRanker's product identity.

## Adapter selection gate

Before implementation, research the current state of:

- MCP tooling and client support;
- OpenClaw skill/plugin model;
- DeepSeek Harness plugin/skill model;
- maintenance burden;
- Python interoperability;
- authorization support;
- packaging/distribution path.

MCP is likely the best first neutral adapter, but the choice must be evidence-based at implementation time.

## Adapter principles

The adapter must:

- be thin;
- call the Tool API;
- not import frozen scientific internals directly;
- expose clear tool descriptions;
- differentiate read-only and mutating tools;
- preserve user-confirmation requirements;
- return structured evidence;
- not let the Agent modify scores or provenance.

## Minimal first adapter scope

Prefer a narrow but complete useful set:

- task status;
- current plan;
- dataset inspection;
- task preparation/information;
- deterministic result analysis;
- approval request with host confirmation;
- execution request with independent host confirmation.

If authorization support is not mature enough, ship read-only/planning Tools first and explicitly defer execution Tools rather than weakening the safety boundary.

## Acceptance test

From a fresh environment:

1. install BinderRanker;
2. install/configure external adapter;
3. connect compatible Agent;
4. ask natural-language task;
5. Agent invokes BinderRanker tools;
6. user can inspect/prepare task;
7. any protected action requires real confirmation;
8. deterministic result agrees with direct BinderRanker path.

---

# Workstream 6 — Integration documentation as an access feature

## Objective

A biology researcher should not need to understand Harness architecture to use an integration.

README should eventually present:

```text
How do you want to use BinderRanker?

A. Fully offline / no model
B. BinderRanker's built-in assistant
C. Connect BinderRanker to your Agent
```

Recommended docs:

- `docs/QUICKSTART_OFFLINE.md`
- `docs/BUILTIN_AGENT.md`
- `docs/AGENT_INTEGRATION.md`
- `docs/integrations/MCP.md`
- `docs/integrations/OPENCLAW.md`
- `docs/integrations/DEEPSEEK_HARNESS.md`

Only create integration docs for paths that are actually tested.

Each tutorial should include:

- supported versions;
- installation;
- configuration;
- security/authorization model;
- minimal working example;
- smoke test;
- troubleshooting;
- scientific limitations.

---

# Workstream 7 — Scientific transparency and score explanation

Target: v0.4.0.

Status: implementation, artifact-contract stabilization, and v0.4.0 release-cut
verification complete; final tag and release require owner approval.

## Objective

Users should understand why candidates rank differently without turning documentation into unsupported biological certainty.

Current public source already exposes scoring formulas and metrics.

The first v0.4 slice establishes a shared, model-independent primary-score
decomposition layer. Deterministic result summaries now expose the active
formula, audited weights, per-candidate weighted contributions, reconstructed
score, and reconstruction error when the report provides sufficient evidence.
The optional model explainer delegates to the same logic. Legacy reports stay
readable with an explicit `UNAVAILABLE` status instead of inferred evidence.

This slice does not change scoring, ranking, filters, or frozen Ranker
resources.

The second v0.4 slice adds a sealed, human-readable deterministic analysis
report for offline and HPC-friendly review. It composes the validated result
summary and failure-gap analysis without duplicating or recomputing scientific
logic. Scope policy is enforced in the rendered view: `SMOKE_TEST_ONLY`
suppresses unstable threshold details, while exploratory and full-dataset
analyses can expose numerical gaps with explicit batch-relative limitations.
The report path and SHA256 are included in the completed analysis provenance
seal, and pre-report manifests remain readable.

This slice also leaves scoring, ranking, filters, Tool authorization, and
frozen Ranker resources unchanged.

The third v0.4 slice adds shared adjacent-rank comparison evidence. Each
comparison subtracts the lower-ranked candidate's direct-primary contributions
from the adjacent higher-ranked candidate and requires their sum to reconstruct
the recorded `final_score_v4` difference. The deterministic report exposes the
largest positive term, the largest negative offset, all contribution deltas,
and reconstruction error. Only adjacent pairs are generated, keeping artifact
growth linear. Single-candidate and legacy/insufficient-evidence cases use
explicit `NOT_APPLICABLE` or `UNAVAILABLE` semantics.

These comparisons explain arithmetic in the recorded empirical score. They do
not assert causality, binding energetics, or biological mechanism, and they do
not change ranking or screening behavior.

The fourth v0.4 slice seals a shared scientific-interpretation contract into
the deterministic result summary. It binds the complete controlled metric
ontology to the recorded scoring mode and analysis-scope policy, including
metric direction and role, batch-relative score and threshold boundaries,
prohibited claims, and required downstream validation. Result-summary loading,
the deterministic Markdown report, and optional evidence-bound explanation all
validate and reuse the same contract. Legacy summaries remain readable with an
explicit `UNAVAILABLE` status instead of inferred run-bound semantics.

The generated metrics reference is now checked byte-for-byte against its
deterministic renderer so ontology documentation cannot silently drift.

The stabilization slice following implementation hardens the serialized
artifact boundary. Result summaries explicitly accept known schema generations
`0.1` through `0.4`, reject unknown future generations, and require every field
introduced by the declared generation. Completed analysis manifests similarly
accept their known `0.1` through `0.3` generations, while schema `0.3` requires
the deterministic-report integrity fields. Derived numeric evidence rejects
NaN and infinity again when summaries are loaded, including through explicit
or legacy analysis entry points.

This completes the planned Workstream 7 implementation scope. It does not
start the v0.5 scientific-validation infrastructure workstream.

Focus on:

- metric semantics;
- directionality;
- candidate contribution/decomposition;
- failed gates;
- threshold gaps;
- batch-relative nature;
- known limitations.

Do not present empirical weights as universal biophysical truth.

Do not claim affinity, stability, solubility, or experimental success prediction.

A polished paper-grade calibration rationale/ablation document may be deferred until scientific publication work is ready, but existing open implementation must remain reproducible.

---

# Workstream 8 — Scientific validation infrastructure

Target: v0.5.0.

Status: Phase 1 benchmark input contract, Phase 2 fixed-budget metric layer,
and Phase 3 target-removal sensitivity layer implemented on v0.5 development
branches; real empirical benchmark evidence, formal uncertainty inference, and
scientific interpretation remain pending.

## Objective

Demonstrate whether BinderRanker improves candidate prioritization under fixed downstream budgets.

## Priority order

1. retrospective known campaigns;
2. downstream complex-prediction comparison;
3. enrichment analysis;
4. selected vs nonselected/baseline comparison;
5. MD where scientifically appropriate;
6. prospective experimental validation where available.

## Benchmark design questions

- What is the baseline?
- What downstream outcome is measured?
- How is leakage prevented?
- What batch size and targets are included?
- How robust are rankings to parameter choices?
- What is the compute saved at a fixed success/enrichment level?
- Are results target-specific or generalizable?

## Important

Do not let Agent/integration expansion substitute for scientific validation.

## Phase 1 — Sealed benchmark input contract

Before computing performance metrics, require a self-contained YAML/CSV bundle
that declares the downstream outcome, evidence type, comparator baseline,
frozen Ranker provenance, fixed selection budgets, parameter-selection policy,
and outcome-blinding assumptions.

The shared intake gate must verify the CSV SHA256, candidate identity, complete
BinderRanker and baseline rankings, finite scores, binary outcomes, comparable
campaign budgets, and target-level isolation between `CALIBRATION` and
`EVALUATION`.

Passing this gate means only that benchmark inputs satisfy the documented
contract. It is not BinderRanker performance evidence.

## Phase 2 — Fixed-budget comparison metrics

Compute BinderRanker and baseline results side by side only from a validated
bundle. Calibration rows must not enter reported evaluation metrics. Undefined
metric states, campaign heterogeneity, and scientific claim boundaries must be
preserved rather than replaced with optimistic defaults.

Implementation status: complete on the v0.5 fixed-budget metrics branch. The
immutable report revalidates sealed inputs, computes campaign-level and pooled
hits, precision, recall, enrichment, and success for BinderRanker and the
declared baseline, and explicitly marks zero-positive campaign recall and
enrichment as unavailable. Synthetic regression fixtures validate arithmetic
and packaging only; they are not empirical BinderRanker performance evidence.

## Phase 3 — Target heterogeneity and removal sensitivity

Aggregate repeated evaluation campaigns within the same target before
cross-target review. Report equal-target metric distributions and
leave-one-target-out macro-estimate ranges, while preserving zero-positive
target states and explicit insufficient-target semantics.

Implementation status: complete on the v0.5 target-sensitivity branch. The
range is explicitly descriptive removal sensitivity, not a confidence interval
or hypothesis test. Formal uncertainty inference remains gated on an adequately
sized real benchmark and a predeclared scientific analysis plan.

---

# Workstream 9 — Additional adapters and ecosystem integration

Only after Tool contracts and first adapter are stable.

Candidates:

- OpenClaw;
- DeepSeek Harness;
- additional MCP clients;
- Python Agent frameworks;
- workflow platforms.

Every adapter should remain thin.

If an adapter begins reimplementing BinderRanker business logic, stop and move that logic downward into the Tool API/Core.

---

# 10. Cross-cutting engineering rules

## 10.1 Root-cause-first

Repeated special-case patches are a design smell.

If the same class of failure requires multiple keyword/OS/provider branches, stop and identify the violated abstraction.

## 10.2 Test the behavior category

Tests should cover invariants such as:

- no self-approval;
- zero valid candidates cannot silently look successful;
- deterministic result survives model explanation failure;
- foreign path styles are rejected safely;
- frozen scientific resources retain checksum identity.

Phrase-specific tests can exist as acceptance examples but should not become the implementation strategy.

## 10.3 Fresh-environment acceptance

Major release gates must include:

- fresh venv;
- installed wheel;
- outside source checkout;
- no developer environment assumptions;
- representative Windows/Linux checks.

## 10.4 No silent scientific changes

Any scoring/threshold/metric semantic change requires:

- explicit scientific review;
- before/after output comparison;
- documentation;
- versioning decision;
- tests.

## 10.5 Backlog discipline

If a reasonable improvement is discovered but is not in current scope, add it to `docs/IMPROVEMENT_BACKLOG.md` with:

- discovery location;
- problem;
- suggested direction;
- reason for deferral;
- priority;
- suggested version/phase.

---

# 11. Codex phase-completion protocol

At the end of every significant phase Codex should report:

```text
Phase:
Status:

Commits:
- ...

Files changed:
- ...

Behavior changed:
- ...

Behavior intentionally unchanged:
- ...

Tests:
- targeted:
- full suite:
- CI:
- clean-wheel:
- external acceptance:

New backlog items:
- ...

Known risks:
- ...

Next recommended phase:
- ...
```

Do not use “tests pass” without stating which tests and environment.

---

# 12. Stop conditions

Codex must stop broad implementation and request architectural review when any of the following occurs:

- a change requires altering BinderRanker scoring semantics;
- a new external adapter cannot preserve independent user authorization;
- the built-in Agent redesign starts becoming a generic Harness project;
- Tool API compatibility would be broken;
- the same CI failure persists after two substantially similar fixes;
- implementation requires multiple phrase-specific or runner-specific special cases;
- a migration would delete working code before parity tests exist;
- a requirement contradicts `ARCHITECTURE_EVOLUTION.md`.

---

# 13. Definition of success

The roadmap succeeds when BinderRanker has:

1. a reliable deterministic scientific path usable entirely offline;
2. interpretable ranking and screening behavior with growing scientific validation evidence;
3. preserved reproducibility, provenance, and authorization semantics;
4. a stable Tool/API boundary;
5. a modest but supported optional built-in conversational path;
6. external-Agent compatibility when justified by real integration needs;
7. clear tutorials for every supported access mode;
8. no home-grown general-purpose Harness requirement.

That is the intended post-v0.3 trajectory.
