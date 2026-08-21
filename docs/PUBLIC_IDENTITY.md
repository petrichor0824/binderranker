# BinderRanker Public Identity

This document defines the canonical public identity, terminology,
scientific positioning, and compatibility policy for BinderRanker.

It is the source of truth for public-facing names and descriptions used in:

- README files
- package metadata
- command-line help and user-facing output
- generated workspace documentation
- GitHub repository metadata
- release notes
- scientific and technical documentation

Historical documents may preserve earlier names when required for traceability.

---

## 1. Canonical project name

**BinderRanker**

The project must not be presented primarily as "Protein Design Agent".

"Protein Design Agent" is the historical project identity and may remain only
where compatibility, implementation history, or historical documentation
requires it.

---

## 2. Canonical positioning

### English

**BinderRanker — Interpretable Ranking and Layered Screening for Generated Protein Backbone Candidates**

### 中文

**BinderRanker：生成式蛋白骨架候选的可解释排序与分层筛选工具**

### Short English description

**Interpretable ranking and layered screening for generated protein backbone candidates.**

### 中文短描述

**面向生成式蛋白骨架候选的可解释排序与分层筛选工具。**

### Canonical product identity

**BinderRanker is an interpretable ranking and layered screening system for
generated protein backbone candidates.**

BinderRanker is not an Agent product. It must not be described as a protein
design Agent, an AI Agent for protein design, or an LLM-powered protein design
system, except when accurately documenting historical development context.

---

## 3. Problem statement

Modern protein-design workflows can generate large collections of candidate
protein backbones before downstream sequence design, structure prediction,
molecular simulation, and experimental validation.

BinderRanker addresses the intermediate prioritization problem:

RFdiffusion / other backbone generators
→ candidate backbone PDBs
→ BinderRanker
→ interpretable multi-metric ranking
→ layered screening
→ failure analysis
→ prioritized candidates
→ ProteinMPNN / complex prediction / MD / experiments

BinderRanker helps users identify which generated backbone candidates are worth
further computational or experimental investigation.

It does not replace the downstream methods used to evaluate those candidates.

---

## 4. Scientific core

The scientific core of the project is the **BinderRanker Engine**.

Its responsibilities include:

- deterministic structural metric calculation
- multi-metric candidate scoring
- candidate ranking
- broad / medium / strict layered screening
- failed-gate and threshold-gap analysis
- interpretable candidate-level evidence
- reproducible result generation

The scientific contribution of the project must not be described primarily as
a conversational Agent.

---

## 5. Product architecture

The public product is **BinderRanker**.

The interaction boundary is:

External Agents
→ BinderRanker Tool/API interface
→ BinderRanker scientific capability

Direct CLI/Python use and the optional built-in Agent converge on the same
Tool API, deterministic Core, and Engine. No interaction layer owns a separate
scientific implementation.

### BinderRanker Engine

The scientific ranking and screening engine.

### BinderRanker Core

The deterministic workflow and safety layer, including:

- task preparation
- validation
- planning state
- approval
- execution guards
- provenance
- result parsing
- deterministic result analysis

### BinderRanker Tool API

The controlled application interface used by CLI, Agent runtimes, and future
integrations.

Current examples include:

- `prepare_task`
- `provide_information`
- `inspect_dataset`
- `get_current_plan`
- `get_task_status`
- `request_approval`
- `execute_ranker`
- `analyze_results`

### BinderRanker Agent

The optional conversational interaction layer.

It may assist with:

- natural-language request understanding
- guided task preparation
- tool selection
- explanation of deterministic evidence
- future interactive workflow orchestration

The Agent is an optional usability and interaction layer.

It is not the scientific ranking algorithm.

---

## 6. Canonical public terminology

Prefer:

- BinderRanker
- BinderRanker Engine
- BinderRanker Core
- BinderRanker Tool API
- BinderRanker Agent
- BinderRanker workspace
- BinderRanker analysis
- BinderRanker result
- candidate backbone
- candidate prioritization
- ranking
- layered screening
- deterministic analysis
- failed-gate analysis
- provenance

Avoid using the following as the primary public identity:

- Protein Design Agent
- PDA
- protein-design chatbot
- conversational triage system
- AI protein designer
- autonomous protein-design Agent

The word "Agent" remains valid only when referring specifically to the optional
BinderRanker Agent layer, an external integration, or historical development
context.

---

## 7. Public package and CLI identity

The intended public distribution name for v0.3 is:

`binderranker`

The canonical public CLI is:

`binderranker`

New user-facing documentation should teach commands such as:

`binderranker --help`

`binderranker doctor`

`binderranker init`

`binderranker chat`

The historical CLI:

`protein-design-agent`

may remain temporarily as a compatibility alias during the public-name
transition.

New documentation should not present it as the preferred CLI.

---

## 8. Python namespace compatibility

The internal Python namespace remains:

`protein_design_agent`

for v0.3.

For example:

`from protein_design_agent.agent.tool_api import analyze_results`

remains valid.

The namespace should not be mechanically renamed solely for branding before
release.

Public branding and Python import paths are intentionally decoupled during the
v0.3 transition.

---

## 9. Persistent compatibility identifiers

