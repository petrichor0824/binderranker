import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.chat_dialogue as module
from protein_design_agent.agent.chat_dialogue import (
    ChatDialogueError,
    DialogueDecision,
    load_pending_action,
    process_dialogue_message,
)
from protein_design_agent.agent.chat_session import (
    ChatTurnResult,
)


class FakeDialogueProvider:
    def __init__(
        self,
        intent: str,
        reply: str | None = None,
        safety_topics: (
            list[str] | None
        ) = None,
    ) -> None:
        self.intent = intent
        self.reply = reply
        self.safety_topics = (
            safety_topics or []
        )
        self.last_messages = None

    @property
    def name(self) -> str:
        return "fake-provider"

    def parse_user_request(self, raw_text):
        raise AssertionError(
            "本测试不应调用任务解析"
        )

    def generate_json(self, messages):
        self.last_messages = messages
        payload = {
            "intent": self.intent,
            "reason": "test",
        }

        if self.reply is not None:
            payload["reply"] = self.reply

        if self.safety_topics:
            payload["safety_topics"] = (
                self.safety_topics
            )

        return payload


def write_json(
    path: Path,
    value: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(value),
        encoding="utf-8",
    )


def prepared_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "demo",
        },
    )

    return bundle


def test_natural_approval_creates_pending_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    called = False

    def fake_engine(**kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "提出批准意图时不能直接执行"
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    result = process_dialogue_message(
        message="这个方案没问题，就按它来吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == (
        "AWAITING_CONFIRMATION"
    )
    assert "请回答“确认”" in result.message
    assert called is False

    pending = load_pending_action(
        bundle
    )

    assert pending is not None
    assert pending.action == "APPROVE"


def test_confirmation_calls_deterministic_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    first = process_dialogue_message(
        message="批准这个方案",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert first.status == (
        "AWAITING_CONFIRMATION"
    )

    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)

        return ChatTurnResult(
            action="APPROVE",
            status="APPROVED",
            message="计划已批准",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    result = process_dialogue_message(
        message="确认",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "CONFIRM"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "APPROVED"
    assert (
        captured["message"]
        == "批准计划并确认小样本限制"
    )
    assert load_pending_action(
        bundle
    ) is None


def test_cancel_does_not_call_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "EXPLORATORY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    process_dialogue_message(
        message="批准吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    result = process_dialogue_message(
        message="取消",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "CANCEL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "CANCELLED"
    assert load_pending_action(
        bundle
    ) is None


def test_missing_fields_are_humanized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "missing_information": [
                "input_layout",
                "source_chain",
            ],
        },
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    result = process_dialogue_message(
        message="我还需要告诉你什么？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert "已经是不同链" in result.message
    assert "源链" in result.message
    assert "不需要输入字段名" in result.message


def test_stale_confirmation_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "EXPLORATORY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    process_dialogue_message(
        message="批准吧",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_APPROVAL"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    # 模拟用户确认前任务清单发生变化。
    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "READY_FOR_REVIEW",
            "project_name": "changed",
        },
    )

    with pytest.raises(
        ChatDialogueError,
        match="状态在等待确认期间发生了变化",
    ):
        process_dialogue_message(
            message="确认",
            bundle_dir=bundle,
            provider=FakeDialogueProvider(
                "CONFIRM"
            ),
            approved_by="tester",
            model_config_path=None,
            profile_name=None,
            allow_network=True,
        )

    assert load_pending_action(
        bundle
    ) is None


def test_general_question_returns_model_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "missing_information": [
                "source_chain",
            ],
        },
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    answer = (
        "源链是指标准化之前，原始 PDB 中"
        "target 和 binder 所在的链。"
        "你刚才已经说明它们拼在同一条 A 链中，"
        "因此这里的源链应当是 A。"
    )

    result = process_dialogue_message(
        message="我咋知道源链是哪一条？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=answer,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert "标准化之前" in result.message
    assert "源链应当是 A" in result.message
    assert "还需要补充" not in result.message


def create_incomplete_inspection_bundle(
    tmp_path: Path,
) -> Path:
    from protein_design_agent.schemas.planning_session import (
        PlanningSession,
    )
    from protein_design_agent.agent.planner import (
        build_agent_plan,
    )
    from protein_design_agent.schemas.agent_models import (
        UserRequest,
    )

    pdb_dir = tmp_path / "pdbs"
    pdb_dir.mkdir()

    request = UserRequest(
        raw_text="分析这个目录里的 PDB",
        input_dir=pdb_dir,
    )

    plan = build_agent_plan(request)

    bundle = tmp_path / "inspection_bundle"
    bundle.mkdir()

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=plan,
        request_explicit_fields=[
            "input_dir",
        ],
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )

    write_json(
        bundle
        / "agent_prepare_manifest.json",
        {
            "status": "NEEDS_INFORMATION",
            "missing_information": (
                plan.missing_information
            ),
        },
    )

    return bundle


