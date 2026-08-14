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

    assert "影响：" in text
    assert "RuntimeError" not in text
    assert "只有执行完成后才能分析" not in text
    assert "当前请求与任务阶段不匹配" in text
    assert "可能原因" in text
    assert "建议处理" in text
    assert "不建议立即重试" in text
    assert "确定性兜底说明" not in text


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


def test_guidance_hides_failure_evidence_from_user_output(
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

    assert "当前操作没有完成" in text
    assert "影响：" in text
    assert "建议处理" in text

    assert "已读取的失败证据" not in text
    assert "execution_test.json" not in text
    assert "进程返回码：1" not in text
    assert "missing required column" not in text
    assert "ValueError" not in text


def test_user_guidance_hides_technical_failure_details(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    stderr = bundle / "internal_stderr.log"
    stderr.write_text(
        "VERY_INTERNAL_TRACE_DETAIL\n",
        encoding="utf-8",
    )

    manifest = bundle / "execution_private.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "FAILED",
                "error_type": "InternalRankerError",
                "error_message": (
                    "VERY_INTERNAL_ERROR_MESSAGE"
                ),
                "return_code": 17,
                "stderr_log": str(stderr),
            }
        ),
        encoding="utf-8",
    )

    error = ExecutionManifestError(
        "TOP_LEVEL_TECHNICAL_ERROR",
        manifest,
    )

    context = module.build_safe_error_context(
        kind="FAILED",
        error=error,
        bundle_dir=bundle,
    )

    # 技术诊断仍然必须完整存在。
    assert context["error_type"] == (
        "ExecutionManifestError"
    )
    assert (
        "TOP_LEVEL_TECHNICAL_ERROR"
        in context["error_message"]
    )

    evidence = context["failure_evidence"]
    assert evidence["return_code"] == 17
    assert evidence["error_type"] == (
        "InternalRankerError"
    )

    text = format_error_guidance(
        kind="FAILED",
        error=error,
        bundle_dir=bundle,
        provider=None,
    )

    # 普通用户必须知道操作没有完成。
    assert "当前操作没有完成" in text
    assert "建议处理" in text

    # 但默认界面不能直接倾倒技术诊断。
    assert "ExecutionManifestError" not in text
    assert "TOP_LEVEL_TECHNICAL_ERROR" not in text
    assert "InternalRankerError" not in text
    assert "VERY_INTERNAL_ERROR_MESSAGE" not in text
    assert "VERY_INTERNAL_TRACE_DETAIL" not in text
    assert "execution_private.json" not in text
    assert "stderr" not in text.lower()


