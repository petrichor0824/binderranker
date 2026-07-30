from pathlib import Path

import pytest

from protein_design_agent.agent.workspace_tasks import (
    DEFAULT_TASK_NAME,
    TaskPathError,
    resolve_task_bundle,
    validate_task_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "default",
        "group_a",
        "munc18-syntaxin",
        "3c98_test",
        "第一组",
        "第一组_A",
    ],
)
def test_valid_task_names_are_preserved(
    name: str,
) -> None:
    assert validate_task_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        " group_a",
        "group_a ",
        ".",
        "..",
        "../group_b",
        "group/a",
        r"group\b",
        "/absolute",
        "group a",
        ".hidden",
        "-option",
        "runs",
        "RUNS",
        "con",
        "COM1",
    ],
)
def test_unsafe_task_names_are_rejected(
    name: str,
) -> None:
    with pytest.raises(TaskPathError):
        validate_task_name(name)


def test_task_name_length_is_limited() -> None:
    with pytest.raises(
        TaskPathError,
        match="过长",
    ):
        validate_task_name("a" * 65)


def test_different_tasks_have_different_bundles(
    tmp_path: Path,
) -> None:
    group_a = resolve_task_bundle(
        workspace_dir=tmp_path,
        task_name="group_a",
    )
    group_b = resolve_task_bundle(
        workspace_dir=tmp_path,
        task_name="group_b",
    )

    assert group_a == (
        tmp_path / "runs" / "group_a"
    ).resolve()
    assert group_b == (
        tmp_path / "runs" / "group_b"
    ).resolve()
    assert group_a != group_b


def test_default_task_uses_default_bundle(
    tmp_path: Path,
) -> None:
    result = resolve_task_bundle(
        workspace_dir=tmp_path,
        task_name=DEFAULT_TASK_NAME,
    )

    assert result == (
        tmp_path / "runs" / "default"
    ).resolve()


def test_resolver_does_not_create_directories(
    tmp_path: Path,
) -> None:
    result = resolve_task_bundle(
        workspace_dir=tmp_path,
        task_name="group_a",
    )

    assert not result.exists()
    assert not (
        tmp_path / "runs"
    ).exists()


def test_runs_symlink_cannot_escape_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"

    workspace.mkdir()
    outside.mkdir()

    try:
        (
            workspace / "runs"
        ).symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "当前平台不允许创建目录符号链接"
        )

    with pytest.raises(
        TaskPathError,
        match="超出",
    ):
        resolve_task_bundle(
            workspace_dir=workspace,
            task_name="group_a",
        )


def test_existing_task_symlink_cannot_escape_runs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    runs = workspace / "runs"
    outside = tmp_path / "outside"

    runs.mkdir(parents=True)
    outside.mkdir()

    try:
        (
            runs / "group_a"
        ).symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "当前平台不允许创建目录符号链接"
        )

    with pytest.raises(
        TaskPathError,
        match="超出",
    ):
        resolve_task_bundle(
            workspace_dir=workspace,
            task_name="group_a",
        )
