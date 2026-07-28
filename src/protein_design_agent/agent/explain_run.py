#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
已完成 Ranker 任务的结果解释入口。

职责：
1. 检查 bundle 中的确定性结果；
2. 加载指定模型 Provider；
3. 显式检查联网授权；
4. 调用受控结果解释器；
5. 返回生成产物的位置。

本模块不执行 BinderRanker，也不修改原始结果。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from protein_design_agent.agent.provider_factory import (
    build_request_parser_provider,
)
from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.agent.providers.openai_compatible import (
    OpenAICompatibleProvider,
)
from protein_design_agent.agent.result_explainer import (
    explain_ranker_results,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


class ExplainRunError(RuntimeError):
    """结果解释入口错误。"""


class ExplainRunResult(BaseModel):
    """一次 explain-run 的确定性返回记录。"""

    schema_version: str = "0.1"
    status: str = Field(default="EXPLAINED")

    provider_name: str = Field(min_length=1)

    bundle_dir: Path
    output_dir: Path

    result_summary_path: Path
    failure_analysis_path: Path

    evidence_path: Path
    explanation_json_path: Path
    explanation_markdown_path: Path


def resolve_explanation_output_dir(
    *,
    bundle_dir: Path,
    output_dir: Path,
) -> Path:
    """
    相对输出目录相对于 bundle 解析。

    例如：
        output_dir=explanations/cli_v1
    最终得到：
        <bundle>/explanations/cli_v1
    """
    if output_dir.is_absolute():
        return output_dir.resolve()

    return (
        bundle_dir
        / output_dir
    ).resolve()


def run_explain_run(
    *,
    bundle_dir: Path,
    model_config_path: Path,
    profile_name: str | None,
    output_dir: Path,
    allow_network: bool,
    result_summary_path: Path | None = None,
    failure_analysis_path: Path | None = None,
    max_output_tokens: int = 8192,
    timeout_seconds: float = 180.0,
) -> ExplainRunResult:
    """
    对一个已经完成结果解析的 bundle 生成模型解释。

    默认读取 bundle 根目录中的结果文件，也允许
    analyze-run 显式传入本次新生成的结果文件。
    """
    if not allow_network:
        raise ExplainRunError(
            "真实模型解释需要显式传入 "
            "--allow-network"
        )

    if max_output_tokens < 128:
        raise ExplainRunError(
            "max_output_tokens 不能小于 128"
        )

    if timeout_seconds <= 0:
        raise ExplainRunError(
            "timeout_seconds 必须大于 0"
        )

    resolved_bundle = bundle_dir.resolve()

    if not resolved_bundle.is_dir():
        raise ExplainRunError(
            f"bundle 目录不存在：{resolved_bundle}"
        )

    resolved_model_config = (
        model_config_path.resolve()
    )

    if not resolved_model_config.is_file():
        raise ExplainRunError(
            "模型配置文件不存在："
            f"{resolved_model_config}"
        )

    resolved_result_summary_path = (
        result_summary_path.resolve()
        if result_summary_path is not None
        else (
            resolved_bundle
            / "agent_result_summary.json"
        )
    )

    resolved_failure_analysis_path = (
        failure_analysis_path.resolve()
        if failure_analysis_path is not None
        else (
            resolved_bundle
            / "agent_failure_analysis_v2.json"
        )
    )

    for required_path in (
        resolved_result_summary_path,
        resolved_failure_analysis_path,
    ):
        if not required_path.is_file():
            raise ExplainRunError(
                "结果解释缺少必要输入："
                f"{required_path}"
            )

    resolved_output_dir = (
        resolve_explanation_output_dir(
            bundle_dir=resolved_bundle,
            output_dir=output_dir,
        )
    )

    resolved_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    expected_paths = {
        "evidence": (
            resolved_output_dir
            / "agent_explanation_evidence.json"
        ),
        "json": (
            resolved_output_dir
            / "agent_explanation.json"
        ),
        "markdown": (
            resolved_output_dir
            / "agent_explanation.md"
        ),
    }

    existing = [
        output_path
        for output_path in expected_paths.values()
        if output_path.exists()
    ]

    if existing:
        raise ExplainRunError(
            "解释输出已经存在，禁止覆盖："
            + ", ".join(
                str(output_path)
                for output_path in existing
            )
        )

    config = load_model_provider_config(
        resolved_model_config
    )

    provider = build_request_parser_provider(
        config,
        profile_name=profile_name,
    )

    if not isinstance(
        provider,
        StructuredJSONProvider,
    ):
        raise ExplainRunError(
            "所选 Provider 不支持结构化 JSON 生成"
        )

    if isinstance(
        provider,
        OpenAICompatibleProvider,
    ):
        provider.settings = (
            provider.settings.model_copy(
                update={
                    "max_output_tokens": (
                        max_output_tokens
                    ),
                    "timeout_seconds": (
                        timeout_seconds
                    ),
                }
            )
        )

    explain_ranker_results(
        provider=provider,
        result_summary_path=(
            resolved_result_summary_path
        ),
        failure_analysis_path=(
            resolved_failure_analysis_path
        ),
        output_dir=resolved_output_dir,
        confirm_model_call=True,
    )

    missing_outputs = [
        output_path
        for output_path in expected_paths.values()
        if not output_path.is_file()
    ]

    if missing_outputs:
        raise ExplainRunError(
            "模型解释完成后缺少预期输出："
            + ", ".join(
                str(output_path)
                for output_path in missing_outputs
            )
        )

    return ExplainRunResult(
        provider_name=provider.name,
        bundle_dir=resolved_bundle,
        output_dir=resolved_output_dir,
        result_summary_path=(
            resolved_result_summary_path
        ),
        failure_analysis_path=(
            resolved_failure_analysis_path
        ),
        evidence_path=(
            expected_paths["evidence"]
        ),
        explanation_json_path=(
            expected_paths["json"]
        ),
        explanation_markdown_path=(
            expected_paths["markdown"]
        ),
    )
