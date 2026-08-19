from pathlib import Path

import pytest

from protein_design_agent.path_semantics import (
    IncompatiblePathError,
    detect_absolute_path_style,
    resolve_local_path,
)


def test_detects_windows_absolute_paths() -> None:
    assert (
        detect_absolute_path_style(
            r"C:\Users\Alice\data"
        )
        == "windows"
    )
    assert (
        detect_absolute_path_style(
            "C:/Users/Alice/data"
        )
        == "windows"
    )


def test_detects_posix_absolute_path() -> None:
    assert (
        detect_absolute_path_style(
            "/home/alice/data"
        )
        == "posix"
    )


def test_relative_path_has_no_absolute_style() -> None:
    assert (
        detect_absolute_path_style(
            "data/pdbs"
        )
        is None
    )


@pytest.mark.skipif(
    __import__("os").name == "nt",
    reason="POSIX-specific cross-platform regression",
)
def test_windows_absolute_path_is_not_silently_resolved_on_posix(
    tmp_path: Path,
) -> None:
    value = r"C:\Users\Alice\data\pdbs"

    with pytest.raises(
        IncompatiblePathError,
        match="Windows 风格绝对路径",
    ):
        resolve_local_path(
            value,
            base_directory=tmp_path,
            field_name="input_dir",
        )


def test_relative_path_uses_explicit_base_directory(
    tmp_path: Path,
) -> None:
    result = resolve_local_path(
        "data/pdbs",
        base_directory=tmp_path,
        field_name="input_dir",
    )

    assert result == (
        tmp_path / "data" / "pdbs"
    ).resolve()


def test_relative_path_without_base_uses_current_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = resolve_local_path(
        "data/pdbs",
        field_name="input_dir",
    )

    assert result == (
        tmp_path / "data" / "pdbs"
    ).resolve()