Internal or persisted identifiers must not be renamed merely for cosmetic
consistency if doing so could break:

- existing workspaces
- manifests
- provenance
- stored task state
- compatibility with previous releases

For example:

`workspace_type = "protein-design-agent"`

may remain as an internal compatibility identifier.

Such identifiers are implementation contracts, not public branding.

Any future migration must be explicit and backward-compatible.

---

## 10. Historical documentation policy

Historical records must not be rewritten to imply that older releases already
used the BinderRanker identity.

Documents such as:

- `docs/V0.2_ROADMAP.md`
- historical CHANGELOG entries
- previous release notes
- migration records

may preserve:

- Protein Design Agent
- `protein-design-agent`
- v0.2 terminology
- earlier architectural descriptions

When useful, a historical note may explain that the project was later publicly
repositioned as BinderRanker.

Historical facts must remain historically accurate.

BinderRanker originally explored Agent-based interaction because protein-design
workflows are complex, many biological researchers do not have programming
backgrounds, and natural-language interfaces can improve accessibility. This
motivation remains relevant, but it does not define the current product:
historical motivation is not current product identity.

---

## 11. Scientific claim boundaries

BinderRanker ranks and screens generated backbone candidates using structural
and workflow evidence.

It must not be described as directly predicting:

- experimental binding success
- binding affinity
- thermodynamic stability
- solubility
- universal binder quality
- experimental success probability

BinderRanker does not replace:

- RFdiffusion or other backbone generators
- ProteinMPNN or other sequence-design systems
- AlphaFold, Boltz, or other structure / complex prediction methods
- molecular dynamics simulation
- experimental validation

A high BinderRanker score is not biological proof.

Preferred language includes:

- prioritized candidate
- higher-ranked backbone
- candidate worth further investigation
- passed the configured screening layer
- structurally favorable according to the evaluated metrics

Avoid unsupported language such as:

- best binder
- highest-affinity candidate
- guaranteed binder
- experimentally successful candidate
- validated hit

unless independently supported by appropriate downstream evidence.

---

## 12. Interpretation of screening layers

Broad, medium, and strict pools are BinderRanker screening layers.

They must not be presented as universal biological categories.

Their interpretation depends on:

- the evaluated dataset
- the configured metrics
- the configured or dynamic thresholds
- the permitted analysis scope
- the evidence available for the current run

Small smoke-test datasets must not be presented as formal scientific ranking
validation.

---

## 13. README language policy

The project should provide:

- `README.md` — canonical English README
- `README.zh-CN.md` — complete Simplified Chinese README

Both versions should use the same conceptual structure and scientific claims.

The README should prioritize:

1. What BinderRanker is
2. Why candidate prioritization is needed
3. Where BinderRanker fits in the protein-design pipeline
4. Scientific methodology
5. Outputs and interpretability
6. Quick Start
7. Installation
8. Scientific limitations
9. Reproducibility and provenance
10. Optional BinderRanker Agent
11. Architecture
12. Validation status
13. Roadmap
14. Citation and contribution information

Natural-language interaction must not dominate the opening description of the
project.

---

## 14. GitHub identity

### Repository display name

**BinderRanker**

### Recommended repository name

`binderranker`

### Recommended GitHub description

**Interpretable ranking and layered screening for generated protein backbone candidates.**

### Recommended topics

- protein-design
- protein-engineering
- structural-biology
- structural-bioinformatics
- computational-biology
- bioinformatics
- protein-binder
- rfdiffusion

Agent or LLM terminology may appear as secondary topics but should not define
the scientific identity of the repository.

---

## 15. Release identity

Public releases should use:

**BinderRanker vX.Y.Z**

For v0.3.0, the preferred release framing is:

**BinderRanker v0.3.0 — Interpretable Ranking and Layered Screening for Generated Protein Backbones**

The release should emphasize the complete candidate-ranking workflow rather
than presenting the release primarily as an Agent release.

---

## 16. Validation language

Engineering validation and scientific validation must remain clearly
separated.

Engineering validation may include:

- deterministic regression tests
- execution-integrity checks
- frozen-file verification
- provenance validation
- package installation tests
- smoke-test workflows

Scientific validation may include:

- retrospective comparison on real design campaigns
- downstream complex-prediction comparison
- enrichment analysis
- prospective experimental validation

Engineering correctness must not be presented as evidence of biological
predictive accuracy.

---

## 17. Public identity principle

When deciding how to describe the project, ask:

"If the conversational Agent were removed, what scientific capability would
remain?"

The answer should still clearly be BinderRanker:

an interpretable ranking and layered-screening system for generated protein
backbone candidates.

The Agent improves accessibility and workflow usability.

The governing principle is:

> BinderRanker is a scientific ranking and screening capability. Agent
> interfaces are optional interaction layers used to improve accessibility and
> integration, not the core product.

Future work is prioritized in this order:

1. Scientific ranking and screening capability.
2. Reproducibility and validation.
3. Stable Tool/API interfaces.
4. External Agent ecosystem compatibility.

Generic chatbot capabilities, general-purpose Agent infrastructure, and
memory/personality/planning expansion are not independent priorities. They are
in scope only when they directly improve BinderRanker usability without
competing with the priorities above.

**BinderRanker is the project.**
