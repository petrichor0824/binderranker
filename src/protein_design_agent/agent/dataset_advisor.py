#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
根据 PDB 文件的只读检查结果，为规划对话生成可审计建议。

本模块：
- 只读取 PDB；
- 不调用大模型；
- 不修改规划参数；
- 不批准或执行任务；
- 只生成事实、条件建议和待确认问题。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from protein_design_agent.path_semantics import (
    resolve_local_path,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    build_dataset_report,
    collect_pdb_files,
    inspect_one_pdb,
)


AdviceStatus = Literal[
    "NEEDS_USER_CONFIRMATION",
    "INCONCLUSIVE",
]


class DatasetAdvisorError(RuntimeError):
    """PDB 数据集只读分析失败。"""


class DatasetFileEvidence(BaseModel):
    """一个 PDB 文件的可审计检查证据。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    file_name: str
    file_path: Path
    sha256: str

    valid: bool
    chain_count: int
    chain_ids: list[str]
    total_residue_count: int

    chain_signature: str | None = None

    warnings: list[str] = Field(
        default_factory=list
    )
    errors: list[str] = Field(
        default_factory=list
    )


class ConditionalDatasetSuggestion(BaseModel):
    """
    只有条件得到用户确认后才能采用的参数建议。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    condition: str
    candidate_patch: dict[str, str]

    evidence_summary: list[str] = Field(
        default_factory=list
    )


