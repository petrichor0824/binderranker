#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Protein Design Agent 公开命令行入口。

当前 Local Agent v0.1 支持：

1. validate-model-config
   验证模型配置，不访问网络。

2. plan-mock
   使用固定的模拟模型输出生成 AgentPlan，
   不访问网络，适合测试和公开演示。

3. plan
   使用用户选择的真实模型 Provider 解析自然语言。
   必须显式提供 --allow-network 才能调用模型接口。

当前所有命令都只生成计划：
- 不运行 BinderRanker；
- 不连接服务器；
- 不提交 Slurm；
- 不执行任意 Shell。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import ValidationError

from protein_design_agent.agent.approval import (
    create_approval_record,
)
from protein_design_agent.agent.natural_language_prepare import (
    prepare_from_natural_language,
)
from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
    PlanningSession,
)
from protein_design_agent.agent.plan_materializer import (
    materialize_planning_session,
)
from protein_design_agent.agent.prepare_pipeline import (
    AgentPreparationError,
    prepare_agent_run,
)
from protein_design_agent.agent.provider_factory import (
    build_request_parser_provider,
    resolve_provider_profile,
)
from protein_design_agent.agent.providers.base import (
    ProviderError,
)
from protein_design_agent.agent.providers.mock import (
    MockProvider,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Protein Design Agent："
        "配置驱动、可审核的蛋白骨架排名 Agent。"
    ),
)


def read_user_text(
    *,
    text: Optional[str],
    text_file: Optional[Path],
) -> str:
    """
    从 --text 或 --text-file 读取用户请求。

    两者必须且只能提供一个，避免来源不明确。
    """
    if text is not None and text_file is not None:
        raise ValueError(
            "--text 和 --text-file 不能同时使用"
        )

    if text is None and text_file is None:
        raise ValueError(
            "必须提供 --text 或 --text-file"
        )

    if text_file is not None:
        try:
            content = text_file.read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise ValueError(
                f"无法读取用户请求文件：{exc}"
            ) from exc
    else:
        assert text is not None
        content = text

    content = content.strip()

    if not content:
        raise ValueError(
            "用户请求不能为空"
        )

    return content


def write_planning_session(
    session: PlanningSession,
    output: Path,
) -> Path:
    """将完整规划会话写成可追溯 JSON。"""
    output = output.resolve()
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return output


def print_plan_summary(
    session: PlanningSession,
    output_path: Path,
) -> None:
    """在终端显示简洁的计划摘要。"""
    plan = session.plan

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("Protein Design Agent 规划结果")
    typer.echo("=" * 60)
    typer.echo(
        f"Provider：{session.provider_name}"
    )
    typer.echo(f"状态：{plan.status}")
    typer.echo(
        f"允许自动执行：{plan.execution_allowed}"
    )

    if plan.missing_information:
        typer.echo("缺失信息：")

        for item in plan.missing_information:
            typer.echo(f"  - {item}")

    if plan.warnings:
        typer.echo("提示与警告：")

        for warning in plan.warnings:
            typer.echo(f"  - {warning}")

    if plan.steps:
        typer.echo("计划步骤：")

        for index, step in enumerate(
            plan.steps,
            start=1,
        ):
            approval = (
                "，需要审核"
                if step.requires_approval
                else ""
            )

            typer.echo(
                f"  {index}. {step.description}"
                f" [{step.status}{approval}]"
            )

    typer.echo(f"完整计划：{output_path}")


