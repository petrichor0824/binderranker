#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
已完成 BinderRanker 运行的统一分析流水线。

流程：
1. 从执行产物解析 Ranker 结果；
2. 生成确定性结果摘要；
3. 生成确定性失败分析；
4. 可选调用受控大模型解释器；
5. 写入分析清单。

本模块不会执行 BinderRanker。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from protein_design_agent.agent.analysis_artifacts import (
    build_analysis_provenance_seal,
)

from protein_design_agent.agent.failure_analysis import (
    write_failure_analysis,
)
from protein_design_agent.agent.ranker_result_parser import (
    write_ranker_result_summary,
)


def run_explain_run(**kwargs: Any) -> Any:
    """
    按需加载可选的模型解释运行时。

    保留模块级依赖 seam，便于现有调用方和测试注入；
    deterministic analyze 路径不会因此加载模型 runtime。
    """
    from protein_design_agent.agent.explain_run import (
        run_explain_run as _run_explain_run,
    )

    return _run_explain_run(**kwargs)


class AnalyzeRunError(RuntimeError):
    """统一结果分析失败。"""


class AnalyzeRunManifest(BaseModel):
    """一次 analyze-run 的审计清单。"""

    schema_version: str = "0.2"
    status: str

    bundle_dir: Path
    analysis_dir: Path

    with_model: bool
    provider_name: str | None = None

    result_summary_path: Path | None = None
    failure_analysis_path: Path | None = None

    completed_at_utc: str | None = None
    result_summary_sha256: str | None = None
    failure_analysis_sha256: str | None = None
    execution_manifest_path: Path | None = None
    execution_manifest_sha256: str | None = None

    explanation_evidence_path: Path | None = None
    explanation_json_path: Path | None = None
    explanation_markdown_path: Path | None = None

    explanation_status: str | None = None
    explanation_error_type: str | None = None
    explanation_error_message: str | None = None

    error_type: str | None = None
    error_message: str | None = None


class AnalyzeRunResult(BaseModel):
    """analyze-run 的返回结果。"""

    schema_version: str = "0.1"
    status: str = Field(default="COMPLETED")

    bundle_dir: Path
    analysis_dir: Path
    manifest_path: Path

    result_summary_path: Path
    failure_analysis_path: Path

    with_model: bool
    provider_name: str | None = None

    explanation_evidence_path: Path | None = None
    explanation_json_path: Path | None = None
    explanation_markdown_path: Path | None = None

    explanation_status: str | None = None
    explanation_error_type: str | None = None
    explanation_error_message: str | None = None


