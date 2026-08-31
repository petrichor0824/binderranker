# BinderRanker private remote-MCP security contract

This document defines the Phase 5A boundary for connecting BinderRanker's
read-only MCP server to remote Agent surfaces. It is a threat model and local
readiness contract, not evidence that a live tunnel or OpenAI account has been
configured.

## Decision

Use the existing local `stdio` MCP server through OpenAI Secure MCP Tunnel for
the first private remote integration. Do not add a public HTTP listener.

Secure MCP Tunnel is an outbound-only transport: `tunnel-client` runs inside
the network that can reach BinderRanker, authenticates to the OpenAI control
plane, forwards MCP requests to the local stdio command, and returns responses
through the same tunnel. The BinderRanker process remains private and does not
open an inbound firewall port.

Primary references, reviewed on 2026-08-27:

- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [OpenAI MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)

This design is suitable for private developer and controlled-workspace use. It
is not a public plugin endpoint and it is not a multi-tenant BinderRanker
service.

## Trust boundaries

| Boundary | Owner | BinderRanker guarantee |
| --- | --- | --- |
| Scientific state and managed task paths | BinderRanker | One initialized workspace per process; external callers submit only `task_name` |
| Tool registration and result projection | BinderRanker | Five read-only tools; no host paths, raw request text, or protected operations |
| Tunnel runtime authentication | OpenAI Platform and `tunnel-client` operator | Not accepted, stored, or inferred by BinderRanker |
| Organization/workspace tunnel access | OpenAI Platform/ChatGPT administration | Not locally observable; reported as unverified |
| Model Tool approval | Agent host/developer | Useful host policy, but not BinderRanker trusted execution authorization |
| Scientific performance claims | BinderRanker evidence policy | Remains `SCIENTIFIC_VALIDATION_PENDING` |

The current adapter is single trust domain. Every caller that can reach the
configured tunnel can read the same managed BinderRanker workspace through the
same five path-free tools. There is no per-user workspace routing or
BinderRanker-side identity contract.

## Threat analysis

### Arbitrary filesystem access

Threat: a remote model submits an absolute path, traversal sequence, or symlink
to inspect another directory.

Control: MCP inputs contain only a validated managed `task_name`. BinderRanker
resolves `<workspace>/runs/<task_name>`, rejects traversal, missing tasks,
symlink task bundles, and an unsafe `runs` root.

### Host-data disclosure

Threat: plans, errors, warnings, or dataset evidence reveal host-local paths,
credentials, stored raw prompts, or exception details.

Control: successful results use explicit external view models. Unsafe
structured scientific tokens fail closed through the shared sanitized error
envelope. Raw exception text and validation inputs are never returned.

### Unauthorized mutation or execution

Threat: an Agent calls preparation, approval, execution, or analysis-write
operations through the tunnel.

Control: those operations are not registered. The MCP server exposes only
`get_current_plan`, `get_task_status`, `inspect_dataset`, the sealed read-only
`get_result_summary`, and bounded read-only `list_tasks`. Host-side MCP
approval cannot create BinderRanker's in-process authorization capability.

### Cross-tenant access

Threat: one external identity reads another user's workspace.

Control: Phase 5A makes no multi-tenant claim. Deploy one BinderRanker process,
workspace, and tunnel association per trust domain. A shared multi-user service
requires authenticated identity propagation and explicit workspace mapping
before implementation.

### Credential leakage

Threat: OpenAI runtime keys or tunnel credentials enter MCP arguments, results,
logs, or repository files.

Control: BinderRanker does not accept these credentials. Configure
`tunnel-client` through its documented runtime environment and local profile;
never place keys in `--mcp-command`, BinderRanker task files, or Git.

### Public ingress expansion

Threat: a local development server is exposed directly to the Internet without
TLS, authentication, rate limits, or tenant isolation.

Control: BinderRanker continues to provide stdio only. Phase 5A neither starts
an HTTP server nor opens a port. Public plugin distribution remains a separate
architecture and security review.

### Audit ambiguity

Threat: transport authentication logs are mistaken for BinderRanker scientific
or authorization audit evidence.

Control: tunnel control-plane and host app logs remain owned by OpenAI and the
host. BinderRanker does not add generic audit infrastructure in this slice.
Any future protected operation must retain BinderRanker's task-, action-,
review-hash-, and confirmation-bound domain audit independently.

## Local readiness preflight

Install the optional MCP dependency and validate an initialized workspace:

```bash
python -m pip install "binderranker[mcp]"
binderranker-mcp \
  --workspace /absolute/path/to/workspace \
  --check-tunnel-readiness
```

A successful report has status
`READY_FOR_PRIVATE_TUNNEL_CONFIGURATION`. It proves only:

- the BinderRanker workspace is initialized and path-safe;
- the supported MCP SDK major version is installed;
- the server is local stdio with no public listener;
- exactly five read-only operations remain exposed;
- protected operations and trusted confirmation remain unavailable.

The report intentionally keeps these fields false:

- `openai_control_plane_access_verified`;
- `live_tunnel_connection_verified`;
- `caller_identity_contract_available`;
- `trusted_human_confirmation_bridge_available`.

It contains no workspace path or credential.

A blocked report uses stable local reason codes:

- `WORKSPACE_INVALID_OR_UNSAFE`;
- `MCP_SDK_NOT_INSTALLED`;
- `MCP_SDK_VERSION_UNSUPPORTED`.

## Operator-controlled tunnel setup

After local preflight passes, an authorized operator can follow the current
OpenAI documentation. A typical stdio profile has this shape:

```bash
export CONTROL_PLANE_API_KEY="<runtime key>"

tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile binderranker-readonly \
  --tunnel-id tunnel_<id> \
  --mcp-command "binderranker-mcp --workspace /absolute/path/to/workspace"

tunnel-client doctor --profile binderranker-readonly --explain
tunnel-client run --profile binderranker-readonly
```

The operator must separately verify:

1. the intended Platform organization and ChatGPT workspace associations;
2. Tunnels Read + Use permissions, and Manage permission when creating or
   editing the tunnel;
3. ChatGPT developer-mode permission when that surface is used;
4. outbound HTTPS reachability and tunnel-client health;
5. actual Tool discovery and calls from the selected OpenAI surface.

Until that end-to-end check occurs, BinderRanker reports local configuration
readiness only.

## Deferred gates

The following remain blocked after a successful read-only tunnel test:

- public HTTP or public plugin publication;
- multi-tenant routing;
- BinderRanker-side caller identity;
- approval, execution, mutation, and analysis-write MCP tools;
- treating host MCP approval as trusted BinderRanker confirmation;
- any scientific performance or wet-lab success claim.
