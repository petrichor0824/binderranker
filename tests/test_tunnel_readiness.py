import json
from pathlib import Path

import pytest

from protein_design_agent.adapters import tunnel_readiness
from protein_design_agent.adapters.mcp_entrypoint import main as mcp_main
from protein_design_agent.agent.workspace_init import WORKSPACE_MARKER_TEMPLATE


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    (workspace / ".pda-workspace.json").write_text(
        WORKSPACE_MARKER_TEMPLATE,
        encoding="utf-8",
    )
    return workspace


def test_private_tunnel_preflight_reports_only_locally_provable_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setattr(
        tunnel_readiness,
        "installed_mcp_version",
        lambda: "2.1.1",
    )

    report = tunnel_readiness.assess_private_tunnel_readiness(workspace)
    encoded = report.model_dump_json()

    assert report.status == "READY_FOR_PRIVATE_TUNNEL_CONFIGURATION"
    assert report.local_preflight_passed is True
    assert report.local_transport == "MCP_STDIO"
    assert report.tunnel_target_mode == "STDIO_COMMAND"
    assert report.public_network_listener_exposed is False
    assert report.inbound_firewall_port_required is False
    assert report.tenant_scope == "SINGLE_TRUST_DOMAIN"
    assert report.exposed_operations == (
        "get_current_plan",
        "get_task_status",
        "inspect_dataset",
    )
    assert report.protected_operations_exposed is False
    assert report.caller_identity_contract_available is False
    assert report.trusted_human_confirmation_bridge_available is False
    assert report.openai_control_plane_access_verified is False
    assert report.live_tunnel_connection_verified is False
    assert report.blocking_reasons == ()
    assert str(workspace.resolve()) not in encoded


@pytest.mark.parametrize(
    ("sdk_version", "blocker"),
    [
        (None, "MCP_SDK_NOT_INSTALLED"),
        ("1.12.0", "MCP_SDK_VERSION_UNSUPPORTED"),
        ("3.0.0", "MCP_SDK_VERSION_UNSUPPORTED"),
    ],
)
def test_private_tunnel_preflight_blocks_missing_or_unsupported_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sdk_version: str | None,
    blocker: str,
) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setattr(
        tunnel_readiness,
        "installed_mcp_version",
        lambda: sdk_version,
    )

    report = tunnel_readiness.assess_private_tunnel_readiness(workspace)

    assert report.status == "BLOCKED"
    assert report.local_preflight_passed is False
    assert blocker in report.blocking_reasons


def test_private_tunnel_preflight_blocks_invalid_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tunnel_readiness,
        "installed_mcp_version",
        lambda: "2.1.1",
    )

    report = tunnel_readiness.assess_private_tunnel_readiness(tmp_path)

    assert report.status == "BLOCKED"
    assert report.workspace_valid is False
    assert report.blocking_reasons == ("WORKSPACE_INVALID_OR_UNSAFE",)


def test_tunnel_readiness_cli_emits_json_and_does_not_start_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setattr(
        tunnel_readiness,
        "installed_mcp_version",
        lambda: "2.1.1",
    )

    mcp_main(
        [
            "--workspace",
            str(workspace),
            "--check-tunnel-readiness",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["local_preflight_passed"] is True
    assert payload["live_tunnel_connection_verified"] is False
    assert str(workspace.resolve()) not in json.dumps(payload)


def test_tunnel_readiness_cli_uses_nonzero_exit_for_blocked_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.setattr(
        tunnel_readiness,
        "installed_mcp_version",
        lambda: None,
    )

    with pytest.raises(SystemExit) as raised:
        mcp_main(
            [
                "--workspace",
                str(workspace),
                "--check-tunnel-readiness",
            ]
        )

    assert raised.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["blocking_reasons"] == ["MCP_SDK_NOT_INSTALLED"]
