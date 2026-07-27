import pytest
from pydantic import ValidationError

from protein_design_agent.schemas.agent_models import (
    AgentPlan,
    UserRequest,
)


def test_incomplete_request_reports_missing_fields() -> None:
    request = UserRequest(
        raw_text="帮我检查并排名这批骨架"
    )

    assert request.required_missing_fields() == [
        "input_dir",
        "input_layout",
    ]


def test_existing_chains_requires_binder_chain() -> None:
    request = UserRequest(
        raw_text="检查已经分链的骨架",
        input_dir="sample_data/test_two_chain",
        input_layout="existing_chains",
    )

    assert request.required_missing_fields() == [
        "binder_chain"
    ]


def test_complete_concatenated_request_has_no_missing_fields() -> None:
    request = UserRequest(
        raw_text=(
            "A链前132个残基是target，"
            "后面是binder"
        ),
        input_dir="sample_data/real/3c98_small",
        input_layout="concatenated_single_chain",
        source_chain="A",
        target_residue_count=132,
    )

    assert request.required_missing_fields() == []


def test_ready_plan_cannot_hide_missing_information() -> None:
    request = UserRequest(
        raw_text="帮我排名骨架"
    )

    with pytest.raises(
        ValidationError,
        match="未声明请求中缺失的信息",
    ):
        AgentPlan(
            status="READY_FOR_REVIEW",
            request=request,
            missing_information=[],
            config_preview={},
        )


def test_v01_plan_cannot_enable_execution() -> None:
    request = UserRequest(
        raw_text="准备排名任务",
        input_dir="sample_data/test_two_chain",
        input_layout="existing_chains",
        binder_chain="A",
    )

    with pytest.raises(
        ValidationError,
        match="execution_allowed 必须为 False",
    ):
        AgentPlan(
            status="READY_FOR_REVIEW",
            request=request,
            config_preview={"project_name": "test"},
            execution_allowed=True,
        )
