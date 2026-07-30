import json
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


class ExecutionManifestError(RuntimeError):
    def __init__(
        self,
        message: str,
        execution_manifest: Path,
    ) -> None:
        super().__init__(message)
        self.execution_manifest = (
            execution_manifest
        )


def test_failed_manifest_and_stderr_are_collected(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    logs = bundle / "logs"
    logs.mkdir()

    stderr = logs / "ranker_stderr.log"
    stderr.write_text(
        "\n".join(
            [
                f"ordinary line {index}"
                for index in range(50)
            ]
            + [
                (
                    "Authorization: Bearer "
                    "secret-token"
                ),
                "DEEPSEEK_API_KEY=real-secret",
            ]
        ),
        encoding="utf-8",
    )

    manifest = bundle / "execution_test.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "FAILED",
                "error_type": "RuntimeError",
                "error_message": (
                    "ranker exited with code 2"
                ),
                "return_code": 2,
                "stderr_log": str(stderr),
                "missing_outputs": [
                    str(
                        bundle
                        / "results"
                        / "scored.csv"
                    )
                ],
                "execution_attempted": True,
                "process_started": True,
                "approval_reusable": False,
            }
        ),
        encoding="utf-8",
    )

    context = module.build_safe_error_context(
        kind="FAILED",
        error=ExecutionManifestError(
            "BinderRanker failed",
            manifest,
        ),
        bundle_dir=bundle,
    )

    evidence = context["failure_evidence"]

    assert evidence["source_kind"] == (
        "execution"
    )
    assert evidence["return_code"] == 2
    assert evidence["missing_outputs"] == [
        "scored.csv"
    ]
    assert len(evidence["stderr_tail"]) <= 40

    combined = "\n".join(
        evidence["stderr_tail"]
    )

    assert "secret-token" not in combined
    assert "real-secret" not in combined
    assert "REDACTED" in combined


def test_guidance_displays_failure_evidence(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    stderr = bundle / "stderr.log"
    stderr.write_text(
        "missing required column\n",
        encoding="utf-8",
    )

    manifest = bundle / "execution_test.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "FAILED",
                "error_type": "ValueError",
                "error_message": (
                    "missing output column"
                ),
                "return_code": 1,
                "stderr_log": str(stderr),
            }
        ),
        encoding="utf-8",
    )

    text = format_error_guidance(
        kind="FAILED",
        error=ExecutionManifestError(
            "execution failed",
            manifest,
        ),
        bundle_dir=bundle,
        provider=None,
    )

    assert "已读取的失败证据" in text
    assert "execution_test.json" in text
    assert "进程返回码：1" in text
    assert "missing required column" in text