def test_natural_language_can_request_read_only_inspection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = create_incomplete_inspection_bundle(
        tmp_path
    )

    advice_path = (
        bundle
        / "chat"
        / "dataset_advice.json"
    )

    suggestion = SimpleNamespace(
        candidate_patch={
            "input_layout": (
                "concatenated_single_chain"
            ),
            "source_chain": "A",
        }
    )

    advice = SimpleNamespace(
        processed_file_count=5,
        valid_file_count=5,
        invalid_file_count=0,
        all_valid_files_are_single_chain=True,
        common_single_chain_id="A",
        conditional_suggestion=suggestion,
        cautions=[
            (
                "单链结构本身不能证明同时包含 "
                "target 和 binder"
            ),
        ],
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    monkeypatch.setattr(
        module,
        "inspect_dataset_for_planning",
        lambda **kwargs: advice,
    )

    def fake_save(**kwargs):
        advice_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        advice_path.write_text(
            "{}",
            encoding="utf-8",
        )
        return advice_path

    monkeypatch.setattr(
        module,
        "save_dataset_advice",
        fake_save,
    )

    result = process_dialogue_message(
        message="我不会判断，你帮我看看这些 PDB 文件",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_DATASET_INSPECTION"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "INSPECT_DATASET"
    assert result.status == (
        "AWAITING_CONFIRMATION"
    )
    assert "5 个 PDB" in result.message
    assert "不是大模型猜测" in result.message
    assert "回答“确认”" in result.message

    pending = load_pending_action(
        bundle
    )

    assert pending is not None
    assert pending.action == (
        "ADOPT_DATASET_ADVICE"
    )


def test_confirmation_adopts_dataset_advice(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = create_incomplete_inspection_bundle(
        tmp_path
    )

    advice_path = (
        bundle
        / "chat"
        / "dataset_advice.json"
    )
    advice_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    advice_path.write_text(
        "{}",
        encoding="utf-8",
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="ADOPT_DATASET_ADVICE",
        summary="确认采用文件建议？",
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    monkeypatch.setattr(
        module,
        "adopt_dataset_advice",
        lambda **kwargs: SimpleNamespace(
            status="NEEDS_INFORMATION",
            planning_session=(
                bundle
                / "planning_session.json"
            ),
            prepare_manifest=(
                bundle
                / "agent_prepare_manifest.json"
            ),
            history_record=(
                bundle
                / "history"
                / "resume_0001"
            ),
        ),
    )

    monkeypatch.setattr(
        module,
        "natural_missing_message",
        lambda path: "还需要 target 边界。",
    )

    result = process_dialogue_message(
        message="确认",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == (
        "ADOPT_DATASET_ADVICE"
    )
    assert result.status == (
        "NEEDS_INFORMATION"
    )
    assert "还需要 target 边界" in result.message
    assert load_pending_action(
        bundle
    ) is None


def test_question_during_pending_action_is_answered(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            approval_status=None,
            execution_status=None,
        ),
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    answer = (
        "批准只会冻结当前配置和文件指纹，"
        "不会立即运行 BinderRanker。"
    )

    result = process_dialogue_message(
        message="批准以后是不是马上就开始运行？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=answer,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert "不会立即运行" in result.message
    assert "待确认动作仍然保留" in result.message

    pending = load_pending_action(
        bundle
    )

    assert pending is not None
    assert pending.action == "APPROVE"


def test_status_can_be_viewed_during_pending_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            prepare_status="READY_FOR_REVIEW",
            approval_status=None,
            execution_status=None,
            analysis_status=None,
            explanation_status=None,
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            candidate_count=5,
            approval_consumed=None,
        ),
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    result = process_dialogue_message(
        message="状态",
        bundle_dir=bundle,
        provider=None,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=False,
    )

    assert result.action == "STATUS"
    assert "当前阶段：PREPARED" in result.message
    assert "待确认动作仍然保留" in result.message

    assert load_pending_action(
        bundle
    ) is not None


def test_pending_approval_safety_facts_are_deterministic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    report = SimpleNamespace(
        current_stage="PREPARED",
        project_name="demo",
        prepare_status="READY_FOR_REVIEW",
        approval_status=None,
        execution_status=None,
        analysis_status=None,
        explanation_status=None,
        analysis_scope_level=(
            "SMOKE_TEST_ONLY"
        ),
        candidate_count=5,
        approval_consumed=None,
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: report,
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    # 故意让模型给出错误回答。
    wrong_model_reply = (
        "批准后会马上执行，"
        "而且仍然可以随时修改参数。"
    )

    result = process_dialogue_message(
        message=(
            "批准后会马上运行吗？"
            "我还能不能修改参数？"
        ),
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=wrong_model_reply,
            safety_topics=[
                (
                    "APPROVAL_"
                    "EXECUTION_SEPARATION"
                ),
                (
                    "APPROVAL_"
                    "CONFIGURATION_FREEZE"
                ),
            ],
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"

    assert (
        "批准不会立即运行 BinderRanker"
        in result.message
    )
    assert (
        "批准后不能直接修改同一个 Bundle"
        in result.message
    )

    assert "会马上执行" not in result.message
    assert "仍然可以随时修改" not in result.message

    assert "待确认动作仍然保留" in result.message
    assert load_pending_action(
        bundle
    ) is not None


def test_pending_smoke_limit_answer_uses_run_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(
        tmp_path
    )

    report = SimpleNamespace(
        current_stage="PREPARED",
        project_name="demo",
        prepare_status="READY_FOR_REVIEW",
        approval_status=None,
        execution_status=None,
        analysis_status=None,
        explanation_status=None,
        analysis_scope_level=(
            "SMOKE_TEST_ONLY"
        ),
        candidate_count=5,
        approval_consumed=None,
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: report,
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    result = process_dialogue_message(
        message="小样本限制到底是什么意思？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply="可以正式选最优候选。",
            safety_topics=[
                "SMOKE_TEST_LIMITATION",
            ],
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert "当前只有 5 个候选" in result.message
    assert "SMOKE_TEST_ONLY" in result.message
    assert "不能把本次排名" in result.message
    assert "可以正式选最优候选" not in result.message


def test_empty_bundle_general_question_does_not_start_task(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty_bundle"
    bundle.mkdir()

    answer = (
        "你好。我可以先介绍程序的用途、原理、"
        "安全边界和完整使用流程。"
    )

    result = process_dialogue_message(
        message="你好，先介绍一下这个程序",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=answer,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert result.message == answer
    assert not (
        bundle / "planning_session.json"
    ).exists()
    assert not (
        bundle / "agent_prepare_manifest.json"
    ).exists()



def test_latest_result_summary_is_injected_into_model_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    summary_path = (
        bundle
        / "analyses"
        / "chat_deterministic_0001"
        / "agent_result_summary.json"
    )
    write_json(
        summary_path,
        {
            "analysis_scope": {
                "level": "SMOKE_TEST_ONLY",
            },
            "candidate_count": 2,
            "candidates_by_engineering_rank": [
                {
                    "pdb_name": "_2577",
                    "engineering_rank": 1,
                    "final_score_v4": 0.6141,
                    "raw_filter_level": "FAIL",
                    "strict_reasons": [
                        "low_score_safety",
                    ],
                    "component_scores": {
                        "score_safety": 0.444,
                    },
                    "key_metrics": {},
                },
                {
                    "pdb_name": "_498",
                    "engineering_rank": 2,
                    "final_score_v4": 0.5977,
                    "raw_filter_level": "MEDIUM",
                    "strict_reasons": [
                        (
                            "low_contact_map_"
                            "continuity_score"
                        ),
                    ],
                    "component_scores": {},
                    "key_metrics": {},
                },
            ],
        },
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="ANALYZED",
            project_name="demo",
            prepare_status=(
                "READY_FOR_REVIEW"
            ),
            approval_status="APPROVED",
            execution_status="COMPLETED",
            analysis_status="COMPLETED",
            explanation_status=None,
            analysis_scope_level=(
                "SMOKE_TEST_ONLY"
            ),
            candidate_count=2,
            approval_consumed=True,
        ),
    )

    provider = FakeDialogueProvider(
        "GENERAL_QUESTION",
        reply="我已经读取当前结果。",
    )

    result = process_dialogue_message(
        message="解释一下刚才的排名",
        bundle_dir=bundle,
        provider=provider,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert provider.last_messages is not None

    model_context = json.loads(
        provider.last_messages[1]["content"]
    )
    evidence = model_context[
        "conversation_context"
    ]["latest_result_evidence"]

    assert evidence["status"] == "AVAILABLE"
    assert evidence["candidate_count"] == 2
    assert (
        evidence[
            "candidates_by_engineering_rank"
        ][0]["pdb_name"]
        == "_2577"
    )
    assert (
        evidence[
            "candidates_by_engineering_rank"
        ][1]["raw_filter_level"]
        == "MEDIUM"
    )


def test_information_correction_replaces_pending_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    report = SimpleNamespace(
        current_stage="PREPARED",
        project_name="demo",
        prepare_status="READY_FOR_REVIEW",
        approval_status=None,
        execution_status=None,
        analysis_status=None,
        explanation_status=None,
        analysis_scope_level="EXPLORATORY",
        candidate_count=20,
        approval_consumed=None,
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: report,
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)
        return ChatTurnResult(
            action="PREPARE",
            status="NEEDS_INFORMATION",
            message="已记录 binder 为 B 链。",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    result = process_dialogue_message(
        message=(
            "我刚才说错了，"
            "target 是 A 链，binder 是 B 链。"
        ),
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "PROVIDE_INFORMATION"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "NEEDS_INFORMATION"
    assert captured["message"] == (
        "我刚才说错了，"
        "target 是 A 链，binder 是 B 链。"
    )
    assert "原待确认动作 APPROVE" in result.message
    assert "取消" in result.message
    assert "已记录 binder 为 B 链" in result.message
    assert load_pending_action(bundle) is None


def test_semantic_view_plan_returns_real_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = create_incomplete_inspection_bundle(tmp_path)

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            prepare_status="READY_FOR_REVIEW",
            approval_status=None,
            execution_status=None,
            analysis_status=None,
            explanation_status=None,
            analysis_scope_level="EXPLORATORY",
            candidate_count=20,
            approval_consumed=None,
        ),
    )

    result = process_dialogue_message(
        message=(
            "执行之前把你准备采用的方案"
            "完整过一遍，我想检查有没有设错。"
        ),
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "VIEW_PLAN"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "VIEW_PLAN"
    assert result.status == "PLAN_AVAILABLE"
    assert "当前任务计划" in result.message
    assert "输入目录：" in result.message
    assert "计划步骤：" in result.message


def test_view_plan_does_not_cancel_pending_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            prepare_status="READY_FOR_REVIEW",
            approval_status=None,
            execution_status=None,
            analysis_status=None,
            explanation_status=None,
            analysis_scope_level="EXPLORATORY",
            candidate_count=20,
            approval_consumed=None,
        ),
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    result = process_dialogue_message(
        message=(
            "我先不确认，把完整参数和"
            "处理步骤再讲一遍。"
        ),
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "VIEW_PLAN"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "VIEW_PLAN"
    assert load_pending_action(bundle) is not None
    assert "待确认动作仍然保留" in result.message



def test_view_plan_reports_when_no_plan_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            prepare_status="READY_FOR_REVIEW",
            approval_status=None,
            execution_status=None,
            analysis_status=None,
            explanation_status=None,
            analysis_scope_level="EXPLORATORY",
            candidate_count=20,
            approval_consumed=None,
        ),
    )

    result = process_dialogue_message(
        message="把当前方案给我看看。",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "VIEW_PLAN"
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "VIEW_PLAN"
    assert result.status == "PLAN_AVAILABLE"
    assert "还没有生成任务计划" in result.message


def test_approval_proposal_displays_plan_before_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    monkeypatch.setattr(
        module,
        "format_current_plan",
        lambda path: (
            "当前任务计划\n"
            "项目：demo\n"
            "输入目录：/data/pdbs\n"
            "标准化 target 链：A\n"
            "标准化 binder 链：B"
        ),
    )

    report = SimpleNamespace(
        project_name="demo",
        analysis_scope_level="EXPLORATORY",
        approval_status=None,
    )

    result = module.create_action_proposal(
        action="APPROVE",
        bundle_dir=bundle,
        report=report,
    )

    assert result.status == "AWAITING_CONFIRMATION"
    assert result.message.startswith("当前任务计划")
    assert "标准化 target 链：A" in result.message
    assert "批准会冻结配置" in result.message
    assert "请回答“确认”" in result.message

    pending = load_pending_action(bundle)

    assert pending is not None
    assert "你正在请求批准项目：demo" in (
        pending.summary
    )
    assert "当前任务计划" not in pending.summary


def test_deterministic_analysis_runs_without_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    report = SimpleNamespace(
        current_stage="EXECUTED",
        project_name="demo",
        prepare_status="READY_FOR_REVIEW",
        approval_status="APPROVED",
        execution_status="COMPLETED",
        analysis_status=None,
        explanation_status=None,
        analysis_scope_level="EXPLORATORY",
        candidate_count=20,
        approval_consumed=True,
    )

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: report,
    )

    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)

        return ChatTurnResult(
            action="ANALYZE",
            status="COMPLETED",
            message="确定性分析完成。",
            bundle_dir=bundle,
        )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        fake_engine,
    )

    def fail_proposal(**kwargs):
        raise AssertionError(
            "确定性分析不应创建待确认动作"
        )

    monkeypatch.setattr(
        module,
        "create_action_proposal",
        fail_proposal,
    )

    result = process_dialogue_message(
        message=(
            "帮我总结这批结果，"
            "看看哪些指标拖了后腿。"
        ),
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "REQUEST_ANALYSIS"
        ),
        approved_by="tester",
        model_config_path=Path("model.yaml"),
        profile_name="deepseek_flash",
        allow_network=True,
    )

    assert result.action == "ANALYZE"
    assert result.status == "COMPLETED"
    assert captured["message"] == "分析结果"
    assert captured["provider"] is None
    assert captured["model_config_path"] is None
    assert captured["profile_name"] is None
    assert captured["allow_network"] is False
    assert load_pending_action(bundle) is None

def test_empty_start_task_routes_to_prepare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "runs" / "default"
    bundle.mkdir(parents=True)

    monkeypatch.setattr(
        module,
        "determine_intent",
        lambda **_kwargs: (
            module.DialogueDecision(
                intent="START_TASK",
                reason="test",
            ),
            None,
            "EMPTY",
            None,
        ),
    )

    prepared = module.ChatTurnResult(
        action="PREPARE",
        status="NEEDS_INFORMATION",
        message="raw missing message",
        bundle_dir=bundle,
    )

    monkeypatch.setattr(
        module,
        "process_chat_message",
        lambda **_kwargs: prepared,
    )
    monkeypatch.setattr(
        module,
        "maybe_auto_inspect_after_information",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        module,
        "natural_missing_message",
        lambda _bundle: "任务信息尚不完整。",
    )

    result = module.process_dialogue_message(
        message="帮我检查并排名一批蛋白骨架",
        bundle_dir=bundle,
        provider=object(),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.action == "PREPARE"
    assert result.status == "NEEDS_INFORMATION"
    assert result.message == "任务信息尚不完整。"

def test_general_question_capability_overclaim_uses_safe_fallback(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty_bundle"
    bundle.mkdir()

    wrong_reply = (
        "BinderRanker 可以预测结合亲和力，"
        "排名越高说明亲和力越强。"
    )

    result = process_dialogue_message(
        message="BinderRanker 能预测结合亲和力吗？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=wrong_reply,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert wrong_reply not in result.message
    assert "候选骨架" in result.message
    assert "排序" in result.message
    assert "不能预测结合亲和力" in result.message


def test_pending_general_question_capability_overclaim_uses_safe_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = prepared_bundle(tmp_path)

    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: SimpleNamespace(
            current_stage="PREPARED",
            project_name="demo",
            analysis_scope_level=None,
            approval_status=None,
            execution_status=None,
        ),
    )

    module.save_pending_action(
        bundle_dir=bundle,
        action="APPROVE",
        summary="是否批准当前计划？",
    )

    wrong_reply = (
        "BinderRanker 可以预测结合亲和力。"
    )

    result = process_dialogue_message(
        message="这个工具能预测结合亲和力吗？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=wrong_reply,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert wrong_reply not in result.message
    assert "不能预测结合亲和力" in result.message
    assert "待确认动作仍然保留" in result.message

    pending = load_pending_action(bundle)

    assert pending is not None
    assert pending.action == "APPROVE"


def test_general_question_safe_capability_reply_is_preserved(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty_bundle"
    bundle.mkdir()

    answer = (
        "BinderRanker 用于当前候选骨架批次内的"
        "工程排序和分层筛选，"
        "不能预测结合亲和力。"
    )

    result = process_dialogue_message(
        message="BinderRanker 是干什么的？",
        bundle_dir=bundle,
        provider=FakeDialogueProvider(
            "GENERAL_QUESTION",
            reply=answer,
        ),
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert result.message == answer


def test_general_question_prompt_contains_capability_truth(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty_bundle"
    bundle.mkdir()

    provider = FakeDialogueProvider(
        "GENERAL_QUESTION",
        reply="这是一个受控工程排序工具。",
    )

    result = process_dialogue_message(
        message="这个程序到底能做什么？",
        bundle_dir=bundle,
        provider=provider,
        approved_by="tester",
        model_config_path=None,
        profile_name=None,
        allow_network=True,
    )

    assert result.status == "ANSWER"
    assert provider.last_messages is not None

    system_message = (
        provider.last_messages[0]["content"]
    )

    assert system_message.startswith(
        "你是 BinderRanker Agent 的受控对话意图分类器。"
    )
    assert "候选骨架排序与分层筛选" in system_message
    assert "结合亲和力预测器" in system_message
    assert "实验成功概率预测器" in system_message
    assert "不能替代" in system_message
