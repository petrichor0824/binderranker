import json
from pathlib import Path

import pytest

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.plan_materializer import (
    PlanMaterializationError,
    load_planning_session,
    materialize_planning_session,
)
from protein_design_agent.agent.providers.mock import (
    MockProvider,
)
from protein_design_agent.schemas.project_config import (
    load_project_config,
)


def write_session(
    tmp_path: Path,
    payload: dict,
    text: str = "测试请求",
) -> Path:
    provider = MockProvider(payload)
    agent = LocalAgentOrchestrator(provider)
    session = agent.plan_from_text(text)

    path = tmp_path / "session.json"
    path.write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return path


def complete_payload() -> dict:
    return {
        "project_name": "materializer_test",
        "input_dir": "sample_data/test_two_chain",
        "input_layout": "existing_chains",
        "binder_chain": "A",
        "region_policy": "diagnostic",
        "region_filter": "off",
        "execute_requested": False,
    }


def test_ready_plan_materializes_to_valid_yaml(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "project.yaml"

    result = materialize_planning_session(
        session_path=session_path,
        output_config=output,
    )

    assert result.status == "MATERIALIZED"
    assert result.workflow_executed is False
    assert output.exists()
    assert result.provenance_file.exists()

    project = load_project_config(output)

    assert project.project_name == (
        "materializer_test"
    )
    assert project.input.binder_chain == "A"

    # 确认字符串 off 没有被 YAML 转成 False。
    assert project.ranking.region_filter == "off"


def test_incomplete_plan_cannot_be_materialized(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        {},
        text="帮我排名这批骨架",
    )

    with pytest.raises(
        ValueError,
        match="只有 READY_FOR_REVIEW",
    ):
        materialize_planning_session(
            session_path=session_path,
            output_config=tmp_path / "blocked.yaml",
        )


def test_existing_output_is_protected(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "existing.yaml"
    output.write_text(
        "important existing content\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        materialize_planning_session(
            session_path=session_path,
            output_config=output,
            overwrite=False,
        )

    assert output.read_text(
        encoding="utf-8"
    ) == "important existing content\n"


def test_mismatched_nested_request_is_rejected(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    raw = json.loads(
        session_path.read_text(encoding="utf-8")
    )

    raw["plan"]["request"]["binder_chain"] = "B"

    session_path.write_text(
        json.dumps(
            raw,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 文件本身仍能解析，但内外 request 不一致。
    load_planning_session(session_path)

    with pytest.raises(
        ValueError,
        match="request 与 plan.request 不一致",
    ):
        materialize_planning_session(
            session_path=session_path,
            output_config=tmp_path / "bad.yaml",
        )


def test_provenance_contains_hashes(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "project.yaml"

    result = materialize_planning_session(
        session_path=session_path,
        output_config=output,
    )

    provenance = json.loads(
        result.provenance_file.read_text(
            encoding="utf-8"
        )
    )

    assert len(
        provenance["source_session_sha256"]
    ) == 64

    assert len(
        provenance["output_config_sha256"]
    ) == 64

    assert provenance["workflow_executed"] is False
    assert provenance["execution_allowed"] is False


def test_non_ready_plan_has_safe_public_message(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        {},
        text="帮我排名这批骨架",
    )

    with pytest.raises(
        PlanMaterializationError
    ) as exc_info:
        materialize_planning_session(
            session_path=session_path,
            output_config=(
                tmp_path / "blocked.yaml"
            ),
        )

    assert (
        "只有 READY_FOR_REVIEW"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "只有 READY_FOR_REVIEW 计划"
            "可以落地为正式项目配置。"
        )
    )


def test_materialization_rejects_same_output_paths(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "same-output.yaml"

    with pytest.raises(
        PlanMaterializationError
    ) as exc_info:
        materialize_planning_session(
            session_path=session_path,
            output_config=output,
            provenance_file=output,
        )

    assert (
        exc_info.value.public_message
        == (
            "项目配置与来源记录"
            "不能使用同一路径。"
        )
    )

    assert not output.exists()


def test_provenance_publish_failure_restores_existing_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "project.yaml"
    provenance = tmp_path / "provenance.json"

    original_config = (
        b"important old project config\n"
    )
    original_provenance = (
        b'{"important": "old provenance"}\n'
    )

    output.write_bytes(
        original_config
    )
    provenance.write_bytes(
        original_provenance
    )

    import protein_design_agent.agent.plan_materializer as module

    real_replace = module.os.replace

    def controlled_replace(
        src,
        dst,
    ):
        src_path = Path(src)
        dst_path = Path(dst)

        if (
            dst_path == provenance
            and ".materializing-"
            in src_path.name
        ):
            raise OSError(
                "PRIVATE_PROVENANCE_PUBLISH_FAILURE"
            )

        return real_replace(
            src,
            dst,
        )

    monkeypatch.setattr(
        module.os,
        "replace",
        controlled_replace,
    )

    with pytest.raises(
        PlanMaterializationError
    ) as exc_info:
        materialize_planning_session(
            session_path=session_path,
            output_config=output,
            provenance_file=provenance,
            overwrite=True,
        )

    assert (
        output.read_bytes()
        == original_config
    )

    assert (
        provenance.read_bytes()
        == original_provenance
    )

    assert (
        "PRIVATE_PROVENANCE_PUBLISH_FAILURE"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "计划落地发布失败；"
            "已恢复发布前的项目配置状态。"
        )
    )


def test_provenance_publish_failure_removes_new_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "new-project.yaml"
    provenance = tmp_path / "new-provenance.json"

    import protein_design_agent.agent.plan_materializer as module

    real_replace = module.os.replace

    def controlled_replace(
        src,
        dst,
    ):
        src_path = Path(src)
        dst_path = Path(dst)

        if (
            dst_path == provenance
            and ".materializing-"
            in src_path.name
        ):
            raise OSError(
                "PRIVATE_NEW_PROVENANCE_FAILURE"
            )

        return real_replace(
            src,
            dst,
        )

    monkeypatch.setattr(
        module.os,
        "replace",
        controlled_replace,
    )

    with pytest.raises(
        PlanMaterializationError
    ) as exc_info:
        materialize_planning_session(
            session_path=session_path,
            output_config=output,
            provenance_file=provenance,
        )

    assert not output.exists()
    assert not provenance.exists()

    assert (
        "PRIVATE_NEW_PROVENANCE_FAILURE"
        in str(exc_info.value)
    )

    assert (
        exc_info.value.public_message
        == (
            "计划落地发布失败；"
            "已恢复发布前的项目配置状态。"
        )
    )


def test_successful_materialization_leaves_no_staging_files(
    tmp_path: Path,
) -> None:
    session_path = write_session(
        tmp_path,
        complete_payload(),
    )

    output = tmp_path / "clean-project.yaml"
    provenance = tmp_path / "clean-provenance.json"

    materialize_planning_session(
        session_path=session_path,
        output_config=output,
        provenance_file=provenance,
    )

    leftovers = [
        path
        for path in tmp_path.iterdir()
        if ".materializing-" in path.name
    ]

    assert leftovers == []
