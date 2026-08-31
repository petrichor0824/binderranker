import json
import queue
import subprocess
import sys
import threading
from importlib.metadata import version
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI
    import tomli as tomllib

from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "runs" / "codex_probe").mkdir(parents=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace


def test_local_mcp_host_probe_uses_real_stdio_subprocess(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_local_mcp_host.py",
            "--python",
            sys.executable,
            "--workspace",
            str(workspace),
            "--task-name",
            "codex_probe",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["transport"] == "MCP_STDIO_SUBPROCESS"
    assert report["client_mode"] == "legacy"
    assert report["protocol_version"] in {
        "2025-06-18",
        "2025-11-25",
    }
    assert report["server_name"] == "BinderRanker"
    assert report["server_version"] == version("binderranker")
    assert report["server_instructions_received"] is True
    assert report["tool_names"] == [
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
        "get_result_summary",
        "list_tasks",
    ]
    assert report["all_tools_read_only"] is True
    assert report["protected_tools_absent"] is True
    assert report["task_list_call"] == {
        "ok": True,
        "total_task_count": 1,
        "returned_task_count": 1,
        "contains_probe_task": True,
    }
    assert report["status_call"] == {
        "ok": True,
        "current_stage": "EMPTY",
    }
    assert report["closed_failure_call"] == {
        "is_error": True,
        "error_code": "TOOL_REJECTED",
    }
    assert report["result_summary_closed_failure_call"] == {
        "is_error": True,
        "error_code": "TOOL_REJECTED",
    }
    assert report["capability_resource"] == {
        "read_only": True,
        "execution_operations_exposed": False,
        "host_paths_exposed": False,
        "scientific_evidence_status": "SCIENTIFIC_VALIDATION_PENDING",
    }
    assert str(workspace.resolve()) not in completed.stdout
    assert str(Path(sys.executable).resolve()) not in completed.stdout


def test_stdio_tool_discovery_supports_codex_2025_06_18_protocol(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "protein_design_agent.adapters.mcp_entrypoint",
            "--workspace",
            str(workspace),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    response_lines: queue.Queue[str | None] = queue.Queue()

    def collect_responses() -> None:
        for line in process.stdout:
            response_lines.put(line)
        response_lines.put(None)

    reader = threading.Thread(target=collect_responses, daemon=True)
    reader.start()

    def send(payload: dict[str, object]) -> None:
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def receive(request_id: int) -> dict[str, object]:
        while True:
            try:
                line = response_lines.get(timeout=15)
            except queue.Empty as exc:
                raise AssertionError(
                    f"timed out waiting for MCP response {request_id}"
                ) from exc
            if line is None:
                raise AssertionError(
                    f"MCP server closed before response {request_id}"
                )
            response = json.loads(line)
            if response.get("id") == request_id:
                return response

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "codex-compatibility-regression",
                        "version": "1",
                    },
                },
            }
        )
        initialize = receive(0)
        send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
        )
        tools_page = receive(1)
        process.stdin.close()
        returncode = process.wait(timeout=15)
        stderr = process.stderr.read()
        assert returncode == 0, stderr
    finally:
        if not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert initialize["result"]["protocolVersion"] == "2025-06-18"
    assert [
        tool["name"] for tool in tools_page["result"]["tools"]
    ] == [
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
        "get_result_summary",
        "list_tasks",
    ]
    assert [
        tool["outputSchema"]["type"]
        for tool in tools_page["result"]["tools"]
    ] == ["object", "object", "object", "object", "object"]


def test_codex_project_config_example_is_forward_safe() -> None:
    example = Path(
        "configs/integrations/codex-mcp.toml.example"
    ).read_text(encoding="utf-8")
    rendered = example.replace(
        "<ABSOLUTE_PYTHON_EXECUTABLE>",
        "C:/Python/python.exe",
    ).replace(
        "<ABSOLUTE_INITIALIZED_BINDERRANKER_WORKSPACE>",
        "D:/BinderRanker/workspace",
    )
    config = tomllib.loads(rendered)
    server = config["mcp_servers"]["binderranker_readonly"]

    assert server["command"] == "C:/Python/python.exe"
    assert server["args"][:2] == [
        "-m",
        "protein_design_agent.adapters.mcp_entrypoint",
    ]
    assert server["enabled_tools"] == [
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
        "get_result_summary",
        "list_tasks",
    ]
    assert server["default_tools_approval_mode"] == "writes"
    assert server["required"] is False


def test_local_mcp_host_probe_failure_is_path_free(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_local_mcp_host.py",
            "--python",
            sys.executable,
            "--workspace",
            str(workspace),
            "--task-name",
            "missing_task",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "local MCP host validation failed" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert str(workspace.resolve()) not in completed.stderr
    assert str(Path(sys.executable).resolve()) not in completed.stderr
