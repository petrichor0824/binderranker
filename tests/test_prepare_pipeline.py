import json
from pathlib import Path

import pytest

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.prepare_pipeline import (
    AgentPreparationError,
    prepare_agent_run,
)
from protein_design_agent.agent.providers.mock import (
    MockProvider,
)


def write_session(
    tmp_path: Path,
    payload: dict,
) -> Path:
    provider = MockProvider(payload)
    agent = LocalAgentOrchestrator(provider)

    session = agent.plan_from_text(
        "测试 Agent 准备流程"
    )

    path = tmp_path / "session.json"

    path.write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return path


def complete_payload() -> dict:
    return {
        "project_name": "prepare_pipeline_test",
        "input_dir": "sample_data/test_two_chain",
        "input_layout": "existing_chains",
        "binder_chain": "A",
        "region_policy": "diagnostic",
        "region_filter": "off",
        "execute_requested": False,
    }


def fake_success_runner(
    command: list[str],
    stdout_log: Path,
    stderr_log: Path,
) -> int:
    """模拟工作流成功，不真正启动子进程。"""
    run_dir_index = command.index(
        "--run-dir"
    ) + 1

    workflow_dir = Path(
        command[run_dir_index]
    )

    ranker_dir = workflow_dir / "ranker"
    ranker_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    workflow_manifest = (
        workflow_dir / "workflow_manifest.json"
    )

    workflow_manifest.write_text(
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
        "fake workflow success\n",
        encoding="utf-8",
    )

    stderr_log.write_text(
        "",
        encoding="utf-8",
    )

    return 0


