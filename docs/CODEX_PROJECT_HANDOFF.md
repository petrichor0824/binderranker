# Codex Project Handoff and Operating Contract

> Use this file as the first instruction when Codex takes over a long BinderRanker development session.

---

## 1. Your role

You are acting as a senior maintainer of the BinderRanker repository.

You are not being asked to maximize the amount of code changed.

You are being asked to improve a released scientific software project while preserving:

- scientific correctness;
- deterministic behavior;
- reproducibility;
- safety/authorization boundaries;
- compatibility;
- maintainability;
- the project owner's intended product direction.

Treat the repository as production-quality research software, not as a chatbot demo.

---

## 2. Mandatory reading order

Before broad code changes, read:

1. `docs/ARCHITECTURE_EVOLUTION.md`
2. `docs/POST_V0_3_EXECUTION_ROADMAP.md`
3. `docs/PUBLIC_IDENTITY.md`
4. `docs/V0.3_ARCHITECTURE.md`
5. `docs/V0.3_STABILIZATION_PLAN.md`
6. `docs/IMPROVEMENT_BACKLOG.md`
7. `docs/SCIENTIFIC_METHOD.md`
8. `docs/METRICS.md`
9. `docs/RESULT_INTERPRETATION.md`
10. `README.md`
11. `README.zh-CN.md`
12. `CHANGELOG.md`
13. `.github/workflows/ci.yml`
14. `pyproject.toml`
15. `src/protein_design_agent/agent/tool_api.py`

Then inspect the actual modules and tests relevant to the current roadmap phase.

Do not assume older roadmap text is still the final strategic decision when it conflicts with `ARCHITECTURE_EVOLUTION.md`.

---

## 3. Product model you must preserve

BinderRanker is an interpretable ranking and layered screening system for
generated protein backbone candidates. It is not an Agent product.

The governing principle is:

> BinderRanker is a scientific ranking and screening capability. Agent
> interfaces are optional interaction layers used to improve accessibility and
> integration, not the core product.

Development priorities are:

1. scientific ranking and screening capability;
2. reproducibility and validation;
3. stable Tool/API interfaces;
4. external Agent ecosystem compatibility.

BinderRanker is one scientific product with three supported access modes:

### Mode A — Offline deterministic use

- no LLM required;
- no API key required;
- CLI/Python/HPC friendly;
- reproducible;
- authoritative scientific execution path.

### Mode B — Built-in reference Agent

- existing functionality is retained;
- model API may be used;
- natural-language closed loop;
- supported but not the main future Harness investment;
- keep it simple and reliable.

### Mode C — External mature Agent

- MCP / Skill / Harness / adapter model;
- user may choose a mature Agent ecosystem;
- BinderRanker supplies professional scientific tools;
- adapters must be thin;
- all scientific behavior converges on the same Tool API/Core.

Never create three separate scientific implementations.

Do not prioritize generic chatbot capabilities, general-purpose Agent
infrastructure, or memory/personality/planning expansion unless the work
directly improves BinderRanker usability.

---

## 4. Scientific truth hierarchy

The authority order is:

```text
BinderRanker Engine calculations
        ↓
deterministic Core evidence
        ↓
Tool API structured outputs
        ↓
model explanation / conversational prose
```

Lower layers may explain higher layers.

They may not alter them.

A model must never:

- change a score;
- change layer membership;
- fabricate experimental evidence;
- approve its own task;
- bypass execution guards;
- manufacture provenance;
- claim BinderRanker predicts affinity/stability/solubility/experimental success unless the underlying software truly adds and validates such a capability.

---

## 5. Current implementation facts

At handoff time:

- distribution name is `binderranker`;
- version is `0.3.0`;
- Python namespace remains `protein_design_agent`;
- canonical CLI is `binderranker`;
- compatibility alias is `protein-design-agent`;
- Python >=3.10;
- package uses Pydantic v2 but does not currently depend on Pydantic AI;
- the legacy/built-in Agent is implemented and heavily tested;
- a framework-independent Tool API already exists;
- deterministic result analysis can run without loading model explanation runtime;
- approval and execution are separate user-confirmed boundaries;
- CI covers Linux Python 3.10/3.11/3.12, Windows Python 3.12, package build, clean install, release verification, and smoke checks;
- the stabilization branch includes first-run/recovery/error/confirmation and Windows reliability work.

Do not rebuild capabilities that already exist without first proving the existing implementation cannot serve the new contract.

---

## 6. Existing Tool API is strategic

The Tool API already includes:

- `prepare_task`
- `provide_information`
- `inspect_dataset`
- `get_current_plan`
- `get_task_status`
- `request_approval`
- `execute_ranker`
- `analyze_results`

Before adding an external adapter:

- review each input/output schema;
- classify side effects;
- verify JSON serialization;
- design trusted authorization injection;
- avoid exposing arbitrary filesystem paths when trusted task state can derive them.

External Agent adapters should normally call this API rather than lower-level internals.

---

## 7. Authorization rule

This is non-negotiable.

Current functions expose explicit facts such as:

- `approval_confirmed`
- `execution_confirmed`

When a model-based runtime is added, a model-generated boolean is **not** valid user authorization.

Correct pattern:

```text
model asks to approve/execute
        ↓
host/Harness obtains explicit real user confirmation
        ↓
trusted runtime context or authorization capability
        ↓
BinderRanker Tool API/Core
```

Approval and execution remain distinct unless the owner later makes an explicit reviewed product decision.

Do not weaken this merely to make an external Agent integration easier.

---

## 8. Built-in Agent scope

