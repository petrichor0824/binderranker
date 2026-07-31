from pathlib import Path

import protein_design_agent.agent.chat_dialogue as module


def test_offline_question_while_waiting_is_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "load_pending_action",
        lambda _bundle: None,
    )
    monkeypatch.setattr(
        module,
        "inspect_bundle",
        lambda _bundle: ("PREPARED", None),
    )
    monkeypatch.setattr(
        module,
        "load_prepare_status",
        lambda _bundle: "NEEDS_INFORMATION",
    )

    decision, pending, stage, report = (
        module.determine_intent(
            message="链布局是什么意思？",
            bundle_dir=tmp_path,
            provider=None,
            allow_network=False,
        )
    )

    assert decision.intent == "GENERAL_QUESTION"
    assert pending is None
    assert stage == "PREPARED"
    assert report is None


def test_explicit_offline_parser_keeps_information_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "load_pending_action",
        lambda _bundle: None,
    )
    monkeypatch.setattr(
        module,
        "inspect_bundle",
        lambda _bundle: ("PREPARED", None),
    )
    monkeypatch.setattr(
        module,
        "load_prepare_status",
        lambda _bundle: "NEEDS_INFORMATION",
    )

    decision, _pending, _stage, _report = (
        module.determine_intent(
            message="binder chain 是 B",
            bundle_dir=tmp_path,
            provider=object(),
            allow_network=False,
        )
    )

    assert decision.intent == "PROVIDE_INFORMATION"
