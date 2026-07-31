from pathlib import Path

import pytest

from protein_design_agent.agent.sample_resources import (
    PackagedSampleError,
    extract_packaged_sample,
    packaged_sample_pdb_names,
)


EXPECTED_NAMES = (
    "_1700.pdb",
    "_2577.pdb",
    "_2832.pdb",
    "_498.pdb",
    "_804.pdb",
)


def test_packaged_sample_contains_five_pdbs() -> None:
    assert packaged_sample_pdb_names() == EXPECTED_NAMES


def test_extract_packaged_sample(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "input"

    result = extract_packaged_sample(
        destination=destination
    )

    assert tuple(
        path.name
        for path in result.pdb_files
    ) == EXPECTED_NAMES

    assert all(
        path.is_file()
        and path.stat().st_size > 1000
        for path in result.pdb_files
    )


def test_nonempty_destination_is_rejected(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "input"
    destination.mkdir()

    existing = destination / "existing.txt"
    existing.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    with pytest.raises(
        PackagedSampleError,
        match="禁止覆盖",
    ):
        extract_packaged_sample(
            destination=destination
        )

    assert existing.read_text(
        encoding="utf-8"
    ) == "do not overwrite"


def test_invalid_sample_name_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        PackagedSampleError,
        match="未知或无效",
    ):
        extract_packaged_sample(
            destination=tmp_path / "input",
            sample_name="../../escape",
        )
