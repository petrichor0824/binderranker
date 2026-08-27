# BinderRanker read-only MCP integration

BinderRanker ships an optional, local MCP adapter for external tools and Agent
hosts. The adapter is an access layer over the existing BinderRanker Tool API;
it does not contain ranking, screening, approval, execution, result-validation,
or provenance logic.

## Current scope

The v0.6 first slice exposes exactly three model-callable tools:

| MCP tool | Behavior |
| --- | --- |
| `get_current_plan` | Read the canonical plan for a managed task |
| `get_task_status` | Read planning and execution lifecycle state |
| `inspect_dataset` | Run deterministic, read-only inspection of the dataset recorded by the task |

The server also exposes the application-controlled resource
`binderranker://adapter/capabilities`. It declares the exposed and deferred
operations, path policy, scientific-evidence status, and absence of execution
capability.

The following operations are deliberately **not** registered as MCP tools:

- `prepare_task`;
- `provide_information`;
- `request_approval`;
- `execute_ranker`;
- `analyze_results`.

No MCP call can approve or execute BinderRanker in this slice. A model or MCP
client claiming that a user approved an action is not sufficient evidence for
BinderRanker's trusted authorization runtime.

## Why MCP was selected

The selection gate was reviewed on 2026-08-26 against current primary sources:

- the OpenAI Responses API supports remote MCP servers and explicit host-side
  approval policies;
- the official MCP Python SDK v2 is the stable line, supports structured output
  and in-memory protocol testing, and uses `stdio` as the default local
  transport;
- MCP tool annotations can describe read-only, idempotent, closed-world tools,
  while BinderRanker retains its own domain authorization and scientific
  guards.

References:

- [OpenAI MCP and Connectors guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK v2 changes](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md)
- [MCP Python SDK server transport guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md)

MCP was preferred over a vendor-specific Agent plugin because it preserves a
neutral Tool boundary and is supported by multiple host ecosystems. OpenClaw,
DeepSeek Harness, generic HTTP, and framework-specific wrappers remain possible
later adapters; they should reuse this boundary rather than reimplement it.

## Install

Install BinderRanker with the optional official MCP SDK dependency:

```bash
python -m pip install "binderranker[mcp]"
```

Initialize a BinderRanker workspace if needed:

```bash
binderranker init --destination /path/to/workspace
```

The configured workspace must contain the managed `runs` directory and
`.pda-workspace.json` marker created by BinderRanker.

## Host configuration

Configure a local MCP host to launch:

```text
binderranker-mcp --workspace /path/to/workspace
```

A typical host configuration has this shape:

```json
{
  "mcpServers": {
    "binderranker": {
      "command": "binderranker-mcp",
      "args": [
        "--workspace",
        "/path/to/workspace"
      ]
    }
  }
}
```

Use an absolute workspace path in host configuration. Do not add API keys or
other secrets to the MCP arguments.

Validate local private-tunnel prerequisites without starting the server:

```bash
binderranker-mcp \
  --workspace /path/to/workspace \
  --check-tunnel-readiness
```

The JSON report is path-free and credential-free. A PASS means only that the
local workspace, MCP SDK, stdio transport, and read-only Tool scope are ready
for private tunnel configuration. It never claims that OpenAI permissions,
runtime authentication, or a live tunnel have been verified.

For an API-key-free local Codex integration, use the project-safe configuration
template and real stdio subprocess probe in
[`CODEX_LOCAL_MCP.md`](CODEX_LOCAL_MCP.md). That path validates local Host
interoperability only; it does not convert local evidence into remote tunnel
evidence.

## Workspace and disclosure boundary

External calls accept `task_name`, not `bundle_dir` or another path. The
adapter resolves the task only as `<workspace>/runs/<task_name>` and rejects:

- absolute paths;
- `.` and `..` traversal;
- path separators and invalid task names;
- missing task directories;
- symbolic-link task bundles;
- a `runs` directory that escapes the configured workspace.

Successful MCP views intentionally omit:

- host-local bundle, planning-session, manifest, dataset, and artifact paths;
- stored free-form request text;
- free-form internal warnings and exceptions that may contain host details.

They retain controlled scientific state, counts, chain evidence, candidate
configuration fields, checksums, and stable lifecycle semantics. Failures use
the shared `AdapterErrorEnvelope`; MCP also marks them with `isError=true`.

## Transport boundary

The BinderRanker server supports **local `stdio` only**. It does not open a
port, provide OAuth, publish a remote URL, or make a private workstation
reachable from the Internet.

OpenAI Secure MCP Tunnel can connect supported OpenAI surfaces to this private
stdio server through an outbound-only tunnel-client process. This avoids a
public BinderRanker HTTP endpoint and is the approved Phase 5A route for private
testing. See [`REMOTE_MCP_SECURITY.md`](REMOTE_MCP_SECURITY.md) for the threat
model, local preflight semantics, operator-controlled setup, and remaining
identity and authorization gates.

Do not expose this local server directly as an unauthenticated HTTP endpoint.
The tunnel authenticates and transports requests at the OpenAI control-plane
boundary, but BinderRanker still receives no trusted per-user identity and has
no external human-confirmation bridge. Deploy only one workspace per trust
domain.

## Scientific boundary

MCP interoperability is an engineering capability. It does not establish
BinderRanker ranking quality, biological predictive accuracy, cross-target
generalization, or wet-lab success. The adapter reports
`SCIENTIFIC_VALIDATION_PENDING` and `performance_claims_established=false`.
