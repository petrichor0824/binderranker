#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
经过批准的 BinderRanker 本地执行器。

执行流程：
1. 验证 approval.json；
2. 验证关键文件、PDB 数据集和冻结 Ranker；
3. 原子创建 RUNNING 执行记录，占用一次性批准；
4. 使用结构化 subprocess 参数执行 BinderRanker；
5. 保存 stdout 和 stderr；
6. 检查四个预期结果文件；
7. 写入 COMPLETED 或 FAILED。

安全原则：
- 不执行 Shell 字符串；
- 不覆盖已有 Ranker 结果；
- 不允许重复使用同一批准；
- 不连接任何远程服务器；
- 即使运行失败，本次批准也视为已经使用。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from protein_design_agent.agent.approval import (
    FileFingerprint,
    fingerprint_file,
)
from protein_design_agent.agent.execution_guard import (
    ExecutionGuardError,
    load_approval_record,
    verify_approval_for_local_execution,
)
from protein_design_agent.agent.user_errors import (
    UserFacingError,
)


ExecutionRunner = Callable[
    [list[str], Path, Path, Path],
    int,
]


class LocalExecutionError(UserFacingError):
    """本地 BinderRanker 执行失败。"""

    def __init__(
        self,
        message: str,
        *,
        execution_manifest: Path,
        public_message: str | None = None,
    ) -> None:
        super().__init__(
            message,
            public_message=public_message,
        )
        self.execution_manifest = (
            execution_manifest
        )


class CompletedLocalExecution(BaseModel):
    """一次成功完成的本地执行结果。"""

    schema_version: str = "0.1"
    status: Literal["COMPLETED"] = "COMPLETED"

    approval_id: str
    project_name: str

    execution_manifest: Path
    stdout_log: Path
    stderr_log: Path

    output_prefix: Path
    output_files: list[FileFingerprint]

    return_code: int = 0

    binderranker_executed: bool = True
    remote_backend_used: bool = False
    approval_reusable: bool = False


def utc_now() -> str:
    """返回带时区的 UTC 时间。"""
    return datetime.now(
        timezone.utc
    ).isoformat()


