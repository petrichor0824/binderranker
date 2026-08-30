# BinderRanker Architecture Evolution and Development Philosophy

> Status: project-owner intent and architectural context for post-v0.3 development
>
> Intended readers: Codex, future maintainers, contributors, and collaborators
> Relationship to other documents: this file explains **why** BinderRanker should evolve in a particular direction. The execution order and acceptance criteria live in `POST_V0_3_EXECUTION_ROADMAP.md`.

---

## 1. Why this document exists

BinderRanker has already passed through several architectural ideas rather than being designed once from a blank sheet.

The project began from a practical scientific problem:

> Modern protein-design workflows can generate many candidate backbones, while downstream sequence design, complex prediction, molecular simulation, manual inspection, and experimental validation are much more expensive. Which generated candidates are worth carrying forward first?

The project owner also had a second usability concern:

> Many biology researchers are not comfortable with command-line tools, APIs, software architecture, or algorithmic configuration. A natural-language interface could make a specialized ranking method much easier to use correctly.

That led the project to develop not only a scientific ranking engine but also a substantial conversational Agent layer. During v0.3 development, this Agent layer accumulated task state, session behavior, model-provider handling, planning, approval, execution controls, error translation, recovery logic, and conversational routing.

This work was useful, but it also revealed an important boundary:

**BinderRanker's scientific value and generic Agent/Harness infrastructure are not the same thing.**

The post-v0.3 architecture should preserve the work that is genuinely BinderRanker-specific while avoiding an open-ended attempt to compete with mature general-purpose Agent/Harness ecosystems.

This document records that reasoning so future development does not accidentally drift back into building a second OpenClaw, DeepSeek Harness, or generic Agent runtime inside BinderRanker.

---

## 2. Current public identity

The canonical public project is **BinderRanker**.

Canonical positioning:

**BinderRanker — Interpretable Ranking and Layered Screening for Generated Protein Backbone Candidates**

BinderRanker is not primarily a chatbot, autonomous protein designer, or general-purpose Agent framework.

More directly: BinderRanker is not an Agent product. The canonical product is
an interpretable ranking and layered screening system for generated protein
backbone candidates.

Its scientific role is:

```text
RFdiffusion / other backbone generators
        ↓
candidate backbone PDBs
        ↓
BinderRanker
        ↓
interpretable multi-metric ranking
+ layered screening
+ failed-gate / threshold-gap analysis
        ↓
prioritized candidates
        ↓
ProteinMPNN / complex prediction / MD / experiments
```

A high BinderRanker score is not biological proof. BinderRanker prioritizes candidates for downstream investigation.

---

## 3. What already exists in the repository

At the time this document was written, the active stabilization branch already contains a mature amount of infrastructure.

### 3.1 Packaging and release identity

- Distribution name: `binderranker`
- Current package/release version: `0.4.0`
- Release focus: scientific transparency and artifact-contract hardening
- Python requirement: `>=3.10`
- Canonical CLI: `binderranker`
- Historical compatibility CLI: `protein-design-agent`
- Internal Python namespace remains `protein_design_agent`
- Public repository: `petrichor0824/binderranker`
- License: Apache-2.0

The canonical CLI entry points currently route through `protein_design_agent.cli:main`.

### 3.2 Scientific and deterministic layers

The repository already contains:

- frozen BinderRanker scientific resources;
- deterministic structure handling and validation;
- candidate scoring/ranking;
- layered screening;
- deterministic result analysis;
- planning state;
- approval records;
- execution guards;
- provenance;
- run status;
- task recovery;
- analysis-scope guardrails.

These are not disposable Agent experiments. They are part of the reproducible scientific software product.

### 3.3 Framework-independent Tool API

The current code already exposes a valuable architectural seam in:

`src/protein_design_agent/agent/tool_api.py`

Current controlled capabilities include:

- `get_current_plan`
- `get_task_status`
- `prepare_task`
- `provide_information`
- `inspect_dataset`
- `request_approval`
- `execute_ranker`
- `analyze_results`

Important properties already present:

- the Tool API does not depend on the legacy Chat runtime;
- model providers are not required for deterministic Tool API import/use;
- dataset paths are derived from trusted task state rather than arbitrary call-time paths;
- approval and execution remain independent authorization boundaries;
- deterministic analysis runs without a model;
- analysis directories are allocated without overwriting historical results.

This Tool API is the most important bridge between the existing v0.3 implementation and the future multi-entry architecture.

### 3.4 Existing built-in Agent

The repository also contains a substantial built-in conversational implementation, including large modules such as:

- `chat_dialogue.py`
- `chat_session.py`
- provider/model readiness infrastructure;
- dataset discovery/advice;
- task navigation and task recovery;
- capability-truth checks;
- result explanation;
- approval/execution conversation flow.

