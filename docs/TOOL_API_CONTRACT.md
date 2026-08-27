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
runtime entrypoints for all eight public operations. It also publishes the
shared adapter error schema and its complete stable error-code inventory.

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

## Adapter error boundary

All HTTP, MCP, workflow, and external-Agent adapters must normalize failures
with `protein_design_agent.agent.tool_adapter_errors`. Successful Tool results
remain the existing operation-specific Pydantic models; they are not wrapped or
changed. Ordinary failures become an `AdapterErrorEnvelope` with schema version
`0.1`:

```json
{
  "schema_version": "0.1",
  "ok": false,
  "operation": "execute_ranker",
  "error": {
    "code": "AUTHORIZATION_REJECTED",
    "category": "AUTHORIZATION",
    "message": "The trusted authorization was rejected or is no longer valid.",
    "retryable": false,
    "recovery_action": "REAUTHORIZE",
    "validation_issue_count": 0,
    "validation_issues": []
  }
}
```

The published codes are:

| Code | Meaning | Recovery action |
| --- | --- | --- |
| `INVALID_REQUEST` | Request failed the published Pydantic schema | `CORRECT_REQUEST` |
| `UNKNOWN_OPERATION` | Name is outside the published Tool inventory | `SELECT_PUBLISHED_OPERATION` |
| `AUTHORIZATION_REQUIRED` | A fresh trusted user decision is required | `OBTAIN_TRUSTED_AUTHORIZATION` |
| `AUTHORIZATION_REJECTED` | Capability is invalid, expired, consumed, or out of scope | `REAUTHORIZE` |
| `TOOL_REJECTED` | Domain state does not permit the operation | `REVIEW_TASK_STATE` |
| `SCIENTIFIC_RESULT_INVALID` | Process output failed scientific semantic validation | `REVIEW_SCIENTIFIC_OUTPUT` |
| `EXECUTION_FAILED` | Local BinderRanker execution did not complete | `INSPECT_EXECUTION_EVIDENCE` |
| `INTERNAL_ERROR` | Unexpected adapter/runtime failure | `CONTACT_OPERATOR` |

`retryable` is deliberately `false` for every v0.1 code. The adapter contract
does not yet provide idempotency keys, so a host must not automatically replay
a mutation, approval, or execution call. Recovery means that the host or user
must perform the declared action and submit a new request, not blindly retry
the same call.

The external envelope never contains:

- raw exception text or exception class names;
- traceback or chained internal diagnostics;
- host filesystem paths;
- credentials, tokens, capability identifiers, subprocess stderr, or request
  values copied from validation errors.

For `INVALID_REQUEST`, `validation_issues` contains only a bounded list of
published top-level request-field locations and stable Pydantic error types.
Unknown or extra locations are reported as `$`, so caller-controlled keys are
not reflected. The original exception chain remains available only inside the
trusted host process for logging under that host's own privacy policy. Unknown
operation names are likewise not reflected and use `operation=null`. Unknown
exceptions fail closed as `INTERNAL_ERROR`.

```python
from protein_design_agent.agent.tool_adapter_errors import (
    invoke_adapter_boundary,
)

result_or_error = invoke_adapter_boundary(
    operation="get_task_status",
    call=lambda: tool_api.get_task_status(bundle_dir=bundle_dir),
)
```

The shared boundary catches ordinary `Exception` values only. Process-control
signals such as `KeyboardInterrupt` and `SystemExit` are not converted into Tool
responses.

## Current compatibility boundary

The first four v0.6 slices add discovery, schema enforcement, trusted
in-process authorization, a stable adapter failure contract, and one local
read-only MCP adapter without changing:

- the eight existing Tool function signatures;
- scoring, ranking, or screening behavior;
- the frozen Ranker resources;
- task execution or scientific completion semantics;
- the optional built-in Agent architecture.

The MCP adapter accepts only managed `task_name` values inside one
BinderRanker-initialized workspace. It exposes `get_current_plan`,
`get_task_status`, and `inspect_dataset`, calls this Tool API directly, maps
successes into explicit path-free external views, and maps failures through
`AdapterErrorEnvelope` with MCP `isError=true`. The optional dependency is
`mcp>=2,<3`; the base BinderRanker installation does not import or require it.

Protected and mutating operations remain deferred. They must not be registered
until a concrete host can provide authenticated user identity and verifiable,
independent confirmation events to the trusted runtime. The current server is
local `stdio` only; it is not an unauthenticated HTTP or remote API service.

See `docs/integrations/MCP.md` for the selection evidence, installation, host
configuration, workspace boundary, and scientific limitations.

Phase 5A adds no Tool and changes no Tool signature. The existing stdio server
may be used through OpenAI Secure MCP Tunnel after the local
`--check-tunnel-readiness` contract passes. That preflight verifies only local
workspace, dependency, transport, and read-only scope facts. It does not grant
authority, verify a caller identity, confirm OpenAI control-plane access, or
establish a live connection. See
`docs/integrations/REMOTE_MCP_SECURITY.md` for the threat model.
