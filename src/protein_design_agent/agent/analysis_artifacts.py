#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
确定性发现一次可用于结果解释的分析产物。

优先级：

1. 调用方显式提供的结果摘要和失败分析；
2. 最新一个 COMPLETED analyze-run manifest；
3. 旧版 Bundle 根目录结果文件。

本模块不调用模型，不执行 BinderRanker，
也不修改任何分析或科研结果。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


AnalysisArtifactSource = Literal[
    "EXPLICIT",
    "ANALYSIS_MANIFEST",
    "LEGACY_ROOT",
]

AnalysisProvenanceStatus = Literal[
    "SEALED_VERIFIED",
    "UNSEALED_LEGACY",
    "EXPLICIT_UNSEALED",
]

ANALYSIS_SEAL_FIELDS = (
    "result_summary_sha256",
    "failure_analysis_sha256",
    "execution_manifest_path",
    "execution_manifest_sha256",
)

OPTIONAL_REPORT_SEAL_FIELDS = (
    "deterministic_report_path",
    "deterministic_report_sha256",
)

SUPPORTED_ANALYSIS_MANIFEST_SCHEMAS = {
    "0.1",
    "0.2",
    "0.3",
}


class AnalysisArtifactError(RuntimeError):
    """无法安全确定分析产物。"""


class AnalysisArtifactNotFoundError(AnalysisArtifactError):
    """当前 Bundle 尚无可读取的完整分析产物。"""


class AnalysisArtifacts(BaseModel):
    """一次解释所使用的确定性分析产物。"""

    schema_version: str = "0.1"

    source: AnalysisArtifactSource
    provenance_status: AnalysisProvenanceStatus
    bundle_dir: Path

    analysis_manifest_path: Path | None = None

    result_summary_path: Path
    failure_analysis_path: Path
    deterministic_report_path: Path | None = None


def path_is_inside_bundle(
    path: Path,
    bundle_dir: Path,
) -> bool:
    """路径必须位于当前 Bundle 内。"""
    try:
        path.resolve().relative_to(
            bundle_dir.resolve()
        )
    except ValueError:
        return False

    return True


