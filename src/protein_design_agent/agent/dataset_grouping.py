#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""基于真实目录证据生成并校验 PDB 数据集分组建议。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from protein_design_agent.agent.dataset_discovery import (
    DatasetDiscoveryReport,
)
from protein_design_agent.agent.workspace_tasks import (
    TaskPathError,
    validate_task_name,
)


MAX_PROPOSED_GROUPS = 100


class DatasetGroupingError(RuntimeError):
    """模型分组建议无法通过结构或证据校验。"""


class DatasetGroupProposal(BaseModel):
    """模型提出的单个数据集分组。"""

    model_config = ConfigDict(extra="forbid")

    task_name: str
    source_relative_path: str
    expected_pdb_count: int = Field(ge=1)
    recursive: bool = False
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


class DatasetGroupingProposal(BaseModel):
    """模型提出的任意数量分组方案。"""

    model_config = ConfigDict(extra="forbid")

    groups: list[DatasetGroupProposal] = Field(
        min_length=1,
        max_length=MAX_PROPOSED_GROUPS,
    )
    summary: str = Field(
        min_length=1,
        max_length=1000,
    )
    questions: list[str] = Field(
        default_factory=list,
        max_length=10,
    )
    requires_user_review: bool = True


@dataclass(frozen=True)
class ValidatedDatasetGroup:
    """通过真实目录证据校验的单组建议。"""

    task_name: str
    input_directory: Path
    source_relative_path: str
    pdb_count: int
    recursive: bool
    reason: str


@dataclass(frozen=True)
class ValidatedDatasetGrouping:
    """通过确定性校验的完整分组方案。"""

    groups: tuple[ValidatedDatasetGroup, ...]
    omitted_relative_paths: tuple[str, ...]
    warnings: tuple[str, ...]
    questions: tuple[str, ...]
    summary: str
    requires_user_review: bool


def build_candidate_mapping(
    report: DatasetDiscoveryReport,
) -> dict[str, tuple[Path, int]]:
    """
    建立模型可选择路径与真实目录的映射。

    "." 表示扫描根目录中的顶层 PDB。
    """
    candidates: dict[str, tuple[Path, int]] = {}

    if report.root_level_pdb_count > 0:
        candidates["."] = (
            report.root_directory,
            report.root_level_pdb_count,
        )

    for group in report.groups:
        candidates[group.relative_path] = (
            group.directory,
            group.pdb_count,
        )

    return candidates


def build_grouping_evidence(
    report: DatasetDiscoveryReport,
) -> dict[str, Any]:
    """构造发送给模型的最小只读目录证据。"""
    candidates = build_candidate_mapping(report)

    return {
        "layout": report.layout,
        "candidate_groups": [
            {
                "source_relative_path": relative_path,
                "pdb_count": pdb_count,
            }
            for relative_path, (
                _directory,
                pdb_count,
            ) in candidates.items()
        ],
        "warnings": list(report.warnings),
        "rules": {
            "root_directory_token": ".",
            "recursive_supported": False,
            "maximum_group_count": (
                MAX_PROPOSED_GROUPS
            ),
        },
    }


