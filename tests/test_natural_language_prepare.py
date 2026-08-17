import json
from pathlib import Path

import pytest

from protein_design_agent.agent.natural_language_prepare import (
    NaturalLanguagePreparationError,
    prepare_from_natural_language,
)
from protein_design_agent.agent.planning_session_prepare import (
    prepare_planning_session,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.providers.mock import (
    MockProvider,
)


def fake_success_runner(
    command: list[str],
    stdout_log: Path,
    stderr_log: Path,
) -> int:
    """模拟确定性工作流成功。"""
    workflow_dir = Path(
        command[
            command.index("--run-dir") + 1
        ]
    )

    ranker_dir = workflow_dir / "ranker"
    ranker_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        workflow_dir
        / "workflow_manifest.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
            }
        ),
        encoding="utf-8",
    )

    (
        ranker_dir
        / "ranker_execution_plan.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "execute_requested": False,
            }
        ),
        encoding="utf-8",
    )

    stdout_log.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    stdout_log.write_text(
        "fake success\n",
        encoding="utf-8",
    )
    stderr_log.write_text(
        "",
        encoding="utf-8",
    )

    return 0


def complete_payload() -> dict:
    return {
        "project_name": "natural_language_test",
        "input_dir": "sample_data/test_two_chain",
        "input_layout": "existing_chains",
        "binder_chain": "A",
        "execute_requested": False,
    }