@app.command("approve-run")
def approve_run_command(
    prepare_manifest: Path = typer.Option(
        ...,
        "--prepare-manifest",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help=(
            "处于 READY_FOR_REVIEW 状态的 "
            "agent_prepare_manifest.json。"
        ),
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        help="批准记录 JSON 输出路径。",
    ),
    approved_by: str = typer.Option(
        ...,
        "--approved-by",
        help=(
            "批准者名称或本地操作员标识。"
            "当前版本不进行身份认证。"
        ),
    ),
    approval_note: str = typer.Option(
        "",
        "--approval-note",
        help="可选的批准说明。",
    ),
    acknowledge_smoke_test: bool = typer.Option(
        False,
        "--acknowledge-smoke-test",
        help=(
            "明确确认 SMOKE_TEST_ONLY 仅用于工程验证，"
            "不能作为正式科研排名。"
        ),
    ),
) -> None:
    """
    为 READY_FOR_REVIEW 任务生成一次 BinderRanker 执行批准。

    本命令会冻结关键配置、Ranker 和标准化 PDB 的 SHA256。

    本命令只生成批准记录，不执行 BinderRanker。
    """
    try:
        record = create_approval_record(
            prepare_manifest_path=prepare_manifest,
            output_path=output,
            approved_by=approved_by,
            approval_note=approval_note,
            acknowledge_smoke_test=(
                acknowledge_smoke_test
            ),
        )
    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"任务批准失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("Protein Design Agent 批准记录")
    typer.echo("=" * 60)
    typer.echo(f"状态：{record.status}")
    typer.echo(f"批准 ID：{record.approval_id}")
    typer.echo(f"批准范围：{record.approval_scope}")
    typer.echo(f"批准者：{record.approved_by}")
    typer.echo(f"项目：{record.project_name}")
    typer.echo(f"Provider：{record.provider_name}")
    typer.echo(
        f"分析级别：{record.analysis_scope_level}"
    )
    typer.echo(
        "已确认小样本限制："
        f"{record.smoke_test_acknowledged}"
    )
    typer.echo(
        "标准化 PDB 数量："
        f"{record.normalized_dataset.pdb_count}"
    )
    typer.echo(
        "数据集指纹："
        f"{record.normalized_dataset.combined_sha256}"
    )
    typer.echo(
        f"Ranker SHA256：{record.ranker_sha256}"
    )
    typer.echo(
        f"批准摘要：{record.approval_digest}"
    )
    typer.echo(f"批准记录：{output.resolve()}")
    typer.echo("")
    typer.echo(
        "当前只生成了批准记录，"
        "没有执行 BinderRanker。"
    )


