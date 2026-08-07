#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将一个审核就绪的 PlanningSession 转换成完整的准备工作流。

处理流程：

PlanningSession JSON
    ↓
复制并冻结会话
    ↓
生成正式项目 YAML
    ↓
调用骨架排名准备工作流
    ↓
检查 workflow_manifest.json
    ↓
停在 READY_FOR_REVIEW

安全原则：
1. 只接受 READY_FOR_REVIEW 会话；
2. 默认禁止覆盖既有任务目录；
3. 使用结构化 subprocess 参数，不执行任意 Shell 字符串；
4. 保存标准输出和错误日志；
5. 验证工作流确实停在 READY_FOR_REVIEW；
6. 不真正执行 BinderRanker；
7. 不连接任何远程服务器。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from protein_design_agent.agent.plan_materializer import (
    load_planning_session,
    materialize_planning_session,
    sha256_file,
    validate_session_for_materialization,
)


# command、stdout日志、stderr日志 -> 退出码
WorkflowRunner = Callable[
    [list[str], Path, Path],
    int,
]


class AgentPreparationError(RuntimeError):
    """Agent 准备流水线失败。"""


class PreparedAgentRun(BaseModel):
    """成功准备完成的一次 Agent 任务记录。"""

    schema_version: str = "0.1"
    status: str = "READY_FOR_REVIEW"

    project_name: str
    provider_name: str

    bundle_directory: Path
    session_copy: Path
    project_config: Path
    project_provenance: Path

    workflow_directory: Path
    workflow_manifest: Path

    stdout_log: Path
    stderr_log: Path

    prepare_manifest: Path

    scientific_workflow_executed: bool = False
    binderranker_executed: bool = False
    remote_backend_used: bool = False


def protect_bundle_directory(
    bundle_dir: Path,
) -> None:
    """
    禁止覆盖非空任务目录。

    本函数只验证目标位置，不提前创建正式 Bundle。
    准备工作必须先在同一父目录的 staging 目录完成。
    """
    if bundle_dir.exists():
        if not bundle_dir.is_dir():
            raise ValueError(
                f"任务路径已经存在且不是目录："
                f"{bundle_dir}"
            )

        existing_items = list(
            bundle_dir.iterdir()
        )

        if existing_items:
            raise ValueError(
                f"任务目录已经存在且非空，禁止覆盖："
                f"{bundle_dir}"
            )


