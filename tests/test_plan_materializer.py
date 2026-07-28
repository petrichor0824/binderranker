import json
from pathlib import Path

import pytest

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.plan_materializer import (
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