@app.command("prepare")
def prepare_command(
    model_config: Path = typer.Option(
        ...,
        "--model-config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="模型 Provider YAML 配置。",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        help="用户自然语言请求。",
    ),
    text_file: Optional[Path] = typer.Option(
        None,
        "--text-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="包含用户请求的 UTF-8 文本文件。",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="临时覆盖 active_profile。",
    ),
    bundle_dir: Path = typer.Option(
        ...,
        "--bundle-dir",
        help="本次 Agent 任务的独立档案目录。",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="显式允许访问模型 API。",
    ),
) -> None:
    """
    从自然语言直接准备一个可审核的骨架排名任务。

    信息不足时停在 NEEDS_INFORMATION；
    信息完整时停在 READY_FOR_REVIEW。

    本命令不会真正执行 BinderRanker，
    也不会连接远程服务器。
    """
    try:
        raw_text = read_user_text(
            text=text,
            text_file=text_file,
        )

        config = load_model_provider_config(
            model_config
        )

        selected_name, selected_profile = (
            resolve_provider_profile(
                config,
                profile_name=profile,
            )
        )

    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"Agent 准备参数错误：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"已选择模型 Profile：{selected_name}"
    )
    typer.echo(
        f"模型：{selected_profile.model}"
    )
    typer.echo(
        f"接口：{selected_profile.base_url}"
    )

    if not allow_network:
        typer.echo("")
        typer.echo(
            "BLOCKED：当前未提供 --allow-network。"
        )
        typer.echo(
            "没有访问模型 API，也没有启动科学工作流。"
        )
        raise typer.Exit(code=3)

    try:
        provider = build_request_parser_provider(
            config,
            profile_name=profile,
        )

        result = prepare_from_natural_language(
            raw_text=raw_text,
            provider=provider,
            bundle_dir=bundle_dir,
        )

    except (
        ValueError,
        ProviderError,
        AgentPreparationError,
        ValidationError,
    ) as exc:
        typer.echo(
            f"自然语言准备失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=4) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("Protein Design Agent 结果")
    typer.echo("=" * 60)
    typer.echo(f"状态：{result.status}")
    typer.echo(
        f"Provider：{result.provider_name}"
    )
    typer.echo(
        f"任务目录：{result.bundle_directory}"
    )
    typer.echo(
        f"规划会话：{result.planning_session}"
    )
    typer.echo(
        f"准备 Manifest：{result.prepare_manifest}"
    )

    if result.missing_information:
        typer.echo("仍需补充的信息：")

        for item in result.missing_information:
            typer.echo(f"  - {item}")

    if result.status == "READY_FOR_REVIEW":
        typer.echo(
            f"项目：{result.project_name}"
        )
        typer.echo(
            f"项目配置：{result.project_config}"
        )
        typer.echo(
            f"工作流目录："
            f"{result.workflow_directory}"
        )
        typer.echo(
            f"工作流 Manifest："
            f"{result.workflow_manifest}"
        )

    typer.echo(
        "BinderRanker 已执行："
        f"{result.binderranker_executed}"
    )
    typer.echo(
        "远程后端已使用："
        f"{result.remote_backend_used}"
    )


@app.command("prepare-session")
def prepare_session_command(
    session: Path = typer.Option(
        ...,
        "--session",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="经过验证的 PlanningSession JSON。",
    ),
    bundle_dir: Path = typer.Option(
        ...,
        "--bundle-dir",
        help="本次 Agent 准备任务的独立档案目录。",
    ),
) -> None:
    """
    从审核就绪的 PlanningSession 创建完整准备任务。

    本命令会：
    - 生成正式项目 YAML；
    - 检查并标准化 PDB；
    - 校验冻结 BinderRanker；
    - 生成 Ranker dry-run 计划。

    本命令不会真正执行 BinderRanker，
    也不会连接任何远程服务器。
    """
    try:
        result = prepare_agent_run(
            session_path=session,
            bundle_dir=bundle_dir,
        )
    except (
        ValueError,
        AgentPreparationError,
        ValidationError,
    ) as exc:
        typer.echo(
            f"Agent 准备失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("Protein Design Agent 准备完成")
    typer.echo("=" * 60)
    typer.echo(f"状态：{result.status}")
    typer.echo(f"项目：{result.project_name}")
    typer.echo(f"Provider：{result.provider_name}")
    typer.echo(
        f"任务目录：{result.bundle_directory}"
    )
    typer.echo(
        f"项目配置：{result.project_config}"
    )
    typer.echo(
        f"工作流目录：{result.workflow_directory}"
    )
    typer.echo(
        f"工作流 Manifest："
        f"{result.workflow_manifest}"
    )
    typer.echo(
        f"准备 Manifest：{result.prepare_manifest}"
    )
    typer.echo(
        "BinderRanker 已执行："
        f"{result.binderranker_executed}"
    )
    typer.echo(
        "远程后端已使用："
        f"{result.remote_backend_used}"
    )
    typer.echo("")
    typer.echo(
        "当前任务已停在 READY_FOR_REVIEW，"
        "没有真正执行 BinderRanker。"
    )


@app.command("materialize-plan")
def materialize_plan_command(
    session: Path = typer.Option(
        ...,
        "--session",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Agent 生成的 PlanningSession JSON。",
    ),
    output_config: Path = typer.Option(
        ...,
        "--output-config",
        help="正式项目 YAML 输出路径。",
    ),
    provenance: Optional[Path] = typer.Option(
        None,
        "--provenance",
        help="可选的来源记录 JSON 路径。",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="显式允许覆盖已有输出文件。",
    ),
) -> None:
    """
    将 READY_FOR_REVIEW 计划落地为项目 YAML。

    本命令不运行科学工作流。
    """
    try:
        result = materialize_planning_session(
            session_path=session,
            output_config=output_config,
            provenance_file=provenance,
            overwrite=overwrite,
        )
    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"计划落地失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo("计划落地成功")
    typer.echo(f"状态：{result.status}")
    typer.echo(f"项目：{result.project_name}")
    typer.echo(f"Provider：{result.provider_name}")
    typer.echo(f"项目配置：{result.output_config}")
    typer.echo(f"来源记录：{result.provenance_file}")
    typer.echo(
        f"配置 SHA256："
        f"{result.output_config_sha256}"
    )
    typer.echo("没有执行任何科学工作流。")


@app.command("validate-model-config")
def validate_model_config_command(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="模型 Provider YAML 配置。",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help=(
            "临时选择一个 profile；"
            "默认使用 active_profile。"
        ),
    ),
) -> None:
    """
    验证模型配置。

    本命令不调用模型，也不访问网络。
    """
    try:
        model_config = load_model_provider_config(
            config
        )

        profile_name, selected = (
            resolve_provider_profile(
                model_config,
                profile_name=profile,
            )
        )

    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"模型配置验证失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    key_is_present = False

    if selected.api_key_env is not None:
        key_is_present = bool(
            os.environ.get(selected.api_key_env)
        )

    typer.echo("模型配置验证成功")
    typer.echo(f"配置文件：{config}")
    typer.echo(f"Profile：{profile_name}")
    typer.echo(
        f"Provider 类型：{selected.kind}"
    )
    typer.echo(f"接口地址：{selected.base_url}")
    typer.echo(f"模型名称：{selected.model}")
    typer.echo(
        f"要求 API Key："
        f"{selected.require_api_key}"
    )
    typer.echo(
        f"API Key 环境变量："
        f"{selected.api_key_env}"
    )

    # 只显示是否存在，绝不显示真正的 Key。
    typer.echo(
        f"环境变量当前已设置：{key_is_present}"
    )
    typer.echo("本命令没有访问网络。")


@app.command("plan-mock")
def plan_mock_command(
    payload: Path = typer.Option(
        ...,
        "--payload",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help=(
            "模拟模型返回的 UserRequest JSON。"
        ),
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        help="用户自然语言请求。",
    ),
    text_file: Optional[Path] = typer.Option(
        None,
        "--text-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="包含用户请求的 UTF-8 文本文件。",
    ),
    output: Path = typer.Option(
        Path("runs/agent/mock_plan.json"),
        "--output",
        help="规划会话 JSON 输出位置。",
    ),
) -> None:
    """
    使用 MockProvider 生成规划。

    完全离线，不访问模型 API。
    """
    try:
        raw_text = read_user_text(
            text=text,
            text_file=text_file,
        )

        raw_payload = json.loads(
            payload.read_text(encoding="utf-8")
        )

        if not isinstance(raw_payload, dict):
            raise ValueError(
                "Mock payload 最外层必须是 JSON 对象"
            )

        provider = MockProvider(raw_payload)

        agent = LocalAgentOrchestrator(provider)

        session = agent.plan_from_text(
            raw_text
        )

        output_path = write_planning_session(
            session,
            output,
        )

    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ProviderError,
        ValidationError,
    ) as exc:
        typer.echo(
            f"Mock 规划失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    print_plan_summary(
        session,
        output_path,
    )

    typer.echo("")
    typer.echo(
        "这是 MockProvider 测试，"
        "没有真实大模型参与。"
    )


