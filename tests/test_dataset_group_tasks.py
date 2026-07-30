from pathlib import Path

import pytest

from protein_design_agent.agent.dataset_discovery import (
    discover_dataset_groups,
)
from protein_design_agent.agent.dataset_grouping import (
    DatasetGroupProposal,
    DatasetGroupingProposal,
    validate_grouping_proposal,
)
from protein_design_agent.agent.dataset_group_tasks import (
    DatasetGroupTaskError,
    create_group_task_bundles,
    save_grouping_proposal,
)


def write_pdb(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "HEADER MOCK\n",
        encoding="utf-8",
    )


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / ".protein-design-agent"
    runs = workspace / "runs"
    source_bundle = runs / "default"

    source_bundle.mkdir(parents=True)

    (
        workspace / ".pda-workspace.json"
    ).write_text(
        '{"schema_version":"0.1",'
        '"workspace_type":"protein-design-agent"}',
        encoding="utf-8",
    )

    return workspace, source_bundle


def prepare_proposal(
    tmp_path: Path,
) -> tuple[Path, Path]:
    _workspace, source_bundle = make_workspace(
        tmp_path
    )
    data = tmp_path / "data"

    for name in (
        "group_a",
        "group_b",
        "group_c",
    ):
        write_pdb(data / name / "one.pdb")

    report = discover_dataset_groups(data)

    proposal = DatasetGroupingProposal(
        groups=[
            DatasetGroupProposal(
                task_name=group.directory_name,
                source_relative_path=(
                    group.relative_path
                ),
                expected_pdb_count=(
                    group.pdb_count
                ),
                recursive=False,
                reason="按子目录分别排序",
            )
            for group in report.groups
        ],
        summary="分别创建任务",
        questions=[],
        requires_user_review=True,
    )

    grouping = validate_grouping_proposal(
        proposal=proposal,
        report=report,
    )

    save_grouping_proposal(
        bundle_dir=source_bundle,
        report=report,
        grouping=grouping,
        user_description="每个目录是一组",
    )

    return source_bundle, data


def test_creates_independent_group_bundles(
    tmp_path: Path,
) -> None:
    source_bundle, _data = prepare_proposal(
        tmp_path
    )

    result = create_group_task_bundles(
        source_bundle=source_bundle
    )

    assert result.task_names == [
        "group_a",
        "group_b",
        "group_c",
    ]

    for bundle in result.created_bundles:
        assert (
            bundle / "group_task_source.json"
        ).is_file()
        assert not (
            bundle / "approval.json"
        ).exists()


def test_existing_target_aborts_before_creation(
    tmp_path: Path,
) -> None:
    source_bundle, _data = prepare_proposal(
        tmp_path
    )

    existing = (
        source_bundle.parent / "group_b"
    )
    existing.mkdir()

    with pytest.raises(
        DatasetGroupTaskError,
        match="未创建任何任务",
    ):
        create_group_task_bundles(
            source_bundle=source_bundle
        )

    assert not (
        source_bundle.parent / "group_a"
    ).exists()
    assert not (
        source_bundle.parent / "group_c"
    ).exists()


def test_changed_dataset_is_rejected(
    tmp_path: Path,
) -> None:
    source_bundle, data = prepare_proposal(
        tmp_path
    )

    write_pdb(
        data / "group_a" / "added.pdb"
    )

    with pytest.raises(
        DatasetGroupTaskError,
        match="发生变化",
    ):
        create_group_task_bundles(
            source_bundle=source_bundle
        )
