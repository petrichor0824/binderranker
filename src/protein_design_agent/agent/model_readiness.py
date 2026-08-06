#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""模型本地配置检查和会话授权状态管理。

本模块分两步处理模型可用性：
- 检查配置文件、Profile、API Key 环境变量和 Provider；
- 将本地配置状态与本次 Chat 的联网授权组合。

所有检查均不会发送网络请求，也不会输出 API Key 内容。
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

ModelSetupStatus = Literal[
    "NOT_CONFIGURED",
    "MISSING_CREDENTIAL",
    "AVAILABLE",
    "ERROR",
]



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

@dataclass(frozen=True)
class ModelSetupReport:
    """不涉及联网授权的模型本地配置状态。"""

    status: ModelSetupStatus
    message: str

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


def assess_model_setup(
    *,
    config_path: Path | None,
    profile_name: str | None,
    environment: Mapping[str, str] | None = None,
) -> ModelSetupReport:
    """
    检查配置、Profile、凭据和 Provider 本地初始化。

    本函数不请求用户授权，也不会发送网络请求。
    """
    if config_path is None:
        return ModelSetupReport(
            status="NOT_CONFIGURED",
            message=(
                "没有指定模型配置文件。"
                "模型功能暂不可用，"
                "确定性功能仍可使用。"
            ),
        )

    path = config_path.expanduser().resolve()

    if not path.is_file():
        return ModelSetupReport(
            status="NOT_CONFIGURED",
            message=(
                "模型配置文件不存在："
                f"{path}"
            ),
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
        return ModelSetupReport(
            status="NOT_CONFIGURED",
            message=(
                "模型配置或 Profile 无法通过验证："
                f"{exc}"
            ),
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
            return ModelSetupReport(
                status="MISSING_CREDENTIAL",
                message=(
                    "模型配置有效，但所需 API Key "
                    "环境变量尚未设置。"
                ),
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
        return ModelSetupReport(
            status="ERROR",
            message=(
                "模型 Provider 本地初始化失败："
                f"{exc}"
            ),
            config_path=path,
            profile_name=selected_name,
            model_name=selected.model,
            api_key_env=key_env,
        )

    return ModelSetupReport(
        status="AVAILABLE",
        message=(
            "配置、Profile、凭据和 Provider "
            "本地初始化均已通过；"
            "尚未发送网络请求。"
        ),
        config_path=path,
        profile_name=selected_name,
        model_name=selected.model,
        api_key_env=key_env,
        provider=provider,
    )


def assess_model_readiness(
    *,
    allow_network: bool,
    config_path: Path | None,
    profile_name: str | None,
    environment: Mapping[str, str] | None = None,
) -> ModelReadinessReport:
    """
    兼容旧调用方式，组合本地配置检查和联网授权。

    未授权联网时保持离线状态，不初始化模型 Provider。
    """
    if not allow_network:
        return ModelReadinessReport(
            status="OFFLINE",
            message=(
                "用户未允许模型联网。"
                "已有任务的确定性状态查看、批准、"
                "执行和分析仍可使用；"
                "空任务的自然语言创建需要启用模型。"
            ),
            network_allowed=False,
            config_path=(
                config_path.expanduser().resolve()
                if config_path is not None
                else None
            ),
        )

    setup = assess_model_setup(
        config_path=config_path,
        profile_name=profile_name,
        environment=environment,
    )

    return finalize_model_readiness(
        setup,
        network_allowed=True,
    )


def finalize_model_readiness(
    setup: ModelSetupReport,
    *,
    network_allowed: bool,
) -> ModelReadinessReport:
    """把本地配置状态和本次会话授权组合成最终状态。"""
    if setup.status == "AVAILABLE":
        if network_allowed:
            return ModelReadinessReport(
                status="READY",
                message=setup.message,
                network_allowed=True,
                config_path=setup.config_path,
                profile_name=setup.profile_name,
                model_name=setup.model_name,
                api_key_env=setup.api_key_env,
                provider=setup.provider,
            )

        return ModelReadinessReport(
            status="OFFLINE",
            message=(
                "模型配置、凭据和 Provider 已就绪，"
                "但用户未允许本次会话联网。"
                "已有任务的确定性功能仍可使用；"
                "空任务的自然语言创建需要启用模型。"
            ),
            network_allowed=False,
            config_path=setup.config_path,
            profile_name=setup.profile_name,
            model_name=setup.model_name,
            api_key_env=setup.api_key_env,
            provider=None,
        )

    status_map: dict[
        ModelSetupStatus,
        ModelReadinessStatus,
    ] = {
        "NOT_CONFIGURED": "NOT_CONFIGURED",
        "MISSING_CREDENTIAL": "MISSING_CREDENTIAL",
        "ERROR": "ERROR",
    }

    return ModelReadinessReport(
        status=status_map[setup.status],
        message=setup.message,
        network_allowed=network_allowed,
        config_path=setup.config_path,
        profile_name=setup.profile_name,
        model_name=setup.model_name,
        api_key_env=setup.api_key_env,
        provider=None,
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
                (
                    "2. 在同一终端复制并运行"
                    "下面的整行命令："
                ),
                (
                    "   read -rsp "
                    "'请粘贴真实 API Key，然后按回车"
                    "（输入不会显示）：' "
                    f"{env_name} && echo && "
                    f"export {env_name}"
                ),
                (
                    "3. 终端出现提示后，粘贴真实 "
                    "API Key 并按回车。"
                ),
                (
                    "   输入过程中不会显示字符，"
                    "这是正常的安全行为。"
                ),
                (
                    "   不要修改命令末尾的 "
                    f"{env_name}；它是环境变量名，"
                    "不是填写 API Key 的位置。"
                ),
                (
                    "4. 不需要再运行其他 "
                    "API Key 设置命令。"
                ),
            ])

            if workspace_root is not None:
                restart = "protein-design-agent chat"

                if report.profile_name is not None:
                    restart += (
                        " --profile "
                        + shlex.quote(
                            report.profile_name
                        )
                    )

                lines.extend([
                    "5. 重新启动普通 Chat：",
                    f"   {restart}",
                    (
                        "   启动后，Agent 会询问"
                        "是否允许本次 Chat 调用模型 API。"
                    ),
                ])
            elif report.config_path is not None:
                config_argument = shlex.quote(
                    str(report.config_path)
                )

                lines.extend([
                    (
                        "5. 重启原 Chat 命令，"
                        "保留原 --bundle-dir，并加入："
                    ),
                    (
                        "   --model-config "
                        f"{config_argument}"
                    ),
                    (
                        "   启动后，Agent 会询问"
                        "是否允许本次 Chat 调用模型 API。"
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
            "当前会话使用离线确定性模式。",
            (
                "下次运行 protein-design-agent chat 时，"
                "如果模型配置和 API Key 已就绪，"
            ),
            (
                "Agent 会再次询问是否允许"
                "本次 Chat 调用模型 API。"
            ),
        ])

    return "\n".join(lines)