def write_manifest_atomic(
    *,
    path: Path,
    manifest: AnalyzeRunManifest,
) -> None:
    """原子更新分析清单。"""
    temporary = path.with_name(
        path.name + ".tmp"
    )

    temporary.write_text(
        manifest.model_dump_json(
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def resolve_analysis_dir(
    *,
    bundle_dir: Path,
    analysis_dir: Path,
) -> Path:
    if analysis_dir.is_absolute():
        return analysis_dir.resolve()

    return (
        bundle_dir
        / analysis_dir
    ).resolve()


def next_analysis_directory(
    *,
    bundle_dir: Path,
    prefix: str,
) -> Path:
    """
    返回一个不会覆盖历史分析尝试的相对目录。

    已存在的 COMPLETED、FAILED 或其他历史目录
    都视为已占用，不进行复用。
    """
    analyses_root = (
        bundle_dir.resolve()
        / "analyses"
    )

    index = 1

    while True:
        name = f"{prefix}_{index:04d}"
        candidate = analyses_root / name

        if not candidate.exists():
            return Path("analyses") / name

        index += 1


def run_analyze_run(
    *,
    bundle_dir: Path,
    analysis_dir: Path,
    with_model: bool,
    model_config_path: Path | None = None,
    profile_name: str | None = None,
    allow_network: bool = False,
    max_output_tokens: int = 8192,
    timeout_seconds: float = 180.0,
) -> AnalyzeRunResult:
    """
    分析一个已经完成 BinderRanker 执行的 bundle。

    with_model=False：
        只进行确定性解析和失败分析。

    with_model=True：
        在确定性结果基础上调用受控解释器。
    """
    resolved_bundle = bundle_dir.resolve()

    if not resolved_bundle.is_dir():
        raise AnalyzeRunError(
            f"bundle 目录不存在：{resolved_bundle}"
        )

    if with_model:
        if not allow_network:
            raise AnalyzeRunError(
                "启用模型解释时必须显式传入 "
                "--allow-network"
            )

        if model_config_path is None:
            raise AnalyzeRunError(
                "启用模型解释时必须提供 "
                "--model-config"
            )

        resolved_model_config = (
            model_config_path.resolve()
        )

        if not resolved_model_config.is_file():
            raise AnalyzeRunError(
                "模型配置文件不存在："
                f"{resolved_model_config}"
            )
    else:
        resolved_model_config = None

    resolved_analysis_dir = (
        resolve_analysis_dir(
            bundle_dir=resolved_bundle,
            analysis_dir=analysis_dir,
        )
    )

    if resolved_analysis_dir.exists():
        raise AnalyzeRunError(
            "分析目录已经存在，禁止覆盖："
            f"{resolved_analysis_dir}"
        )

    resolved_analysis_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    manifest_path = (
        resolved_analysis_dir
        / "analyze_run_manifest.json"
    )

    result_summary_path = (
        resolved_analysis_dir
        / "agent_result_summary.json"
    )

    failure_analysis_path = (
        resolved_analysis_dir
        / "agent_failure_analysis_v2.json"
    )

    running_manifest = AnalyzeRunManifest(
        status="RUNNING",
        bundle_dir=resolved_bundle,
        analysis_dir=resolved_analysis_dir,
        with_model=with_model,
        result_summary_path=(
            result_summary_path
        ),
        failure_analysis_path=(
            failure_analysis_path
        ),
    )

    write_manifest_atomic(
        path=manifest_path,
        manifest=running_manifest,
    )

    try:
        written_summary = (
            write_ranker_result_summary(
                bundle_dir=resolved_bundle,
                output_path=result_summary_path,
            )
        )

        written_failure = (
            write_failure_analysis(
                result_summary_path=(
                    written_summary
                ),
                output_path=(
                    failure_analysis_path
                ),
            )
        )

        provider_name: str | None = None
        explanation_evidence_path = None
        explanation_json_path = None
        explanation_markdown_path = None

        explanation_status = "NOT_REQUESTED"
        explanation_error_type = None
        explanation_error_message = None

        if with_model:
            try:
                explanation_result = (
                    run_explain_run(
                        bundle_dir=resolved_bundle,
                        model_config_path=(
                            resolved_model_config
                        ),
                        profile_name=profile_name,
                        output_dir=(
                            resolved_analysis_dir
                            / "explanation"
                        ),
                        allow_network=True,
                        result_summary_path=(
                            written_summary
                        ),
                        failure_analysis_path=(
                            written_failure
                        ),
                        max_output_tokens=(
                            max_output_tokens
                        ),
                        timeout_seconds=(
                            timeout_seconds
                        ),
                    )
                )
            except Exception as exc:
                # 模型解释是可选增强。
                # 其失败不能覆盖已经成功生成的
                # 确定性摘要和失败分析。
                explanation_status = "UNAVAILABLE"
                explanation_error_type = (
                    type(exc).__name__
                )
                explanation_error_message = str(exc)
            else:
                explanation_status = "EXPLAINED"
                provider_name = (
                    explanation_result.provider_name
                )
                explanation_evidence_path = (
                    explanation_result.evidence_path
                )
                explanation_json_path = (
                    explanation_result
                    .explanation_json_path
                )
                explanation_markdown_path = (
                    explanation_result
                    .explanation_markdown_path
                )

        provenance_seal = (
            build_analysis_provenance_seal(
                bundle_dir=resolved_bundle,
                result_summary_path=(
                    written_summary
                ),
                failure_analysis_path=(
                    written_failure
                ),
            )
        )

        completed_manifest = (
            running_manifest.model_copy(
                update={
                    "status": "COMPLETED",
                    **provenance_seal.model_dump(
                        mode="python"
                    ),
                    "provider_name": (
                        provider_name
                    ),
                    (
                        "explanation_"
                        "evidence_path"
                    ): explanation_evidence_path,
                    (
                        "explanation_"
                        "json_path"
                    ): explanation_json_path,
                    (
                        "explanation_"
                        "markdown_path"
                    ): explanation_markdown_path,
                    "explanation_status": (
                        explanation_status
                    ),
                    "explanation_error_type": (
                        explanation_error_type
                    ),
                    "explanation_error_message": (
                        explanation_error_message
                    ),
                }
            )
        )

        write_manifest_atomic(
            path=manifest_path,
            manifest=completed_manifest,
        )

        return AnalyzeRunResult(
            bundle_dir=resolved_bundle,
            analysis_dir=(
                resolved_analysis_dir
            ),
            manifest_path=manifest_path,
            result_summary_path=(
                written_summary
            ),
            failure_analysis_path=(
                written_failure
            ),
            with_model=with_model,
            provider_name=provider_name,
            explanation_evidence_path=(
                explanation_evidence_path
            ),
            explanation_json_path=(
                explanation_json_path
            ),
            explanation_markdown_path=(
                explanation_markdown_path
            ),
            explanation_status=(
                explanation_status
            ),
            explanation_error_type=(
                explanation_error_type
            ),
            explanation_error_message=(
                explanation_error_message
            ),
        )

    except Exception as exc:
        failed_manifest = (
            running_manifest.model_copy(
                update={
                    "status": "FAILED",
                    "error_type": (
                        type(exc).__name__
                    ),
                    "error_message": str(exc),
                }
            )
        )

        write_manifest_atomic(
            path=manifest_path,
            manifest=failed_manifest,
        )

        raise AnalyzeRunError(
            f"analyze-run 失败：{exc}"
        ) from exc
