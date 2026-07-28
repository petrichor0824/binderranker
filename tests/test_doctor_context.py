from pathlib import Path

from protein_design_agent.agent.doctor import (
    is_agent_workspace,
    is_source_checkout,
    resolve_doctor_context,
)


def create_workspace(
    root: Path,
) -> None:
    (
        root
        / "configs"
        / "models"
    ).mkdir(parents=True)

    (root / "data").mkdir()
    (root / "runs").mkdir()


def create_source_checkout(
    root: Path,
) -> None:
    (
        root
        / "src"
        / "protein_design_agent"
    ).mkdir(parents=True)

    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "protein-design-agent"\n',
        encoding="utf-8",
    )


def test_detects_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    create_workspace(workspace)

    assert is_agent_workspace(workspace)
    assert not is_source_checkout(workspace)

    mode, root, check = (
        resolve_doctor_context(
            start_directory=workspace,
        )
    )

    assert mode == "WORKSPACE"
    assert root == workspace.resolve()
    assert check.status == "PASS"


def test_explicit_workspace_is_valid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    create_workspace(workspace)

    mode, root, check = (
        resolve_doctor_context(
            project_root=workspace,
        )
    )

    assert mode == "WORKSPACE"
    assert root == workspace.resolve()
    assert check.status == "PASS"


def test_explicit_source_checkout_is_valid(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    create_source_checkout(source)

    mode, root, check = (
        resolve_doctor_context(
            project_root=source,
        )
    )

    assert mode == "SOURCE_CHECKOUT"
    assert root == source.resolve()
    assert check.status == "PASS"


def test_invalid_explicit_root_fails(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "ordinary-directory"
    invalid.mkdir()

    mode, root, check = (
        resolve_doctor_context(
            project_root=invalid,
        )
    )

    assert mode == "INVALID_ROOT"
    assert root == invalid.resolve()
    assert check.status == "FAIL"
