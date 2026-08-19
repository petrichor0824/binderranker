#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
骨架排名固定工作流。

流程：
1. 加载并验证项目 YAML；
2. 检查原始 PDB 与配置是否一致；
3. 创建独立运行目录；
4. 标准化 PDB；
5. 检查标准化后的 PDB；
6. 生成 BinderRanker 执行计划和可复现 Shell；
7. 默认不真正执行 Ranker。

注意：
- 原始 PDB 永不修改；
- 每次运行使用独立目录；
- 任一安全检查失败都会停止；
- 当前假测试 PDB 只用于验证流程，不用于科学打分。
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import ValidationError

from protein_design_agent.public_identity import (
    PROJECT_NAME,
)
from protein_design_agent.schemas.project_config import (
    load_project_config,
)
from protein_design_agent.tools.analysis_scope import (
    classify_analysis_scope,
)
from protein_design_agent.tools.check_project_input import (
    evaluate_project_input,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    collect_pdb_files,
    inspect_one_pdb,
)
from protein_design_agent.tools.normalize_pdb_dataset import (
    normalize_one_pdb,
    prepare_output_directory,
    sha256_file,
)
from protein_design_agent.tools.run_binderranker import (
    build_ranker_command,
    get_normalized_binder_chain,
    protect_outputs,
    resolve_ranker,
    validate_ranker_input,
)


app = typer.Typer(
    add_completion=False,
    help="执行配置驱动的骨架标准化与 BinderRanker 准备流程。",
)


def create_run_id(project_name: str) -> str:
    """创建可排序、可追溯的运行编号。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{project_name}"


def write_json(path: Path, content: dict[str, Any]) -> None:
    """写入格式化 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@app.command()