class DatasetPlanningAdvice(BaseModel):
    """用于规划对话的 PDB 文件证据报告。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    schema_version: str = "0.1"
    created_at_utc: str

    status: AdviceStatus

    input_directory: Path
    recursive: bool

    processed_file_count: int
    valid_file_count: int
    invalid_file_count: int

    all_valid_files_are_single_chain: bool
    common_single_chain_id: str | None = None

    chain_count_patterns: dict[str, int] = Field(
        default_factory=dict
    )
    chain_signature_counts: dict[str, int] = Field(
        default_factory=dict
    )
    total_residue_count_patterns: dict[str, int] = Field(
        default_factory=dict
    )

    dataset_warnings: list[str] = Field(
        default_factory=list
    )

    file_evidence: list[DatasetFileEvidence] = Field(
        default_factory=list
    )

    conditional_suggestion: (
        ConditionalDatasetSuggestion | None
    ) = None

    unresolved_questions: list[str] = Field(
        default_factory=list
    )

    cautions: list[str] = Field(
        default_factory=list
    )


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            block = handle.read(
                1024 * 1024
            )

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def normalize_count_mapping(
    value: Any,
) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    return {
        str(key): int(count)
        for key, count in value.items()
    }


def derive_common_single_chain_id(
    file_reports: list[dict[str, Any]],
) -> str | None:
    """
    仅当所有有效文件都恰好只有一条链，
    且链名完全一致时，返回共同链名。
    """
    valid_reports = [
        report
        for report in file_reports
        if report.get("valid") is True
    ]

    if not valid_reports:
        return None

    chain_ids: list[str] = []

    for report in valid_reports:
        if report.get("chain_count") != 1:
            return None

        ids = report.get("chain_ids")

        if (
            not isinstance(ids, list)
            or len(ids) != 1
            or not isinstance(ids[0], str)
        ):
            return None

        chain_ids.append(ids[0])

    unique = set(chain_ids)

    if len(unique) != 1:
        return None

    return chain_ids[0]


def build_planning_advice(
    *,
    input_dir: Path,
    recursive: bool,
    pdb_files: list[Path],
    file_reports: list[dict[str, Any]],
    dataset_report: dict[str, Any],
) -> DatasetPlanningAdvice:
    common_chain = (
        derive_common_single_chain_id(
            file_reports
        )
    )

    evidence: list[DatasetFileEvidence] = []

    for pdb_path, report in zip(
        pdb_files,
        file_reports,
        strict=True,
    ):
        evidence.append(
            DatasetFileEvidence(
                file_name=str(
                    report.get(
                        "file_name",
                        pdb_path.name,
                    )
                ),
                file_path=pdb_path.resolve(),
                sha256=sha256_file(
                    pdb_path
                ),
                valid=bool(
                    report.get(
                        "valid",
                        False,
                    )
                ),
                chain_count=int(
                    report.get(
                        "chain_count",
                        0,
                    )
                ),
                chain_ids=[
                    str(value)
                    for value in report.get(
                        "chain_ids",
                        [],
                    )
                ],
                total_residue_count=int(
                    report.get(
                        "total_residue_count",
                        0,
                    )
                ),
                chain_signature=(
                    str(
                        report[
                            "chain_signature"
                        ]
                    )
                    if report.get(
                        "chain_signature"
                    )
                    is not None
                    else None
                ),
                warnings=[
                    str(value)
                    for value in report.get(
                        "warnings",
                        [],
                    )
                ],
                errors=[
                    str(value)
                    for value in report.get(
                        "errors",
                        [],
                    )
                ],
            )
        )

    valid_count = int(
        dataset_report.get(
            "valid_file_count",
            0,
        )
    )

    invalid_count = int(
        dataset_report.get(
            "invalid_file_count",
            0,
        )
    )

    all_single = bool(
        dataset_report.get(
            "all_valid_files_are_single_chain",
            False,
        )
    )

    warnings = [
        str(value)
        for value in dataset_report.get(
            "warnings",
            [],
        )
    ]

    conditional_suggestion = None
    unresolved_questions: list[str] = []
    cautions: list[str] = []

    if (
        valid_count > 0
        and invalid_count == 0
        and all_single
        and common_chain is not None
    ):
        conditional_suggestion = (
            ConditionalDatasetSuggestion(
                condition=(
                    "用户确认这些单链 PDB 中"
                    "同时包含 target 和 binder"
                ),
                candidate_patch={
                    "input_layout": (
                        "concatenated_single_chain"
                    ),
                    "source_chain": (
                        common_chain
                    ),
                },
                evidence_summary=[
                    (
                        f"{valid_count}/{valid_count} "
                        "个有效 PDB 都只有一条链"
                    ),
                    (
                        "所有有效文件的唯一链名均为 "
                        f"{common_chain}"
                    ),
                ],
            )
        )

        unresolved_questions.append(
            "这些单链 PDB 是否同时包含 "
            "target 和 binder？"
        )

        cautions.append(
            "单链结构本身不能证明该链同时包含 "
            "target 和 binder，因此不能自动确定输入布局。"
        )

        status: AdviceStatus = (
            "NEEDS_USER_CONFIRMATION"
        )

    else:
        unresolved_questions.append(
            "文件之间的链结构不能支持统一建议，"
            "需要用户进一步说明数据布局。"
        )

        cautions.append(
            "没有足够一致的文件证据来建议 "
            "input_layout 或 source_chain。"
        )

        status = "INCONCLUSIVE"

    if (
        "inconsistent_chain_signatures"
        in warnings
    ):
        cautions.append(
            "不同文件的链签名不完全一致，"
            "通常表示残基数量或链组成存在差异。"
        )

    if (
        "inconsistent_total_residue_counts"
        in warnings
    ):
        cautions.append(
            "不同文件的总残基数量不一致；"
            "这不妨碍识别共同链名，"
            "但不能据此推导 target 边界。"
        )

    if invalid_count > 0:
        cautions.append(
            f"存在 {invalid_count} 个无效 PDB，"
            "在解决这些文件之前不能采用统一建议。"
        )

    return DatasetPlanningAdvice(
        created_at_utc=utc_now(),
        status=status,
        input_directory=input_dir.resolve(),
        recursive=recursive,
        processed_file_count=len(
            pdb_files
        ),
        valid_file_count=valid_count,
        invalid_file_count=invalid_count,
        all_valid_files_are_single_chain=(
            all_single
        ),
        common_single_chain_id=(
            common_chain
        ),
        chain_count_patterns=(
            normalize_count_mapping(
                dataset_report.get(
                    "chain_count_patterns"
                )
            )
        ),
        chain_signature_counts=(
            normalize_count_mapping(
                dataset_report.get(
                    "chain_signature_counts"
                )
            )
        ),
        total_residue_count_patterns=(
            normalize_count_mapping(
                dataset_report.get(
                    "total_residue_count_patterns"
                )
            )
        ),
        dataset_warnings=warnings,
        file_evidence=evidence,
        conditional_suggestion=(
            conditional_suggestion
        ),
        unresolved_questions=(
            unresolved_questions
        ),
        cautions=cautions,
    )


def inspect_dataset_for_planning(
    *,
    input_dir: Path,
    recursive: bool = False,
    max_files: int | None = None,
    detail_limit: int = 20,
) -> DatasetPlanningAdvice:
    """
    只读检查一个 PDB 目录，并生成条件建议。
    """
    try:
        resolved = resolve_local_path(
            input_dir,
            field_name="input_dir",
        )
    except ValueError as exc:
        raise DatasetAdvisorError(
            str(exc)
        ) from exc

    if not resolved.is_dir():
        raise DatasetAdvisorError(
            f"PDB 输入目录不存在或不是目录：{resolved}"
        )

    try:
        pdb_files = collect_pdb_files(
            input_dir=resolved,
            recursive=recursive,
            max_files=max_files,
        )

        file_reports = [
            inspect_one_pdb(path)
            for path in pdb_files
        ]

        dataset_report = build_dataset_report(
            input_dir=resolved,
            pdb_files=pdb_files,
            file_reports=file_reports,
            recursive=recursive,
            detail_limit=detail_limit,
        )

        return build_planning_advice(
            input_dir=resolved,
            recursive=recursive,
            pdb_files=pdb_files,
            file_reports=file_reports,
            dataset_report=dataset_report,
        )

    except DatasetAdvisorError:
        raise

    except Exception as exc:
        raise DatasetAdvisorError(
            f"PDB 数据集只读检查失败：{exc}"
        ) from exc


def write_json_atomically(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )

    try:
        with temporary.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True
        )


def save_dataset_advice(
    *,
    bundle_dir: Path,
    advice: DatasetPlanningAdvice,
) -> Path:
    """
    将只读检查证据保存到 Bundle。

    不修改 planning_session.json。
    """
    output_path = (
        bundle_dir.resolve()
        / "chat"
        / "dataset_advice.json"
    )

    write_json_atomically(
        output_path,
        advice.model_dump(
            mode="json"
        ),
    )

    return output_path

def load_dataset_advice(
    path: Path,
) -> DatasetPlanningAdvice:
    """读取并严格验证文件建议报告。"""
    resolved = path.resolve()

    if not resolved.is_file():
        raise DatasetAdvisorError(
            f"数据集建议报告不存在：{resolved}"
        )

    try:
        raw = json.loads(
            resolved.read_text(
                encoding="utf-8"
            )
        )

        return DatasetPlanningAdvice.model_validate(
            raw
        )

    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise DatasetAdvisorError(
            "数据集建议报告无法通过验证："
            f"{resolved}；{exc}"
        ) from exc


def verify_dataset_advice_fresh(
    advice: DatasetPlanningAdvice,
) -> None:
    """
    确认建议生成后，输入文件集合和文件内容均未改变。
    """
    try:
        current_files = collect_pdb_files(
            input_dir=(
                advice.input_directory
            ),
            recursive=advice.recursive,
            max_files=None,
        )
    except Exception as exc:
        raise DatasetAdvisorError(
            f"无法重新枚举 PDB 文件：{exc}"
        ) from exc

    expected_paths = {
        item.file_path.resolve()
        for item in advice.file_evidence
    }

    current_paths = {
        path.resolve()
        for path in current_files
    }

    if current_paths != expected_paths:
        added = sorted(
            str(path)
            for path in (
                current_paths - expected_paths
            )
        )

        removed = sorted(
            str(path)
            for path in (
                expected_paths - current_paths
            )
        )

        raise DatasetAdvisorError(
            "PDB 文件集合在建议生成后发生变化；"
            f"新增={added}，移除={removed}。"
            "请重新执行只读检查。"
        )

    expected_hashes = {
        item.file_path.resolve(): item.sha256
        for item in advice.file_evidence
    }

    changed: list[str] = []

    for path in sorted(
        current_paths,
        key=str,
    ):
        if (
            sha256_file(path)
            != expected_hashes[path]
        ):
            changed.append(
                str(path)
            )

    if changed:
        raise DatasetAdvisorError(
            "以下 PDB 文件在建议生成后内容发生变化："
            f"{changed}。请重新执行只读检查。"
        )

