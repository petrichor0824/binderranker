# BinderRanker Tool API Contract

BinderRanker exposes a framework-independent Tool API for direct Python use
and optional integrations. The versioned catalog in
`protein_design_agent.agent.tool_api_contract` is the machine-readable boundary
for future HTTP, MCP, workflow, and external-Agent adapters.

This contract describes engineering integration behavior. It does not claim
that BinderRanker ranking quality, biological predictive accuracy, or
experimental success has been established. The catalog therefore publishes:

- `scientific_evidence_status=SCIENTIFIC_VALIDATION_PENDING`;
- `performance_claims_established=false`.

## Architecture boundary

```text
untrusted external request
        |
        v
thin host adapter
  - validates the request schema
  - constrains host-local paths
  - supplies trusted runtime facts
        |
        v
BinderRanker Tool API
        |
        v
deterministic services and scientific core
```

Adapters must not reimplement ranking, screening, approval, execution, result
validation, or provenance logic.

## Catalog access

```python
from protein_design_agent.agent.tool_api_contract import get_tool_api_catalog

catalog = get_tool_api_catalog()
payload = catalog.model_dump(mode="json")
```

`payload` is JSON-serializable and includes the contract version, path
semantics, side-effect classification, authorization requirement, untrusted
request JSON Schema, response JSON Schema, and host-injected fields for all
eight public operations.

The current catalog and schema version are both `0.1`. Additive compatible
changes may retain the contract version; changes that invalidate an existing
adapter require an explicit contract-version decision and migration note.

## Operation inventory

| Operation | Side effect | Trusted authorization |
| --- | --- | --- |
| `get_current_plan` | `READ_ONLY` | `NONE` |
| `get_task_status` | `READ_ONLY` | `NONE` |
| `provide_information` | `MUTATING_NON_EXECUTING` | `NONE` |
| `prepare_task` | `MUTATING_NON_EXECUTING` | `NONE` |
| `inspect_dataset` | `READ_ONLY` | `NONE` |
| `request_approval` | `AUTHORIZATION_CHANGING` | `TRUSTED_USER_PLAN_APPROVAL` |
| `execute_ranker` | `EXECUTING` | `TRUSTED_USER_EXECUTION_CONFIRMATION` |
| `analyze_results` | `APPEND_ONLY_ARTIFACT` | `NONE` |

`analyze_results` is not read-only: it creates a new append-only analysis
directory and never overwrites an earlier analysis artifact.

## Untrusted request boundary

Adapter request models use Pydantic `extra="forbid"`, are frozen after
validation, and serialize `Path` values as strings in JSON mode. Paths have
`HOST_LOCAL_PATH` semantics. A network adapter must map or constrain paths to
an adapter-owned workspace root; it must not expose arbitrary host filesystem
access merely because the Python Tool API accepts `Path` values.

The adapter request schemas intentionally differ from the full internal Python
function signatures. Host-owned provenance and authorization facts are absent
from untrusted schemas and listed separately as `host_injected_fields`.

For example:

- `prepare_task` does not accept `provider_name` from an untrusted request;
- `request_approval` accepts only `bundle_dir` from an untrusted request;
- `execute_ranker` accepts only `bundle_dir` from an untrusted request.

The catalog validator rejects a catalog that exposes any of these host fields
through an untrusted request schema:

- `provider_name`;
- `approved_by`;
- `approval_confirmed`;
- `approval_note`;
- `acknowledge_smoke_test`;
- `execution_confirmed`.

## Authorization boundary

A model asking for approval or execution is not user authorization. A future
host runtime must obtain the real user's decision through a trusted UI or
authenticated channel and inject an authorization context independently of
the model-authored arguments.

Until that trusted runtime authorization object and adapter enforcement are
implemented and tested, external adapters must not expose
`request_approval` or `execute_ranker` as directly callable model tools. The
existing internal Tool API confirmation booleans remain available for backward
compatibility; they are not part of the untrusted adapter request contract.

BinderRanker's existing approval record, single-use execution guard, file
fingerprints, and scientific completion validation remain the final domain
guards. The catalog does not weaken or replace them.

## Current compatibility boundary

This first v0.6 slice adds discovery and schema enforcement without changing:

- the eight existing Tool function signatures;
- scoring, ranking, or screening behavior;
- the frozen Ranker resources;
- task execution or scientific completion semantics;
- the optional built-in Agent architecture.

The next bounded Tool/API slice is trusted runtime authorization injection,
followed by adapter-level error envelopes and one deliberately selected thin
external adapter.