def validate_grouping_proposal(
    *,
    proposal: DatasetGroupingProposal,
    report: DatasetDiscoveryReport,
) -> ValidatedDatasetGrouping:
    """用真实扫描结果校验模型建议。"""
    candidates = build_candidate_mapping(report)

    if not candidates:
        raise DatasetGroupingError(
            "扫描报告中没有可供分组的 PDB 数据集"
        )

    used_paths: set[str] = set()
    used_task_names: set[str] = set()
    validated_groups: list[
        ValidatedDatasetGroup
    ] = []

    for group in proposal.groups:
        relative_path = (
            group.source_relative_path.strip()
        )

        if relative_path not in candidates:
            raise DatasetGroupingError(
                "模型建议了扫描报告中不存在的目录："
                f"{relative_path}"
            )

        if relative_path in used_paths:
            raise DatasetGroupingError(
                "同一个数据目录被重复分组："
                f"{relative_path}"
            )

        if group.recursive:
            raise DatasetGroupingError(
                "当前 MVP 只允许顶层 PDB，"
                "不能采用递归分组建议"
            )

        try:
            task_name = validate_task_name(
                group.task_name
            )
        except TaskPathError as exc:
            raise DatasetGroupingError(
                "模型生成了无效任务名："
                f"{group.task_name}；{exc}"
            ) from exc

        normalized_task_name = (
            task_name.casefold()
        )

        if normalized_task_name in used_task_names:
            raise DatasetGroupingError(
                "模型生成了重复任务名："
                f"{task_name}"
            )

        directory, actual_count = candidates[
            relative_path
        ]

        if (
            group.expected_pdb_count
            != actual_count
        ):
            raise DatasetGroupingError(
                "模型记录的 PDB 数量与真实扫描结果"
                "不一致："
                f"{relative_path}；"
                f"模型={group.expected_pdb_count}；"
                f"实际={actual_count}"
            )

        used_paths.add(relative_path)
        used_task_names.add(
            normalized_task_name
        )

        validated_groups.append(
            ValidatedDatasetGroup(
                task_name=task_name,
                input_directory=directory,
                source_relative_path=(
                    relative_path
                ),
                pdb_count=actual_count,
                recursive=False,
                reason=group.reason.strip(),
            )
        )

    omitted = tuple(
        relative_path
        for relative_path in candidates
        if relative_path not in used_paths
    )

    warnings = list(report.warnings)

    if omitted:
        warnings.append(
            "以下已发现数据集未被模型纳入方案："
            + ", ".join(omitted)
        )

    requires_review = (
        proposal.requires_user_review
        or report.layout == "MIXED_LAYOUT"
        or bool(omitted)
        or bool(proposal.questions)
    )

    return ValidatedDatasetGrouping(
        groups=tuple(validated_groups),
        omitted_relative_paths=omitted,
        warnings=tuple(warnings),
        questions=tuple(proposal.questions),
        summary=proposal.summary.strip(),
        requires_user_review=requires_review,
    )


def propose_dataset_grouping(
    *,
    provider: Any,
    user_description: str,
    report: DatasetDiscoveryReport,
) -> ValidatedDatasetGrouping:
    """
    让模型结合用户描述和真实扫描证据提出分组。

    本函数不创建目录、不写 Bundle、不批准、不执行。
    """
    evidence = build_grouping_evidence(report)

    messages = [
        {
            "role": "system",
            "content": (
                "你是 Protein Design Agent 的数据分组助手。"
                "请根据用户描述和确定性扫描证据，"
                "提出任意数量的独立 PDB 排序任务。"
                "只能使用 candidate_groups 中真实存在的"
                " source_relative_path，不能编造目录。"
                "当前 recursive 必须为 false。"
                "每个目录最多出现一次，任务名必须唯一。"
                "expected_pdb_count 必须照抄证据中的数量。"
                "你只提出建议，不能声称已经创建、批准或执行任务。"
                "返回与要求字段完全一致的 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "用户对目录布局和分组需求的描述：\n"
                f"{user_description.strip()}\n\n"
                "确定性扫描证据：\n"
                + json.dumps(
                    evidence,
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        },
    ]

    try:
        payload = provider.generate_json(
            messages
        )
        proposal = (
            DatasetGroupingProposal
            .model_validate(payload)
        )
    except ValidationError as exc:
        raise DatasetGroupingError(
            "模型返回的分组方案结构无效："
            f"{exc}"
        ) from exc
    except Exception as exc:
        raise DatasetGroupingError(
            f"模型分组请求失败：{exc}"
        ) from exc

    return validate_grouping_proposal(
        proposal=proposal,
        report=report,
    )



def format_dataset_grouping_preview(
    *,
    grouping: ValidatedDatasetGrouping,
    report: DatasetDiscoveryReport,
) -> str:
    """把已校验的分组建议格式化为简洁终端文本。"""
    lines = [
        "检测到多个可能独立排序的 PDB 数据集。",
        f"目录布局：{report.layout}",
        f"建议任务数：{len(grouping.groups)}",
        "",
        "任务名 | 来源目录 | 顶层 PDB 数量",
        "-" * 56,
    ]

    for group in grouping.groups:
        lines.append(
            f"{group.task_name} | "
            f"{group.source_relative_path} | "
            f"{group.pdb_count}"
        )

    if grouping.omitted_relative_paths:
        lines.extend(
            [
                "",
                "尚未纳入建议的目录："
                + ", ".join(
                    grouping.omitted_relative_paths
                ),
            ]
        )

    if grouping.warnings:
        lines.append("")
        lines.append("需要注意：")
        lines.extend(
            f"- {warning}"
            for warning in grouping.warnings
        )

    if grouping.questions:
        lines.append("")
        lines.append("仍需用户确认：")
        lines.extend(
            f"- {question}"
            for question in grouping.questions
        )

    lines.extend(
        [
            "",
            "当前只生成了只读分组建议；"
            "尚未创建任务、批准或执行。",
        ]
    )

    return "\n".join(lines)
