#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""检查项目 YAML 配置是否合法。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from protein_design_agent.schemas.project_config import (
    load_project_config,
)


app = typer.Typer(
    add_completion=False,
    help="验证蛋白设计项目 YAML 配置。",
)


@app.command()
def validate(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="项目 YAML 配置路径。",
    ),
    show_json: bool = typer.Option(
        False,
        "--show-json",
        help="显示标准化后的完整 JSON 配置。",
    ),
) -> None:
    """验证 YAML 内容及不同 layout 的必填字段。"""
    try:
        project = load_project_config(config)
    except (ValueError, ValidationError) as exc:
        typer.echo("配置验证失败：", err=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("配置验证成功")
    typer.echo(f"项目名：{project.project_name}")
    typer.echo(f"输入布局：{project.input.layout}")
    typer.echo(
        f"Region 策略：{project.ranking.region_policy}"
    )
    typer.echo(
        f"异常处理：{project.safety.unknown_situation}"
    )

    if project.input.layout == "existing_chains":
        typer.echo(
            f"Binder 链：{project.input.binder_chain}"
        )
    else:
        typer.echo(
            "单链拆分规则："
            f"{project.input.source_chain} 链前 "
            f"{project.input.target_residue_count} 个残基"
            "为 target"
        )
        typer.echo(
            "标准化链："
            f"target={project.input.normalized_target_chain}, "
            f"binder={project.input.normalized_binder_chain}"
        )

    if show_json:
        typer.echo("")
        typer.echo(
            json.dumps(
                project.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    app()
