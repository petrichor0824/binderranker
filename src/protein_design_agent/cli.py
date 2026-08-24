#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 公开命令行入口。

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
import sys
import tempfile
import os
from importlib.metadata import (
    PackageNotFoundError,
    version as distribution_version,
)
from pathlib import Path
from typing import Any, Optional

import typer

from protein_design_agent.agent.chat_dialogue import (
    ChatDialogueError,
    process_dialogue_message,
)
from protein_design_agent.cli_defaults import (
    resolve_chat_target,
    resolve_local_approved_by,
)
from protein_design_agent.agent.chat_session import (
    ChatSessionError,
)
from protein_design_agent.agent.error_guidance import (
    format_error_guidance,
)

from protein_design_agent.agent.run_status import (
    RunStatusError,
    inspect_run_status,
)
from protein_design_agent.agent.user_language import (
    format_user_progress,
    plan_step_status_label,
    translate_internal_terms,
    user_scope,
    user_status,
)

from protein_design_agent.agent.local_executor import (
    LocalExecutionError,
    execute_approved_binderranker,
)

from protein_design_agent.agent.analyze_run import (
    run_analyze_run,
)

from protein_design_agent.agent.explain_run import (
    ExplainRunError,
    run_explain_run,
)
from pydantic import ValidationError

from protein_design_agent.agent.approval import (
    create_approval_record,
)
from protein_design_agent.agent.natural_language_prepare import (
    NaturalLanguagePreparationError,
    prepare_from_natural_language,
)
from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.plan_materializer import (
    PlanMaterializationError,
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
from protein_design_agent.agent.model_readiness import (
    assess_model_setup,
    finalize_model_readiness,
    format_model_readiness,
    resolve_model_config_path,
)
from protein_design_agent.agent.onboarding import (
    format_first_chat_guidance,
    task_is_empty,
)
from protein_design_agent.agent.session_recovery import (
    collect_task_recovery_snapshot,
    format_task_recovery_summary,
)
from protein_design_agent.public_identity import (
    AGENT_NAME,
    PROJECT_NAME,
    SHORT_DESCRIPTION_ZH,
)
from protein_design_agent.schemas.provider_config import (
    load_model_provider_config,
)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        f"{PROJECT_NAME}：{SHORT_DESCRIPTION_ZH}"
    ),
)


def configure_cli_streams() -> None:
    """让重定向的 Windows CLI 输出稳定支持 Unicode。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(
            stream,
            "reconfigure",
            None,
        )

        if not callable(reconfigure):
            continue

        try:
            reconfigure(
                encoding="utf-8",
                errors="replace",
            )
        except (
            AttributeError,
            OSError,
            ValueError,
        ):
            # 测试捕获流或宿主包装流可能不允许重配置。
            continue


def main() -> None:
    """配置安全的文本流后启动公开 CLI。"""
    configure_cli_streams()
    app()


def resolve_cli_version() -> str:
    """读取当前安装的 BinderRanker distribution 版本。"""
    try:
        return distribution_version("binderranker")
    except PackageNotFoundError:
        return "unknown"


def version_callback(value: bool) -> None:
    """显示安装版本并正常退出。"""
    if not value:
        return

    typer.echo(
        f"{PROJECT_NAME} {resolve_cli_version()}"
    )
    raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="显示 BinderRanker 安装版本并退出。",
    ),
) -> None:
    """BinderRanker 根级命令选项。"""


class CLIInputError(ValueError):
    """
    CLI 用户输入错误。

    继续继承 ValueError 保持现有兼容性；
    public_message 仅包含可安全展示的确定事实。
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


