from pathlib import Path

import protein_design_agent.agent.error_guidance as module
from protein_design_agent.agent.error_guidance import (
    format_error_guidance,
    redact_sensitive_text,
)


class FakeGuidanceProvider:
    name = "fake-guidance"

    def generate_json(self, messages):
        return {
            "explanation": (
                "当前请求与任务阶段不匹配，"
                "原有结果没有被删除。"
            ),
            "possible_causes": [
                "用户跳过了前置步骤。",
            ],
            "recommended_actions": [
                "先查看当前计划和任务状态。",
                "完成前置步骤后再重试。",
            ],
            "safe_to_retry": False,
        }


class BrokenGuidanceProvider:
    name = "broken-guidance"

    def generate_json(self, messages):
        raise RuntimeError("provider unavailable")


def test_sensitive_error_text_is_redacted() -> None:
    text = redact_sensitive_text(
        "Authorization: Bearer secret-token "
        "DEEPSEEK_API_KEY=real-secret "
        "sk-abcdefghijk12345"
    )

    assert "secret-token" not in text
    assert "real-secret" not in text
    assert "sk-abcdefghijk12345" not in text
    assert "REDACTED" in text


def test_model_explains_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "inspect_run_status",
        lambda path: type(
            "Report",
            (),
            {
                "current_stage": "APPROVED",
                "prepare_status": "READY_FOR_REVIEW",
                "approval_status": "APPROVED",
                "execution_status": None,
                "analysis_status": None,
                "explanation_status": None,
                "approval_consumed": False,
            },
        )(),
    )

    text = format_error_guidance(
        kind="REJECTED",
        error=RuntimeError(
            "只有执行完成后才能分析"
        ),
        bundle_dir=tmp_path,
        provider=FakeGuidanceProvider(),
    )

    assert "确定性错误" in text
    assert "当前请求与任务阶段不匹配" in text
    assert "可能原因" in text
    assert "建议处理" in text
    assert "不建议立即重试" in text


def test_model_failure_uses_deterministic_fallback(
    tmp_path: Path,
) -> None:
    text = format_error_guidance(
        kind="FAILED",
        error=RuntimeError(
            "input directory not found"
        ),
        bundle_dir=tmp_path,
        provider=BrokenGuidanceProvider(),
    )

    assert "当前操作没有完成" in text
    assert "检查输入路径" in text
    assert "确定性兜底说明" in text