def prepare(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="项目 YAML 配置。",
    ),
    input_dir: Optional[Path] = typer.Option(
        None,
        "--input-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="临时覆盖 YAML 中的 pdb_dir。",
    ),
    run_dir: Optional[Path] = typer.Option(
        None,
        "--run-dir",
        help=(
            "本次任务目录。未指定时自动创建 "
            "runs/时间_项目名。"
        ),
    ),
) -> None:
    """准备完整工作流，但暂不真正执行 BinderRanker。"""
    try:
        project = load_project_config(config)
    except (ValueError, ValidationError) as exc:
        typer.echo(
            f"BLOCKED: 配置加载失败：{exc}",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    effective_input_dir = (
        input_dir
        if input_dir is not None
        else project.input.pdb_dir
    ).resolve()

    if not effective_input_dir.exists():
        typer.echo(
            f"BLOCKED: 输入目录不存在："
            f"{effective_input_dir}",
            err=True,
        )
        raise typer.Exit(code=2)

    if run_dir is None:
        run_dir = (
            Path("runs")
            / create_run_id(project.project_name)
        )

    run_dir = run_dir.resolve()

    try:
        prepare_output_directory(
            run_dir,
            allow_overwrite=False,
        )
    except ValueError as exc:
        typer.echo(f"BLOCKED: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    normalized_dir = run_dir / "normalized_pdbs"
    ranker_dir = run_dir / "ranker"
    reports_dir = run_dir / "reports"

    normalized_dir.mkdir(parents=True)
    ranker_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    typer.echo("================================================")
    typer.echo(f"{PROJECT_NAME}：骨架排名准备工作流")
    typer.echo("================================================")
    typer.echo(f"项目：{project.project_name}")
    typer.echo(f"运行目录：{run_dir}")
    typer.echo(f"原始输入：{effective_input_dir}")
    typer.echo("")

    # --------------------------------------------------------
    # 1. 检查原始输入
    # --------------------------------------------------------
    typer.echo("[1/5] 检查原始 PDB……")

    pdb_files = collect_pdb_files(
        input_dir=effective_input_dir,
        recursive=project.input.recursive,
        max_files=project.safety.max_files,
    )

    if not pdb_files:
        typer.echo(
            "BLOCKED: 输入目录中没有 PDB。",
            err=True,
        )
        raise typer.Exit(code=3)

    analysis_scope = classify_analysis_scope(
        len(pdb_files)
    )

    typer.echo(
        f"    分析级别：{analysis_scope['level']}"
    )
    typer.echo(
        f"    结果用途：{analysis_scope['result_use']}"
    )
    typer.echo(
        f"    说明：{analysis_scope['message']}"
    )

    warning_path = (
        run_dir
        / "SCIENTIFIC_INTERPRETATION_WARNING.txt"
    )
    warning_path.write_text(
        "Analysis scope\n"
        "==============\n\n"
        f"level: {analysis_scope['level']}\n"
        f"pdb_count: {analysis_scope['pdb_count']}\n"
        "workflow_allows_formal_interpretation: "
        f"{analysis_scope['workflow_allows_formal_interpretation']}\n"
        "pool_labels_reliable: "
        f"{analysis_scope['pool_labels_reliable']}\n"
        f"result_use: {analysis_scope['result_use']}\n\n"
        f"{analysis_scope['message']}\n",
        encoding="utf-8",
    )

    original_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    compatibility = evaluate_project_input(
        project,
        original_reports,
    )

    write_json(
        reports_dir / "original_input_check.json",
        {
            "project_name": project.project_name,
            "input_directory": str(effective_input_dir),
            "pdb_count": len(pdb_files),
            "analysis_scope": analysis_scope,
            "status": compatibility["status"],
            "compatibility": compatibility,
            "files": original_reports,
        },
    )

    typer.echo(
        f"    输入兼容状态：{compatibility['status']}"
    )

    if compatibility["status"] == "BLOCKED":
        typer.echo(
            f"BLOCKED: {compatibility['blockers']}",
            err=True,
        )
        raise typer.Exit(code=3)

    # --------------------------------------------------------
    # 2. 标准化
    # --------------------------------------------------------
    typer.echo("[2/5] 标准化 PDB……")

    normalization_items: list[dict[str, Any]] = []

    for index, source_path in enumerate(
        pdb_files,
        start=1,
    ):
        output_path = normalized_dir / source_path.name

        details = normalize_one_pdb(
            input_path=source_path,
            output_path=output_path,
            project=project,
        )

        output_report = inspect_one_pdb(output_path)

        if not output_report["valid"]:
            typer.echo(
                f"BLOCKED: 标准化结果无效："
                f"{output_path.name}",
                err=True,
            )
            raise typer.Exit(code=4)

        normalization_items.append(
            {
                "source_path": str(source_path.resolve()),
                "output_path": str(output_path.resolve()),
                "source_sha256": sha256_file(source_path),
                "output_sha256": sha256_file(output_path),
                "output_chain_signature": output_report[
                    "chain_signature"
                ],
                "details": details,
            }
        )

        typer.echo(
            f"    [{index}/{len(pdb_files)}] "
            f"{source_path.name} -> "
            f"{output_report['chain_signature']}"
        )

    write_json(
        normalized_dir / "normalization_manifest.json",
        {
            "schema_version": "0.1",
            "project_name": project.project_name,
            "source_directory": str(effective_input_dir),
            "output_directory": str(normalized_dir),
            "processed_file_count": len(
                normalization_items
            ),
            "files": normalization_items,
        },
    )

    # --------------------------------------------------------
    # 3. 检查标准化结果
    # --------------------------------------------------------
    typer.echo("[3/5] 检查标准化结果……")

    binder_chain = get_normalized_binder_chain(project)

    try:
        normalized_summary = validate_ranker_input(
            input_dir=normalized_dir,
            binder_chain=binder_chain,
            recursive=False,
            max_files=project.safety.max_files,
        )
    except ValueError as exc:
        typer.echo(
            f"BLOCKED: 标准化结果不适合 Ranker："
            f"{exc}",
            err=True,
        )
        raise typer.Exit(code=4) from exc

    write_json(
        reports_dir / "normalized_input_check.json",
        normalized_summary,
    )

    typer.echo(
        f"    Binder 链：{binder_chain}"
    )
    typer.echo(
        f"    链模式："
        f"{normalized_summary['chain_signature_counts']}"
    )

    # --------------------------------------------------------
    # 4. 校验冻结 Ranker
    # --------------------------------------------------------
    typer.echo("[4/5] 校验冻结 BinderRanker……")

    try:
        ranker_path, ranker_sha256 = resolve_ranker(
            project.ranking.ranker_version
        )
    except ValueError as exc:
        typer.echo(f"BLOCKED: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    typer.echo(
        f"    版本：{project.ranking.ranker_version}"
    )
    typer.echo(
        f"    SHA256：{ranker_sha256}"
    )

    # --------------------------------------------------------
    # 5. 生成 Ranker 计划
    # --------------------------------------------------------
    typer.echo("[5/5] 生成 BinderRanker 计划……")

    output_prefix = ranker_dir / "backbone_rank"

    try:
        protect_outputs(
            output_prefix,
            allow_overwrite=False,
        )

        command = build_ranker_command(
            project,
            ranker_path=ranker_path,
            input_dir=normalized_dir,
            output_prefix=output_prefix,
        )
    except ValueError as exc:
        typer.echo(f"BLOCKED: {exc}", err=True)
        raise typer.Exit(code=5) from exc

    command_display = shlex.join(command)

    ranker_plan = {
        "schema_version": "0.1",
        "project_name": project.project_name,
        "ranker_version": project.ranking.ranker_version,
        "ranker_path": str(ranker_path),
        "ranker_sha256": ranker_sha256,
        "input_directory": str(normalized_dir),
        "input_summary": normalized_summary,
        "analysis_scope": analysis_scope,
        "output_prefix": str(output_prefix),
        "region_policy": project.ranking.region_policy,
        "command": command,
        "command_display": command_display,
        "execute_requested": False,
    }

    write_json(
        ranker_dir / "ranker_execution_plan.json",
        ranker_plan,
    )

    run_script = ranker_dir / "run_ranker.sh"
    run_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        + command_display
        + "\n",
        encoding="utf-8",
    )
    run_script.chmod(0o750)

    workflow_manifest = {
        "schema_version": "0.1",
        "workflow": "backbone_ranking_prepare",
        "project_name": project.project_name,
        "config_path": str(config),
        "original_input_directory": str(
            effective_input_dir
        ),
        "run_directory": str(run_dir),
        "normalized_directory": str(normalized_dir),
        "ranker_plan": str(
            ranker_dir / "ranker_execution_plan.json"
        ),
        "ranker_script": str(run_script),
        "analysis_scope": analysis_scope,
        "interpretation_warning": str(warning_path),
        "status": "READY_FOR_REVIEW",
    }

    write_json(
        run_dir / "workflow_manifest.json",
        workflow_manifest,
    )

    typer.echo("")
    typer.echo("================================================")
    typer.echo("工作流准备完成")
    typer.echo("状态：READY_FOR_REVIEW")
    typer.echo("================================================")
    typer.echo(f"运行目录：{run_dir}")
    typer.echo(
        f"分析级别：{analysis_scope['level']}"
    )
    typer.echo(
        "允许正式解释："
        f"{analysis_scope['workflow_allows_formal_interpretation']}"
    )
    typer.echo(
        f"解释警告：{warning_path}"
    )
    typer.echo(
        f"标准化 PDB：{normalized_dir}"
    )
    typer.echo(
        f"Ranker 计划："
        f"{ranker_dir / 'ranker_execution_plan.json'}"
    )
    typer.echo(f"运行脚本：{run_script}")
    typer.echo("")
    typer.echo("当前没有真正执行 BinderRanker。")
    typer.echo(
        "审核运行计划后，才允许进入正式执行阶段。"
    )


if __name__ == "__main__":
    app()