def read_manifest(
    path: Path,
) -> dict[str, Any] | None:
    """
    尝试读取 analyze-run manifest。

    无法读取或不是 JSON 对象时返回 None。
    这允许忽略未完整写出的历史失败尝试。
    """
    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def validate_completed_manifest_schema(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    """Reject unknown or incomplete completed-analysis generations."""
    version = manifest.get("schema_version")

    if version not in (
        SUPPORTED_ANALYSIS_MANIFEST_SCHEMAS
    ):
        raise AnalysisArtifactError(
            "分析清单使用不支持的 schema_version："
            f"{version!r}；文件：{manifest_path}"
        )

    if version == "0.3":
        required_report_fields = {
            "deterministic_report_path",
            "deterministic_report_sha256",
        }
        missing = sorted(
            field
            for field in required_report_fields
            if manifest.get(field) in (None, "")
        )
        if missing:
            raise AnalysisArtifactError(
                "分析清单 schema 0.3 缺少确定性报告"
                f"完整性字段：{missing}；文件："
                f"{manifest_path}"
            )


def validate_artifact_path(
    *,
    path: Path,
    bundle_dir: Path,
    description: str,
) -> Path:
    """验证分析产物位于 Bundle 内且真实存在。"""
    resolved = path.resolve()

    if not path_is_inside_bundle(
        resolved,
        bundle_dir,
    ):
        raise AnalysisArtifactError(
            f"{description}位于 Bundle 外："
            f"{resolved}"
        )

    if not resolved.is_file():
        raise AnalysisArtifactError(
            f"{description}不存在：{resolved}"
        )

    return resolved


def resolve_manifest_artifact_path(
    *,
    raw_path: Any,
    manifest_path: Path,
    bundle_dir: Path,
    description: str,
) -> Path:
    """解析 manifest 中声明的分析产物路径。"""
    if not isinstance(
        raw_path,
        str,
    ) or not raw_path.strip():
        raise AnalysisArtifactError(
            f"分析清单缺少 {description} 路径："
            f"{manifest_path}"
        )

    declared = Path(raw_path)

    if not declared.is_absolute():
        declared = (
            manifest_path.parent
            / declared
        )

    return validate_artifact_path(
        path=declared,
        bundle_dir=bundle_dir,
        description=description,
    )


def manifest_sort_key(
    item: tuple[
        Path,
        dict[str, Any],
    ],
) -> tuple[str, int, str]:
    """
    为 COMPLETED analysis 建立确定性排序。

    新版 manifest 后续会正式记录 completed_at_utc。
    当前旧 manifest 没有该字段时，暂时使用文件 mtime，
    并以完整路径作为最终稳定 tie-breaker。
    """
    path, manifest = item

    raw_completed = manifest.get(
        "completed_at_utc"
    )

    completed_at = (
        str(raw_completed)
        if raw_completed
        else ""
    )

    try:
        modified_ns = (
            path.stat().st_mtime_ns
        )
    except OSError:
        modified_ns = 0

    return (
        completed_at,
        modified_ns,
        path.as_posix(),
    )


def sha256_file(
    path: Path,
) -> str:
    """计算文件 SHA256。"""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def utc_now() -> str:
    """返回 UTC ISO-8601 时间。"""
    return datetime.now(
        timezone.utc
    ).isoformat()


class AnalysisProvenanceSeal(BaseModel):
    """一次确定性分析的完整性封印。"""

    completed_at_utc: str

    result_summary_sha256: str
    failure_analysis_sha256: str
    deterministic_report_path: Path | None = None
    deterministic_report_sha256: str | None = None

    execution_manifest_path: Path
    execution_manifest_sha256: str


def resolve_summary_execution_manifest(
    *,
    result_summary_path: Path,
    bundle_dir: Path,
) -> Path:
    """读取结果摘要声明的 execution manifest。"""
    summary = read_manifest(
        result_summary_path
    )

    if summary is None:
        raise AnalysisArtifactError(
            "结果摘要不是合法 JSON 对象："
            f"{result_summary_path}"
        )

    raw_path = summary.get(
        "execution_manifest"
    )

    if not isinstance(
        raw_path,
        str,
    ) or not raw_path.strip():
        raise AnalysisArtifactError(
            "结果摘要缺少 execution_manifest"
        )

    execution_path = Path(raw_path)

    if not execution_path.is_absolute():
        execution_path = (
            bundle_dir
            / execution_path
        )

    return validate_artifact_path(
        path=execution_path,
        bundle_dir=bundle_dir,
        description="Execution Manifest",
    )


def build_analysis_provenance_seal(
    *,
    bundle_dir: Path,
    result_summary_path: Path,
    failure_analysis_path: Path,
    deterministic_report_path: Path | None = None,
) -> AnalysisProvenanceSeal:
    """为一次成功的确定性分析生成完整性封印。"""
    bundle = bundle_dir.resolve()

    summary = validate_artifact_path(
        path=result_summary_path,
        bundle_dir=bundle,
        description="结果摘要",
    )

    failure = validate_artifact_path(
        path=failure_analysis_path,
        bundle_dir=bundle,
        description="失败分析",
    )

    report: Path | None = None
    if deterministic_report_path is not None:
        report = validate_artifact_path(
            path=deterministic_report_path,
            bundle_dir=bundle,
            description="确定性分析报告",
        )

    execution = (
        resolve_summary_execution_manifest(
            result_summary_path=summary,
            bundle_dir=bundle,
        )
    )

    return AnalysisProvenanceSeal(
        completed_at_utc=utc_now(),
        result_summary_sha256=(
            sha256_file(summary)
        ),
        failure_analysis_sha256=(
            sha256_file(failure)
        ),
        deterministic_report_path=report,
        deterministic_report_sha256=(
            None
            if report is None
            else sha256_file(report)
        ),
        execution_manifest_path=execution,
        execution_manifest_sha256=(
            sha256_file(execution)
        ),
    )


def verify_analysis_provenance(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    bundle_dir: Path,
    result_summary_path: Path,
    failure_analysis_path: Path,
    deterministic_report_path: Path | None = None,
) -> AnalysisProvenanceStatus:
    """
    验证新版 analysis provenance seal。

    完全没有 seal 字段表示旧版分析；
    只存在部分 seal 字段则视为损坏。
    """
    present = {
        field
        for field in ANALYSIS_SEAL_FIELDS
        if manifest.get(field)
        not in (None, "")
    }

    report_seal_present = {
        field
        for field in OPTIONAL_REPORT_SEAL_FIELDS
        if manifest.get(field)
        not in (None, "")
    }

    if not present:
        if report_seal_present:
            raise AnalysisArtifactError(
                "分析清单仅包含确定性报告 seal，"
                "缺少基础 provenance seal："
                f"{manifest_path}"
            )
        return "UNSEALED_LEGACY"

    required = set(
        ANALYSIS_SEAL_FIELDS
    )

    if present != required:
        raise AnalysisArtifactError(
            "分析清单 provenance seal 不完整："
            f"{manifest_path}"
        )

    if report_seal_present and (
        report_seal_present
        != set(OPTIONAL_REPORT_SEAL_FIELDS)
    ):
        raise AnalysisArtifactError(
            "确定性分析报告 provenance seal 不完整："
            f"{manifest_path}"
        )

    if (
        report_seal_present
        and deterministic_report_path is None
    ):
        raise AnalysisArtifactError(
            "分析清单声明了确定性报告 seal，"
            "但没有可验证的报告路径"
        )

    completed_at = manifest.get(
        "completed_at_utc"
    )

    if not isinstance(
        completed_at,
        str,
    ) or not completed_at.strip():
        raise AnalysisArtifactError(
            "分析清单 provenance seal "
            "缺少 completed_at_utc"
        )

    execution = (
        resolve_manifest_artifact_path(
            raw_path=manifest.get(
                "execution_manifest_path"
            ),
            manifest_path=manifest_path,
            bundle_dir=bundle_dir,
            description="Execution Manifest",
        )
    )

    checks = (
        (
            result_summary_path,
            manifest.get(
                "result_summary_sha256"
            ),
            "结果摘要",
        ),
        (
            failure_analysis_path,
            manifest.get(
                "failure_analysis_sha256"
            ),
            "失败分析",
        ),
        (
            execution,
            manifest.get(
                "execution_manifest_sha256"
            ),
            "Execution Manifest",
        ),
    )

    mutable_checks = list(checks)
    if deterministic_report_path is not None:
        mutable_checks.append(
            (
                deterministic_report_path,
                manifest.get(
                    "deterministic_report_sha256"
                ),
                "确定性分析报告",
            )
        )

    for path, expected, description in (
        mutable_checks
    ):
        if not isinstance(
            expected,
            str,
        ) or len(expected) != 64:
            raise AnalysisArtifactError(
                f"{description} SHA256 字段无效"
            )

        actual = sha256_file(path)

        if actual != expected:
            raise AnalysisArtifactError(
                f"{description} SHA256 不匹配："
                f"{path}"
            )

    summary_execution = (
        resolve_summary_execution_manifest(
            result_summary_path=(
                result_summary_path
            ),
            bundle_dir=bundle_dir,
        )
    )

    if summary_execution != execution:
        raise AnalysisArtifactError(
            "结果摘要声明的 Execution Manifest "
            "与分析清单 provenance 不一致"
        )

    return "SEALED_VERIFIED"


def resolve_analysis_artifacts(
    *,
    bundle_dir: Path,
    result_summary_path: Path | None = None,
    failure_analysis_path: Path | None = None,
) -> AnalysisArtifacts:
    """
    找到本次结果解释应使用的确定性分析产物。
    """
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise AnalysisArtifactError(
            f"Bundle 目录不存在：{bundle}"
        )

    explicit_count = sum(
        path is not None
        for path in (
            result_summary_path,
            failure_analysis_path,
        )
    )

    if explicit_count == 1:
        raise AnalysisArtifactError(
            "result_summary_path 和 "
            "failure_analysis_path 必须同时提供"
        )

    if explicit_count == 2:
        assert result_summary_path is not None
        assert failure_analysis_path is not None

        summary = validate_artifact_path(
            path=result_summary_path,
            bundle_dir=bundle,
            description="显式结果摘要",
        )
        failure = validate_artifact_path(
            path=failure_analysis_path,
            bundle_dir=bundle,
            description="显式失败分析",
        )

        return AnalysisArtifacts(
            source="EXPLICIT",
            provenance_status="EXPLICIT_UNSEALED",
            bundle_dir=bundle,
            result_summary_path=summary,
            failure_analysis_path=failure,
        )

    completed: list[
        tuple[
            Path,
            dict[str, Any],
        ]
    ] = []

    analyses_root = (
        bundle / "analyses"
    )

    if analyses_root.is_dir():
        for manifest_path in analyses_root.rglob(
            "analyze_run_manifest.json"
        ):
            resolved_manifest = (
                manifest_path.resolve()
            )

            if not path_is_inside_bundle(
                resolved_manifest,
                bundle,
            ):
                continue

            manifest = read_manifest(
                resolved_manifest
            )

            if (
                manifest is not None
                and manifest.get("status")
                == "COMPLETED"
            ):
                validate_completed_manifest_schema(
                    manifest_path=(
                        resolved_manifest
                    ),
                    manifest=manifest,
                )
                completed.append(
                    (
                        resolved_manifest,
                        manifest,
                    )
                )

    if completed:
        completed.sort(
            key=manifest_sort_key,
            reverse=True,
        )

        manifest_path, manifest = (
            completed[0]
        )

        summary = (
            resolve_manifest_artifact_path(
                raw_path=manifest.get(
                    "result_summary_path"
                ),
                manifest_path=manifest_path,
                bundle_dir=bundle,
                description="结果摘要",
            )
        )

        failure = (
            resolve_manifest_artifact_path(
                raw_path=manifest.get(
                    "failure_analysis_path"
                ),
                manifest_path=manifest_path,
                bundle_dir=bundle,
                description="失败分析",
            )
        )

        deterministic_report = None
        raw_report_path = manifest.get(
            "deterministic_report_path"
        )
        if raw_report_path not in (None, ""):
            deterministic_report = (
                resolve_manifest_artifact_path(
                    raw_path=raw_report_path,
                    manifest_path=manifest_path,
                    bundle_dir=bundle,
                    description=(
                        "确定性分析报告"
                    ),
                )
            )

        provenance_status = (
            verify_analysis_provenance(
                manifest_path=manifest_path,
                manifest=manifest,
                bundle_dir=bundle,
                result_summary_path=summary,
                failure_analysis_path=failure,
                deterministic_report_path=(
                    deterministic_report
                ),
            )
        )

        return AnalysisArtifacts(
            source="ANALYSIS_MANIFEST",
            provenance_status=provenance_status,
            bundle_dir=bundle,
            analysis_manifest_path=(
                manifest_path
            ),
            result_summary_path=summary,
            failure_analysis_path=failure,
            deterministic_report_path=(
                deterministic_report
            ),
        )

    legacy_summary = (
        bundle
        / "agent_result_summary.json"
    )
    legacy_failure = (
        bundle
        / "agent_failure_analysis_v2.json"
    )

    if (
        legacy_summary.is_file()
        and legacy_failure.is_file()
    ):
        return AnalysisArtifacts(
            source="LEGACY_ROOT",
            provenance_status="UNSEALED_LEGACY",
            bundle_dir=bundle,
            result_summary_path=(
                legacy_summary.resolve()
            ),
            failure_analysis_path=(
                legacy_failure.resolve()
            ),
        )

    raise AnalysisArtifactNotFoundError(
        "结果解释缺少必要输入："
        "没有找到可用的 COMPLETED analysis，"
        "也没有找到完整的旧版 Bundle 根目录结果文件"
    )
