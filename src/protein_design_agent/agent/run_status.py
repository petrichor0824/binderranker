#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""只读解析 Protein Design Agent bundle 的当前状态。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


RunStage = Literal[
    "EMPTY",
    "PREPARED",
    "APPROVED",
    "RUNNING",
    "EXECUTION_FAILED",
    "EXECUTED",
    "ANALYZED",
    "EXPLAINED",
]


class RunStatusError(RuntimeError):
    """bundle 状态无法可靠解析。"""


class AnalysisAttempt(BaseModel):
    """一次 analyze-run 尝试。"""

    manifest_path: Path
    status: str
    with_model: bool | None = None
    provider_name: str | None = None

    explanation_path: Path | None = None
    explanation_status: str | None = None


class RunStatusReport(BaseModel):
    """bundle 的只读状态报告。"""

    schema_version: str = "0.1"

    bundle_dir: Path
    project_name: str
    current_stage: RunStage

    prepare_status: str | None = None
    approval_status: str | None = None
    execution_status: str | None = None
    analysis_status: str | None = None
    explanation_status: str | None = None

    analysis_scope_level: str | None = None
    approval_id: str | None = None
    approval_consumed: bool | None = None

    candidate_count: int | None = None
    formal_candidate_recommendation_allowed: bool | None = None
    thresholds_formally_interpretable: bool | None = None

    prepare_manifest: Path | None = None
    approval_manifest: Path | None = None
    execution_manifest: Path | None = None

    analysis_attempts: list[AnalysisAttempt] = []
    warnings: list[str] = []


def load_json_object(
    path: Path,
    *,
    description: str,
) -> dict[str, Any]:
    """读取 JSON 对象并拒绝损坏或非对象内容。"""
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise RunStatusError(
            f"无法读取{description}：{path}；{exc}"
        ) from exc

    if not isinstance(value, dict):
        raise RunStatusError(
            f"{description}必须是 JSON 对象：{path}"
        )

    return value


def newest_path(paths: list[Path]) -> Path | None:
    """仅用于同类展示记录选择，不参与科学结论。"""
    if not paths:
        return None

    return max(
        paths,
        key=lambda path: (
            path.stat().st_mtime_ns,
            str(path),
        ),
    )


def aggregate_status(
    statuses: list[str],
    precedence: tuple[str, ...],
) -> str | None:
    """按照明确优先级聚合多次尝试的状态。"""
    for expected in precedence:
        if expected in statuses:
            return expected

    if statuses:
        return statuses[-1]

    return None


def find_explanation_files(
    bundle_dir: Path,
) -> list[Path]:
    """找到历史和 analyze-run 生成的解释记录。"""
    patterns = (
        "agent_explanation.json",
        "explanations/*/agent_explanation.json",
        "analyses/*/explanation/agent_explanation.json",
    )

    found: set[Path] = set()

    for pattern in patterns:
        for path in bundle_dir.glob(pattern):
            if path.is_file():
                found.add(path.resolve())

    return sorted(found)


