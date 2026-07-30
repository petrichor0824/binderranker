from pathlib import Path

import pytest

from protein_design_agent.agent.dataset_discovery import (
    DatasetDiscoveryError,
    classify_layout,
    discover_dataset_groups,
)


def write_pdb(path: Path) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "HEADER MOCK PDB\n",
        encoding="utf-8",
    )


def test_discovers_arbitrary_number_of_groups(
    tmp_path: Path,
) -> None:
    group_names = [
        "group_a",
        "group_b",
        "group_c",
        "group_d",
        "group_e",
        "group_f",
    ]

    for index, group_name in enumerate(
        group_names,
        start=1,
    ):
        for pdb_index in range(index):
            write_pdb(
                tmp_path
                / group_name
                / f"candidate_{pdb_index}.pdb"
            )

    report = discover_dataset_groups(
        tmp_path
    )

    assert report.layout == "CHILD_DATASETS"
    assert report.total_group_count == 6
    assert [
        group.directory_name
        for group in report.groups
    ] == group_names
    assert [
        group.pdb_count
        for group in report.groups
    ] == [1, 2, 3, 4, 5, 6]
    assert report.total_discovered_pdb_count == 21


def test_root_only_dataset_is_detected(
    tmp_path: Path,
) -> None:
    write_pdb(tmp_path / "one.pdb")
    write_pdb(tmp_path / "two.PDB")

    report = discover_dataset_groups(
        tmp_path
    )

    assert report.layout == "ROOT_DATASET"
    assert report.root_level_pdb_count == 2
    assert report.groups == ()


def test_mixed_layout_requires_review(
    tmp_path: Path,
) -> None:
    write_pdb(tmp_path / "loose.pdb")
    write_pdb(
        tmp_path
        / "batch_01"
        / "candidate.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    assert report.layout == "MIXED_LAYOUT"
    assert report.root_level_pdb_count == 1
    assert report.total_group_count == 1
    assert any(
        "必须由用户确认"
        in warning
        for warning in report.warnings
    )


def test_empty_child_directories_are_not_groups(
    tmp_path: Path,
) -> None:
    (
        tmp_path / "notes"
    ).mkdir()

    write_pdb(
        tmp_path
        / "real_group"
        / "candidate.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    assert report.total_group_count == 1
    assert report.groups[0].directory_name == (
        "real_group"
    )
    assert report.empty_child_directories == (
        "notes",
    )


def test_invalid_directory_name_is_reported(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path
        / "group with spaces"
        / "candidate.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    group = report.groups[0]

    assert group.directory_name == (
        "group with spaces"
    )
    assert group.suggested_task_name is None
    assert group.naming_warning is not None
    assert any(
        "不能直接作为任务名"
        in warning
        for warning in report.warnings
    )


def test_nested_pdbs_are_not_silently_included(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path
        / "batch"
        / "nested"
        / "candidate.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    assert report.layout == "EMPTY"
    assert report.total_group_count == 0
    assert report.total_discovered_pdb_count == 0


def test_missing_root_is_rejected(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(
        DatasetDiscoveryError,
        match="不存在",
    ):
        discover_dataset_groups(missing)


@pytest.mark.parametrize(
    (
        "root_count",
        "group_count",
        "expected",
    ),
    [
        (0, 0, "EMPTY"),
        (3, 0, "ROOT_DATASET"),
        (0, 4, "CHILD_DATASETS"),
        (2, 5, "MIXED_LAYOUT"),
    ],
)
def test_layout_classification(
    root_count: int,
    group_count: int,
    expected: str,
) -> None:
    assert classify_layout(
        root_level_pdb_count=root_count,
        group_count=group_count,
    ) == expected