The built-in Agent works and should not be deleted merely because the strategic focus changes.

However, it should no longer be treated as a project whose goal is to become a first-class general-purpose Harness.

### 3.5 Current stabilization work

The stabilization branch has already implemented or documented improvements including:

- state-aware first-workflow guidance;
- automatic workspace initialization guidance;
- secure API-key setup guidance;
- deterministic session recovery summaries;
- public translation of internal task-state/error concepts;
- compact confirmation prompts;
- explicit continuation phrases for current proposals;
- Windows path/encoding hardening;
- Linux and Windows CI coverage;
- frozen Ranker line-ending protection.

These changes should be preserved unless a later redesign provides equal or stronger behavior with regression coverage.

---

## 4. The original Agent hypothesis

The early product hypothesis was reasonable:

> If BinderRanker is wrapped in an Agent, a biology researcher can describe a task in natural language and avoid learning command syntax, file-layout details, configuration semantics, and execution steps.

That remains true.

Natural language is still a valuable interaction mode.

The mistake would be to infer from this requirement that BinderRanker must itself build and maintain every layer required by a modern Agent.

During v0.3 development, the project encountered questions such as:

- How should conversation history be stored?
- How should task state differ from dialogue state?
- What happens when a model returns HTTP 200 but no usable formal content?
- How should retries work?
- How should pending actions interact with new read-only user intents?
- How should a model select tools?
- How should permissions be represented?
- How should a user resume a session?
- How should arbitrary tool execution be sandboxed?
- How should providers be portable?
- How should UI, scheduling, memory, and Agent loops evolve?

Most of these are generic Harness problems.

They are important, but they are not BinderRanker's scientific differentiator.

---

## 5. The key architectural reflection

The post-v0.3 conclusion is:

> BinderRanker should be excellent at being a scientific capability and excellent at being callable by Agents. It does not need to become a general-purpose Agent platform.

This is not a declaration that the existing Agent work was wasted.

The existing work produced several lasting assets:

1. a real deterministic Core;
2. a controlled Tool API;
3. approval and execution semantics;
4. provenance and audit behavior;
5. behavioral regression tests;
6. evidence-bound scientific explanation boundaries;
7. real user acceptance evidence about where conversational workflows fail.

The correct response is therefore **repositioning, not deletion**.

---

## 6. The three supported usage modes

BinderRanker should intentionally support **three first-class ways to use the same scientific capability**.

```text
                         BinderRanker
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
  Mode A: Offline      Mode B: Built-in     Mode C: External
   deterministic       reference Agent        mature Agent
          │                   │                   │
    CLI / Python          model API         MCP / Harness /
      direct use          simple chat       Skill / adapter
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                    BinderRanker Tool API
                              │
                    deterministic Core
                              │
                    BinderRanker Engine
```

These modes are alternatives for users, not separate scientific implementations.

### 6.1 Mode A — Offline deterministic use

Purpose:

- zero model requirement;
- zero API-key requirement;
- reproducible scientific/HPC use;
- scripting and batch automation;
- publication/research reproducibility;
- users who prefer CLI or Python.

Properties:

- must remain fully usable without importing or configuring an LLM runtime;
- must never require network access merely to rank/analyze data;
- should be the reference path for scientific correctness;
- should have stable machine-readable outputs and clear command documentation.

This is the foundation of the project, not a fallback mode.

### 6.2 Mode B — Built-in reference Agent

Purpose:

- lower the barrier for users who want natural-language interaction;
- provide an official simple end-to-end experience;
- provide a reference implementation showing how BinderRanker tools can be orchestrated;
- allow users to use BinderRanker without installing a separate Agent platform.

Strategic scope:

- preserve the existing working Agent;
- keep it capable of a simple reliable closed loop;
- fix critical usability, compatibility, data-integrity, and security problems;
- do **not** turn it into a competing general-purpose Harness.

It should remain supported, but it is not where most future engineering effort should go.

The stop condition is:

> A new user can use the built-in Agent to complete a straightforward BinderRanker task safely and understandably.

Beyond that, generic capabilities such as universal memory, sophisticated general planning, multi-agent orchestration, generic sandboxing, scheduling, or broad provider abstractions should normally be delegated to external mature ecosystems.

### 6.3 Mode C — External Agent integration

Purpose:

- let researchers use BinderRanker through whichever mature Agent/Harness they already prefer;
- reuse better conversational interfaces, memory, tool loops, UI, scheduling, model portability, and ecosystem integrations;
- keep BinderRanker focused on domain capability.

Possible adapters include:

- MCP;
- OpenClaw Skill / integration;
- DeepSeek Harness plugin/skill;
- other function-calling or Agent frameworks.