def test_ready_session_prepares_bundle(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    bundle = tmp_path / "bundle"

    result = prepare_agent_run(
        session_path=session_path,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    assert result.status == "READY_FOR_REVIEW"
    assert result.binderranker_executed is False
    assert result.remote_backend_used is False

    assert result.session_copy.exists()
    assert result.project_config.exists()
    assert result.project_provenance.exists()
    assert result.workflow_manifest.exists()
    assert result.prepare_manifest.exists()

    manifest = json.loads(
        result.prepare_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert manifest["status"] == (
        "READY_FOR_REVIEW"
    )
    assert (
        manifest["binderranker_executed"]
        is False
    )
    assert (
        manifest["remote_backend_used"]
        is False
    )


def test_incomplete_session_is_rejected(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        {},
    )

    with pytest.raises(
        ValueError,
        match="只有 READY_FOR_REVIEW",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=tmp_path / "blocked",
            runner=fake_success_runner,
        )


def test_nonempty_bundle_is_protected(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    bundle = tmp_path / "existing_bundle"
    bundle.mkdir()

    existing = bundle / "important.txt"
    existing.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=bundle,
            runner=fake_success_runner,
        )

    assert existing.read_text(
        encoding="utf-8"
    ) == "do not overwrite"


def test_failed_workflow_is_recorded(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    bundle = tmp_path / "failed_bundle"

    def failing_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
    ) -> int:
        stdout_log.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        stdout_log.write_text(
            "",
            encoding="utf-8",
        )
        stderr_log.write_text(
            "simulated failure\n",
            encoding="utf-8",
        )

        return 7

    with pytest.raises(
        AgentPreparationError,
        match="退出码=7",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=bundle,
            runner=failing_runner,
        )

    # 正式 Bundle 不能被失败准备污染。
    assert (
        not bundle.exists()
        or not any(bundle.iterdir())
    )

    audit_root = (
        tmp_path
        / ".pda-failures"
        / "failed_bundle"
    )

    failure_dirs = list(
        audit_root.glob("prepare-*")
    )

    assert len(failure_dirs) == 1

    failure_manifest = (
        failure_dirs[0]
        / "failure_manifest.json"
    )

    assert failure_manifest.is_file()

    data = json.loads(
        failure_manifest.read_text(
            encoding="utf-8"
        )
    )

    assert data["status"] == "FAILED"
    assert data["return_code"] == 7
    assert (
        data["formal_bundle_published"]
        is False
    )
    assert (
        data["binderranker_executed"]
        is False
    )

    stderr_copy = Path(
        data["stderr_log"]
    )

    assert stderr_copy.is_file()
    assert stderr_copy.read_text(
        encoding="utf-8"
    ) == "simulated failure\n"


def test_unexpected_ranker_results_are_rejected(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    bundle = tmp_path / "unsafe_bundle"

    def unsafe_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
    ) -> int:
        result = fake_success_runner(
            command,
            stdout_log,
            stderr_log,
        )

        workflow_dir = Path(
            command[
                command.index("--run-dir") + 1
            ]
        )

        (
            workflow_dir
            / "ranker"
            / "backbone_rank_scored.csv"
        ).write_text(
            "unexpected execution\n",
            encoding="utf-8",
        )

        return result

    with pytest.raises(
        AgentPreparationError,
        match="执行边界被破坏",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=bundle,
            runner=unsafe_runner,
        )


def test_failed_workflow_does_not_publish_partial_bundle(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )
    bundle = tmp_path / "rollback_failed_bundle"

    def failing_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
    ) -> int:
        stdout_log.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        stdout_log.write_text(
            "partial stdout\n",
            encoding="utf-8",
        )
        stderr_log.write_text(
            "simulated failure\n",
            encoding="utf-8",
        )
        return 9

    with pytest.raises(
        AgentPreparationError,
        match="退出码=9",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=bundle,
            runner=failing_runner,
        )

    assert (
        not bundle.exists()
        or not any(bundle.iterdir())
    )


def test_unsafe_prepare_does_not_publish_partial_bundle(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )
    bundle = tmp_path / "rollback_unsafe_bundle"

    def unsafe_runner(
        command: list[str],
        stdout_log: Path,
        stderr_log: Path,
    ) -> int:
        result = fake_success_runner(
            command,
            stdout_log,
            stderr_log,
        )

        workflow_dir = Path(
            command[
                command.index("--run-dir") + 1
            ]
        )

        (
            workflow_dir
            / "ranker"
            / "backbone_rank_scored.csv"
        ).write_text(
            "unexpected execution\n",
            encoding="utf-8",
        )

        return result

    with pytest.raises(
        AgentPreparationError,
        match="执行边界被破坏",
    ):
        prepare_agent_run(
            session_path=session_path,
            bundle_dir=bundle,
            runner=unsafe_runner,
        )

    assert (
        not bundle.exists()
        or not any(bundle.iterdir())
    )


def test_successful_prepare_does_not_leak_staging_paths(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )
    bundle = tmp_path / "published_bundle"

    result = prepare_agent_run(
        session_path=session_path,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    assert result.bundle_directory == bundle.resolve()
    assert result.prepare_manifest.is_file()
    assert result.workflow_manifest.is_file()

    # 所有正式返回路径都必须位于发布后的 Bundle 中。
    returned_paths = [
        result.session_copy,
        result.project_config,
        result.project_provenance,
        result.workflow_directory,
        result.workflow_manifest,
        result.stdout_log,
        result.stderr_log,
        result.prepare_manifest,
    ]

    for path in returned_paths:
        assert path == bundle.resolve() or bundle.resolve() in path.parents
        assert path.exists()

    # 正式元数据不能继续引用已经被移走的 staging 目录。
    metadata_files = [
        result.project_provenance,
        result.workflow_manifest,
        result.prepare_manifest,
        (
            result.workflow_directory
            / "ranker"
            / "ranker_execution_plan.json"
        ),
    ]

    for path in metadata_files:
        content = path.read_text(
            encoding="utf-8"
        )
        assert ".preparing-" not in content

    # staging 目录在成功发布后也不应残留。
    staging_dirs = list(
        tmp_path.glob(
            ".published_bundle.preparing-*"
        )
    )
    assert staging_dirs == []


def test_published_bundle_has_no_staging_paths_in_metadata(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )
    bundle = tmp_path / "metadata_bundle"

    prepare_agent_run(
        session_path=session_path,
        bundle_dir=bundle,
        runner=fake_success_runner,
    )

    text_suffixes = {
        ".json",
        ".yaml",
        ".yml",
        ".sh",
    }

    checked_files = []

    for path in bundle.rglob("*"):
        if (
            path.is_file()
            and path.suffix in text_suffixes
        ):
            checked_files.append(path)

            content = path.read_text(
                encoding="utf-8"
            )

            assert ".preparing-" not in content, (
                f"正式产物仍包含 staging 路径：{path}"
            )

    assert checked_files
