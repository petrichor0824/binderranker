from pathlib import Path

import protein_design_agent.agent.chat_dialogue as module


def test_offline_question_does_not_prompt_for_parameters(
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

    result = module.process_dialogue_message(
        message="链布局是什么意思？",
        bundle_dir=tmp_path,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "HELP"
    assert result.status == "GUIDANCE"
    assert "离线只读模式" in result.message
    assert "不会把这句话当作科研参数" in result.message
    assert "不会修改当前任务" in result.message

    assert "还需要" not in result.message
    assert "请补充" not in result.message
    assert "binder_chain" not in result.message