class PlanningOutputError(ValueError):
    """
    CLI 规划输出错误。

    继续继承 ValueError 保持现有兼容性；
    public_message 只包含可安全展示的确定事实。
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
        raise CLIInputError(
            "--text 和 --text-file 不能同时使用",
            public_message=(
                "--text 和 --text-file "
                "不能同时使用。"
            ),
        )

    if text is None and text_file is None:
        raise CLIInputError(
            "必须提供 --text 或 --text-file",
            public_message=(
                "必须提供 --text 或 --text-file。"
            ),
        )

    if text_file is not None:
        try:
            content = text_file.read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise CLIInputError(
                f"无法读取用户请求文件：{exc}",
                public_message=(
                    "用户请求文件无法读取。"
                ),
            ) from exc
    else:
        assert text is not None
        content = text

    content = content.strip()

    if not content:
        raise CLIInputError(
            "用户请求不能为空",
            public_message=(
                "用户请求不能为空。"
            ),
        )

    return content


def write_planning_session(
    session: PlanningSession,
    output: Path,
) -> Path:
    """
    原子写入完整 PlanningSession。

    正式输出在 staging 文件完成写入和结构验证后
    才通过 replace 发布。
    """
    output = output.resolve()
    staged: Path | None = None

    try:
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{output.name}.planning-",
            dir=str(output.parent),
            delete=False,
        ) as handle:
            staged = Path(handle.name)
            handle.write(
                session.model_dump_json(
                    indent=2
                )
            )

        reloaded = (
            PlanningSession.model_validate_json(
                staged.read_text(
                    encoding="utf-8"
                )
            )
        )

        if (
            reloaded.model_dump(mode="json")
            != session.model_dump(mode="json")
        ):
            raise PlanningOutputError(
                "PlanningSession staging "
                "写入前后不一致",
                public_message=(
                    "规划会话输出未通过"
                    "一致性验证，因此没有发布。"
                ),
            )

        staged.replace(output)
        staged = None

        return output

    except PlanningOutputError:
        raise

    except (
        OSError,
        ValidationError,
    ) as exc:
        raise PlanningOutputError(
            "PlanningSession 输出失败："
            f"{exc}",
            public_message=(
                "规划会话输出文件写入或验证失败。"
            ),
        ) from exc

    finally:
        if staged is not None:
            try:
                staged.unlink(
                    missing_ok=True
                )
            except OSError:
                pass


def print_plan_summary(
    session: PlanningSession,
    output_path: Path,
) -> None:
    """在终端显示简洁的计划摘要。"""
    plan = session.plan

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"{PROJECT_NAME} 规划结果")
    typer.echo("=" * 60)
    typer.echo(
        f"Provider：{session.provider_name}"
    )
    typer.echo(
        "状态："
        + user_status(
            plan.status,
            area="prepare",
        )
    )
    typer.echo(
        "允许自动执行："
        + (
            "是"
            if plan.execution_allowed
            else "否"
        )
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
                " ["
                + plan_step_status_label(
                    step.status
                )
                + approval
                + "]"
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
    except (
        ValueError,
        ValidationError,
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = "任务批准未完成。"

        guidance = format_error_guidance(
            kind="REJECTED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "BinderRanker 执行：否；"
            "本命令只生成批准记录。",
            err=True,
        )

        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"{PROJECT_NAME} 批准记录")
    typer.echo("=" * 60)
    typer.echo(
        "状态："
        + user_status(
            record.status,
            area="approval",
        )
    )
    typer.echo(f"批准 ID：{record.approval_id}")
    typer.echo(f"批准范围：{record.approval_scope}")
    typer.echo(f"批准者：{record.approved_by}")
    typer.echo(f"项目：{record.project_name}")
    typer.echo(f"Provider：{record.provider_name}")
    typer.echo(
        "结果使用范围："
        + user_scope(
            record.analysis_scope_level
        )
    )
    typer.echo(
        "已确认小样本限制："
        + (
            "是"
            if record.smoke_test_acknowledged
            else "否"
        )
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

    except (
        ValueError,
        ValidationError,
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = (
                "自然语言任务的输入或"
                "模型配置无法用于本次准备。"
            )

        guidance = format_error_guidance(
            kind="REJECTED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：尚未调用模型 API，"
            "也没有启动科学工作流。",
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
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            if isinstance(exc, ProviderError):
                public_message = (
                    "模型请求或响应处理"
                    "没有成功完成。"
                )
            else:
                public_message = (
                    "自然语言任务准备未完成。"
                )

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=bundle_dir,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：本命令只授权模型解析"
            "和任务准备，不授权执行 BinderRanker，"
            "也不使用远程科学计算后端。",
            err=True,
        )

        raise typer.Exit(code=4) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"{PROJECT_NAME} 结果")
    typer.echo("=" * 60)
    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="prepare",
        )
    )
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
        + (
            "是"
            if result.binderranker_executed
            else "否"
        )
    )
    typer.echo(
        "远程后端已使用："
        + (
            "是"
            if result.remote_backend_used
            else "否"
        )
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
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = "Agent 准备未完成。"

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=bundle_dir,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：本命令仅用于准备任务，"
            "不授权执行 BinderRanker，"
            "也不使用远程后端。",
            err=True,
        )

        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"{PROJECT_NAME} 准备完成")
    typer.echo("=" * 60)
    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="prepare",
        )
    )
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
        + (
            "是"
            if result.binderranker_executed
            else "否"
        )
    )
    typer.echo(
        "远程后端已使用："
        + (
            "是"
            if result.remote_backend_used
            else "否"
        )
    )
    typer.echo("")
    typer.echo(
        "当前任务计划已准备完成，等待审核和批准，"
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
    except (
        ValueError,
        ValidationError,
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = "计划落地未完成。"

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：本命令只生成项目配置"
            "和来源记录，不运行科学工作流，"
            "也不执行 BinderRanker。",
            err=True,
        )

        raise typer.Exit(code=2) from exc

    typer.echo("计划落地成功")
    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="prepare",
        )
    )
    typer.echo(f"项目：{result.project_name}")
    typer.echo(f"Provider：{result.provider_name}")
    typer.echo(f"项目配置：{result.output_config}")
    typer.echo(f"来源记录：{result.provenance_file}")
    typer.echo(
        f"配置 SHA256："
        f"{result.output_config_sha256}"
    )
    typer.echo("没有执行任何科学工作流。")






def stdin_is_interactive() -> bool:
    """判断当前标准输入是否支持交互式授权。"""
    try:
        return bool(sys.stdin.isatty())
    except (
        AttributeError,
        OSError,
        ValueError,
    ):
        return False


def resolve_chat_network_permission(
    *,
    explicit_allow_network: bool,
    setup_status: str,
) -> bool:
    """
    决定本次 Chat 会话是否允许调用模型。

    --allow-network 表示已由高级用户显式授权；
    普通交互式启动则在本地模型就绪后询问一次。
    """
    if explicit_allow_network:
        return True

    if setup_status != "AVAILABLE":
        return False

    if not stdin_is_interactive():
        return False

    return typer.confirm(
        (
            "检测到模型配置和 API Key 已就绪。"
            "是否允许本次 Chat 调用模型 API？"
            "这可能产生网络请求和 API 费用"
        ),
        default=False,
        abort=False,
    )


@app.command("chat")
def chat_command(
    bundle_dir: Path | None = typer.Option(
        None,
        "--bundle-dir",
        help=(
            "本次任务的 Bundle 目录。"
            "未提供时使用当前目录下的安全默认工作空间。"
        ),
    ),
    task_name: str | None = typer.Option(
        None,
        "--task",
        help=(
            "默认工作空间中的任务名称。"
            "每个任务拥有独立计划、批准、执行和结果。"
        ),
    ),
    approved_by: str | None = typer.Option(
        None,
        "--approved-by",
        help=(
            "本地批准者标识。"
            "未提供时使用当前系统用户名；"
            "该标识不代表身份认证。"
        ),
    ),
    model_config: Path | None = typer.Option(
        None,
        "--model-config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help=(
            "模型 Provider YAML 配置。"
            "默认工作空间未提供时会自动使用 "
            "configs/models/deepseek.local.yaml；"
            "外部 Bundle 需要显式提供。"
        ),
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="临时覆盖模型 active_profile。",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help=(
            "显式允许访问模型 API。"
            "批准、执行和确定性分析本身不依赖模型。"
        ),
    ),
) -> None:
    """
    启动 BinderRanker Agent 安全自然语言会话。

    大模型负责理解自然语言和生成受控解释，
    不生成或执行 Shell。
    批准与执行由确定性安全控制器校验，
    并在产生副作用前要求用户明确确认。
    """
    try:
        chat_target = resolve_chat_target(
            bundle_dir=bundle_dir,
            task_name=task_name,
        )
    except (
        ValueError,
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if (
            bundle_dir is not None
            and task_name is not None
        ):
            public_message = (
                "--bundle-dir 与 --task "
                "不能同时使用。"
            )

        elif not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            if isinstance(exc, ValueError):
                public_message = (
                    "Chat 任务选择参数无效。"
                    "请检查任务名称和目标路径。"
                )
            else:
                public_message = (
                    "Chat 任务目标无法安全解析。"
                )

        guidance = format_error_guidance(
            kind="REJECTED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：尚未进入模型 API 调用，"
            "也没有执行 BinderRanker。",
            err=True,
        )

        raise typer.Exit(code=2) from exc

    resolved_bundle = chat_target.bundle_dir
    resolved_task_name = chat_target.task_name

    resolved_approved_by = (
        resolve_local_approved_by(
            approved_by
        )
    )

    workspace_report = None
    workspace_root = None

    if chat_target.uses_default_workspace:
        from protein_design_agent.agent.workspace_init import (
            WorkspaceInitError,
            ensure_workspace,
        )

        workspace_root = (
            chat_target.workspace_dir
        )

        try:
            if workspace_root is None:
                raise RuntimeError(
                    "默认工作空间解析结果缺少根目录"
                )

            workspace_report = ensure_workspace(
                workspace_root
            )
            resolved_bundle.mkdir(
                parents=True,
                exist_ok=True,
            )

        except Exception as exc:
            public_message = getattr(
                exc,
                "public_message",
                None,
            )

            if not (
                isinstance(public_message, str)
                and public_message.strip()
            ):
                public_message = (
                    "默认工作空间没有成功初始化。"
                    "请检查当前目录和文件系统权限后重试。"
                )

            guidance = format_error_guidance(
                kind="FAILED",
                error=exc,
                bundle_dir=None,
                provider=None,
                public_message_override=(
                    public_message
                ),
            )

            typer.echo(
                guidance,
                err=True,
            )
            typer.echo("", err=True)
            typer.echo(
                "执行边界：Chat 尚未进入模型 API "
                "调用或科学工作流；"
                "BinderRanker 没有执行。",
                err=True,
            )

            raise typer.Exit(
                code=2
            ) from exc

    resolved_model_config = resolve_model_config_path(
        explicit_path=model_config,
        workspace_root=workspace_root,
    )

    model_setup = assess_model_setup(
        config_path=resolved_model_config,
        profile_name=profile,
    )

    session_network_allowed = (
        resolve_chat_network_permission(
            explicit_allow_network=allow_network,
            setup_status=model_setup.status,
        )
    )

    model_readiness = finalize_model_readiness(
        model_setup,
        network_allowed=session_network_allowed,
    )


    provider = model_readiness.provider
    model_calls_enabled = (
        model_readiness.status == "READY"
    )

    typer.echo(
        format_model_readiness(
            model_readiness,
            workspace_root=workspace_root,
        )
    )

    typer.echo("")
    typer.echo("=" * 72)
    typer.echo(f"{AGENT_NAME} Chat")
    typer.echo("=" * 72)
    if workspace_root is not None:
        typer.echo(
            f"工作空间：{workspace_root}"
        )

        workspace_status_text = {
            "CREATED": "已自动创建",
            "REUSED": "已存在，安全复用",
            "REUSED_LEGACY": (
                "已识别旧版工作空间，安全复用"
            ),
        }.get(
            workspace_report.status,
            workspace_report.status,
        )

        typer.echo(
            "工作空间状态："
            f"{workspace_status_text}"
        )

    typer.echo(
        f"当前任务：{resolved_task_name}"
    )
    typer.echo(
        f"Bundle：{resolved_bundle}"
    )
    typer.echo(
        "本地审计标识："
        f"{resolved_approved_by}"
    )
    typer.echo(
        "输入“帮助”查看操作；"
        "输入“退出”结束会话。"
    )
    typer.echo(
        "你可以直接使用自然语言。"
        "批准、执行和模型解释等动作会先复述影响，"
        "再等待你确认。"
    )

    current_task_is_empty = task_is_empty(
        resolved_bundle
    )

    first_chat_guidance = (
        format_first_chat_guidance(
            task_empty=current_task_is_empty,
            model_status=(
                model_readiness.status
            ),
            uses_default_workspace=(
                chat_target.uses_default_workspace
            ),
            workspace_status=(
                workspace_report.status
                if workspace_report is not None
                else None
            ),
        )
    )

    if first_chat_guidance is not None:
        typer.echo("")
        typer.echo(first_chat_guidance)
    elif not current_task_is_empty:
        recovery_snapshot = (
            collect_task_recovery_snapshot(
                resolved_bundle
            )
        )
        typer.echo("")
        typer.echo(
            format_task_recovery_summary(
                recovery_snapshot,
                model_status=(
                    model_readiness.status
                ),
            )
        )

    exit_commands = {
        "退出",
        "exit",
        "quit",
        "/exit",
        "/quit",
    }

    while True:
        try:
            message = typer.prompt(
                "\n你",
                prompt_suffix=" > ",
            )

        except (
            EOFError,
            KeyboardInterrupt,
            typer.Abort,
        ):
            typer.echo("")
            typer.echo(
                "会话已结束。"
            )
            break

        clean = message.strip()

        if clean.lower() in exit_commands:
            typer.echo(
                "会话已结束。"
            )
            break

        try:
            result = process_dialogue_message(
                message=clean,
                bundle_dir=resolved_bundle,
                provider=provider,
                approved_by=(
                    resolved_approved_by
                ),
                model_config_path=(
                    resolved_model_config
                ),
                profile_name=profile,
                allow_network=model_calls_enabled,
            )

            resolved_bundle = (
                result.bundle_dir.resolve()
            )

        except (
            ChatDialogueError,
            ChatSessionError,
        ) as exc:
            guidance = format_error_guidance(
                kind="REJECTED",
                error=exc,
                bundle_dir=resolved_bundle,
                provider=(
                    provider
                    if model_calls_enabled
                    else None
                ),
            )
            typer.echo("")
            typer.echo("Agent >")
            typer.echo(guidance, err=True)
            continue

        except Exception as exc:
            guidance = format_error_guidance(
                kind="FAILED",
                error=exc,
                bundle_dir=resolved_bundle,
                provider=(
                    provider
                    if model_calls_enabled
                    else None
                ),
            )
            typer.echo("")
            typer.echo("Agent >")
            typer.echo(guidance, err=True)
            continue

        typer.echo("")
        typer.echo("Agent >")
        typer.echo(result.message)

        if result.artifact_paths:
            typer.echo("")
            typer.echo("相关产物：")

            for name, artifact_path in (
                result.artifact_paths.items()
            ):
                typer.echo(
                    f"  - {name}: {artifact_path}"
                )


@app.command("run-status")
def run_status_command(
    bundle_dir: Path = typer.Option(
        ...,
        "--bundle-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help=f"要检查的 {PROJECT_NAME} bundle。",
    ),
) -> None:
    """
    只读显示任务当前所处阶段。

    本命令不会执行 Ranker、不会联网，也不会修改文件。
    """
    try:
        report = inspect_run_status(
            bundle_dir
        )

    except RunStatusError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=bundle_dir,
            provider=None,
            public_message_override=(
                "任务状态检查未完成。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    def show_bool(
        value: bool | None,
        *,
        true_text: str,
        false_text: str,
    ) -> str:
        if value is True:
            return true_text

        if value is False:
            return false_text

        return "未知"

    typer.echo("=" * 72)
    typer.echo(f"{PROJECT_NAME} 任务状态")
    typer.echo("=" * 72)

    typer.echo(
        f"项目：{report.project_name}"
    )
    typer.echo(
        f"Bundle：{report.bundle_dir}"
    )
    typer.echo(
        "当前进度："
        + user_status(
            report.current_stage,
            area="stage",
        )
    )

    typer.echo("")
    typer.echo("进度明细")
    typer.echo("-" * 72)

    progress = format_user_progress(
        {
            "current_stage": report.current_stage,
            "prepare_status": report.prepare_status,
            "approval_status": report.approval_status,
            "execution_status": report.execution_status,
            "analysis_status": report.analysis_status,
            "explanation_status": (
                report.explanation_status
            ),
        },
        include_explanation=True,
    )

    for line in progress[1:]:
        typer.echo(line)

    typer.echo("")
    typer.echo("任务属性")
    typer.echo("-" * 72)

    typer.echo(
        "结果使用范围："
        + user_scope(
            report.analysis_scope_level
        )
    )

    typer.echo(
        "批准 ID："
        f"{report.approval_id or '未发现'}"
    )

    typer.echo(
        "一次性批准："
        + show_bool(
            report.approval_consumed,
            true_text="已消耗",
            false_text="尚未消耗",
        )
    )

    typer.echo(
        "候选数量："
        + (
            str(report.candidate_count)
            if report.candidate_count
            is not None
            else "未知"
        )
    )

    typer.echo(
        "正式候选推荐："
        + show_bool(
            report
            .formal_candidate_recommendation_allowed,
            true_text="允许",
            false_text="不允许",
        )
    )

    typer.echo(
        "动态阈值正式解释："
        + show_bool(
            report
            .thresholds_formally_interpretable,
            true_text="允许",
            false_text="不允许",
        )
    )

    if report.analysis_attempts:
        typer.echo("")
        typer.echo("分析尝试")
        typer.echo("-" * 72)

        for attempt in report.analysis_attempts:
            used_model = show_bool(
                attempt.with_model,
                true_text="是",
                false_text="否",
            )

            typer.echo(
                f"- {attempt.manifest_path.parent.name}: "
                + user_status(
                    attempt.status,
                    area="analysis",
                )
                + f"；调用模型：{used_model}；"
                + "Provider："
                + (attempt.provider_name or "无")
                + "；模型解释："
                + user_status(
                    attempt.explanation_status,
                    area="explanation",
                )
            )

    if report.warnings:
        typer.echo("")
        typer.echo("警告")
        typer.echo("-" * 72)

        for warning in report.warnings:
            typer.echo(
                "- "
                + translate_internal_terms(
                    warning
                )
            )


@app.command("execute-run")
def execute_run_command(
    approval: Path = typer.Option(
        ...,
        "--approval",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help=(
            "approve-run 生成的一次性批准文件。"
        ),
    ),
    confirm_execute: bool = typer.Option(
        False,
        "--confirm-execute",
        help=(
            "显式确认在本机执行 BinderRanker。"
        ),
    ),
) -> None:
    """
    根据一次性批准在本机执行 BinderRanker。

    执行前会重新检查批准摘要、关键文件、
    标准化数据集、Ranker 哈希和输出状态。
    """
    if not confirm_execute:
        typer.echo(
            "ERROR：本地执行需要显式传入 "
            "--confirm-execute",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = execute_approved_binderranker(
            approval_path=approval,
            confirm_execute=True,
        )

    except LocalExecutionError as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )
        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = (
                "BinderRanker 执行未完成。"
            )

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )

        manifest = getattr(
            exc,
            "execution_manifest",
            None,
        )

        if manifest is not None:
            typer.echo("", err=True)
            typer.echo(
                "恢复信息：",
                err=True,
            )
            typer.echo(
                f"执行清单：{manifest}",
                err=True,
            )

        raise typer.Exit(code=1) from exc

    except Exception as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                "BinderRanker 执行未完成。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    typer.echo("=" * 72)
    typer.echo("BinderRanker 本地执行完成")
    typer.echo("=" * 72)

    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="execution",
        )
    )
    typer.echo(
        f"项目：{result.project_name}"
    )
    typer.echo(
        f"批准 ID：{result.approval_id}"
    )
    typer.echo(
        f"返回码：{result.return_code}"
    )
    typer.echo(
        f"输出前缀：{result.output_prefix}"
    )
    typer.echo(
        f"标准输出日志：{result.stdout_log}"
    )
    typer.echo(
        f"标准错误日志：{result.stderr_log}"
    )
    typer.echo(
        f"执行清单：{result.execution_manifest}"
    )
    typer.echo(
        f"输出文件数量：{len(result.output_files)}"
    )

    for item in result.output_files:
        typer.echo(
            f"  - {item.path}"
        )

    typer.echo("")
    typer.echo(
        "该批准已经消耗，不能再次使用。"
    )
    typer.echo(
        "下一步使用 analyze-run 解析和解释结果。"
    )


@app.command("analyze-run")
def analyze_run_command(
    bundle_dir: Path = typer.Option(
        ...,
        "--bundle-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="已经完成 BinderRanker 执行的 bundle。",
    ),
    analysis_dir: Path = typer.Option(
        Path("analyses/analysis_v1"),
        "--analysis-dir",
        help=(
            "分析输出目录；相对路径按 bundle 解析。"
        ),
    ),
    with_model: bool = typer.Option(
        False,
        "--with-model",
        help="在确定性分析后调用受控大模型解释。",
    ),
    model_config: Path | None = typer.Option(
        None,
        "--model-config",
        help="模型 Provider 配置文件。",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="模型配置中的 Profile 名。",
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help="显式允许真实模型 API 调用。",
    ),
    max_output_tokens: int = typer.Option(
        8192,
        "--max-output-tokens",
        min=128,
        max=100000,
    ),
    timeout_seconds: float = typer.Option(
        180.0,
        "--timeout-seconds",
        min=1.0,
        max=600.0,
    ),
) -> None:
    """
    解析、分析并可选解释已完成的 Ranker 运行。

    本命令不会重新执行 BinderRanker。
    """
    try:
        result = run_analyze_run(
            bundle_dir=bundle_dir,
            analysis_dir=analysis_dir,
            with_model=with_model,
            model_config_path=model_config,
            profile_name=profile,
            allow_network=allow_network,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    except Exception as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=bundle_dir,
            provider=None,
            public_message_override=(
                "结果分析未完成。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    typer.echo("=" * 72)
    typer.echo("Ranker 结果分析完成")
    typer.echo("=" * 72)
    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="analysis",
        )
    )
    typer.echo(f"Bundle：{result.bundle_dir}")
    typer.echo(f"分析目录：{result.analysis_dir}")
    typer.echo(f"分析清单：{result.manifest_path}")
    typer.echo(
        f"结果摘要：{result.result_summary_path}"
    )
    typer.echo(
        f"失败分析：{result.failure_analysis_path}"
    )
    typer.echo(
        "确定性报告："
        f"{result.deterministic_report_path}"
    )
    typer.echo(
        "启用模型："
        + (
            "是"
            if result.with_model
            else "否"
        )
    )

    if result.with_model:
        typer.echo(
            f"Provider：{result.provider_name}"
        )
        typer.echo(
            "模型报告："
            f"{result.explanation_markdown_path}"
        )


@app.command("explain-run")
def explain_run_command(
    bundle_dir: Path = typer.Option(
        ...,
        "--bundle-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help=(
            "已完成执行和结果解析的 Agent bundle。"
        ),
    ),
    model_config: Path = typer.Option(
        ...,
        "--model-config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="模型 Provider 配置文件。",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help=(
            "模型配置中的 Profile 名；"
            "省略时使用配置默认值。"
        ),
    ),
    output_dir: Path = typer.Option(
        Path("explanations/cli_v1"),
        "--output-dir",
        help=(
            "解释输出目录。相对路径按 bundle 解析。"
        ),
    ),
    allow_network: bool = typer.Option(
        False,
        "--allow-network",
        help=(
            "显式允许调用真实模型 API。"
        ),
    ),
    max_output_tokens: int = typer.Option(
        8192,
        "--max-output-tokens",
        min=128,
        max=100000,
        help="本次模型最大输出 token 数。",
    ),
    timeout_seconds: float = typer.Option(
        180.0,
        "--timeout-seconds",
        min=1.0,
        max=600.0,
        help="模型 API 超时时间。",
    ),
) -> None:
    """
    为已经完成 Ranker 解析的 bundle 生成受控模型解释。

    本命令不会重新执行 BinderRanker。
    """
    try:
        result = run_explain_run(
            bundle_dir=bundle_dir,
            model_config_path=(
                model_config
            ),
            profile_name=profile,
            output_dir=output_dir,
            allow_network=allow_network,
            max_output_tokens=(
                max_output_tokens
            ),
            timeout_seconds=(
                timeout_seconds
            ),
        )

    except Exception as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=bundle_dir,
            provider=None,
            public_message_override=(
                "模型解释未完成。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    typer.echo("=" * 72)
    typer.echo("结果解释完成")
    typer.echo("=" * 72)
    typer.echo(
        "状态："
        + user_status(
            result.status,
            area="explanation",
        )
    )
    typer.echo(
        f"Provider：{result.provider_name}"
    )
    typer.echo(
        f"Bundle：{result.bundle_dir}"
    )
    typer.echo(
        f"输出目录：{result.output_dir}"
    )
    typer.echo(
        f"证据：{result.evidence_path}"
    )
    typer.echo(
        "结构化解释："
        f"{result.explanation_json_path}"
    )
    typer.echo(
        "Markdown 报告："
        f"{result.explanation_markdown_path}"
    )


@app.command("extract-sample")
def extract_sample_command(
    destination: Path = typer.Option(
        Path("sample_data/3c98_small"),
        "--destination",
        "-d",
        file_okay=False,
        dir_okay=True,
        help="提取目录；默认当前目录下 sample_data/3c98_small。",
    ),
    sample_name: str = typer.Option(
        "3c98_small",
        "--sample",
        help="要提取的内置样例名称。",
    ),
) -> None:
    """安全提取随安装包发布的 smoke-test 样例。"""
    from protein_design_agent.agent.sample_resources import (
        PackagedSampleError,
        extract_packaged_sample,
    )

    try:
        result = extract_packaged_sample(
            destination=destination,
            sample_name=sample_name,
        )
    except PackagedSampleError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=2) from exc

    except OSError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                "样例提取未完成。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(f"样例：{result.sample_name}")
    typer.echo(f"目录：{result.destination}")
    typer.echo(f"PDB 数量：{len(result.pdb_files)}")
    typer.echo(
        "用途：仅用于安装和 smoke test，"
        "不得作为正式筛选结论。"
    )
    typer.echo("下一步：在 Chat 中提供上述目录。")


@app.command("init")
def init_command(
    destination: Path = typer.Option(
        ...,
        "--destination",
        "-d",
        file_okay=False,
        dir_okay=True,
        help="要创建的工作区目录。",
    ),
) -> None:
    """
    创建可移植的本地工作区。

    本命令不联网、不写入真实 API Key，
    也不会覆盖已有的受管文件。
    """
    from protein_design_agent.agent.workspace_init import (
        WorkspaceInitError,
        initialize_workspace,
        render_workspace_init_report,
    )

    try:
        report = initialize_workspace(
            destination
        )
    except WorkspaceInitError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
        )
        typer.echo(
            guidance,
            err=True,
        )

        if exc.conflicts:
            typer.echo("", err=True)
            typer.echo(
                "恢复信息：",
                err=True,
            )
            typer.echo(
                "检测到的冲突路径：",
                err=True,
            )

            root = (
                destination
                .expanduser()
                .resolve()
            )

            for conflict in exc.conflicts:
                try:
                    displayed = (
                        conflict
                        .resolve()
                        .relative_to(root)
                    )
                except ValueError:
                    displayed = Path(
                        conflict.name
                    )

                typer.echo(
                    f"  - {displayed}",
                    err=True,
                )

            typer.echo(
                "已有冲突内容不会被自动覆盖；"
                "请确认这些文件后再重试，"
                "或选择新的工作区目录。",
                err=True,
            )

        raise typer.Exit(code=2) from exc

    except OSError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                "工作区初始化未完成："
                "文件系统操作失败。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "恢复信息：请检查目标路径、"
            "文件权限和目录当前状态后再重试。",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    typer.echo(
        render_workspace_init_report(
            report
        )
    )


@app.command("doctor")
def doctor_command(
    project_root: Optional[Path] = typer.Option(
        None,
        "--project-root",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="源码仓库或用户工作区目录；未指定时自动识别。",
    ),
    model_config: Optional[Path] = typer.Option(
        None,
        "--model-config",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help=(
            "模型 Provider YAML；"
            "默认检查项目中的 DeepSeek 配置。"
        ),
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help=(
            "要检查的模型 Profile；"
            "默认使用 active_profile。"
        ),
    ),
    ranker_version: str = typer.Option(
        "v0.1-expert",
        "--ranker-version",
        help="要验证的冻结 Ranker 版本。",
    ),
) -> None:
    """
    只读检查本地安装、Ranker、示例数据和模型配置。

    本命令不会访问网络，也不会修改环境。
    """
    from protein_design_agent.agent.doctor import (
        render_doctor_report,
        run_doctor,
    )

    report = run_doctor(
        project_root=project_root,
        model_config_path=model_config,
        profile_name=profile,
        ranker_version=ranker_version,
    )

    typer.echo(
        render_doctor_report(report)
    )

    if report.exit_code() != 0:
        raise typer.Exit(
            code=report.exit_code()
        )


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

    except ValidationError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                "模型配置字段验证未通过。"
                "请检查必填字段、字段类型、"
                "active_profile 和 profiles 配置。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        typer.echo(
            "网络访问：否；"
            "本命令没有调用模型 API。",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    except ValueError as exc:
        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                "模型配置文件无法读取或基础格式无效。"
                "请检查 YAML 语法和配置文件结构。"
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        typer.echo(
            "网络访问：否；"
            "本命令没有调用模型 API。",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    try:
        profile_name, selected = (
            resolve_provider_profile(
                model_config,
                profile_name=profile,
            )
        )

    except ValueError as exc:
        requested_profile = (
            profile
            if profile is not None
            else model_config.active_profile
        )
        supported_profiles = ", ".join(
            sorted(model_config.profiles)
        )

        public_message = (
            "指定的模型 Profile 不存在："
            f"{requested_profile!r}。"
        )

        if supported_profiles:
            public_message += (
                "可用 Profile："
                f"{supported_profiles}。"
            )

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )
        typer.echo(
            guidance,
            err=True,
        )
        typer.echo(
            "网络访问：否；"
            "本命令没有调用模型 API。",
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

    完全离线，不访问模型 API，也不会执行 BinderRanker。

    示例 payload：

        {
          "project_name": "demo",
          "input_dir": "sample_data/test_two_chain",
          "input_layout": "existing_chains",
          "binder_chain": "A",
          "execute_requested": false
        }

    核心字段：

    project_name=项目标识；input_dir=候选 PDB 目录；
    input_layout=输入布局；
    binder_chain=existing_chains 布局中的 binder 链；
    execute_requested=仅记录执行请求，不代表批准或执行。

    concatenated_single_chain 布局还需要
    source_chain 和 target_residue_count。
    """
    try:
        raw_text = read_user_text(
            text=text,
            text_file=text_file,
        )

        try:
            raw_payload = json.loads(
                payload.read_text(
                    encoding="utf-8"
                )
            )
        except OSError as exc:
            raise CLIInputError(
                f"无法读取 Mock payload：{exc}",
                public_message=(
                    "Mock payload 文件无法读取。"
                ),
            ) from exc
        except json.JSONDecodeError as exc:
            raise CLIInputError(
                "Mock payload 不是合法 JSON："
                f"第 {exc.lineno} 行，"
                f"第 {exc.colno} 列",
                public_message=(
                    "Mock payload 不是合法 JSON。"
                ),
            ) from exc

        if not isinstance(raw_payload, dict):
            raise CLIInputError(
                "Mock payload 最外层必须是 JSON 对象",
                public_message=(
                    "Mock payload 最外层"
                    "必须是 JSON 对象。"
                ),
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
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = "Mock 规划未完成。"

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：plan-mock 完全离线，"
            "不调用模型 API，"
            "也不执行 BinderRanker。",
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

    except (
        ValueError,
        ValidationError,
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            public_message = (
                "规划输入或模型配置"
                "无法用于本次规划。"
            )

        guidance = format_error_guidance(
            kind="REJECTED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：尚未调用模型 API，"
            "也没有执行 BinderRanker。",
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
        OSError,
    ) as exc:
        public_message = getattr(
            exc,
            "public_message",
            None,
        )

        if not (
            isinstance(public_message, str)
            and public_message.strip()
        ):
            if isinstance(exc, ProviderError):
                public_message = (
                    "模型请求或响应处理"
                    "没有成功完成。"
                )
            else:
                public_message = (
                    "模型规划未完成。"
                )

        guidance = format_error_guidance(
            kind="FAILED",
            error=exc,
            bundle_dir=None,
            provider=None,
            public_message_override=(
                public_message
            ),
        )

        typer.echo(
            guidance,
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "执行边界：本命令只授权模型解析"
            "并生成规划，不授权执行 BinderRanker "
            "或远程科学计算任务。",
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
    main()
