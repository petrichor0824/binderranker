import json
from pathlib import Path

import pytest

from protein_design_agent.agent.natural_language_prepare import (
    prepare_from_natural_language,
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

    assert result.scientific_workflow_executed is True
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