def test_explicit_public_message_is_shown(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.user_errors import (
        UserFacingError,
    )

    error = UserFacingError(
        "INTERNAL_TECHNICAL_DETAIL",
        public_message="只有执行完成后才能分析。",
    )

    text = format_error_guidance(
        kind="REJECTED",
        error=error,
        bundle_dir=tmp_path,
        provider=None,
    )

    assert "已确认：" in text
    assert "只有执行完成后才能分析。" in text
    assert "INTERNAL_TECHNICAL_DETAIL" not in text


def test_missing_public_message_hides_raw_error(
    tmp_path: Path,
) -> None:
    from protein_design_agent.agent.user_errors import (
        UserFacingError,
    )

    error = UserFacingError(
        "PRIVATE_INTERNAL_FAILURE"
    )

    text = format_error_guidance(
        kind="FAILED",
        error=error,
        bundle_dir=tmp_path,
        provider=None,
    )

    assert "PRIVATE_INTERNAL_FAILURE" not in text
    assert "已确认：" not in text
    assert "影响：" in text
    assert "建议处理" in text


def test_public_message_override_hides_raw_error(
    tmp_path: Path,
) -> None:
    error = RuntimeError(
        "PRIVATE_CLI_TECHNICAL_DETAIL"
    )

    context = module.build_safe_error_context(
        kind="FAILED",
        error=error,
        bundle_dir=tmp_path,
    )

    assert (
        "PRIVATE_CLI_TECHNICAL_DETAIL"
        in context["error_message"]
    )

    text = format_error_guidance(
        kind="FAILED",
        error=error,
        bundle_dir=tmp_path,
        provider=None,
        public_message_override=(
            "结果分析未完成。"
        ),
    )

    assert "已确认：" in text
    assert "结果分析未完成。" in text
    assert (
        "PRIVATE_CLI_TECHNICAL_DETAIL"
        not in text
    )


def test_error_guidance_supports_missing_bundle() -> None:
    error = RuntimeError(
        "PRIVATE_STARTUP_TECHNICAL_DETAIL"
    )

    context = module.build_safe_error_context(
        kind="FAILED",
        error=error,
        bundle_dir=None,
    )

    assert context["error_type"] == "RuntimeError"
    assert (
        context["error_message"]
        == "PRIVATE_STARTUP_TECHNICAL_DETAIL"
    )
    assert context["state"] == {}
    assert "bundle_name" not in context
    assert "failure_evidence" not in context

    text = format_error_guidance(
        kind="FAILED",
        error=error,
        bundle_dir=None,
        provider=None,
        public_message_override=(
            "模型配置验证未完成。"
        ),
    )

    assert "当前操作没有完成。" in text
    assert "模型配置验证未完成。" in text
    assert "当前任务状态：" not in text
    assert (
        "请检查相关输入和配置后再决定是否重试。"
        in text
    )

    assert "RuntimeError" not in text
    assert (
        "PRIVATE_STARTUP_TECHNICAL_DETAIL"
        not in text
    )


def test_model_guidance_echoing_error_detail_is_rejected(
    tmp_path: Path,
) -> None:
    class EchoErrorProvider:
        name = "echo-error"

        def generate_json(self, messages):
            return {
                "explanation": (
                    "RuntimeError: "
                    "PRIVATE_GUIDANCE_ERROR_MESSAGE"
                ),
                "possible_causes": [],
                "recommended_actions": [
                    "请检查输入。"
                ],
                "safe_to_retry": False,
            }

    text = format_error_guidance(
        kind="FAILED",
        error=RuntimeError(
            "PRIVATE_GUIDANCE_ERROR_MESSAGE"
        ),
        bundle_dir=tmp_path,
        provider=EchoErrorProvider(),
    )

    assert (
        "PRIVATE_GUIDANCE_ERROR_MESSAGE"
        not in text
    )
    assert "RuntimeError" not in text

    assert (
        "确定性兜底说明"
        in text
    )


def test_model_guidance_echoing_internal_evidence_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    internal_manifest = (
        tmp_path
        / "private_execution_manifest.json"
    )

    monkeypatch.setattr(
        module,
        "collect_failure_evidence",
        lambda **kwargs: {
            "error_type": (
                "InternalRankerFailure"
            ),
            "error_message": (
                "PRIVATE_RANKER_FAILURE"
            ),
            "execution_manifest": str(
                internal_manifest
            ),
            "stderr_tail": [
                "PRIVATE_STDERR_LINE_42",
            ],
        },
    )

    class EchoEvidenceProvider:
        name = "echo-evidence"

        def generate_json(self, messages):
            return {
                "explanation": (
                    "请查看 "
                    "private_execution_manifest.json"
                ),
                "possible_causes": [
                    "PRIVATE_STDERR_LINE_42",
                ],
                "recommended_actions": [
                    "检查运行环境。"
                ],
                "safe_to_retry": False,
            }

    text = format_error_guidance(
        kind="FAILED",
        error=RuntimeError(
            "top level failure"
        ),
        bundle_dir=tmp_path,
        provider=EchoEvidenceProvider(),
    )

    assert (
        "private_execution_manifest.json"
        not in text
    )
    assert (
        "PRIVATE_STDERR_LINE_42"
        not in text
    )
    assert (
        "PRIVATE_RANKER_FAILURE"
        not in text
    )

    assert (
        "确定性兜底说明"
        in text
    )