def inspect_run_status(
    bundle_dir: Path,
) -> RunStatusReport:
    """只读检查 bundle 当前达到的最高阶段。"""
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise RunStatusError(
            f"bundle 目录不存在：{bundle}"
        )

    warnings: list[str] = []

    prepare_path = (
        bundle / "agent_prepare_manifest.json"
    )
    workflow_manifest_path = (
        bundle
        / "workflow"
        / "workflow_manifest.json"
    )
    approval_path = bundle / "approval.json"

    prepare: dict[str, Any] | None = None
    workflow_manifest: (
        dict[str, Any] | None
    ) = None
    approval: dict[str, Any] | None = None

    if prepare_path.is_file():
        prepare = load_json_object(
            prepare_path,
            description="准备清单",
        )

    if workflow_manifest_path.is_file():
        workflow_manifest = load_json_object(
            workflow_manifest_path,
            description="工作流清单",
        )

    if approval_path.is_file():
        approval = load_json_object(
            approval_path,
            description="批准清单",
        )

    project_name = bundle.name

    if prepare is not None:
        project_name = str(
            prepare.get("project_name")
            or project_name
        )
    elif approval is not None:
        project_name = str(
            approval.get("project_name")
            or project_name
        )

    prepare_status = (
        str(prepare.get("status"))
        if prepare is not None
        else None
    )

    approval_status = (
        str(approval.get("status"))
        if approval is not None
        else None
    )

    approval_id = (
        str(approval.get("approval_id"))
        if approval is not None
        and approval.get("approval_id")
        else None
    )

    workflow_scope: dict[str, Any] | None = None

    if workflow_manifest is not None:
        raw_workflow_scope = (
            workflow_manifest.get(
                "analysis_scope"
            )
        )

        if isinstance(
            raw_workflow_scope,
            dict,
        ):
            workflow_scope = (
                raw_workflow_scope
            )

        elif raw_workflow_scope is not None:
            warnings.append(
                "工作流清单中的 analysis_scope "
                "不是 JSON 对象，无法用于状态汇总。"
            )

    approval_scope_level = (
        str(
            approval.get(
                "analysis_scope_level"
            )
        )
        if approval is not None
        and approval.get(
            "analysis_scope_level"
        )
        else None
    )

    workflow_scope_level = (
        str(workflow_scope.get("level"))
        if workflow_scope is not None
        and workflow_scope.get("level")
        else None
    )

    # 已批准记录是冻结后的权威来源；
    # 批准前使用准备阶段工作流清单。
    analysis_scope_level = (
        approval_scope_level
        or workflow_scope_level
    )

    if (
        approval_scope_level is not None
        and workflow_scope_level is not None
        and approval_scope_level
        != workflow_scope_level
    ):
        warnings.append(
            "批准清单与工作流清单的分析级别不一致："
            f"approval={approval_scope_level!r}，"
            f"workflow={workflow_scope_level!r}。"
            "状态报告优先采用批准清单。"
        )

    execution_records: list[
        tuple[Path, dict[str, Any]]
    ] = []

    for path in sorted(
        bundle.glob("execution_*.json")
    ):
        if not path.is_file():
            continue

        record = load_json_object(
            path,
            description="执行清单",
        )

        if (
            approval_id is not None
            and record.get("approval_id")
            != approval_id
        ):
            continue

        execution_records.append(
            (path.resolve(), record)
        )

    execution_statuses = [
        str(record.get("status"))
        for _, record in execution_records
        if record.get("status")
    ]

    execution_status = aggregate_status(
        execution_statuses,
        (
            "COMPLETED",
            "RUNNING",
            "FAILED",
        ),
    )

    selected_execution_path = newest_path(
        [
            path
            for path, record in execution_records
            if str(record.get("status"))
            == execution_status
        ]
    )

    for _, record in execution_records:
        value = record.get(
            "analysis_scope_level"
        )

        if not value:
            continue

        execution_scope_level = str(
            value
        )

        if analysis_scope_level is None:
            analysis_scope_level = (
                execution_scope_level
            )

        elif (
            execution_scope_level
            != analysis_scope_level
        ):
            warnings.append(
                "执行清单与当前权威分析级别不一致："
                f"execution={execution_scope_level!r}，"
                f"authoritative={analysis_scope_level!r}。"
            )

        break

    approval_consumed: bool | None

    if approval is None:
        approval_consumed = None
    else:
        approval_consumed = bool(
            execution_records
        )

    attempts: list[AnalysisAttempt] = []

    for manifest_path in sorted(
        bundle.glob(
            "analyses/*/analyze_run_manifest.json"
        )
    ):
        manifest = load_json_object(
            manifest_path,
            description="分析清单",
        )

        explanation_path = (
            manifest_path.parent
            / "explanation"
            / "agent_explanation.json"
        )

        explanation_status: str | None = None

        if explanation_path.is_file():
            explanation = load_json_object(
                explanation_path,
                description="模型解释记录",
            )

            if explanation.get("status"):
                explanation_status = str(
                    explanation["status"]
                )

        attempts.append(
            AnalysisAttempt(
                manifest_path=(
                    manifest_path.resolve()
                ),
                status=str(
                    manifest.get("status")
                    or "UNKNOWN"
                ),
                with_model=(
                    bool(manifest["with_model"])
                    if manifest.get("with_model")
                    is not None
                    else None
                ),
                provider_name=(
                    str(manifest["provider_name"])
                    if manifest.get(
                        "provider_name"
                    )
                    else None
                ),
                explanation_path=(
                    explanation_path.resolve()
                    if explanation_path.is_file()
                    else None
                ),
                explanation_status=(
                    explanation_status
                ),
            )
        )

    analysis_status = aggregate_status(
        [
            attempt.status
            for attempt in attempts
        ],
        (
            "COMPLETED",
            "RUNNING",
            "FAILED",
        ),
    )

    explanation_files = (
        find_explanation_files(bundle)
    )

    explanation_statuses: list[str] = []

    for path in explanation_files:
        record = load_json_object(
            path,
            description="模型解释记录",
        )

        if record.get("status"):
            explanation_statuses.append(
                str(record["status"])
            )

    explanation_status = aggregate_status(
        explanation_statuses,
        ("EXPLAINED", "FAILED"),
    )

    summary_paths = [
        path.resolve()
        for pattern in (
            "agent_result_summary.json",
            "analyses/*/agent_result_summary.json",
        )
        for path in bundle.glob(pattern)
        if path.is_file()
    ]

    candidate_count: int | None = None
    recommendation_allowed: bool | None = None
    thresholds_interpretable: bool | None = None

    summary_values: list[dict[str, Any]] = []

    for path in summary_paths:
        summary_values.append(
            load_json_object(
                path,
                description="结果摘要",
            )
        )

    for summary in reversed(summary_values):
        if (
            candidate_count is None
            and isinstance(
                summary.get("candidate_count"),
                int,
            )
        ):
            candidate_count = summary[
                "candidate_count"
            ]

        if (
            recommendation_allowed is None
            and isinstance(
                summary.get(
                    "formal_candidate_"
                    "recommendation_allowed"
                ),
                bool,
            )
        ):
            recommendation_allowed = summary[
                "formal_candidate_"
                "recommendation_allowed"
            ]

        if (
            thresholds_interpretable is None
            and isinstance(
                summary.get(
                    "thresholds_formally_"
                    "interpretable"
                ),
                bool,
            )
        ):
            thresholds_interpretable = summary[
                "thresholds_formally_"
                "interpretable"
            ]

    if (
        candidate_count is None
        and workflow_scope is not None
        and isinstance(
            workflow_scope.get("pdb_count"),
            int,
        )
    ):
        candidate_count = int(
            workflow_scope["pdb_count"]
        )

    # 在正式结果政策尚未生成前，只对明确的小样本
    # 安全限制给出保守的 False；不为其他级别猜测。
    if analysis_scope_level == "SMOKE_TEST_ONLY":
        if recommendation_allowed is None:
            recommendation_allowed = False

        if thresholds_interpretable is None:
            thresholds_interpretable = False

    root_summary = (
        bundle / "agent_result_summary.json"
    )

    parsed_result_exists = False

    if root_summary.is_file():
        root_record = load_json_object(
            root_summary,
            description="根结果摘要",
        )
        parsed_result_exists = (
            root_record.get("status")
            == "PARSED"
        )

    if explanation_status == "EXPLAINED":
        current_stage: RunStage = "EXPLAINED"
    elif (
        analysis_status == "COMPLETED"
        or parsed_result_exists
    ):
        current_stage = "ANALYZED"
    elif execution_status == "COMPLETED":
        current_stage = "EXECUTED"
    elif execution_status == "RUNNING":
        current_stage = "RUNNING"
    elif execution_status == "FAILED":
        current_stage = "EXECUTION_FAILED"
    elif approval_status == "APPROVED":
        current_stage = "APPROVED"
    elif prepare_status is not None:
        current_stage = "PREPARED"
    else:
        current_stage = "EMPTY"

    return RunStatusReport(
        bundle_dir=bundle,
        project_name=project_name,
        current_stage=current_stage,
        prepare_status=prepare_status,
        approval_status=approval_status,
        execution_status=execution_status,
        analysis_status=analysis_status,
        explanation_status=explanation_status,
        analysis_scope_level=analysis_scope_level,
        approval_id=approval_id,
        approval_consumed=approval_consumed,
        candidate_count=candidate_count,
        formal_candidate_recommendation_allowed=(
            recommendation_allowed
        ),
        thresholds_formally_interpretable=(
            thresholds_interpretable
        ),
        prepare_manifest=(
            prepare_path.resolve()
            if prepare_path.is_file()
            else None
        ),
        approval_manifest=(
            approval_path.resolve()
            if approval_path.is_file()
            else None
        ),
        execution_manifest=(
            selected_execution_path
        ),
        analysis_attempts=attempts,
        warnings=warnings,
    )
