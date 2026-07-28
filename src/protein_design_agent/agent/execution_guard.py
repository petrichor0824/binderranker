#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
本地 BinderRanker 执行前安全检查。

本模块只验证，不执行 BinderRanker。

它会确认：
1. approval.json 本身没有被篡改；
2. 批准范围确实是执行一次 BinderRanker；
3. 批准时冻结的关键文件全部未改变；
4. 标准化 PDB 数据集全部未改变；
5. Ranker 文件及 SHA256 未改变；
6. Ranker 计划和批准记录相互一致；
7. 执行命令只指向批准过的输入、Ranker 和输出；
8. 当前任务尚未执行；
9. 预期结果文件尚不存在。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from protein_design_agent.agent.approval import (
    ApprovalRecord,
    fingerprint_file,
    load_json_object,
    resolve_recorded_path,
    snapshot_pdb_dataset,
)
from protein_design_agent.tools.run_binderranker import (
    expected_output_files,
)


VerificationStatus = Literal[
    "VERIFIED_FOR_LOCAL_EXECUTION"
]


class ExecutionGuardError(RuntimeError):
    """批准记录或当前任务状态不适合执行。"""


class VerifiedLocalExecution(BaseModel):
    """通过全部检查后的本地执行信息。"""

    schema_version: str = "0.1"
    status: VerificationStatus = (
        "VERIFIED_FOR_LOCAL_EXECUTION"
    )

    approval_id: str
    approval_path: Path

    project_name: str
    analysis_scope_level: str

    prepare_manifest: Path
    ranker_plan: Path
    ranker_path: Path
    normalized_input_directory: Path

    command: list[str]
    output_prefix: Path
    expected_outputs: list[Path]

    execution_manifest: Path

    dataset_combined_sha256: str
    ranker_sha256: str

    binderranker_executed: bool = False
    remote_backend_used: bool = False


def load_approval_record(
    path: Path,
) -> ApprovalRecord:
    """读取并严格验证批准记录。"""
    try:
        text = path.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise ExecutionGuardError(
            f"无法读取批准记录：{exc}"
        ) from exc

    try:
        return ApprovalRecord.model_validate_json(
            text
        )
    except ValidationError as exc:
        raise ExecutionGuardError(
            "批准记录无法通过结构验证：\n"
            f"{exc}"
        ) from exc


def calculate_approval_digest(
    record: ApprovalRecord,
) -> str:
    """
    重新计算批准摘要。

    approval_id 和 approval_digest 本身不参与摘要，
    其他字段必须与批准时完全一致。
    """
    payload = record.model_dump(
        mode="json",
        exclude={
            "approval_id",
            "approval_digest",
        },
    )

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def verify_approval_digest(
    record: ApprovalRecord,
) -> None:
    """确认 approval.json 自身没有被修改。"""
    actual = calculate_approval_digest(
        record
    )

    if actual != record.approval_digest:
        raise ExecutionGuardError(
            "批准记录摘要不匹配，"
            "approval.json 可能已被修改：\n"
            f"记录摘要：{record.approval_digest}\n"
            f"当前摘要：{actual}"
        )

    expected_id = (
        "apr_" + actual[:16]
    )

    if record.approval_id != expected_id:
        raise ExecutionGuardError(
            "批准 ID 与批准摘要不匹配：\n"
            f"记录 ID：{record.approval_id}\n"
            f"预期 ID：{expected_id}"
        )


def verify_critical_files(
    record: ApprovalRecord,
) -> None:
    """重新验证全部关键文件的大小和 SHA256。"""
    for approved in record.critical_files:
        try:
            current = fingerprint_file(
                approved.path
            )
        except ValueError as exc:
            raise ExecutionGuardError(
                str(exc)
            ) from exc

        if (
            current.sha256
            != approved.sha256
        ):
            raise ExecutionGuardError(
                "批准后的关键文件发生变化：\n"
                f"文件：{approved.path}\n"
                f"批准时：{approved.sha256}\n"
                f"当前：{current.sha256}"
            )

        if (
            current.size_bytes
            != approved.size_bytes
        ):
            raise ExecutionGuardError(
                "批准后的关键文件大小发生变化：\n"
                f"文件：{approved.path}\n"
                f"批准时：{approved.size_bytes}\n"
                f"当前：{current.size_bytes}"
            )


