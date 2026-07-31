from pathlib import Path
from types import SimpleNamespace

import protein_design_agent.agent.chat_dialogue as module
from protein_design_agent.agent.chat_session import (
    ChatTurnResult,
)


def install_information_intent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "determine_intent",
        lambda **_kwargs: (
            module.DialogueDecision(
                intent="PROVIDE_INFORMATION",
                reason="test",
            ),
            None,
            "PREPARED",
            None,
        ),
    )


def test_input_directory_triggers_automatic_inspection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    session_path = bundle / "planning_session.json"
    session_path.write_text(
        "{}",
        encoding="utf-8",
    )

    install_information_intent(monkeypatch)

    monkeypatch.setattr(
        module,
        "process_chat_message",
        lambda **_kwargs: ChatTurnResult(
            action="PREPARE",
            status="NEEDS_INFORMATION",
            message="还缺少链布局。",
            bundle_dir=bundle,
        ),
    )

    monkeypatch.setattr(
        module,
        "load_planning_session",
        lambda _path: SimpleNamespace(
            request=SimpleNamespace(
                input_dir=tmp_path / "pdbs"
            )
        ),
    )

    monkeypatch.setattr(
        module,
        "load_pending_action",
        lambda _bundle: None,
    )

    inspected = ChatTurnResult(
        action="INSPECT_DATASET",
        status="AWAITING_CONFIRMATION",
        message="已自动检查 PDB。",
        bundle_dir=bundle,
    )

    monkeypatch.setattr(
        module,
        "inspect_dataset_and_propose_adoption",
        lambda **_kwargs: inspected,
    )

    result = module.process_dialogue_message(
        message="分析 /data/demo，binder 是 B 链",
        bundle_dir=bundle,
        provider=object(),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "INSPECT_DATASET"
    assert result.status == "AWAITING_CONFIRMATION"
    assert result.message == "已自动检查 PDB。"


def test_missing_input_directory_keeps_missing_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    (
        bundle / "planning_session.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    install_information_intent(monkeypatch)

    monkeypatch.setattr(
        module,
        "process_chat_message",
        lambda **_kwargs: ChatTurnResult(
            action="PREPARE",
            status="NEEDS_INFORMATION",
            message="missing",
            bundle_dir=bundle,
        ),
    )

    monkeypatch.setattr(
        module,
        "load_planning_session",
        lambda _path: SimpleNamespace(
            request=SimpleNamespace(
                input_dir=None
            )
        ),
    )

    monkeypatch.setattr(
        module,
        "load_pending_action",
        lambda _bundle: None,
    )

    monkeypatch.setattr(
        module,
        "inspect_dataset_and_propose_adoption",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "没有输入目录时不应检查数据"
            )
        ),
    )

    monkeypatch.setattr(
        module,
        "natural_missing_message",
        lambda _bundle: "还需要提供 PDB 输入目录。",
    )

    result = module.process_dialogue_message(
        message="帮我分析",
        bundle_dir=bundle,
        provider=object(),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "PREPARE"
    assert result.status == "NEEDS_INFORMATION"
    assert result.message == "还需要提供 PDB 输入目录。"
