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
import os
import tempfile
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


class PlanMaterializationError(ValueError):
    """
    计划落地领域错误。

    继续继承 ValueError 以保持现有 API 兼容；
    public_message 仅保存可以安全展示给用户的确定事实。
    """

    def __init__(
        self,
        message: str,
        *,
        public_message: str | None = None,
    ) -> None:
        super().__init__(message)

        clean_public_message = (
            public_message.strip()
            if isinstance(public_message, str)
            else None
        )

        self.public_message = (
            clean_public_message
            if clean_public_message
            else None
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
        raise PlanMaterializationError(
            "只有 READY_FOR_REVIEW 计划可以落地；"
            f"当前状态为 {plan.status}",
            public_message=(
                "只有 READY_FOR_REVIEW 计划"
                "可以落地为正式项目配置。"
            ),
        )

    if plan.missing_information:
        raise PlanMaterializationError(
            "计划仍包含缺失信息："
            f"{plan.missing_information}",
            public_message=(
                "当前计划仍有缺失信息，"
                "不能落地为正式项目配置。"
            ),
        )

    if plan.config_preview is None:
        raise PlanMaterializationError(
            "计划没有 config_preview",
            public_message=(
                "当前计划没有可落地的项目配置预览。"
            ),
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
        raise PlanMaterializationError(
            "规划会话中的 request 与 "
            "plan.request 不一致",
            public_message=(
                "PlanningSession 内部请求记录"
                "不一致，因此拒绝落地。"
            ),
        )

    if plan.execution_allowed:
        raise PlanMaterializationError(
            "当前版本不允许自动执行",
            public_message=(
                "当前计划包含不允许的自动执行状态，"
                "因此拒绝落地。"
            ),
        )

    try:
        project = ProjectConfig.model_validate(
            plan.config_preview
        )
    except ValidationError as exc:
        raise PlanMaterializationError(
            "config_preview 无法通过正式项目配置验证：\n"
            f"{exc}",
            public_message=(
                "计划中的项目配置预览"
                "未通过正式配置验证。"
            ),
        ) from exc

    return project


def protect_output_file(
    path: Path,
    *,
    overwrite: bool,
) -> None:
    """默认禁止覆盖已有文件。"""
    if path.exists() and not path.is_file():
        raise PlanMaterializationError(
            f"目标输出路径不是普通文件：{path}",
            public_message=(
                "目标输出路径已经存在，"
                "但不是普通文件。"
            ),
        )

    if path.exists() and not overwrite:
        raise PlanMaterializationError(
            f"输出文件已经存在，禁止覆盖：{path}",
            public_message=(
                "目标输出文件已经存在，"
                "默认禁止覆盖。"
            ),
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def create_staged_output(
    target: Path,
) -> Path:
    """
    在目标文件同目录创建 staging 文件。

    同目录保证最终 os.replace 不跨文件系统。
    """
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.materializing-",
        dir=str(target.parent),
    )
    os.close(descriptor)

    return Path(raw_path)


def cleanup_staged_output(
    path: Path | None,
) -> str | None:
    """
    尽力清理 staging 文件。

    清理失败只返回内部诊断，不掩盖原始错误。
    """
    if path is None:
        return None

    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return str(exc)

    return None


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

    if output_config == provenance_file:
        raise PlanMaterializationError(
            "项目配置与 provenance 使用了同一路径："
            f"{output_config}",
            public_message=(
                "项目配置与来源记录不能使用同一路径。"
            ),
        )

    if session_path in {
        output_config,
        provenance_file,
    }:
        raise PlanMaterializationError(
            "计划落地输出路径与源 PlanningSession "
            f"发生冲突：{session_path}",
            public_message=(
                "计划落地输出不能覆盖源 "
                "PlanningSession。"
            ),
        )

    try:
        session = load_planning_session(
            session_path
        )
    except ValueError as exc:
        raise PlanMaterializationError(
            "读取 PlanningSession 失败："
            f"{exc}",
            public_message=(
                "PlanningSession 无法读取"
                "或结构无效。"
            ),
        ) from exc

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

    staged_config: Path | None = None
    staged_provenance: Path | None = None

    try:
        staged_config = create_staged_output(
            output_config
        )
        staged_provenance = create_staged_output(
            provenance_file
        )

        staged_config.write_text(
            yaml_text,
            encoding="utf-8",
        )

        # 发布前验证真正准备发布的 staging YAML。
        try:
            reloaded = load_project_config(
                staged_config
            )
        except (
            ValueError,
            ValidationError,
        ) as exc:
            raise PlanMaterializationError(
                "staging 项目配置验证失败："
                f"{exc}",
                public_message=(
                    "生成的项目配置未通过验证，"
                    "因此没有发布。"
                ),
            ) from exc

        if (
            reloaded.model_dump(mode="json")
            != project.model_dump(mode="json")
        ):
            raise PlanMaterializationError(
                "staging YAML 与原计划不一致",
                public_message=(
                    "生成的项目配置未通过"
                    "一致性验证，因此没有发布。"
                ),
            )

        try:
            source_hash = sha256_file(
                session_path
            )
            config_hash = sha256_file(
                staged_config
            )
        except OSError as exc:
            raise PlanMaterializationError(
                "计划落地完整性验证失败："
                f"{exc}",
                public_message=(
                    "无法完成计划落地所需的"
                    "完整性验证，因此没有发布。"
                ),
            ) from exc

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

        staged_provenance.write_text(
            json.dumps(
                provenance,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        try:
            reloaded_provenance = json.loads(
                staged_provenance.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise PlanMaterializationError(
                "staging provenance 验证失败："
                f"{exc}",
                public_message=(
                    "生成的来源记录未通过验证，"
                    "因此没有发布。"
                ),
            ) from exc

        if reloaded_provenance != provenance:
            raise PlanMaterializationError(
                "staging provenance "
                "写入前后不一致",
                public_message=(
                    "生成的来源记录未通过"
                    "一致性验证，因此没有发布。"
                ),
            )

        result = MaterializationResult(
            provider_name=session.provider_name,
            project_name=project.project_name,
            output_config=output_config,
            provenance_file=provenance_file,
            source_session_sha256=source_hash,
            output_config_sha256=config_hash,
            workflow_executed=False,
        )

        # 两个 staging 文件都通过验证以后，
        # 才开始修改正式输出。
        previous_config: bytes | None = None

        if output_config.exists():
            try:
                previous_config = (
                    output_config.read_bytes()
                )
            except OSError as exc:
                raise PlanMaterializationError(
                    "无法读取已有项目配置以准备回滚："
                    f"{exc}",
                    public_message=(
                        "无法安全保护已有项目配置，"
                        "因此没有开始发布新输出。"
                    ),
                ) from exc

        # overwrite=False 时再次检查目标，
        # 避免准备过程中出现的新文件被静默覆盖。
        if not overwrite and (
            output_config.exists()
            or provenance_file.exists()
        ):
            raise PlanMaterializationError(
                "正式发布前检测到目标输出已经存在",
                public_message=(
                    "目标输出在计划落地期间已存在，"
                    "为避免覆盖已停止发布。"
                ),
            )

        try:
            os.replace(
                staged_config,
                output_config,
            )
        except OSError as exc:
            raise PlanMaterializationError(
                "项目配置正式发布失败："
                f"{exc}",
                public_message=(
                    "计划落地正式发布失败；"
                    "原有正式输出未被替换。"
                ),
            ) from exc

        # 已经移动，不再让 finally 尝试清理该路径。
        staged_config = None

        try:
            os.replace(
                staged_provenance,
                provenance_file,
            )
        except OSError as exc:
            rollback_error: OSError | None = None
            rollback_path: Path | None = None

            try:
                if previous_config is None:
                    output_config.unlink(
                        missing_ok=True
                    )
                else:
                    rollback_path = (
                        create_staged_output(
                            output_config
                        )
                    )
                    rollback_path.write_bytes(
                        previous_config
                    )
                    os.replace(
                        rollback_path,
                        output_config,
                    )
                    rollback_path = None

            except OSError as rollback_exc:
                rollback_error = rollback_exc

            finally:
                cleanup_staged_output(
                    rollback_path
                )

            internal_message = (
                "来源记录正式发布失败："
                f"{exc}"
            )

            if rollback_error is not None:
                internal_message += (
                    "；项目配置回滚失败："
                    f"{rollback_error}"
                )

            public_message = (
                "计划落地发布失败；"
                "已恢复发布前的项目配置状态。"
                if rollback_error is None
                else (
                    "计划落地发布失败，且无法确认"
                    "项目配置已经恢复。"
                    "请勿使用本次输出，"
                    "并检查输出文件。"
                )
            )

            raise PlanMaterializationError(
                internal_message,
                public_message=public_message,
            ) from exc

        # provenance 也成功发布。
        staged_provenance = None

        return result

    except PlanMaterializationError:
        raise

    except (
        OSError,
        ValueError,
        ValidationError,
    ) as exc:
        raise PlanMaterializationError(
            "计划落地 staging 阶段失败："
            f"{exc}",
            public_message=(
                "项目配置或来源记录生成失败，"
                "正式输出没有发布。"
            ),
        ) from exc

    finally:
        # 这里只处理尚未发布的 staging 文件。
        # 清理是 best-effort，绝不能掩盖主异常。
        cleanup_staged_output(
            staged_config
        )
        cleanup_staged_output(
            staged_provenance
        )
