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
        / "runs"
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


def test_named_chat_target_uses_independent_bundle(
    tmp_path: Path,
) -> None:
    from protein_design_agent.cli_defaults import (
        resolve_chat_target,
    )

    target = resolve_chat_target(
        bundle_dir=None,
        task_name="group_c",
        cwd=tmp_path,
    )

    assert target.task_name == "group_c"
    assert target.uses_default_workspace is True
    assert target.workspace_dir == (
        tmp_path / ".protein-design-agent"
    ).resolve()
    assert target.bundle_dir == (
        tmp_path
        / ".protein-design-agent"
        / "runs"
        / "group_c"
    ).resolve()


def test_explicit_bundle_and_task_are_ambiguous(
    tmp_path: Path,
) -> None:
    from protein_design_agent.cli_defaults import (
        resolve_chat_target,
    )

    import pytest

    with pytest.raises(
        ValueError,
        match="不能同时使用",
    ):
        resolve_chat_target(
            bundle_dir=tmp_path / "bundle",
            task_name="group_c",
        )


def test_initialized_current_workspace_is_reused(
    tmp_path: Path,
) -> None:
    marker = tmp_path / ".pda-workspace.json"
    marker.write_text("{}\n", encoding="utf-8")

    target = module.resolve_chat_target(
        bundle_dir=None,
        task_name=None,
        cwd=tmp_path,
    )

    assert target.workspace_dir == tmp_path.resolve()
    assert target.bundle_dir == (
        tmp_path / "runs" / "default"
    ).resolve()
    assert not (
        tmp_path / ".protein-design-agent"
    ).exists()
