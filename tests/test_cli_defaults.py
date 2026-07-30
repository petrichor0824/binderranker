from pathlib import Path

import protein_design_agent.cli_defaults as module
from protein_design_agent.cli_defaults import (
    resolve_chat_bundle_dir,
    resolve_local_approved_by,
)


def test_explicit_bundle_path_has_priority(
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "custom-bundle"

    assert resolve_chat_bundle_dir(
        explicit
    ) == explicit.resolve()


def test_default_bundle_is_inside_current_directory(
    tmp_path: Path,
) -> None:
    result = resolve_chat_bundle_dir(
        None,
        cwd=tmp_path,
    )

    assert result == (
        tmp_path
        / ".protein-design-agent"
        / "bundles"
        / "default"
    ).resolve()


def test_explicit_approved_by_is_preserved() -> None:
    assert resolve_local_approved_by(
        "  researcher  "
    ) == "researcher"


def test_system_username_is_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module.getpass,
        "getuser",
        lambda: "local-tester",
    )

    assert resolve_local_approved_by(
        None
    ) == "local-tester"


def test_empty_username_has_safe_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module.getpass,
        "getuser",
        lambda: "",
    )

    assert resolve_local_approved_by(
        None
    ) == "local-user"
