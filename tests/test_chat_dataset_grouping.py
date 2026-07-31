from pathlib import Path
from types import SimpleNamespace

import protein_design_agent.agent.chat_dialogue as module


class FakeGroupingProvider:
    def generate_json(self, messages):
        return {
            "groups": [
                {
                    "task_name": "group_a",
                    "source_relative_path": "group_a",
                    "expected_pdb_count": 1,
                    "recursive": False,
                    "reason": "用户要求按子目录分别排序",
                },
                {
                    "task_name": "group_b",
                    "source_relative_path": "group_b",
                    "expected_pdb_count": 1,
                    "recursive": False,
                    "reason": "用户要求按子目录分别排序",
                },
            ],
            "summary": "两个目录分别建立独立任务",
            "questions": [],
            "requires_user_review": True,
        }


def write_pdb(path: Path) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "HEADER MOCK PDB\n",
        encoding="utf-8",
    )


def test_chat_proposes_multiple_dataset_groups(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    session_path = (
        bundle / "planning_session.json"
    )
    session_path.write_text(
        "{}",
        encoding="utf-8",
    )

    data_root = tmp_path / "data"

    write_pdb(
        data_root / "group_a" / "one.pdb"
    )
    write_pdb(
        data_root / "group_b" / "one.pdb"
    )

    monkeypatch.setattr(
        module,
        "load_prepare_status",
        lambda bundle_dir: (
            "NEEDS_INFORMATION"
        ),
    )

    monkeypatch.setattr(
        module,
        "load_planning_session",
        lambda path: SimpleNamespace(
            request=SimpleNamespace(
                input_dir=data_root
            )
        ),
    )

    result = (
        module
        .inspect_dataset_and_propose_adoption(
            bundle_dir=bundle,
            provider=FakeGroupingProvider(),
            user_message=(
                "每个子目录是一组，分别排序"
            ),
        )
    )

    assert result.action == (
        "INSPECT_DATASET"
    )
    assert result.status == (
        "AWAITING_CONFIRMATION"
    )
    assert "group_a | group_a | 1" in (
        result.message
    )
    assert "group_b | group_b | 1" in (
        result.message
    )
    assert "尚未创建任务" in result.message

    assert not (
        bundle
        / "chat"
        / "dataset_advice.json"
    ).exists()

    assert (
        bundle
        / "chat"
        / "dataset_grouping_proposal.json"
    ).is_file()

    pending = module.load_pending_action(bundle)
    assert pending is not None
    assert pending.action == (
        "CREATE_DATASET_GROUP_TASKS"
    )