def default_workflow_runner(
    command: list[str],
    stdout_log: Path,
    stderr_log: Path,
) -> int:
    """
    使用当前 Python 环境启动确定性工作流。

    注意：
    command 是参数列表，不经过 Shell 解释。
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
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            check=False,
        )

    return completed.returncode


def write_json(
    path: Path,
    content: dict[str, Any],
) -> None:
    """写入格式化 JSON。"""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def relocate_staged_metadata(
    *,
    staging_dir: Path,
    bundle_dir: Path,
) -> None:
    """
    将成功准备产物中的 staging 绝对路径改为正式 Bundle 路径。

    这里只修改明确包含运行路径的文本元数据，
    不修改 PDB 数据和运行日志。
    """
    metadata_paths = [
        staging_dir / "project.provenance.json",
        (
            staging_dir
            / "workflow"
            / "workflow_manifest.json"
        ),
        (
            staging_dir
            / "workflow"
            / "normalized_pdbs"
            / "normalization_manifest.json"
        ),
        (
            staging_dir
            / "workflow"
            / "ranker"
            / "ranker_execution_plan.json"
        ),
        (
            staging_dir
            / "workflow"
            / "ranker"
            / "run_ranker.sh"
        ),
    ]

    old_root = str(staging_dir)
    new_root = str(bundle_dir)

    for path in metadata_paths:
        if not path.is_file():
            continue

        content = path.read_text(
            encoding="utf-8"
        )

        if old_root not in content:
            continue

        path.write_text(
            content.replace(
                old_root,
                new_root,
            ),
            encoding="utf-8",
        )


def publish_staged_bundle(
    *,
    staging_dir: Path,
    bundle_dir: Path,
) -> None:
    """把完整 staging Bundle 一次性发布到正式位置。"""
    if bundle_dir.exists():
        if any(bundle_dir.iterdir()):
            raise ValueError(
                f"正式任务目录在准备过程中变为非空："
                f"{bundle_dir}"
            )

        bundle_dir.rmdir()

    os.replace(
        staging_dir,
        bundle_dir,
    )


def record_prepare_failure(
    *,
    bundle_dir: Path,
    session_path: Path,
    staging_dir: Path,
    project_name: str,
    provider_name: str,
    error: Exception,
    return_code: int | None,
    stdout_log: Path,
    stderr_log: Path,
) -> Path:
    """
    在正式 Bundle 外保存准备失败审计记录。

    失败记录不会使正式 Bundle 看起来像有效任务。
    """
    audit_root = (
        bundle_dir.parent
        / ".pda-failures"
        / bundle_dir.name
    )

    audit_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    failure_dir = Path(
        tempfile.mkdtemp(
            prefix="prepare-",
            dir=str(audit_root),
        )
    )

    logs_dir = failure_dir / "logs"
    logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    copied_stdout = None
    copied_stderr = None

    if stdout_log.is_file():
        copied_stdout = (
            logs_dir / "workflow_stdout.log"
        )
        shutil.copy2(
            stdout_log,
            copied_stdout,
        )

    if stderr_log.is_file():
        copied_stderr = (
            logs_dir / "workflow_stderr.log"
        )
        shutil.copy2(
            stderr_log,
            copied_stderr,
        )

    manifest = {
        "schema_version": "0.1",
        "status": "FAILED",
        "project_name": project_name,
        "provider_name": provider_name,
        "requested_bundle_directory": str(
            bundle_dir
        ),
        "source_session": str(session_path),
        "formal_bundle_published": False,
        "exception_type": type(error).__name__,
        "error_message": str(error),
        "return_code": return_code,
        "stdout_log": (
            str(copied_stdout)
            if copied_stdout is not None
            else None
        ),
        "stderr_log": (
            str(copied_stderr)
            if copied_stderr is not None
            else None
        ),
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    manifest_path = (
        failure_dir / "failure_manifest.json"
    )

    write_json(
        manifest_path,
        manifest,
    )

    return manifest_path

def load_workflow_manifest(
    path: Path,
) -> dict[str, Any]:
    """读取骨架排名工作流的 Manifest。"""
    if not path.exists():
        raise AgentPreparationError(
            f"工作流没有生成 Manifest：{path}"
        )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise AgentPreparationError(
            "工作流 Manifest 不是合法 JSON："
            f"{exc}"
        ) from exc

    if not isinstance(data, dict):
        raise AgentPreparationError(
            "工作流 Manifest 最外层必须是对象"
        )

    return data


def prepare_agent_run(
    *,
    session_path: Path,
    bundle_dir: Path,
    runner: WorkflowRunner | None = None,
) -> PreparedAgentRun:
    """
    从 PlanningSession 原子地创建完整准备任务。

    所有准备工作先写入同一父目录中的 staging Bundle。
    只有全部验证通过后，才一次性发布为正式 Bundle。
    BinderRanker 不会在本阶段真正执行。
    """
    session_path = session_path.resolve()
    bundle_dir = bundle_dir.resolve()

    # 在创建任何输出前先验证 PlanningSession。
    session = load_planning_session(
        session_path
    )
    project = validate_session_for_materialization(
        session
    )

    # 这里只检查正式目标是否安全，不提前写入正式 Bundle。
    protect_bundle_directory(
        bundle_dir
    )

    bundle_dir.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{bundle_dir.name}.preparing-",
            dir=str(bundle_dir.parent),
        )
    ).resolve()

    # 提前定义失败审计需要的路径。
    # 即使后续在真正启动 workflow 前失败，也能安全记录。
    stdout_log = (
        staging_dir
        / "logs"
        / "workflow_stdout.log"
    )
    stderr_log = (
        staging_dir
        / "logs"
        / "workflow_stderr.log"
    )
    return_code: int | None = None

    try:
        session_copy = (
            staging_dir / "planning_session.json"
        )
        project_config = (
            staging_dir / "project.yaml"
        )
        project_provenance = (
            staging_dir / "project.provenance.json"
        )
        workflow_dir = (
            staging_dir / "workflow"
        )
        logs_dir = (
            staging_dir / "logs"
        )
        stdout_log = (
            logs_dir / "workflow_stdout.log"
        )
        stderr_log = (
            logs_dir / "workflow_stderr.log"
        )
        prepare_manifest = (
            staging_dir
            / "agent_prepare_manifest.json"
        )

        # 保存规划会话的不可变副本。
        shutil.copy2(
            session_path,
            session_copy,
        )

        if (
            sha256_file(session_path)
            != sha256_file(session_copy)
        ):
            raise AgentPreparationError(
                "PlanningSession 复制后的 SHA256 不一致"
            )

        materialization = materialize_planning_session(
            session_path=session_copy,
            output_config=project_config,
            provenance_file=project_provenance,
            overwrite=False,
        )

        command = [
            sys.executable,
            "-m",
            (
                "protein_design_agent.workflows."
                "backbone_ranking_workflow"
            ),
            "--config",
            str(project_config),
            "--run-dir",
            str(workflow_dir),
        ]

        selected_runner = (
            runner
            if runner is not None
            else default_workflow_runner
        )

        return_code = selected_runner(
            command,
            stdout_log,
            stderr_log,
        )

        workflow_manifest = (
            workflow_dir
            / "workflow_manifest.json"
        )

        if return_code != 0:
            raise AgentPreparationError(
                "骨架排名准备工作流执行失败，"
                f"退出码={return_code}"
            )

        workflow_data = load_workflow_manifest(
            workflow_manifest
        )

        workflow_status = workflow_data.get(
            "status"
        )

        if workflow_status != "READY_FOR_REVIEW":
            raise AgentPreparationError(
                "工作流没有停在 READY_FOR_REVIEW；"
                f"实际状态为 {workflow_status}"
            )

        ranker_plan_path = (
            workflow_dir
            / "ranker"
            / "ranker_execution_plan.json"
        )

        if not ranker_plan_path.exists():
            raise AgentPreparationError(
                "工作流没有生成 BinderRanker 计划："
                f"{ranker_plan_path}"
            )

        # 准备阶段绝不能产生真正的 Ranker 结果。
        forbidden_ranker_outputs = [
            (
                workflow_dir
                / "ranker"
                / "backbone_rank_metrics.csv"
            ),
            (
                workflow_dir
                / "ranker"
                / "backbone_rank_scored.csv"
            ),
            (
                workflow_dir
                / "ranker"
                / "backbone_rank_ranking.xlsx"
            ),
            (
                workflow_dir
                / "ranker"
                / "backbone_rank_report.txt"
            ),
        ]

        unexpected_outputs = [
            output
            for output in forbidden_ranker_outputs
            if output.exists()
        ]

        if unexpected_outputs:
            formatted = "\n".join(
                f"- {output}"
                for output in unexpected_outputs
            )

            raise AgentPreparationError(
                "准备阶段意外生成了 Ranker 结果，"
                "说明执行边界被破坏：\n"
                f"{formatted}"
            )

        # 工作流实际在 staging 中运行，因此在正式发布前，
        # 将可执行元数据里的 staging 绝对路径改成正式路径。
        relocate_staged_metadata(
            staging_dir=staging_dir,
            bundle_dir=bundle_dir,
        )

        final_session_copy = (
            bundle_dir / "planning_session.json"
        )
        final_project_config = (
            bundle_dir / "project.yaml"
        )
        final_project_provenance = (
            bundle_dir / "project.provenance.json"
        )
        final_workflow_dir = (
            bundle_dir / "workflow"
        )
        final_workflow_manifest = (
            final_workflow_dir
            / "workflow_manifest.json"
        )
        final_ranker_plan = (
            final_workflow_dir
            / "ranker"
            / "ranker_execution_plan.json"
        )
        final_stdout_log = (
            bundle_dir
            / "logs"
            / "workflow_stdout.log"
        )
        final_stderr_log = (
            bundle_dir
            / "logs"
            / "workflow_stderr.log"
        )
        final_prepare_manifest = (
            bundle_dir
            / "agent_prepare_manifest.json"
        )

        published_command = [
            item.replace(
                str(staging_dir),
                str(bundle_dir),
            )
            for item in command
        ]

        manifest_content = {
            "schema_version": "0.1",
            "status": "READY_FOR_REVIEW",
            "project_name": project.project_name,
            "provider_name": session.provider_name,
            "bundle_directory": str(bundle_dir),
            "source_session": str(session_path),
            "session_copy": str(final_session_copy),
            "session_sha256": sha256_file(
                session_copy
            ),
            "project_config": str(
                final_project_config
            ),
            "project_config_sha256": (
                materialization.output_config_sha256
            ),
            "project_provenance": str(
                final_project_provenance
            ),
            "workflow_directory": str(
                final_workflow_dir
            ),
            "workflow_manifest": str(
                final_workflow_manifest
            ),
            "workflow_status": workflow_status,
            "ranker_plan": str(
                final_ranker_plan
            ),
            "stdout_log": str(
                final_stdout_log
            ),
            "stderr_log": str(
                final_stderr_log
            ),
            "command": published_command,
            "scientific_workflow_executed": False,
            "binderranker_executed": False,
            "remote_backend_used": False,
        }

        write_json(
            prepare_manifest,
            manifest_content,
        )

        # 最后一步才发布正式 Bundle。
        publish_staged_bundle(
            staging_dir=staging_dir,
            bundle_dir=bundle_dir,
        )

        return PreparedAgentRun(
            project_name=project.project_name,
            provider_name=session.provider_name,
            bundle_directory=bundle_dir,
            session_copy=final_session_copy,
            project_config=final_project_config,
            project_provenance=(
                final_project_provenance
            ),
            workflow_directory=(
                final_workflow_dir
            ),
            workflow_manifest=(
                final_workflow_manifest
            ),
            stdout_log=final_stdout_log,
            stderr_log=final_stderr_log,
            prepare_manifest=(
                final_prepare_manifest
            ),
            scientific_workflow_executed=False,
            binderranker_executed=False,
            remote_backend_used=False,
        )

    except Exception as exc:
        # 失败证据保存在正式 Bundle 外部。
        # 审计写入本身若失败，不得掩盖原始准备异常。
        try:
            record_prepare_failure(
                bundle_dir=bundle_dir,
                session_path=session_path,
                staging_dir=staging_dir,
                project_name=project.project_name,
                provider_name=session.provider_name,
                error=exc,
                return_code=return_code,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
            )
        except Exception:
            pass

        raise

    finally:
        # 成功发布后 staging 已被 os.replace 移走；
        # 任何失败则在这里清理全部半成品。
        if staging_dir.exists():
            shutil.rmtree(
                staging_dir,
                ignore_errors=True,
            )
