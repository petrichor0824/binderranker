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
import shutil
import subprocess
import sys
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

    scientific_workflow_executed: bool = True
    binderranker_executed: bool = False
    remote_backend_used: bool = False


def protect_bundle_directory(
    bundle_dir: Path,
) -> None:
    """默认禁止使用非空任务目录。"""
    if bundle_dir.exists():
        existing_items = list(
            bundle_dir.iterdir()
        )

        if existing_items:
            raise ValueError(
                f"任务目录已经存在且非空，禁止覆盖："
                f"{bundle_dir}"
            )

    bundle_dir.mkdir(
        parents=True,
        exist_ok=True,
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
    从 PlanningSession 创建完整准备任务。

    本函数会检查和标准化 PDB，
    但不会真正运行 BinderRanker。
    """
    session_path = session_path.resolve()
    bundle_dir = bundle_dir.resolve()

    # 在创建任何输出前，先检查会话是否合法。
    session = load_planning_session(
        session_path
    )

    project = validate_session_for_materialization(
        session
    )

    protect_bundle_directory(
        bundle_dir
    )

    session_copy = (
        bundle_dir / "planning_session.json"
    )

    project_config = (
        bundle_dir / "project.yaml"
    )

    project_provenance = (
        bundle_dir / "project.provenance.json"
    )

    workflow_dir = (
        bundle_dir / "workflow"
    )

    logs_dir = (
        bundle_dir / "logs"
    )

    stdout_log = (
        logs_dir / "workflow_stdout.log"
    )

    stderr_log = (
        logs_dir / "workflow_stderr.log"
    )

    prepare_manifest = (
        bundle_dir / "agent_prepare_manifest.json"
    )

    # 保存大模型规划会话的不可变副本。
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
        workflow_dir / "workflow_manifest.json"
    )

    if return_code != 0:
        failure_record = {
            "schema_version": "0.1",
            "status": "FAILED",
            "project_name": project.project_name,
            "provider_name": session.provider_name,
            "command": command,
            "return_code": return_code,
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "binderranker_executed": False,
            "remote_backend_used": False,
        }

        write_json(
            prepare_manifest,
            failure_record,
        )

        raise AgentPreparationError(
            "骨架排名准备工作流执行失败，"
            f"退出码={return_code}；"
            f"错误日志：{stderr_log}"
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

    # 这些结果文件只有真正执行 Ranker 后才应出现。
    forbidden_ranker_outputs = [
        workflow_dir
        / "ranker"
        / "backbone_rank_metrics.csv",
        workflow_dir
        / "ranker"
        / "backbone_rank_scored.csv",
        workflow_dir
        / "ranker"
        / "backbone_rank_ranking.xlsx",
        workflow_dir
        / "ranker"
        / "backbone_rank_report.txt",
    ]

    unexpected_outputs = [
        path
        for path in forbidden_ranker_outputs
        if path.exists()
    ]

    if unexpected_outputs:
        formatted = "\n".join(
            f"- {path}"
            for path in unexpected_outputs
        )

        raise AgentPreparationError(
            "准备阶段意外生成了 Ranker 结果，"
            "说明执行边界被破坏：\n"
            f"{formatted}"
        )

    manifest_content = {
        "schema_version": "0.1",
        "status": "READY_FOR_REVIEW",
        "project_name": project.project_name,
        "provider_name": session.provider_name,
        "bundle_directory": str(bundle_dir),
        "source_session": str(session_path),
        "session_copy": str(session_copy),
        "session_sha256": sha256_file(
            session_copy
        ),
        "project_config": str(project_config),
        "project_config_sha256": (
            materialization.output_config_sha256
        ),
        "project_provenance": str(
            project_provenance
        ),
        "workflow_directory": str(
            workflow_dir
        ),
        "workflow_manifest": str(
            workflow_manifest
        ),
        "workflow_status": workflow_status,
        "ranker_plan": str(
            ranker_plan_path
        ),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "command": command,
        "scientific_workflow_executed": True,
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    write_json(
        prepare_manifest,
        manifest_content,
    )

    return PreparedAgentRun(
        project_name=project.project_name,
        provider_name=session.provider_name,
        bundle_directory=bundle_dir,
        session_copy=session_copy,
        project_config=project_config,
        project_provenance=project_provenance,
        workflow_directory=workflow_dir,
        workflow_manifest=workflow_manifest,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        prepare_manifest=prepare_manifest,
        scientific_workflow_executed=True,
        binderranker_executed=False,
        remote_backend_used=False,
    )