The project should not hard-bind scientific logic to one Agent vendor.

All adapters must converge on the same BinderRanker Tool API and deterministic Core.

As of v0.6 Phase 4, the first concrete adapter is a local read-only MCP server.
The choice follows an implementation-time review of the OpenAI remote-MCP
interface and the official MCP Python SDK v2 stable line. The server uses the
official SDK, local `stdio`, structured outputs, read-only/idempotent/closed-
world annotations, and the shared BinderRanker error envelope.

Only `get_current_plan`, `get_task_status`, and `inspect_dataset` are exposed.
The adapter accepts managed task names rather than paths and emits purpose-built
views without host paths or stored free-form request text. Preparation,
mutation, approval, execution, and append-only analysis remain unavailable
until a host-specific design can authenticate the human and bind a real
confirmation event to BinderRanker's trusted runtime. MCP protocol support by
itself does not satisfy that domain authorization requirement.

The current server is not a remote API: it has no HTTP listener, OAuth, tenant
model, or public deployment. Those are separate future decisions.

As of v0.6 Phase 5A, private OpenAI connectivity no longer requires a public
BinderRanker HTTP listener. OpenAI Secure MCP Tunnel can invoke the existing
stdio command through an outbound-only tunnel-client process. BinderRanker now
publishes a local readiness preflight and a threat model, but it does not own or
infer OpenAI control-plane permissions, runtime authentication, organization or
workspace association, or live tunnel health.

This remains a single-trust-domain design: one process is bound to one managed
workspace. The tunnel does not provide BinderRanker with a trusted caller
identity or human-confirmation event, so protected Tools remain deferred even
after a successful read-only tunnel connection.

Phase 5B-local validates the same boundary without an API credential: a generic
local MCP Host launches the official entry point as a real stdio subprocess,
receives BinderRanker's server identity/version/instructions, discovers only
the three read-only Tools, and observes both successful and fail-closed calls.
Codex configuration adds a matching host-side Tool allow list. The 2026-08-30
live local check also fixes and covers the Codex `2025-06-18` requirement that
structured Tool output schemas have an explicit object root. This is local Host
interoperability evidence, not remote tunnel or scientific-performance evidence.

---

## 7. The modes must be isolated at the interaction layer, not duplicated at the scientific layer

The three modes require **architectural separation** but not three implementations.

Correct:

```text
Offline CLI ───────┐
Built-in Agent ────┼──> Tool API / deterministic services ──> Engine
External Adapter ──┘
```

Incorrect:

```text
Offline ranking implementation
Built-in Agent ranking implementation
MCP ranking implementation
```

There must be only one authoritative scientific execution path.

A future acceptance test should demonstrate that equivalent inputs reaching the same deterministic operation through different entry modes produce equivalent scientific results and provenance semantics.

---

## 8. Harness safety vs BinderRanker domain safety

A major lesson from the Agent work is that “safety” is not one monolithic layer.

### 8.1 Generic Harness responsibilities

Mature Harnesses may provide:

- tool-call transport;
- sandbox/process isolation;
- generic permission prompts;
- session/message history;
- secrets handling;
- model-provider support;
- retry infrastructure;
- scheduling;
- UI;
- generic audit logs.

BinderRanker should avoid rebuilding these without a domain-specific reason.

### 8.2 BinderRanker responsibilities that must remain owned by the project

BinderRanker still owns domain semantics such as:

- which task evidence is trusted;
- how a planning session may mutate;
- what configuration is approved;
- frozen-file/config fingerprints;
- one-time approval semantics;
- execution guards;
- provenance requirements;
- scientific capability boundaries;
- smoke/exploratory/full analysis-scope restrictions;
- what constitutes authoritative deterministic evidence.

An external Harness saying “the user approved this tool call” does not automatically define BinderRanker's scientific authorization model.

In particular, the existing Tool API accepts values such as `approval_confirmed` and `execution_confirmed`. When external Agents are introduced, these must come from **trusted runtime authorization context**, not from model-generated tool arguments.

A model must never be able to approve its own plan or manufacture execution authorization.

---

## 9. Relationship to Pydantic AI

Earlier v0.3 architecture documents planned a Pydantic AI migration for the built-in Chat runtime.

That decision should now be interpreted more narrowly.

Pydantic AI remains a possible implementation tool if it:

- substantially reduces maintenance burden;
- replaces fragile handwritten generic Agent plumbing;
- preserves current deterministic boundaries;
- does not create a second major migration project without user benefit.

However:

> A full Pydantic AI migration is no longer automatically the main product objective.

The new first-class architectural goal is **Agent interoperability through a stable Tool API**.

The built-in reference Agent may remain on the existing runtime for a period if it is stable and inexpensive to maintain.

