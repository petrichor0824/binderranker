import json
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

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
    assert report["server_name"] == "BinderRanker"
    assert report["server_version"] == version("binderranker")
    assert report["server_instructions_received"] is True
    assert report["tool_names"] == [
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
    ]
    assert report["all_tools_read_only"] is True
    assert report["protected_tools_absent"] is True
    assert report["status_call"] == {
        "ok": True,
        "current_stage": "EMPTY",
    }
    assert report["closed_failure_call"] == {
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
