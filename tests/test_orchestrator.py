import pytest

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.providers.base import (
    ProviderOutputError,
)
from protein_design_agent.agent.providers.mock import (
    MockProvider,
)


def test_mock_provider_uses_actual_user_text() -> None:
    """模型不能伪造或替换用户原始文本。"""
    provider = MockProvider(
        {
            "raw_text": "模型伪造的文本",
            "input_dir": "sample_data/test_two_chain",
            "input_layout": "existing_chains",
            "binder_chain": "A",
        }
    )

    orchestrator = LocalAgentOrchestrator(provider)

    session = orchestrator.plan_from_text(
        "用户真实输入"
    )

    assert session.request.raw_text == "用户真实输入"
    assert session.plan.request.raw_text == "用户真实输入"


def test_incomplete_mock_request_needs_information() -> None:
    provider = MockProvider({})

    orchestrator = LocalAgentOrchestrator(provider)

    session = orchestrator.plan_from_text(
        "帮我检查并排名这批骨架"
    )

    assert session.provider_name == "mock"
    assert session.plan.status == "NEEDS_INFORMATION"

    assert session.plan.missing_information == [
        "input_dir",
        "input_layout",
    ]

    assert session.plan.execution_allowed is False


def test_complete_single_chain_request_is_ready() -> None:
    provider = MockProvider(
        {
            "project_name": "3c98_agent_test",
            "input_dir": "sample_data/real/3c98_small",
            "input_layout": (
                "concatenated_single_chain"
            ),
            "source_chain": "A",
            "target_residue_count": 132,
            "hotspots": [
                "A:115",
                "A:127",
            ],
            "execute_requested": False,
        }
    )

    orchestrator = LocalAgentOrchestrator(provider)

    session = orchestrator.plan_from_text(
        "检查3C98骨架，A链前132个残基是target，"
        "其余是binder，hotspot为A115和A127。"
    )

    assert session.plan.status == "READY_FOR_REVIEW"
    assert session.plan.execution_allowed is False

    config = session.plan.config_preview
    assert config is not None

    assert config["project_name"] == "3c98_agent_test"
    assert config["input"]["source_chain"] == "A"
    assert config["input"]["target_residue_count"] == 132
    assert config["input"]["normalized_binder_chain"] == "B"

    assert config["regions"]["hotspots"] == [
        "A:115",
        "A:127",
    ]


def test_execution_request_still_requires_review() -> None:
    provider = MockProvider(
        {
            "input_dir": "sample_data/test_two_chain",
            "input_layout": "existing_chains",
            "binder_chain": "A",
            "execute_requested": True,
        }
    )

    orchestrator = LocalAgentOrchestrator(provider)

    session = orchestrator.plan_from_text(
        "直接帮我执行排名"
    )

    assert session.plan.status == "READY_FOR_REVIEW"
    assert session.plan.execution_allowed is False

    assert any(
        "不会自动执行" in warning
        for warning in session.plan.warnings
    )


def test_invalid_provider_output_is_rejected() -> None:
    provider = MockProvider(
        {
            "input_layout": "invented_layout",
        }
    )

    orchestrator = LocalAgentOrchestrator(provider)

    with pytest.raises(
        ProviderOutputError,
        match="无法通过 UserRequest 验证",
    ):
        orchestrator.plan_from_text(
            "测试非法模型输出"
        )


def test_empty_user_text_is_rejected() -> None:
    provider = MockProvider({})

    orchestrator = LocalAgentOrchestrator(provider)

    with pytest.raises(
        ValueError,
        match="用户请求不能为空",
    ):
        orchestrator.plan_from_text("   ")