def command_sha256(
    command: list[str],
) -> str:
    """对结构化命令参数生成确定性摘要。"""
    canonical = json.dumps(
        command,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def write_json_exclusive(
    path: Path,
    content: dict[str, Any],
) -> None:
    """
    以排他方式创建 JSON 文件。

    mode='x' 保证多个进程不能同时使用同一批准。
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        with path.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                content,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")

    except FileExistsError as exc:
        raise ExecutionGuardError(
            "执行记录已经存在，"
            "该一次性批准可能已被使用："
            f"{path}"
        ) from exc


def replace_json_atomically(
    path: Path,
    content: dict[str, Any],
) -> None:
    """使用临时文件原子更新执行记录。"""
    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}"
    )

    try:
        with temporary.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                content,
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True
        )


def default_local_runner(
    command: list[str],
    stdout_log: Path,
    stderr_log: Path,
    working_directory: Path,
) -> int:
    """
    使用当前本地环境执行结构化命令。

    不使用 shell=True，因此不会解释：
    - 重定向；
    - 管道；
    - 分号；
    - 命令替换；
    - 通配符。
    """
    stdout_log.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    stderr_log.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with (
        stdout_log.open(
            "w",
            encoding="utf-8",
        ) as stdout_handle,
        stderr_log.open(
            "w",
            encoding="utf-8",
        ) as stderr_handle,
    ):
        completed = subprocess.run(
            command,
            cwd=working_directory,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            check=False,
        )

    return completed.returncode


def failure_manifest(
    *,
    running: dict[str, Any],
    error_type: str,
    error_message: str,
    return_code: int | None,
    missing_outputs: list[Path] | None = None,
    empty_outputs: list[Path] | None = None,
) -> dict[str, Any]:
    """由 RUNNING 记录生成 FAILED 记录。"""
    result = dict(running)

    # runner 正常返回返回码，说明进程至少已经成功启动。
    # 若在创建进程时直接抛出异常，return_code 为 None。
    process_started = return_code is not None

    result.update(
        {
            "status": "FAILED",
            "finished_at_utc": utc_now(),
            "return_code": return_code,
            "error_type": error_type,
            "error_message": error_message,
            "missing_outputs": [
                str(path)
                for path in (
                    missing_outputs or []
                )
            ],
            "empty_outputs": [
                str(path)
                for path in (
                    empty_outputs or []
                )
            ],
            # 进入 failure_manifest 意味着本次批准已经被
            # 消耗并进入过执行阶段，但进程未必成功启动。
            "execution_attempted": True,
            "process_started": process_started,
            "binderranker_executed": process_started,
            "approval_reusable": False,
        }
    )

    return result


def execute_approved_binderranker(
    *,
    approval_path: Path,
    confirm_execute: bool = False,
    runner: ExecutionRunner | None = None,
) -> CompletedLocalExecution:
    """
    执行一次经过批准的本地 BinderRanker。

    confirm_execute 必须显式为 True。
    """
    if not confirm_execute:
        raise ValueError(
            "必须显式设置 confirm_execute=True，"
            "本函数才会真正运行 BinderRanker"
        )

    approval_path = approval_path.resolve()

    # 完整执行前安全检查。
    verified = (
        verify_approval_for_local_execution(
            approval_path
        )
    )

    approval = load_approval_record(
        approval_path
    )

    bundle_directory = (
        verified.prepare_manifest
        .resolve()
        .parent
    )

    logs_directory = (
        bundle_directory / "logs"
    )

    stdout_log = (
        logs_directory
        / (
            "binderranker_"
            f"{verified.approval_id}_stdout.log"
        )
    )

    stderr_log = (
        logs_directory
        / (
            "binderranker_"
            f"{verified.approval_id}_stderr.log"
        )
    )

    # 不在抢占 execution manifest 前创建或清空日志。
    #
    # default_local_runner 会在唯一取得执行权之后
    # 创建日志目录并打开日志文件。这样并发失败的进程
    # 不会截断真正执行进程的 stdout/stderr。

    started_at = utc_now()

    running_record: dict[str, Any] = {
        "schema_version": "0.1",
        "status": "RUNNING",
        "approval_id": (
            verified.approval_id
        ),
        "approval_path": str(
            approval_path
        ),
        "approval_digest": (
            approval.approval_digest
        ),
        "approval_scope": (
            approval.approval_scope
        ),
        "approval_reusable": False,
        "project_name": (
            verified.project_name
        ),
        "analysis_scope_level": (
            verified.analysis_scope_level
        ),
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "working_directory": str(
            bundle_directory
        ),
        "command": verified.command,
        "command_sha256": command_sha256(
            verified.command
        ),
        "ranker_path": str(
            verified.ranker_path
        ),
        "ranker_sha256": (
            verified.ranker_sha256
        ),
        "normalized_input_directory": str(
            verified
            .normalized_input_directory
        ),
        "dataset_combined_sha256": (
            verified
            .dataset_combined_sha256
        ),
        "output_prefix": str(
            verified.output_prefix
        ),
        "expected_outputs": [
            str(path)
            for path in (
                verified.expected_outputs
            )
        ],
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "return_code": None,
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    # 原子占用这次一次性批准。
    write_json_exclusive(
        verified.execution_manifest,
        running_record,
    )

    # 只有成功取得一次性执行权的进程，
    # 才允许创建日志目录。
    #
    # 此处只创建目录，不预先清空日志文件；
    # 日志文件由实际 runner 在执行时打开。
    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected_runner = (
        runner
        if runner is not None
        else default_local_runner
    )

    try:
        return_code = selected_runner(
            verified.command,
            stdout_log,
            stderr_log,
            bundle_directory,
        )

    except KeyboardInterrupt as exc:
        failed = failure_manifest(
            running=running_record,
            error_type="KeyboardInterrupt",
            error_message=(
                "本地执行被用户中断"
            ),
            return_code=None,
        )

        replace_json_atomically(
            verified.execution_manifest,
            failed,
        )

        raise LocalExecutionError(
            "BinderRanker 执行被中断；"
            "本次批准已经使用，不能直接重试。",
            execution_manifest=(
                verified.execution_manifest
            ),
            public_message=(
                "BinderRanker 执行被中断；"
                "本次批准已经使用，不能直接重试。"
            ),
        ) from exc

    except Exception as exc:
        failed = failure_manifest(
            running=running_record,
            error_type=type(exc).__name__,
            error_message=str(exc),
            return_code=None,
        )

        replace_json_atomically(
            verified.execution_manifest,
            failed,
        )

        raise LocalExecutionError(
            "BinderRanker 进程无法正常启动；"
            f"执行记录："
            f"{verified.execution_manifest}",
            execution_manifest=(
                verified.execution_manifest
            ),
            public_message=(
                "BinderRanker 进程未能正常启动；"
                "本次批准已经使用，不能直接重试。"
            ),
        ) from exc

    if return_code != 0:
        failed = failure_manifest(
            running=running_record,
            error_type=(
                "NonZeroReturnCode"
            ),
            error_message=(
                "BinderRanker 返回非零退出码："
                f"{return_code}"
            ),
            return_code=return_code,
        )

        replace_json_atomically(
            verified.execution_manifest,
            failed,
        )

        raise LocalExecutionError(
            "BinderRanker 执行失败，"
            f"退出码={return_code}；"
            f"错误日志：{stderr_log}",
            execution_manifest=(
                verified.execution_manifest
            ),
            public_message=(
                "BinderRanker 执行没有成功完成；"
                "本次批准已经使用，不能直接重试。"
            ),
        )

    missing_outputs = [
        path
        for path in verified.expected_outputs
        if not path.exists()
    ]

    empty_outputs = [
        path
        for path in verified.expected_outputs
        if path.exists()
        and path.stat().st_size == 0
    ]

    if missing_outputs or empty_outputs:
        failed = failure_manifest(
            running=running_record,
            error_type=(
                "OutputValidationError"
            ),
            error_message=(
                "BinderRanker 返回成功退出码，"
                "但预期结果不完整"
            ),
            return_code=return_code,
            missing_outputs=missing_outputs,
            empty_outputs=empty_outputs,
        )

        replace_json_atomically(
            verified.execution_manifest,
            failed,
        )

        raise LocalExecutionError(
            "BinderRanker 未生成完整且非空的"
            "预期结果；"
            f"执行记录："
            f"{verified.execution_manifest}",
            execution_manifest=(
                verified.execution_manifest
            ),
            public_message=(
                "BinderRanker 执行结束，"
                "但预期结果不完整；"
                "本次批准已经使用，不能直接重试。"
            ),
        )

    output_fingerprints = [
        fingerprint_file(path)
        for path in verified.expected_outputs
    ]

    completed_record = dict(
        running_record
    )

    completed_record.update(
        {
            "status": "COMPLETED",
            "finished_at_utc": utc_now(),
            "return_code": return_code,
            "output_files": [
                item.model_dump(
                    mode="json"
                )
                for item in (
                    output_fingerprints
                )
            ],
            "binderranker_executed": True,
            "approval_reusable": False,
        }
    )

    replace_json_atomically(
        verified.execution_manifest,
        completed_record,
    )

    return CompletedLocalExecution(
        approval_id=(
            verified.approval_id
        ),
        project_name=(
            verified.project_name
        ),
        execution_manifest=(
            verified.execution_manifest
        ),
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        output_prefix=(
            verified.output_prefix
        ),
        output_files=(
            output_fingerprints
        ),
        return_code=return_code,
        binderranker_executed=True,
        remote_backend_used=False,
        approval_reusable=False,
    )