If a Pydantic AI migration is pursued, it should be justified as a maintenance simplification and parity-preserving refactor, not as the scientific roadmap.

---

## 10. Relationship to OpenClaw, DeepSeek Harness, MCP, and Skills

BinderRanker should not compete with these systems.

They solve generic Agent runtime and integration problems.

BinderRanker solves a domain scientific prioritization problem.

The intended relationship is:

```text
OpenClaw / DeepSeek Harness / other Agent
                 ↓
        thin BinderRanker adapter
                 ↓
          BinderRanker Tool API
                 ↓
        deterministic BinderRanker Core
                 ↓
          BinderRanker Engine
```

A “BinderRanker Skill” should therefore be a thin capability adapter and instruction layer around stable BinderRanker interfaces, not a copy of the scoring/workflow logic.

The project may publish several adapters over time, but adapters should stay thin.

---

## 11. Scientific interpretation remains more important than Agent polish

Agent compatibility can make BinderRanker easier to use, but it does not establish scientific validity.

The long-term scientific question is:

> At a fixed downstream compute or experimental budget, does BinderRanker enrich candidates that perform better in downstream validation than unscreened or baseline selections?

Future credibility should therefore prioritize:

- retrospective benchmark campaigns;
- downstream complex-prediction comparisons;
- enrichment analysis;
- selected-vs-nonselected comparisons;
- prospective validation when feasible;
- transparent limitations.

Agent work should never crowd this out.

---

## 12. Public-method transparency

The repository is open source and already exposes significant scoring logic and formulas.

Do not attempt to retroactively hide public implementation details.

At the same time, documentation should distinguish:

- user-facing metric meaning and score decomposition;
- reproducible implementation behavior;
- unpublished scientific rationale, calibration history, ablations, or paper-grade method exposition that may be documented more fully alongside a preprint/paper.

The goal is interpretability without overclaiming scientific validation.

---

## 13. Engineering principles

The governing principle is:

> BinderRanker is a scientific ranking and screening capability. Agent
> interfaces are optional interaction layers used to improve accessibility and
> integration, not the core product.

Future development follows this priority order:

1. Scientific ranking and screening capability.
2. Reproducibility and validation.
3. Stable Tool/API interfaces.
4. External Agent ecosystem compatibility.

Generic chatbot capabilities, general-purpose Agent infrastructure, and
memory/personality/planning expansion are not independent product goals. They
are considered only when they directly improve BinderRanker usability.

### 13.1 Core first

BinderRanker scientific semantics must remain deterministic and model-independent.

### 13.2 Tool API as the stable integration boundary

New interaction modes should call stable domain capabilities rather than internal implementation details.

### 13.3 Framework-first for generic Agent infrastructure

Before building generic memory, routing, provider, scheduling, sandbox, or tool-loop code, ask whether a mature framework should own it.

### 13.4 Root-cause-first

Do not accumulate phrase-specific or CI-runner-specific patches when a shared invariant or abstraction is wrong.

### 13.5 Compatibility is deliberate

Keep compatibility aliases and historical workspace/schema identifiers when needed, but do not let historical naming dictate new public architecture.

### 13.6 Scientific authority is deterministic

Model prose may explain evidence but cannot alter scores, screening membership, approval facts, provenance, or execution evidence.

### 13.7 No sunk-cost deletion

Existing Agent code should not be deleted merely to make the architecture look cleaner.

Retire code only when:

- its role has been replaced;
- behavioral parity exists where required;
- migration value exceeds compatibility cost;
- tests protect the new boundary.

---

## 14. Decision test for future features

Before adding a feature, ask:

1. Does this improve BinderRanker's ranking/screening science?
2. Does it improve deterministic workflow reliability?
3. Does it improve evidence/provenance/auditability?
4. Does it make one of the three supported usage modes materially easier?
5. Is this actually generic Harness functionality that should live outside BinderRanker?

If the answer is mainly #5, prefer an adapter or external framework rather than expanding the built-in runtime.

---

## 15. The project-owner intent in one paragraph

The project owner originally wanted a natural-language Agent because many biological researchers are not software specialists. That user need remains valid. The architectural correction is not to abandon natural language, but to stop assuming BinderRanker must personally implement every layer of a modern Agent system. BinderRanker should remain usable offline, retain a simple supported built-in Agent for a self-contained closed loop, and become easy to connect to mature external Agents. The scientific ranking capability stays central; Agent runtimes become interchangeable ways of reaching it.

---

## 16. Long-term target

A mature BinderRanker should be describable as:

> **A reproducible and interpretable protein-backbone candidate ranking and layered-screening system that can be used directly, through its built-in reference Agent, or as a professional scientific capability inside external Agent ecosystems.**

That is the architectural destination.