def test_incomplete_request_stops_before_workflow(
    tmp_path: Path,
) -> None:
    provider = MockProvider({})

    bundle = tmp_path / "incomplete_bundle"
    bundle.mkdir()

    result = prepare_from_natural_language(
        raw_text="帮我检查并排名这批骨架",
        provider=provider,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    assert result.status == "NEEDS_INFORMATION"
    assert result.scientific_workflow_executed is False
    assert result.binderranker_executed is False

    assert result.missing_information == [
        "input_dir",
        "input_layout",
    ]

    assert result.planning_session.exists()
    assert result.prepare_manifest.exists()

    assert not (
        bundle / "workflow"
    ).exists()


def test_complete_request_prepares_workflow(
    tmp_path: Path,
) -> None:
    provider = MockProvider(
        complete_payload()
    )

    bundle = tmp_path / "ready_bundle"

    result = prepare_from_natural_language(
        raw_text=(
            "检查已经正确分链的数据，"
            "A链是binder，只准备计划。"
        ),
        provider=provider,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    assert result.status == "READY_FOR_REVIEW"
    assert result.project_name == (
        "natural_language_test"
    )

    assert result.scientific_workflow_executed is False
    assert result.binderranker_executed is False
    assert result.remote_backend_used is False

    assert result.project_config is not None
    assert result.project_config.exists()

    assert result.workflow_manifest is not None
    assert result.workflow_manifest.exists()


def test_nonempty_bundle_is_rejected_before_provider_call(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "existing"
    bundle.mkdir()

    existing_file = bundle / "important.txt"
    existing_file.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    provider = MockProvider(
        complete_payload()
    )

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        prepare_from_natural_language(
            raw_text="测试请求",
            provider=provider,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert existing_file.read_text(
        encoding="utf-8"
    ) == "do not overwrite"


def test_empty_text_is_rejected(
    tmp_path: Path,
) -> None:
    provider = MockProvider({})

    with pytest.raises(
        ValueError,
        match="用户请求不能为空",
    ):
        prepare_from_natural_language(
            raw_text="   ",
            provider=provider,
            bundle_dir=tmp_path / "empty",
            runner=fake_success_runner,
        )


def test_nonempty_bundle_has_safe_public_message(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "existing_public"
    bundle.mkdir()

    (
        bundle / "important.txt"
    ).write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    provider = MockProvider(
        complete_payload()
    )

    with pytest.raises(
        NaturalLanguagePreparationError
    ) as exc_info:
        prepare_from_natural_language(
            raw_text="测试请求",
            provider=provider,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert "禁止覆盖" in str(exc_info.value)

    assert (
        exc_info.value.public_message
        == (
            "目标任务目录已经存在且非空，"
            "默认禁止覆盖。"
        )
    )


def test_incomplete_save_failure_preserves_existing_empty_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import protein_design_agent.agent.planning_session_prepare as module

    bundle = tmp_path / "existing_empty"
    bundle.mkdir()

    provider = MockProvider({})

    real_write_json = module.write_json

    def failing_write_json(
        path: Path,
        content: dict,
    ) -> None:
        if (
            path.name
            == "agent_prepare_manifest.json"
        ):
            raise OSError(
                "PRIVATE_INCOMPLETE_MANIFEST_WRITE"
            )

        real_write_json(
            path,
            content,
        )

    monkeypatch.setattr(
        module,
        "write_json",
        failing_write_json,
    )

    with pytest.raises(
        NaturalLanguagePreparationError
    ) as exc_info:
        prepare_from_natural_language(
            raw_text="帮我排名这批骨架",
            provider=provider,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert bundle.exists()
    assert list(bundle.iterdir()) == []

    assert (
        "PRIVATE_INCOMPLETE_MANIFEST_WRITE"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "信息不完整的任务记录保存失败；"
            "正式任务目录没有发布。"
        )
    )

    leftovers = [
        path
        for path in tmp_path.iterdir()
        if (
            ".incomplete-preparing-"
            in path.name
        )
    ]

    assert leftovers == []


def test_incomplete_save_failure_does_not_create_new_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import protein_design_agent.agent.planning_session_prepare as module

    bundle = tmp_path / "new_incomplete"

    provider = MockProvider({})

    def failing_write_json(
        path: Path,
        content: dict,
    ) -> None:
        raise OSError(
            "PRIVATE_NEW_INCOMPLETE_FAILURE"
        )

    monkeypatch.setattr(
        module,
        "write_json",
        failing_write_json,
    )

    with pytest.raises(
        NaturalLanguagePreparationError
    ) as exc_info:
        prepare_from_natural_language(
            raw_text="帮我排名这批骨架",
            provider=provider,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert not bundle.exists()

    assert (
        "PRIVATE_NEW_INCOMPLETE_FAILURE"
        in str(exc_info.value)
    )

    leftovers = [
        path
        for path in tmp_path.iterdir()
        if (
            ".incomplete-preparing-"
            in path.name
        )
    ]

    assert leftovers == []

def test_prepare_planning_session_persists_incomplete_session(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="帮我检查并排名这批骨架",
    )
    session = PlanningSession(
        provider_name="unit-test",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[],
    )

    def forbidden_runner(*args, **kwargs):
        raise AssertionError(
            "incomplete session must not run workflow"
        )

    bundle = tmp_path / "session_incomplete"

    result = prepare_planning_session(
        session=session,
        bundle_dir=bundle,
        runner=forbidden_runner,
    )

    assert result.status == "NEEDS_INFORMATION"
    assert result.provider_name == "unit-test"
    assert result.missing_information == [
        "input_dir",
        "input_layout",
    ]
    assert result.planning_session.exists()
    assert result.prepare_manifest.exists()
    assert not (bundle / "workflow").exists()


def test_prepare_planning_session_prepares_ready_session(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="检查已经正确分链的数据，只准备计划。",
        **complete_payload(),
    )
    session = PlanningSession(
        provider_name="unit-test",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[
            "project_name",
            "input_dir",
            "input_layout",
            "binder_chain",
            "execute_requested",
        ],
    )

    bundle = tmp_path / "session_ready"

    result = prepare_planning_session(
        session=session,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    assert result.status == "READY_FOR_REVIEW"
    assert result.provider_name == "unit-test"
    assert result.project_name == "natural_language_test"
    assert result.project_config is not None
    assert result.project_config.exists()
    assert result.workflow_manifest is not None
    assert result.workflow_manifest.exists()


def test_prepare_planning_session_rejects_nonempty_bundle(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="检查已经正确分链的数据，只准备计划。",
        **complete_payload(),
    )
    session = PlanningSession(
        provider_name="unit-test",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[],
    )

    bundle = tmp_path / "existing_session_bundle"
    bundle.mkdir()

    existing_file = bundle / "important.txt"
    existing_file.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    with pytest.raises(
        NaturalLanguagePreparationError,
        match="禁止覆盖",
    ):
        prepare_planning_session(
            session=session,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert existing_file.read_text(
        encoding="utf-8"
    ) == "do not overwrite"