def verify_normalized_dataset(
    record: ApprovalRecord,
) -> None:
    """重新验证标准化 PDB 数据集。"""
    try:
        current = snapshot_pdb_dataset(
            record.normalized_dataset.root
        )
    except ValueError as exc:
        raise ExecutionGuardError(
            str(exc)
        ) from exc

    approved = record.normalized_dataset

    if (
        current.root.resolve()
        != approved.root.resolve()
    ):
        raise ExecutionGuardError(
            "标准化数据集根目录发生变化"
        )

    if current.pdb_count != approved.pdb_count:
        raise ExecutionGuardError(
            "标准化 PDB 数量发生变化：\n"
            f"批准时：{approved.pdb_count}\n"
            f"当前：{current.pdb_count}"
        )

    if (
        current.combined_sha256
        != approved.combined_sha256
    ):
        raise ExecutionGuardError(
            "标准化 PDB 数据集发生变化：\n"
            f"批准时：{approved.combined_sha256}\n"
            f"当前：{current.combined_sha256}"
        )

    approved_files = [
        item.model_dump(mode="json")
        for item in approved.files
    ]
    current_files = [
        item.model_dump(mode="json")
        for item in current.files
    ]

    if current_files != approved_files:
        raise ExecutionGuardError(
            "标准化 PDB 逐文件指纹发生变化"
        )


def command_argument(
    command: list[str],
    flag: str,
) -> str:
    """从结构化命令中读取一个唯一参数。"""
    positions = [
        index
        for index, value in enumerate(
            command
        )
        if value == flag
    ]

    if len(positions) != 1:
        raise ExecutionGuardError(
            f"Ranker 命令中的 {flag} "
            "必须且只能出现一次"
        )

    position = positions[0]

    if position + 1 >= len(command):
        raise ExecutionGuardError(
            f"Ranker 命令中的 {flag} 缺少参数值"
        )

    return command[position + 1]


def default_execution_manifest_path(
    approval_path: Path,
    approval_id: str,
) -> Path:
    """生成该批准记录对应的一次性执行结果路径。"""
    return (
        approval_path.resolve().parent
        / f"execution_{approval_id}.json"
    )


