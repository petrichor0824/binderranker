# Codex local MCP integration

This runbook covers the v0.6 Phase 5B-local path: a local Codex client starts
BinderRanker's read-only MCP server as a stdio subprocess. It requires no
OpenAI API key and opens no network listener.

The official Codex MCP documentation confirms that the ChatGPT desktop app,
Codex CLI, and IDE extension support local stdio servers and share MCP
configuration on the same host:

- [OpenAI Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

This is local interoperability evidence. It is not a successful Secure MCP
Tunnel test and it does not establish remote availability.

## Prerequisites

Install BinderRanker with the optional MCP dependency and initialize a
dedicated workspace:

```bash
python -m pip install "binderranker[mcp]"
binderranker init --destination /absolute/path/to/workspace
```

The Python executable used by Codex must be the same environment that contains
BinderRanker and the supported MCP SDK. Keep scientific datasets outside the
source checkout.

## Validate the real stdio boundary

Create or select an existing empty managed task, then run the subprocess probe:

```bash
python scripts/verify_local_mcp_host.py \
  --python /absolute/path/to/python \
  --workspace /absolute/path/to/workspace \
  --task-name existing_task
```

Unlike an in-process unit test, this command launches
`protein_design_agent.adapters.mcp_entrypoint` as a child process and exchanges
MCP JSON-RPC over stdin/stdout. A successful path-free JSON report proves:

- MCP initialization returns the BinderRanker name, installed version, and
  read-only server instructions;
- exactly `get_current_plan`, `get_task_status`, and `inspect_dataset` are
  discoverable;
- all three Tools are annotated read-only and non-destructive;
- a valid task-status call succeeds;
- an invalid empty-dataset inspection fails closed through the shared stable
  error envelope;
- the capability resource declares no execution access, no host-path
  disclosure, and `SCIENTIFIC_VALIDATION_PENDING`.

The report never includes the Python executable or workspace path.

## Configure Codex

The repository provides
`configs/integrations/codex-mcp.toml.example`. Copy its server table into a
trusted project's `.codex/config.toml` or the user's `~/.codex/config.toml`,
then replace both placeholders with absolute local paths.

The equivalent configuration shape is:

```toml
[mcp_servers.binderranker_readonly]
command = "/absolute/path/to/python"
args = [
  "-m",
  "protein_design_agent.adapters.mcp_entrypoint",
  "--workspace",
  "/absolute/path/to/workspace",
]
startup_timeout_sec = 20
tool_timeout_sec = 60
enabled = true
required = false
enabled_tools = [
  "get_current_plan",
  "get_task_status",
  "inspect_dataset",
]
default_tools_approval_mode = "writes"
```

Alternatively, in the ChatGPT desktop app open **Settings → MCP servers → Add
server**, choose **STDIO**, enter the same command and arguments, save, and
select **Restart**. In a refreshed Codex session, use `/mcp` to confirm the
server and Tool list.

`enabled_tools` is a host-side allow list in addition to BinderRanker's own
three-Tool registration boundary. The `writes` approval mode permits correctly
annotated read-only calls while ensuring that any future non-read-only Tool
would require confirmation. It does not grant BinderRanker execution
authorization.

## Security and scientific boundary

- Bind one process to one initialized workspace and one trust domain.
- Do not add credentials to the command, arguments, task files, or repository.
- External callers submit only a managed `task_name`, never a path.
- Codex host approval is not BinderRanker's trusted scientific execution
  authorization.
- Preparation, approval, execution, and analysis-write Tools remain absent.
- Scientific performance remains pending real-data validation.

## Acceptance status

Phase 5B-local is complete only when both layers pass:

1. the deterministic subprocess probe passes in a clean supported environment;
2. a refreshed local Codex client lists the server and the same three Tools.

Remote Secure MCP Tunnel acceptance remains a separate credential-dependent
checkpoint.
