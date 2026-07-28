#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Protein Design Agent 本地环境诊断。

原则：
- 只读；
- 不访问网络；
- 不显示 API Key；
- 不安装或修改任何依赖；
- Ranker 哈希错误属于 FAIL；
- 缺少可选模型 Key 属于 WARN。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from protein_design_agent.agent.provider_factory import (
    resolve_provider_profile,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)
from protein_design_agent.tools.run_binderranker import (
    resolve_ranker,
)


DoctorStatus = Literal[
    "PASS",
    "WARN",
    "FAIL",
]


class DoctorCheck(BaseModel):
    """单项诊断结果。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    name: str
    status: DoctorStatus
    message: str
    detail: str | None = None


class DoctorReport(BaseModel):
    """完整诊断报告。"""

    model_config = ConfigDict(
        extra="forbid",
    )

    schema_version: str = "0.1"

    context_mode: str = "SOURCE_CHECKOUT"
    project_root: Path
    working_directory: Path

    checks: list[DoctorCheck] = Field(
        default_factory=list
    )

    network_accessed: bool = False
    environment_modified: bool = False

    def overall_status(
        self,
    ) -> DoctorStatus:
        statuses = {
            check.status
            for check in self.checks
        }

        if "FAIL" in statuses:
            return "FAIL"

        if "WARN" in statuses:
            return "WARN"

        return "PASS"

    def exit_code(self) -> int:
        return (
            2
            if self.overall_status() == "FAIL"
            else 0
        )


class DoctorError(RuntimeError):
    """Doctor 无法完成基础诊断。"""


def sha256_file(
    path: Path,
) -> str:
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


def discover_project_root(
    start_directory: Path | None = None,
) -> Path:
    """
    从当前目录和包源码位置向上寻找项目根目录。
    """
    starts = [
        (
            start_directory.resolve()
            if start_directory is not None
            else Path.cwd().resolve()
        ),
        Path(__file__).resolve(),
    ]

    visited: set[Path] = set()

    for start in starts:
        base = (
            start
            if start.is_dir()
            else start.parent
        )

        for candidate in (
            base,
            *base.parents,
        ):
            resolved = candidate.resolve()

            if resolved in visited:
                continue

            visited.add(resolved)

            if (
                (
                    resolved
                    / "pyproject.toml"
                ).is_file()
                and (
                    resolved
                    / "src"
                    / "protein_design_agent"
                ).is_dir()
            ):
                return resolved

    raise DoctorError(
        "无法自动定位项目根目录。"
        "请使用 --project-root 显式指定。"
    )


def is_source_checkout(
    path: Path,
) -> bool:
    """判断目录是否为源码检出目录。"""
    root = path.resolve()

    return (
        (root / "pyproject.toml").is_file()
        and (
            root
            / "src"
            / "protein_design_agent"
        ).is_dir()
    )


def is_agent_workspace(
    path: Path,
) -> bool:
    """判断目录是否为 init 创建的用户工作区。"""
    root = path.resolve()

    required_directories = (
        root / "configs" / "models",
        root / "data",
        root / "runs",
    )

    return all(
        item.is_dir()
        for item in required_directories
    )


def resolve_doctor_context(
    *,
    project_root: Path | None = None,
    start_directory: Path | None = None,
) -> tuple[str, Path, DoctorCheck]:
    """
    识别当前诊断上下文。

    工作区优先于源码仓库识别，避免 editable
    安装时错误跳回源码目录。
    """
    if project_root is not None:
        root = project_root.expanduser().resolve()

        if is_source_checkout(root):
            return (
                "SOURCE_CHECKOUT",
                root,
                DoctorCheck(
                    name="runtime_context",
                    status="PASS",
                    message="指定目录是源码仓库",
                    detail=str(root),
                ),
            )

        if is_agent_workspace(root):
            return (
                "WORKSPACE",
                root,
                DoctorCheck(
                    name="runtime_context",
                    status="PASS",
                    message="指定目录是用户工作区",
                    detail=str(root),
                ),
            )

        return (
            "INVALID_ROOT",
            root,
            DoctorCheck(
                name="runtime_context",
                status="FAIL",
                message=(
                    "指定目录既不是源码仓库，"
                    "也不是有效用户工作区"
                ),
                detail=str(root),
            ),
        )

    current = (
        start_directory.expanduser().resolve()
        if start_directory is not None
        else Path.cwd().resolve()
    )

    if is_agent_workspace(current):
        return (
            "WORKSPACE",
            current,
            DoctorCheck(
                name="runtime_context",
                status="PASS",
                message="当前目录是用户工作区",
                detail=str(current),
            ),
        )

    try:
        source_root = discover_project_root(
            current
        )

        return (
            "SOURCE_CHECKOUT",
            source_root,
            DoctorCheck(
                name="runtime_context",
                status="PASS",
                message="已定位源码仓库",
                detail=str(source_root),
            ),
        )

    except DoctorError:
        return (
            "INSTALLED_PACKAGE",
            current,
            DoctorCheck(
                name="runtime_context",
                status="WARN",
                message=(
                    "当前运行自已安装的软件包，"
                    "但没有进入用户工作区"
                ),
                detail=(
                    "可运行 protein-design-agent init "
                    "--destination <目录>"
                ),
            ),
        )


def check_ranker_integrity(
    *,
    version: str,
) -> DoctorCheck:
    """验证冻结 Ranker 文件与 SHA256。"""
    try:
        ranker_path, expected_sha256 = (
            resolve_ranker(version)
        )

        ranker_path = ranker_path.resolve()

        if not ranker_path.is_file():
            return DoctorCheck(
                name="frozen_ranker",
                status="FAIL",
                message=(
                    "冻结 Ranker 文件不存在"
                ),
                detail=str(ranker_path),
            )

        actual_sha256 = sha256_file(
            ranker_path
        )

        if actual_sha256 != expected_sha256:
            return DoctorCheck(
                name="frozen_ranker",
                status="FAIL",
                message=(
                    "冻结 Ranker SHA256 不匹配"
                ),
                detail=(
                    f"path={ranker_path}; "
                    f"expected={expected_sha256}; "
                    f"actual={actual_sha256}"
                ),
            )

        return DoctorCheck(
            name="frozen_ranker",
            status="PASS",
            message=(
                f"冻结 Ranker {version} "
                "完整性验证通过"
            ),
            detail=(
                f"path={ranker_path}; "
                f"sha256={actual_sha256}"
            ),
        )

    except Exception as exc:
        return DoctorCheck(
            name="frozen_ranker",
            status="FAIL",
            message=(
                "无法验证冻结 Ranker"
            ),
            detail=str(exc),
        )


def check_model_profile(
    *,
    config_path: Path | None,
    profile_name: str | None,
    environment: (
        Mapping[str, str] | None
    ) = None,
) -> list[DoctorCheck]:
    """
    验证模型配置和 API Key。

    不访问 Provider 网络。
    """
    env = (
        environment
        if environment is not None
        else os.environ
    )

    if config_path is None:
        return [
            DoctorCheck(
                name="model_config",
                status="WARN",
                message=(
                    "没有找到或指定模型配置"
                ),
                detail=(
                    "确定性工作流仍可使用；"
                    "自然语言解析和模型解释不可用。"
                ),
            )
        ]

    path = config_path.resolve()

    if not path.is_file():
        return [
            DoctorCheck(
                name="model_config",
                status="FAIL",
                message="模型配置文件不存在",
                detail=str(path),
            )
        ]

    try:
        config = load_model_provider_config(
            path
        )

        selected_name, selected = (
            resolve_provider_profile(
                config,
                profile_name=profile_name,
            )
        )

    except Exception as exc:
        return [
            DoctorCheck(
                name="model_config",
                status="FAIL",
                message=(
                    "模型配置无法通过验证"
                ),
                detail=(
                    f"path={path}; error={exc}"
                ),
            )
        ]

    checks = [
        DoctorCheck(
            name="model_config",
            status="PASS",
            message=(
                f"模型 Profile "
                f"{selected_name} 配置有效"
            ),
            detail=(
                f"kind={selected.kind}; "
                f"model={selected.model}; "
                f"base_url={selected.base_url}"
            ),
        )
    ]

    if not selected.require_api_key:
        checks.append(
            DoctorCheck(
                name="model_api_key",
                status="PASS",
                message=(
                    "当前 Profile 不要求 API Key"
                ),
            )
        )
        return checks

    key_env = selected.api_key_env

    if (
        key_env is not None
        and bool(env.get(key_env))
    ):
        checks.append(
            DoctorCheck(
                name="model_api_key",
                status="PASS",
                message=(
                    f"API Key 环境变量 "
                    f"{key_env} 已设置"
                ),
                detail=(
                    "Doctor 不会显示 Key 内容，"
                    "也没有访问网络。"
                ),
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="model_api_key",
                status="WARN",
                message=(
                    "模型所需 API Key "
                    "环境变量尚未设置"
                ),
                detail=str(key_env),
            )
        )

    return checks


def run_doctor(
    *,
    project_root: Path | None = None,
    model_config_path: Path | None = None,
    profile_name: str | None = None,
    ranker_version: str = (
        "v0.1-expert"
    ),
) -> DoctorReport:
    """执行全部只读诊断。"""
    checks: list[DoctorCheck] = []

    context_mode, root, context_check = (
        resolve_doctor_context(
            project_root=project_root,
        )
    )

    checks.append(context_check)

    python_version = (
        f"{sys.version_info.major}."
        f"{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )

    if sys.version_info >= (3, 10):
        checks.append(
            DoctorCheck(
                name="python",
                status="PASS",
                message=(
                    f"Python {python_version} "
                    "满足最低要求 3.10"
                ),
                detail=sys.executable,
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="python",
                status="FAIL",
                message=(
                    f"Python {python_version} "
                    "低于最低要求 3.10"
                ),
                detail=sys.executable,
            )
        )

    in_virtual_environment = (
        sys.prefix != sys.base_prefix
        or bool(
            os.environ.get("VIRTUAL_ENV")
        )
    )

    checks.append(
        DoctorCheck(
            name="virtual_environment",
            status=(
                "PASS"
                if in_virtual_environment
                else "WARN"
            ),
            message=(
                "当前位于虚拟环境中"
                if in_virtual_environment
                else (
                    "当前未检测到虚拟环境"
                )
            ),
            detail=(
                os.environ.get("VIRTUAL_ENV")
                or sys.prefix
            ),
        )
    )

    cli_path = shutil.which(
        "protein-design-agent"
    )

    checks.append(
        DoctorCheck(
            name="cli",
            status=(
                "PASS"
                if cli_path
                else "FAIL"
            ),
            message=(
                "protein-design-agent CLI "
                "可从 PATH 调用"
                if cli_path
                else (
                    "PATH 中找不到 "
                    "protein-design-agent"
                )
            ),
            detail=cli_path,
        )
    )

    checks.append(
        check_ranker_integrity(
            version=ranker_version
        )
    )

    if context_mode == "SOURCE_CHECKOUT":
        sample_dir = (
            root
            / "sample_data"
            / "real"
            / "3c98_small"
        )

        sample_count = (
            len(
                list(
                    sample_dir.glob("*.pdb")
                )
            )
            if sample_dir.is_dir()
            else 0
        )

        checks.append(
            DoctorCheck(
                name="sample_data",
                status=(
                    "PASS"
                    if sample_count > 0
                    else "WARN"
                ),
                message=(
                    f"示例数据可用："
                    f"{sample_count} 个 PDB"
                    if sample_count > 0
                    else "没有找到源码示例数据"
                ),
                detail=str(sample_dir),
            )
        )

        license_path = root / "LICENSE"

        checks.append(
            DoctorCheck(
                name="license",
                status=(
                    "PASS"
                    if license_path.is_file()
                    else "WARN"
                ),
                message=(
                    "LICENSE 文件存在"
                    if license_path.is_file()
                    else (
                        "尚未提供 LICENSE，"
                        "不适合公开发布"
                    )
                ),
                detail=str(license_path),
            )
        )

    elif context_mode == "WORKSPACE":
        workspace_paths = (
            root / "configs" / "models",
            root / "data",
            root / "runs",
        )

        layout_valid = all(
            path.is_dir()
            for path in workspace_paths
        )

        checks.append(
            DoctorCheck(
                name="workspace_layout",
                status=(
                    "PASS"
                    if layout_valid
                    else "FAIL"
                ),
                message=(
                    "用户工作区目录结构完整"
                    if layout_valid
                    else "用户工作区目录结构不完整"
                ),
                detail=str(root),
            )
        )

    else:
        checks.append(
            DoctorCheck(
                name="workspace_layout",
                status="WARN",
                message=(
                    "当前未指定用户工作区，"
                    "跳过工作区目录检查"
                ),
                detail=str(root),
            )
        )

    workdir = Path.cwd().resolve()

    checks.append(
        DoctorCheck(
            name="working_directory",
            status=(
                "PASS"
                if os.access(
                    workdir,
                    os.W_OK,
                )
                else "FAIL"
            ),
            message=(
                "当前工作目录具有写权限"
                if os.access(
                    workdir,
                    os.W_OK,
                )
                else (
                    "当前工作目录没有写权限"
                )
            ),
            detail=str(workdir),
        )
    )

    if model_config_path is not None:
        resolved_model_config = (
            model_config_path.expanduser().resolve()
        )
    elif context_mode in {
        "SOURCE_CHECKOUT",
        "WORKSPACE",
    }:
        candidate_model_config = (
            root
            / "configs"
            / "models"
            / "deepseek.local.yaml"
        )

        resolved_model_config = (
            candidate_model_config
            if candidate_model_config.is_file()
            else None
        )
    else:
        resolved_model_config = None

    checks.extend(
        check_model_profile(
            config_path=(
                resolved_model_config
            ),
            profile_name=profile_name,
        )
    )

    return DoctorReport(
        context_mode=context_mode,
        project_root=root,
        working_directory=workdir,
        checks=checks,
        network_accessed=False,
        environment_modified=False,
    )


def render_doctor_report(
    report: DoctorReport,
) -> str:
    """生成终端友好的诊断报告。"""
    lines = [
        "=" * 72,
        "Protein Design Agent Doctor",
        "=" * 72,
        f"运行模式：{report.context_mode}",
        f"诊断根目录：{report.project_root}",
        (
            "工作目录："
            f"{report.working_directory}"
        ),
        "",
    ]

    for check in report.checks:
        lines.append(
            f"[{check.status}] "
            f"{check.name}: "
            f"{check.message}"
        )

        if check.detail:
            lines.append(
                f"       {check.detail}"
            )

    pass_count = sum(
        check.status == "PASS"
        for check in report.checks
    )
    warn_count = sum(
        check.status == "WARN"
        for check in report.checks
    )
    fail_count = sum(
        check.status == "FAIL"
        for check in report.checks
    )

    lines.extend(
        [
            "",
            "-" * 72,
            (
                "总体状态："
                f"{report.overall_status()}"
            ),
            (
                f"PASS={pass_count} "
                f"WARN={warn_count} "
                f"FAIL={fail_count}"
            ),
            "网络访问：否",
            "环境修改：否",
        ]
    )

    return "\n".join(lines)
