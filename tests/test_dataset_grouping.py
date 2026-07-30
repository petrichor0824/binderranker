from pathlib import Path

import pytest

from protein_design_agent.agent.dataset_discovery import (
    discover_dataset_groups,
)
from protein_design_agent.agent.dataset_grouping import (
    DatasetGroupingError,
    propose_dataset_grouping,
)


class FakeGroupingProvider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_messages = None

    def generate_json(self, messages):
        self.last_messages = messages
        return self.payload


def write_pdb(path: Path) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "HEADER MOCK\n",
        encoding="utf-8",
    )


def make_payload(
    groups: list[dict],
    *,
    requires_user_review: bool = False,
) -> dict:
    return {
        "groups": groups,
        "summary": "按目录分别建立独立排序任务",
        "questions": [],
        "requires_user_review": (
            requires_user_review
        ),
    }


def test_model_can_propose_arbitrary_group_count(
    tmp_path: Path,
) -> None:
    names = [
        "group_a",
        "group_b",
        "group_c",
        "group_d",
        "group_e",
        "group_f",
    ]

    for name in names:
        write_pdb(
            tmp_path / name / "one.pdb"
        )

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": name,
                "source_relative_path": name,
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "用户要求按子目录分组",
            }
            for name in names
        ])
    )

    result = propose_dataset_grouping(
        provider=provider,
        user_description=(
            "每个子目录是一组，分别排序"
        ),
        report=report,
    )

    assert len(result.groups) == 6
    assert [
        group.task_name
        for group in result.groups
    ] == names
    assert result.omitted_relative_paths == ()
    assert provider.last_messages is not None


def test_invented_directory_is_rejected(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path / "real_group" / "one.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": "fake_group",
                "source_relative_path": "missing",
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "test",
            }
        ])
    )

    with pytest.raises(
        DatasetGroupingError,
        match="不存在",
    ):
        propose_dataset_grouping(
            provider=provider,
            user_description="分组",
            report=report,
        )


def test_duplicate_directory_is_rejected(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path / "group_a" / "one.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": "task_1",
                "source_relative_path": "group_a",
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "first",
            },
            {
                "task_name": "task_2",
                "source_relative_path": "group_a",
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "second",
            },
        ])
    )

    with pytest.raises(
        DatasetGroupingError,
        match="重复分组",
    ):
        propose_dataset_grouping(
            provider=provider,
            user_description="分组",
            report=report,
        )


def test_wrong_pdb_count_is_rejected(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path / "group_a" / "one.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": "group_a",
                "source_relative_path": "group_a",
                "expected_pdb_count": 999,
                "recursive": False,
                "reason": "test",
            }
        ])
    )

    with pytest.raises(
        DatasetGroupingError,
        match="数量",
    ):
        propose_dataset_grouping(
            provider=provider,
            user_description="分组",
            report=report,
        )


def test_omitted_groups_require_review(
    tmp_path: Path,
) -> None:
    write_pdb(
        tmp_path / "group_a" / "one.pdb"
    )
    write_pdb(
        tmp_path / "group_b" / "one.pdb"
    )

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": "group_a",
                "source_relative_path": "group_a",
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "只处理第一组",
            }
        ])
    )

    result = propose_dataset_grouping(
        provider=provider,
        user_description="只处理 group_a",
        report=report,
    )

    assert result.omitted_relative_paths == (
        "group_b",
    )
    assert result.requires_user_review is True


def test_root_dataset_uses_dot_token(
    tmp_path: Path,
) -> None:
    write_pdb(tmp_path / "one.pdb")

    report = discover_dataset_groups(
        tmp_path
    )

    provider = FakeGroupingProvider(
        make_payload([
            {
                "task_name": "root_dataset",
                "source_relative_path": ".",
                "expected_pdb_count": 1,
                "recursive": False,
                "reason": "PDB 位于根目录",
            }
        ])
    )

    result = propose_dataset_grouping(
        provider=provider,
        user_description="根目录是一组",
        report=report,
    )

    assert result.groups[0].input_directory == (
        tmp_path.resolve()
    )
