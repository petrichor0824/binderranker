#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将审核通过的 AgentPlan 落地为正式项目 YAML。

安全原则：
1. 只接受 READY_FOR_REVIEW；
2. 存在缺失信息时拒绝；
3. 不接受 request 与 plan.request 不一致的会话；
4. config_preview 必须再次通过 ProjectConfig 验证；
5. 默认禁止覆盖已有文件；
6. 写入 YAML 后重新读取验证，防止序列化改变语义；
7. 本模块只生成配置，不运行科学工作流。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from protein_design_agent.agent.orchestrator import (
    PlanningSession,
)
from protein_design_agent.schemas.project_config import (
    ProjectConfig,
    load_project_config,
)


class MaterializationResult(BaseModel):
    """一次计划落地的结果记录。"""

    schema_version: str = "0.1"
    status: str = "MATERIALIZED"

    provider_name: str
    project_name: str

    output_config: Path
    provenance_file: Path

    source_session_sha256: str
    output_config_sha256: str

    workflow_executed: bool = False


def sha256_file(path: Path) -> str:
    """计算文件 SHA256。"""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def load_planning_session(
    path: Path,
) -> PlanningSession:
    """从 JSON 文件读取并验证 PlanningSession。"""
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ValueError(
            f"无法读取规划会话：{exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            "规划会话不是合法 JSON："
            f"第 {exc.lineno} 行，第 {exc.colno} 列"
        ) from exc

    try:
        return PlanningSession.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(
            "规划会话无法通过结构验证：\n"
            f"{exc}"
        ) from exc


def validate_session_for_materialization(
    session: PlanningSession,
) -> ProjectConfig:
    """
    检查会话是否可以落地，并返回正式 ProjectConfig。
    """
    plan = session.plan

    if plan.status != "READY_FOR_REVIEW":
        raise ValueError(
            "只有 READY_FOR_REVIEW 计划可以落地；"
            f"当前状态为 {plan.status}"
        )

    if plan.missing_information:
        raise ValueError(
            "计划仍包含缺失信息："
            f"{plan.missing_information}"
        )

    if plan.config_preview is None:
        raise ValueError(
            "计划没有 config_preview"
        )

    # PlanningSession 中保存了两份 request：
    # session.request 和 session.plan.request。
    # 二者必须完全相同，防止文件被局部篡改。
    outer_request = session.request.model_dump(
        mode="json"
    )
    inner_request = plan.request.model_dump(
        mode="json"
    )

    if outer_request != inner_request:
        raise ValueError(
            "规划会话中的 request 与 "
            "plan.request 不一致"
        )

    if plan.execution_allowed:
        raise ValueError(
            "当前版本不允许自动执行"
        )

    try:
        project = ProjectConfig.model_validate(
            plan.config_preview
        )
    except ValidationError as exc:
        raise ValueError(
            "config_preview 无法通过正式项目配置验证：\n"
            f"{exc}"
        ) from exc

    return project


def protect_output_file(
    path: Path,
    *,
    overwrite: bool,
) -> None:
    """默认禁止覆盖已有文件。"""
    if path.exists() and not overwrite:
        raise ValueError(
            f"输出文件已经存在，禁止覆盖：{path}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def materialize_planning_session(
    *,
    session_path: Path,
    output_config: Path,
    provenance_file: Path | None = None,
    overwrite: bool = False,
) -> MaterializationResult:
    """
    将 PlanningSession 转换为项目 YAML 和来源记录。

    本函数不会启动工作流。
    """
    session_path = session_path.resolve()
    output_config = output_config.resolve()

    if provenance_file is None:
        provenance_file = Path(
            str(output_config) + ".provenance.json"
        )
    else:
        provenance_file = provenance_file.resolve()

    session = load_planning_session(
        session_path
    )

    project = validate_session_for_materialization(
        session
    )

    protect_output_file(
        output_config,
        overwrite=overwrite,
    )
    protect_output_file(
        provenance_file,
        overwrite=overwrite,
    )

    project_data: dict[str, Any] = (
        project.model_dump(mode="json")
    )

    yaml_text = yaml.safe_dump(
        project_data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    output_config.write_text(
        yaml_text,
        encoding="utf-8",
    )

    # 写完以后重新读取，确认 YAML 没有改变字段含义。
    reloaded = load_project_config(
        output_config
    )

    if (
        reloaded.model_dump(mode="json")
        != project.model_dump(mode="json")
    ):
        output_config.unlink(missing_ok=True)

        raise ValueError(
            "YAML 写入后的配置与原计划不一致，"
            "已删除不可靠输出"
        )

    source_hash = sha256_file(session_path)
    config_hash = sha256_file(output_config)

    provenance = {
        "schema_version": "0.1",
        "materialized_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_session": str(session_path),
        "source_session_sha256": source_hash,
        "provider_name": session.provider_name,
        "plan_status": session.plan.status,
        "execution_allowed": (
            session.plan.execution_allowed
        ),
        "project_name": project.project_name,
        "output_config": str(output_config),
        "output_config_sha256": config_hash,
        "workflow_executed": False,
    }

    provenance_file.write_text(
        json.dumps(
            provenance,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return MaterializationResult(
        provider_name=session.provider_name,
        project_name=project.project_name,
        output_config=output_config,
        provenance_file=provenance_file,
        source_session_sha256=source_hash,
        output_config_sha256=config_hash,
        workflow_executed=False,
    )