def verify_ranker_plan(
    *,
    record: ApprovalRecord,
    prepare_manifest_path: Path,
) -> tuple[
    Path,
    dict[str, Any],
    list[str],
    Path,
    list[Path],
]:
    """
    验证 Ranker 计划，并返回执行所需信息。

    返回：
    - ranker_plan_path
    - ranker_plan 数据
    - command
    - output_prefix
    - expected_outputs
    """
    prepare_manifest = load_json_object(
        prepare_manifest_path,
        description="Agent Prepare Manifest",
    )

    ranker_plan_path = resolve_recorded_path(
        prepare_manifest.get("ranker_plan"),
        base_directory=(
            prepare_manifest_path.parent
        ),
        field_name="ranker_plan",
    )

    approved_critical_paths = {
        item.path.resolve()
        for item in record.critical_files
    }

    if (
        ranker_plan_path.resolve()
        not in approved_critical_paths
    ):
        raise ExecutionGuardError(
            "当前 Ranker 计划不在批准的关键文件中"
        )

    ranker_plan = load_json_object(
        ranker_plan_path,
        description="Ranker Execution Plan",
    )

    if (
        ranker_plan.get("execute_requested")
        is not False
    ):
        raise ExecutionGuardError(
            "批准前的 Ranker 计划必须明确处于 "
            "execute_requested=False"
        )

    ranker_path = resolve_recorded_path(
        ranker_plan.get("ranker_path"),
        base_directory=ranker_plan_path.parent,
        field_name="ranker_path",
    )

    if (
        ranker_path.resolve()
        != record.ranker_path.resolve()
    ):
        raise ExecutionGuardError(
            "Ranker 计划中的脚本路径与批准记录不一致"
        )

    recorded_sha = ranker_plan.get(
        "ranker_sha256"
    )

    if recorded_sha != record.ranker_sha256:
        raise ExecutionGuardError(
            "Ranker 计划中的 SHA256 "
            "与批准记录不一致"
        )

    try:
        current_ranker = fingerprint_file(
            ranker_path
        )
    except ValueError as exc:
        raise ExecutionGuardError(
            str(exc)
        ) from exc

    if (
        current_ranker.sha256
        != record.ranker_sha256
    ):
        raise ExecutionGuardError(
            "冻结 Ranker 文件在批准后发生变化"
        )

    input_directory = resolve_recorded_path(
        ranker_plan.get("input_directory"),
        base_directory=ranker_plan_path.parent,
        field_name="input_directory",
    )

    if (
        input_directory.resolve()
        != record.normalized_dataset.root.resolve()
    ):
        raise ExecutionGuardError(
            "Ranker 输入目录与批准的数据集不一致"
        )

    command = ranker_plan.get("command")

    if (
        not isinstance(command, list)
        or not command
    ):
        raise ExecutionGuardError(
            "Ranker command 必须是非空列表"
        )

    if not all(
        isinstance(item, str)
        for item in command
    ):
        raise ExecutionGuardError(
            "Ranker command 的每个元素"
            "都必须是字符串"
        )

    # 结构化 subprocess 参数允许空字符串。
    # 例如没有 undesired region 时：
    # ["--undesired_regions", ""]
    #
    # 空字符串作为参数值是合法的；
    # 但参数中不能包含 NUL 字符。
    if any(
        "\x00" in item
        for item in command
    ):
        raise ExecutionGuardError(
            "Ranker command 中包含非法 NUL 字符"
        )

    if len(command) < 2:
        raise ExecutionGuardError(
            "Ranker command 长度异常"
        )

    command_python = Path(
        command[0]
    ).resolve()

    current_python = Path(
        sys.executable
    ).resolve()

    if command_python != current_python:
        raise ExecutionGuardError(
            "Ranker 计划使用的 Python 环境"
            "与当前执行环境不一致：\n"
            f"计划：{command_python}\n"
            f"当前：{current_python}"
        )

    command_ranker = Path(
        command[1]
    ).resolve()

    if command_ranker != ranker_path:
        raise ExecutionGuardError(
            "Ranker 命令中的脚本路径与批准记录不一致"
        )

    command_input = Path(
        command_argument(
            command,
            "--input_dir",
        )
    ).resolve()

    if command_input != input_directory:
        raise ExecutionGuardError(
            "Ranker 命令中的输入目录与批准记录不一致"
        )

    output_prefix_value = (
        ranker_plan.get("output_prefix")
    )

    if (
        not isinstance(
            output_prefix_value,
            str,
        )
        or not output_prefix_value.strip()
    ):
        raise ExecutionGuardError(
            "Ranker 计划缺少有效 output_prefix"
        )

    output_prefix = Path(
        output_prefix_value
    ).resolve()

    command_output = Path(
        command_argument(
            command,
            "--output_prefix",
        )
    ).resolve()

    if command_output != output_prefix:
        raise ExecutionGuardError(
            "Ranker 命令中的输出前缀"
            "与计划记录不一致"
        )

    bundle_directory = (
        prepare_manifest_path.parent.resolve()
    )

    if not output_prefix.is_relative_to(
        bundle_directory
    ):
        raise ExecutionGuardError(
            "Ranker 输出目录位于任务档案目录之外，"
            "拒绝执行"
        )

    outputs = expected_output_files(
        output_prefix
    )

    existing_outputs = [
        path
        for path in outputs
        if path.exists()
    ]

    if existing_outputs:
        formatted = "\n".join(
            f"- {path}"
            for path in existing_outputs
        )

        raise ExecutionGuardError(
            "检测到已有 Ranker 结果，"
            "一次性执行不能覆盖：\n"
            f"{formatted}"
        )

    plan_scope = ranker_plan.get(
        "analysis_scope",
        {},
    )

    if isinstance(plan_scope, dict):
        plan_level = str(
            plan_scope.get(
                "level",
                "UNKNOWN",
            )
        )

        if (
            plan_level
            != record.analysis_scope_level
        ):
            raise ExecutionGuardError(
                "Ranker 计划中的分析级别"
                "与批准记录不一致"
            )

    return (
        ranker_plan_path,
        ranker_plan,
        command,
        output_prefix,
        outputs,
    )


