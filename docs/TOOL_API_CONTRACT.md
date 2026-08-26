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
request JSON Schema, response JSON Schema, host-injected fields, and trusted
runtime entrypoints for all eight public operations.

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

A model asking for approval or execution is not user authorization. The host
runtime must obtain the real user's decision through a trusted UI or
authenticated channel. It then uses `TrustedAuthorizationBroker` to issue an
opaque capability and calls the protected operation through
`TrustedToolRuntime`.

No model-authored arguments can substitute for that host confirmation event.
The host runtime owns both authorization objects.

```python
from protein_design_agent.agent.tool_api_contract import (
    RequestApprovalToolRequest,
)
from protein_design_agent.agent.tool_runtime_authorization import (
    TrustedAuthorizationBroker,
    TrustedToolRuntime,
)

request = RequestApprovalToolRequest.model_validate(model_arguments)

# This confirmation event must come from the host, not model_arguments.
grant = broker.issue_plan_approval(
    bundle_dir=request.bundle_dir,
    authorized_by=authenticated_user,
    user_confirmed=host_confirmation,
)
result = runtime.request_approval(
    request=request,
    authorization=grant,
)
```

The broker issuance methods must never be registered as model-callable tools.
The host owns both `broker` and `runtime`; the external request receives
neither object.

### Capability guarantees

The v0.6 trusted runtime capability is:

- an in-process Python object that ordinary JSON tool arguments cannot encode;
- issued only when the host supplies `user_confirmed=True` and a non-empty
  audit identity;
- bound to one protected action and one canonical task directory;
- bound to the SHA256 of the reviewed `agent_prepare_manifest.json` or
  `approval.json` present when the user confirmed;
- valid for five minutes by default;
- atomically consumable once, including under concurrent attempts;
- invalid after a wrong-action, wrong-directory, expired, or changed-resource
  use attempt;
- accepted only by the broker instance that issued it.

`TrustedToolRuntime` is the only adapter-facing path that converts a consumed
capability into the existing internal confirmation booleans. Those booleans
remain available on the internal Python Tool API for backward compatibility;
they are not part of the untrusted adapter request contract.

Capabilities intentionally live only in memory.
Capabilities do not survive process restart.
They are not remote bearer tokens. Authentication of the human user and
collection of the confirmation event remain responsibilities of the host
adapter. A future network adapter must not serialize or transport the internal
capability.

BinderRanker's existing approval record, single-use execution guard, file
fingerprints, and scientific completion validation remain the final domain
guards. The catalog does not weaken or replace them.

## Current compatibility boundary

The first two v0.6 slices add discovery, schema enforcement, and trusted
in-process authorization without changing:

- the eight existing Tool function signatures;
- scoring, ranking, or screening behavior;
- the frozen Ranker resources;
- task execution or scientific completion semantics;
- the optional built-in Agent architecture.

The next bounded Tool/API slice is adapter-level error envelopes, followed by
one deliberately selected thin external adapter. The adapter must use this
runtime rather than exposing internal confirmation booleans.
