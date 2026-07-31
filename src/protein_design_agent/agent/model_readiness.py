#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""模型本地就绪状态检查。

这里只检查：
- 用户是否允许联网；
- 配置文件和 Profile 是否有效；
- 所需凭据环境变量是否存在；
- Provider 是否可以在不联网的情况下完成初始化。

不会发送网络请求，也不会输出 API Key 内容。
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from protein_design_agent.agent.provider_factory import (
    build_request_parser_provider,
    resolve_provider_profile,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


ModelReadinessStatus = Literal[
    "OFFLINE",
    "NOT_CONFIGURED",
    "MISSING_CREDENTIAL",
    "READY",
    "ERROR",
]


@dataclass(frozen=True)
class ModelReadinessReport:
    status: ModelReadinessStatus
    message: str

    network_allowed: bool
    config_path: Path | None = None

    profile_name: str | None = None
    model_name: str | None = None
    api_key_env: str | None = None

    provider: RequestParserProvider | None = None


def resolve_model_config_path(
    *,
    explicit_path: Path | None,
    workspace_root: Path | None,
) -> Path | None:
    """
    解析 Chat 使用的模型配置。

    显式参数优先；只有受管默认工作空间才能自动发现。
    外部 Bundle 不猜测配置路径。
    """
    if explicit_path is not None:
        return explicit_path.expanduser().resolve()

    if workspace_root is not None:
        return (
            workspace_root.expanduser().resolve()
            / "configs"
            / "models"
            / "deepseek.local.yaml"
        ).resolve()

    return None


def assess_model_readiness(
    *,
    allow_network: bool,
    config_path: Path | None,
    profile_name: str | None,
    environment: Mapping[str, str] | None = None,
) -> ModelReadinessReport:
    """执行不联网的模型就绪检查。"""
    if not allow_network:
        return ModelReadinessReport(
            status="OFFLINE",
            message=(
                "用户未允许模型联网。"
                "确定性状态查看、规划、批准、执行和分析仍可使用。"
            ),
            network_allowed=False,
            config_path=(
                config_path.resolve()
                if config_path is not None
                else None
            ),
        )

    if config_path is None:
        return ModelReadinessReport(
            status="NOT_CONFIGURED",
            message=(
                "已允许联网，但没有指定模型配置文件。"
                "模型功能暂不可用，确定性功能仍可使用。"
            ),
            network_allowed=True,
        )

    path = config_path.expanduser().resolve()

    if not path.is_file():
        return ModelReadinessReport(
            status="NOT_CONFIGURED",
            message=(
                "模型配置文件不存在："
                f"{path}"
            ),
            network_allowed=True,
            config_path=path,
        )

    try:
        config = load_model_provider_config(path)
        selected_name, selected = (
            resolve_provider_profile(
                config,
                profile_name=profile_name,
            )
        )
    except Exception as exc:
        return ModelReadinessReport(
            status="NOT_CONFIGURED",
            message=(
                "模型配置或 Profile 无法通过验证："
                f"{exc}"
            ),
            network_allowed=True,
            config_path=path,
        )

    env = (
        environment
        if environment is not None
        else os.environ
    )

    key_env = selected.api_key_env

    if selected.require_api_key:
        key_value = (
            env.get(key_env, "")
            if key_env is not None
            else ""
        )

        if not str(key_value).strip():
            return ModelReadinessReport(
                status="MISSING_CREDENTIAL",
                message=(
                    "模型配置有效，但所需 API Key "
                    "环境变量尚未设置。"
                ),
                network_allowed=True,
                config_path=path,
                profile_name=selected_name,
                model_name=selected.model,
                api_key_env=key_env,
            )

    try:
        provider = build_request_parser_provider(
            config,
            profile_name=profile_name,
            environ=env,
        )
    except Exception as exc:
        return ModelReadinessReport(
            status="ERROR",
            message=(
                "模型 Provider 本地初始化失败："
                f"{exc}"
            ),
            network_allowed=True,
            config_path=path,
            profile_name=selected_name,
            model_name=selected.model,
            api_key_env=key_env,
        )

    return ModelReadinessReport(
        status="READY",
        message=(
            "配置、Profile、凭据和 Provider "
            "本地初始化均已通过；尚未发送网络请求。"
        ),
        network_allowed=True,
        config_path=path,
        profile_name=selected_name,
        model_name=selected.model,
        api_key_env=key_env,
        provider=provider,
    )


def format_model_readiness(
    report: ModelReadinessReport,
    *,
    workspace_root: Path | None = None,
) -> str:
    """生成不泄露凭据的启动状态和修复指引。"""
    lines = [
        f"模型状态：{report.status}",
        (
            "网络权限：已显式允许"
            if report.network_allowed
            else "网络权限：未允许"
        ),
    ]

    if report.config_path is not None:
        lines.append(
            f"模型配置：{report.config_path}"
        )

    if report.profile_name is not None:
        lines.append(
            f"模型 Profile：{report.profile_name}"
        )

    if report.model_name is not None:
        lines.append(
            f"模型：{report.model_name}"
        )

    if (
        report.status == "MISSING_CREDENTIAL"
        and report.api_key_env is not None
    ):
        lines.append(
            "缺少环境变量："
            f"{report.api_key_env}"
        )

    lines.append(report.message)

    if report.status == "MISSING_CREDENTIAL":
        env_name = report.api_key_env

        if (
            env_name is not None
            and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                env_name,
            )
        ):
            lines.extend([
                "",
                "修复步骤：",
                "1. 退出当前 Chat。",
                "2. 在同一终端运行：",
                (
                    "   read -rsp 'API Key: ' "
                    f"{env_name}; echo; "
                    f"export {env_name}"
                ),
            ])

            if workspace_root is not None:
                restart = (
                    "protein-design-agent chat "
                    "--allow-network"
                )

                if report.profile_name is not None:
                    restart += (
                        " --profile "
                        + shlex.quote(
                            report.profile_name
                        )
                    )

                lines.extend([
                    "3. 重新启动：",
                    f"   {restart}",
                ])
            elif report.config_path is not None:
                lines.extend([
                    "3. 重启原 Chat 命令，并保留原 "
                    "--bundle-dir，同时加入：",
                    (
                        "   --allow-network "
                        "--model-config "
                        + shlex.quote(
                            str(report.config_path)
                        )
                    ),
                ])
        else:
            lines.extend([
                "",
                "配置中的 API Key 环境变量名称无效，"
                "请先修正模型 YAML。",
            ])

    elif report.status == "NOT_CONFIGURED":
        lines.append("")

        if report.config_path is not None:
            config_argument = shlex.quote(
                str(report.config_path)
            )

            lines.extend([
                "请检查该配置文件，并运行：",
                (
                    "   protein-design-agent doctor "
                    f"--model-config {config_argument}"
                ),
            ])
        else:
            lines.extend([
                "当前使用外部 Bundle，无法安全推断"
                "模型配置路径。",
                "重启时请显式加入：",
                "   --model-config 你的模型配置文件",
            ])

    elif (
        report.status == "OFFLINE"
        and workspace_root is not None
    ):
        lines.extend([
            "",
            "需要模型功能时，重新启动：",
            "   protein-design-agent chat --allow-network",
        ])

    return "\n".join(lines)