def verify_approval_for_local_execution(
    approval_path: Path,
) -> VerifiedLocalExecution:
    """
    执行所有安全检查。

    本函数通过后仍然不会执行 BinderRanker。
    """
    approval_path = approval_path.resolve()

    record = load_approval_record(
        approval_path
    )

    if record.status != "APPROVED":
        raise ExecutionGuardError(
            "批准记录状态不是 APPROVED"
        )

    if (
        record.approval_scope
        != "execute_binderranker_once"
    ):
        raise ExecutionGuardError(
            "批准范围不允许执行 BinderRanker"
        )

    if (
        record.binderranker_executed_at_approval
        is not False
    ):
        raise ExecutionGuardError(
            "批准记录没有证明 Ranker 尚未执行"
        )

    if (
        record.remote_backend_used_at_approval
        is not False
    ):
        raise ExecutionGuardError(
            "当前仅支持本地执行批准"
        )

    if (
        record.analysis_scope_level
        == "SMOKE_TEST_ONLY"
        and not record.smoke_test_acknowledged
    ):
        raise ExecutionGuardError(
            "小样本任务没有确认科研解释限制"
        )

    verify_approval_digest(record)
    verify_critical_files(record)
    verify_normalized_dataset(record)

    prepare_manifest_path = (
        record.prepare_manifest.resolve()
    )

    # 一次性批准的使用记录应优先于输出文件检查。
    #
    # 成功或失败执行后，execution manifest 都会存在。
    # 只要该文件存在，就说明批准已经被消费，
    # 应直接报告“不能重复使用”，而不是先因为结果
    # 文件存在而报告“不能覆盖”。
    execution_manifest = (
        default_execution_manifest_path(
            approval_path,
            record.approval_id,
        )
    )

    if execution_manifest.exists():
        raise ExecutionGuardError(
            "该批准记录已经存在执行结果，"
            "一次性批准不能重复使用："
            f"{execution_manifest}"
        )

    (
        ranker_plan_path,
        _ranker_plan,
        command,
        output_prefix,
        outputs,
    ) = verify_ranker_plan(
        record=record,
        prepare_manifest_path=(
            prepare_manifest_path
        ),
    )

    return VerifiedLocalExecution(
        approval_id=record.approval_id,
        approval_path=approval_path,
        project_name=record.project_name,
        analysis_scope_level=(
            record.analysis_scope_level
        ),
        prepare_manifest=(
            prepare_manifest_path
        ),
        ranker_plan=ranker_plan_path,
        ranker_path=(
            record.ranker_path.resolve()
        ),
        normalized_input_directory=(
            record.normalized_dataset.root.resolve()
        ),
        command=command,
        output_prefix=output_prefix,
        expected_outputs=outputs,
        execution_manifest=execution_manifest,
        dataset_combined_sha256=(
            record
            .normalized_dataset
            .combined_sha256
        ),
        ranker_sha256=record.ranker_sha256,
        binderranker_executed=False,
        remote_backend_used=False,
    )