@app.command("plan")
def plan_command(
    model_config: Path = typer.Option(
        ...,
        "--model-config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="模型 Provider YAML 配置。",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        help="用户自然语言请求。",
    ),
    text_file: Optional[Path] = typer.Option(
        None,
        "--text-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="包含用户请求的 UTF-8 文本文件。",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help=(
            "临时覆盖配置中的 active_profile。"
        ),
    ),
    output: Path = typer.Option(
        Path("runs/agent/agent_plan.json"),
        "--output",
        help="规划会话 JSON 输出位置。",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help=(
            "显式允许调用外部模型 API。"
            "未提供时，命令会安全停止。"
        ),
    ),
) -> None:
    """
    使用真实模型 Provider 解析自然语言并生成计划。

    只生成 AgentPlan，不执行科学工作流。
    """
    try:
        raw_text = read_user_text(
            text=text,
            text_file=text_file,
        )

        config = load_model_provider_config(
            model_config
        )

        selected_name, selected_profile = (
            resolve_provider_profile(
                config,
                profile_name=profile,
            )
        )

    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"规划准备失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(
        f"已选择模型 Profile：{selected_name}"
    )
    typer.echo(
        f"模型：{selected_profile.model}"
    )
    typer.echo(
        f"接口：{selected_profile.base_url}"
    )

    if not allow_network:
        typer.echo("")
        typer.echo(
            "BLOCKED：当前未提供 --allow-network。"
        )
        typer.echo(
            "没有访问模型 API，也没有产生费用。"
        )
        typer.echo(
            "确认模型配置后，显式添加 "
            "--allow-network 才会调用模型。"
        )
        raise typer.Exit(code=3)

    try:
        provider = build_request_parser_provider(
            config,
            profile_name=profile,
        )

        agent = LocalAgentOrchestrator(provider)

        session = agent.plan_from_text(
            raw_text
        )

        output_path = write_planning_session(
            session,
            output,
        )

    except (
        ValueError,
        ProviderError,
        ValidationError,
    ) as exc:
        typer.echo(
            f"真实模型规划失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=4) from exc

    print_plan_summary(
        session,
        output_path,
    )

    typer.echo("")
    typer.echo(
        "模型只生成了规划，"
        "没有执行 BinderRanker 或远程任务。"
    )


if __name__ == "__main__":
    app()