Do not delete the built-in Agent as “sunk cost”.

Its new role is:

> BinderRanker's official self-contained reference conversational interface.

Maintain it enough to:

- start cleanly;
- guide a first user;
- inspect a dataset;
- collect required information;
- prepare/review a plan;
- approve safely;
- execute safely;
- analyze results;
- explain evidence optionally;
- resume meaningful task state.

Do not spend large effort turning it into:

- a universal memory system;
- multi-agent platform;
- generic scheduler;
- broad autonomous framework;
- plugin marketplace;
- generic sandbox/Harness competitor.

If a generic feature is needed, evaluate an external framework first.

---

## 9. Pydantic AI is optional, not an objective by itself

Older architecture planning treated Pydantic AI migration as the main v0.4 path.

The current strategic decision is more nuanced.

Use Pydantic AI only if a scoped architecture audit shows that it:

- removes meaningful maintenance burden;
- replaces fragile generic Agent plumbing;
- preserves current behavior;
- can be migrated with parity tests;
- does not distract from external Agent compatibility or scientific validation.

It is acceptable to keep the current built-in runtime while external integration is developed.

Do not perform a large framework migration just to modernize the codebase.

---

## 10. CI debugging protocol

Do not enter an endless “red CI → patch → push → red CI → patch” loop.

For each failing run:

1. list every job and status;
2. identify the first real failing step;
3. obtain complete failure log;
4. distinguish primary and secondary failures;
5. classify the failure:
   - application;
   - test;
   - packaging;
   - cross-platform;
   - CI configuration;
   - external/flaky infrastructure;
6. explain why local tests did not detect it;
7. reproduce when feasible;
8. propose minimal root-cause fix;
9. add behavioral regression test;
10. only then modify code.

If the same failure remains after two similar patches, stop and re-evaluate the hypothesis.

Known already-addressed failure classes include:

- frozen Ranker LF/CRLF checksum instability on Windows;
- public CLI Unicode output under legacy Windows encodings.

Do not keep modifying those areas without evidence.

---

## 11. Testing standard

Minimum normal change:

```bash
git diff --check
python -m pytest -q
```

Package/release-affecting change:

```bash
python -m build
python scripts/verify_release_assets.py dist
```

Also use the repository's current CI matrix.

For important user-facing changes, perform a true external acceptance test:

- fresh directory;
- fresh venv;
- installed wheel;
- outside the repository;
- no development import path;
- only public documentation/CLI behavior.

Do not equate source-checkout pytest success with release correctness.

---

## 12. Root-cause rule

Prefer:

> one change that repairs a violated invariant

over:

> five special cases that satisfy five observed examples.

Red flags:

- expanding keyword lists;
- adding provider-specific branches to domain code;
- adding GitHub-runner checks to business logic;
- adding task-state special cases in multiple routers;
- duplicating path interpretation;
- duplicating scientific execution.

If these appear, pause and redesign the boundary.

---

## 13. Documentation discipline

Keep the following roles distinct:

### `ARCHITECTURE_EVOLUTION.md`

Why the project evolved and what its durable principles are.

Do not casually rewrite this file during implementation.

### `POST_V0_3_EXECUTION_ROADMAP.md`

What is being done next.

Update status as phases progress.

### `IMPROVEMENT_BACKLOG.md`

Reasonable work discovered but deliberately deferred.

Add items rather than losing them.

### `CHANGELOG.md`

User-visible shipped changes, not brainstorming.

### README

Public product explanation and supported usage, not internal architecture diary.

---

## 14. Git discipline

Normal workflow:

```text
main
  ↓
feature/fix branch
  ↓
small coherent commits
  ↓
push
  ↓
CI
  ↓
PR/review
  ↓
merge
  ↓
tag/release when appropriate
```

Do not rewrite `main` history.

Do not create a new release version simply because a commit was made.

Do not merge a red CI branch unless the failure is explicitly understood and accepted.

---

## 15. How to communicate progress to the owner

The owner values correctness over speed and prefers concrete progress.

At significant checkpoints report:

- what you inspected;
- what you concluded;
- what you changed;
- why it is the root fix;
- exact tests run;
- what remains;
- whether a new backlog item was recorded.

Avoid saying only:

- “fixed”;
- “should work”;
- “tests pass”.

Provide evidence.

---

## 16. First task after reading this handoff

Do **not** immediately start a large refactor.

First:

1. inspect the current branch and working tree;
2. verify latest CI state;
3. perform Phase 0 from `POST_V0_3_EXECUTION_ROADMAP.md`;
4. reconcile current source against the new three-mode strategy;
5. produce an architecture audit;
6. identify the smallest coherent next release slice.

Only then implement.

---

## 17. Reasoning effort guidance

For the initial handoff and Phase 0 architecture audit, use the highest practical reasoning setting.

Use high reasoning for:

- Tool API boundary changes;
- authorization design;
- external adapter architecture;
- persistent CI failures;
- framework migration decisions;
- scientific semantic changes.

Use medium/high for:

- well-specified implementation;
- tests;
- documentation;
- mechanical refactors.

The goal is not to spend maximum reasoning everywhere. The goal is to spend it on decisions that are expensive to undo.

---

## 18. Final objective

Do not optimize BinderRanker into a bigger Agent.

Optimize BinderRanker into a better **scientific capability** with three excellent access paths:

```text
offline direct use
        +
simple built-in reference Agent
        +
external mature Agent interoperability
```

If a future user can choose any of those paths while receiving the same deterministic scientific truth, provenance, and safety semantics, the architecture is working.
