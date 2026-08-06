from pathlib import Path

import pytest

from protein_design_agent.agent.workspace_init import (
    WorkspaceInitError,
    initialize_workspace,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


def test_initialize_workspace_creates_expected_tree(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"

    report = initialize_workspace(
        destination
    )

    expected_files = (
        (
            destination
            / "configs"
            / "models"
            / "deepseek.local.yaml"
        ),
        destination / ".env.example",
        destination / ".gitignore",
        destination / "QUICKSTART.md",
    )

    for path in expected_files:
        assert path.is_file()

    assert (
        destination / "data"
    ).is_dir()

    assert (
        destination / "runs"
    ).is_dir()

    assert report.destination == (
        destination.resolve()
    )

    assert report.network_accessed is False
    assert report.api_key_written is False
    assert (
        report.existing_files_overwritten
        is False
    )


def test_generated_model_config_is_valid(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"

    initialize_workspace(destination)

    config_path = (
        destination
        / "configs"
        / "models"
        / "deepseek.local.yaml"
    )

    config = load_model_provider_config(
        config_path
    )

    assert (
        config.active_profile
        == "deepseek_flash"
    )

    profile = config.profiles[
        "deepseek_flash"
    ]

    assert (
        profile.api_key_env
        == "DEEPSEEK_API_KEY"
    )

    assert profile.require_api_key is True

    assert (
        profile.base_url
        == "https://api.deepseek.com"
    )


def test_init_does_not_copy_real_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = (
        "real-secret-must-not-appear"
    )

    monkeypatch.setenv(
        "DEEPSEEK_API_KEY",
        secret,
    )

    destination = tmp_path / "workspace"

    report = initialize_workspace(
        destination
    )

    for path in report.created_files:
        content = path.read_text(
            encoding="utf-8"
        )

        assert secret not in content

    env_example = (
        destination / ".env.example"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "DEEPSEEK_API_KEY="
        in env_example
    )

    assert secret not in env_example


def test_init_rejects_existing_managed_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"
    destination.mkdir()

    existing = (
        destination / ".env.example"
    )

    existing.write_text(
        "DO_NOT_OVERWRITE=1\n",
        encoding="utf-8",
    )

    with pytest.raises(
        WorkspaceInitError
    ):
        initialize_workspace(
            destination
        )

    assert existing.read_text(
        encoding="utf-8"
    ) == "DO_NOT_OVERWRITE=1\n"

    assert not (
        destination / "QUICKSTART.md"
    ).exists()

    assert not (
        destination / "configs"
    ).exists()


def test_init_preserves_unrelated_existing_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"
    destination.mkdir()

    unrelated = destination / "notes.txt"

    unrelated.write_text(
        "keep me\n",
        encoding="utf-8",
    )

    initialize_workspace(destination)

    assert unrelated.read_text(
        encoding="utf-8"
    ) == "keep me\n"

    assert (
        destination / "QUICKSTART.md"
    ).is_file()


def test_generated_files_are_portable(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"

    report = initialize_workspace(
        destination
    )

    forbidden_values = (
        "/home/petrichor/",
        "/root/",
        ".venv/bin/python",
        (
            "/home/petrichor/"
            "protein-design-agent"
        ),
    )

    for path in report.created_files:
        content = path.read_text(
            encoding="utf-8"
        )

        for forbidden in forbidden_values:
            assert forbidden not in content


def test_ensure_workspace_is_idempotent(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.workspace_init import (
        ensure_workspace,
    )

    destination = tmp_path / "workspace"

    first = ensure_workspace(destination)
    second = ensure_workspace(destination)

    assert first.status == "CREATED"
    assert second.status == "REUSED"
    assert second.created_files == ()
    assert second.created_directories == ()


def test_ensure_workspace_preserves_edited_config(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.workspace_init import (
        ensure_workspace,
    )

    destination = tmp_path / "workspace"
    ensure_workspace(destination)

    config = (
        destination
        / "configs"
        / "models"
        / "deepseek.local.yaml"
    )

    custom_content = (
        config.read_text(encoding="utf-8")
        + "\n# user customization\n"
    )
    config.write_text(
        custom_content,
        encoding="utf-8",
    )

    report = ensure_workspace(destination)

    assert report.status == "REUSED"
    assert config.read_text(
        encoding="utf-8"
    ) == custom_content


def test_invalid_workspace_marker_is_not_accepted(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.workspace_init import (
        ensure_workspace,
    )

    destination = tmp_path / "workspace"
    destination.mkdir()

    marker = (
        destination / ".pda-workspace.json"
    )
    marker.write_text(
        '{"workspace_type":"other"}',
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceInitError):
        ensure_workspace(destination)

    assert marker.read_text(
        encoding="utf-8"
    ) == '{"workspace_type":"other"}'


def test_quickstart_explains_secure_api_key_input(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "workspace"
    initialize_workspace(destination)

    quickstart = (
        destination / "QUICKSTART.md"
    ).read_text(encoding="utf-8")

    assert "read -rsp" in quickstart
    assert (
        "DEEPSEEK_API_KEY && echo && "
        "export DEEPSEEK_API_KEY"
        in quickstart
    )
    assert (
        "终端出现提示后，粘贴真实 DeepSeek API Key"
        in quickstart
    )
    assert (
        "不要修改命令末尾的 `DEEPSEEK_API_KEY`"
        in quickstart
    )
    assert (
        'export DEEPSEEK_API_KEY="你的真实 API Key"'
        not in quickstart
    )
    assert "protein-design-agent chat" in quickstart
