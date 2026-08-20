#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 通用调用器。

职责：
1. 读取项目 YAML；
2. 检查冻结的 Ranker 版本和 SHA256；
3. 检查输入 PDB 是否已有可用的 binder/target 分链；
4. 将通用配置转换为 BinderRanker 命令；
5. 默认只生成运行计划，显式传入 --execute 才真正执行。

不会修改原始 PDB。
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from protein_design_agent.path_semantics import (
    resolve_local_path,
)

from protein_design_agent.schemas.project_config import (
    ProjectConfig,
    load_project_config,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    collect_pdb_files,
    inspect_one_pdb,
)


app = typer.Typer(
    add_completion=False,
    help="根据项目 YAML 安全调用冻结版 BinderRanker。",
)


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
)

RANKER_RESOURCE_ROOT = (
    PACKAGE_ROOT
    / "resources"
    / "binderranker"
)

RANKER_REGISTRY = {
    "v0.1-expert": {
        "path": (
            RANKER_RESOURCE_ROOT
            / "v0.1-expert"
            / "contact_field_rank_integrated_region.py"
        ),
        "sha256_manifest": (
            RANKER_RESOURCE_ROOT
            / "v0.1-expert"
            / "SHA256SUMS"
        ),
    }
}


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


def load_expected_sha256(
    manifest_path: Path,
    ranker_path: Path,
) -> str:
    """从 SHA256SUMS 中读取指定 Ranker 文件的预期哈希。"""
    if not manifest_path.exists():
        raise ValueError(
            f"SHA256 校验清单不存在：{manifest_path}"
        )

    try:
        lines = manifest_path.read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError as exc:
        raise ValueError(
            f"无法读取 SHA256 清单：{exc}"
        ) from exc

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split(maxsplit=1)

        if len(parts) != 2:
            raise ValueError(
                f"SHA256 清单第 {line_number} 行格式错误："
                f"{stripped}"
            )

        digest, filename = parts
        filename = filename.lstrip("*")

        if Path(filename).name != ranker_path.name:
            continue

        if len(digest) != 64:
            raise ValueError(
                f"SHA256 长度错误：{digest}"
            )

        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError(
                f"SHA256 含有非十六进制字符：{digest}"
            ) from exc

        return digest.lower()

    raise ValueError(
        f"SHA256 清单中没有找到：{ranker_path.name}"
    )


def resolve_ranker(
    version: str,
) -> tuple[Path, str]:
    """定位并校验指定版本的 Ranker。"""
    if version not in RANKER_REGISTRY:
        supported = ", ".join(
            sorted(RANKER_REGISTRY)
        )
        raise ValueError(
            f"未知 Ranker 版本：{version}；"
            f"当前支持：{supported}"
        )

    item = RANKER_REGISTRY[version]
    ranker_path = Path(item["path"])
    manifest_path = Path(item["sha256_manifest"])

    if not ranker_path.exists():
        raise ValueError(
            f"Ranker 文件不存在：{ranker_path}"
        )

    expected_sha256 = load_expected_sha256(
        manifest_path=manifest_path,
        ranker_path=ranker_path,
    )

    actual_sha256 = sha256_file(ranker_path)

    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Ranker SHA256 与冻结版本不一致。\n"
            f"期望：{expected_sha256}\n"
            f"实际：{actual_sha256}\n"
            "为防止实验版本被静默修改，已停止。"
        )

    return ranker_path, actual_sha256


def get_normalized_binder_chain(
    project: ProjectConfig,
) -> str:
    """确定标准化数据中的 binder 链。"""
    if project.input.layout == "existing_chains":
        if project.input.binder_chain is None:
            raise ValueError("项目未配置 binder_chain")

        return project.input.binder_chain

    return project.input.normalized_binder_chain


def validate_ranker_input(
    input_dir: Path,
    *,
    binder_chain: str,
    recursive: bool,
    max_files: int | None,
) -> dict[str, Any]:
    """
    检查输入是否已经是 Ranker 可接受的分链结构。

    即使原项目是 concatenated_single_chain，
    传给本工具的也必须是标准化后的双链目录。
    """
    pdb_files = collect_pdb_files(
        input_dir=input_dir,
        recursive=recursive,
        max_files=max_files,
    )

    if not pdb_files:
        raise ValueError(
            f"输入目录中没有 PDB：{input_dir}"
        )

    blockers: Counter[str] = Counter()
    chain_patterns: Counter[str] = Counter()
    examples: list[dict[str, str]] = []

    for pdb_path in pdb_files:
        report = inspect_one_pdb(pdb_path)

        chain_patterns[report["chain_signature"]] += 1

        if not report["valid"]:
            blockers["invalid_pdb"] += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "file": pdb_path.name,
                        "problem": "PDB 无法正常解析",
                    }
                )
            continue

        chain_ids = set(report["chain_ids"])

        if binder_chain not in chain_ids:
            blockers["binder_chain_missing"] += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "file": pdb_path.name,
                        "problem": (
                            f"缺少 binder 链 {binder_chain}；"
                            f"实际链为 {sorted(chain_ids)}"
                        ),
                    }
                )
            continue

        target_chains = chain_ids - {binder_chain}

        if not target_chains:
            blockers["no_target_chain"] += 1

            if len(examples) < 10:
                examples.append(
                    {
                        "file": pdb_path.name,
                        "problem": (
                            "除 binder 链外没有 target 链"
                        ),
                    }
                )

    if blockers:
        raise ValueError(
            "Ranker 输入结构不符合要求：\n"
            f"阻止项：{dict(blockers)}\n"
            f"示例：{examples}"
        )

    return {
        "pdb_count": len(pdb_files),
        "binder_chain": binder_chain,
        "chain_signature_counts": dict(chain_patterns),
    }


def region_settings(
    project: ProjectConfig,
) -> dict[str, str]:
    """
    将通用 region_policy 映射到冻结 Ranker 参数。

    off:
        不传 region/hotspot，主分使用原始分。

    diagnostic:
        计算 region/hotspot 指标，但主排名仍使用原始分。

    weak:
        region 以冻结脚本中的弱权重进入主分。

    constraint:
        region 进入主分并使用 soft/strict 过滤；
        必须在 YAML 中明确指定过滤等级。
    """
    policy = project.ranking.region_policy

    desired = ",".join(project.regions.desired)
    undesired = ",".join(project.regions.undesired)
    hotspots = ",".join(project.regions.hotspots)

    if policy == "off":
        return {
            "desired_regions": "",
            "undesired_regions": "",
            "hotspot_regions": "",
            "region_score_mode": "off",
            "region_filter": "off",
        }

    if policy == "diagnostic":
        return {
            "desired_regions": desired,
            "undesired_regions": undesired,
            "hotspot_regions": hotspots,
            "region_score_mode": "off",
            "region_filter": "off",
        }

    if policy == "weak":
        return {
            "desired_regions": desired,
            "undesired_regions": undesired,
            "hotspot_regions": hotspots,
            "region_score_mode": "auto",
            "region_filter": project.ranking.region_filter,
        }

    # constraint
    if not desired and not hotspots:
        raise ValueError(
            "region_policy=constraint 时，"
            "必须配置 desired region 或 hotspot"
        )

    if project.ranking.region_filter == "off":
        raise ValueError(
            "region_policy=constraint 时，"
            "region_filter 不能为 off，"
            "请设置为 soft 或 strict"
        )

    return {
        "desired_regions": desired,
        "undesired_regions": undesired,
        "hotspot_regions": hotspots,
        "region_score_mode": "auto",
        "region_filter": project.ranking.region_filter,
    }


def expected_output_files(
    output_prefix: Path,
) -> list[Path]:
    """冻结 Ranker 应生成的四个核心结果。"""
    prefix = str(output_prefix)

    return [
        Path(prefix + "_metrics.csv"),
        Path(prefix + "_scored.csv"),
        Path(prefix + "_ranking.xlsx"),
        Path(prefix + "_report.txt"),
    ]


def build_ranker_command(
    project: ProjectConfig,
    *,
    ranker_path: Path,
    input_dir: Path,
    output_prefix: Path,
) -> list[str]:
    """构造结构化 subprocess 命令，不使用任意 Shell 拼接。"""
    binder_chain = get_normalized_binder_chain(project)
    region = region_settings(project)

    command = [
        sys.executable,
        str(ranker_path),
        "--input_dir",
        str(input_dir),
        "--output_prefix",
        str(output_prefix),
        "--binder_chain",
        binder_chain,
        "--desired_regions",
        region["desired_regions"],
        "--undesired_regions",
        region["undesired_regions"],
        "--hotspot_regions",
        region["hotspot_regions"],
        "--hotspot_expand_radius",
        str(project.regions.hotspot_expand_radius),
        "--region_score_mode",
        region["region_score_mode"],
        "--region_filter",
        region["region_filter"],
        "--top_k_report",
        str(project.ranking.top_k_report),
        "--top_n_sheets",
        str(project.ranking.top_n_sheets),
    ]

    if project.safety.max_files is not None:
        command.extend(
            [
                "--max_files",
                str(project.safety.max_files),
            ]
        )

    return command


def protect_outputs(
    output_prefix: Path,
    *,
    allow_overwrite: bool,
) -> None:
    """默认保护既有 Ranker 结果。"""
    existing = [
        path
        for path in expected_output_files(output_prefix)
        if path.exists()
    ]

    if existing and not allow_overwrite:
        formatted = "\n".join(
            f"- {path}" for path in existing
        )

        raise ValueError(
            "检测到已有结果，禁止覆盖：\n"
            f"{formatted}"
        )


@app.command()
def run(
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
    input_dir: Path = typer.Option(
        ...,
        "--input-dir",
        exists=False,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=False,
        help=(
            "传给 Ranker 的标准化 PDB 目录。"
            "单链拼接项目不能直接传原始目录。"
        ),
    ),
    output_prefix: Path = typer.Option(
        ...,
        "--output-prefix",
        help="Ranker 输出文件前缀。",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="真正执行；默认仅生成和检查运行计划。",
    ),
) -> None:
    """构建并可选执行 BinderRanker。"""
    try:
        project = load_project_config(config)

        ranker_path, ranker_sha256 = resolve_ranker(
            project.ranking.ranker_version
        )

        binder_chain = get_normalized_binder_chain(project)

        resolved_input_dir = resolve_local_path(
            input_dir,
            field_name="input_dir",
        )

        input_summary = validate_ranker_input(
            input_dir=resolved_input_dir,
            binder_chain=binder_chain,
            recursive=project.input.recursive,
            max_files=project.safety.max_files,
        )

        output_prefix = output_prefix.resolve()
        output_prefix.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        protect_outputs(
            output_prefix,
            allow_overwrite=project.safety.allow_overwrite,
        )

        command = build_ranker_command(
            project,
            ranker_path=ranker_path,
            input_dir=resolved_input_dir,
            output_prefix=output_prefix,
        )

    except (ValueError, ValidationError) as exc:
        typer.echo(f"BLOCKED: {exc}", err=True)
        raise typer.Exit(code=3) from exc

    plan_path = Path(
        str(output_prefix) + "_execution_plan.json"
    )
    shell_path = Path(
        str(output_prefix) + "_run.sh"
    )

    plan = {
        "schema_version": "0.1",
        "project_name": project.project_name,
        "ranker_version": project.ranking.ranker_version,
        "ranker_path": str(ranker_path),
        "ranker_sha256": ranker_sha256,
        "input_directory": str(resolved_input_dir),
        "input_summary": input_summary,
        "output_prefix": str(output_prefix),
        "region_policy": project.ranking.region_policy,
        "command": command,
        "command_display": shlex.join(command),
        "execute_requested": execute,
    }

    plan_path.write_text(
        json.dumps(
            plan,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    shell_path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        + shlex.join(command)
        + "\n",
        encoding="utf-8",
    )
    shell_path.chmod(0o750)

    typer.echo("BinderRanker 运行计划已生成")
    typer.echo(
        f"Ranker：{project.ranking.ranker_version}"
    )
    typer.echo(
        f"输入 PDB：{input_summary['pdb_count']} 个"
    )
    typer.echo(f"Binder 链：{binder_chain}")
    typer.echo(
        f"Region 策略："
        f"{project.ranking.region_policy}"
    )
    typer.echo(f"运行计划：{plan_path}")
    typer.echo(f"可复现脚本：{shell_path}")
    typer.echo("")
    typer.echo("命令：")
    typer.echo(shlex.join(command))

    if not execute:
        typer.echo("")
        typer.echo(
            "当前为 DRY-RUN，没有真正运行 Ranker。"
        )
        typer.echo(
            "确认计划无误后，添加 --execute 执行。"
        )
        return

    stdout_path = Path(
        str(output_prefix) + "_stdout.log"
    )
    stderr_path = Path(
        str(output_prefix) + "_stderr.log"
    )

    typer.echo("")
    typer.echo("开始执行 BinderRanker……")

    with (
        stdout_path.open(
            "w",
            encoding="utf-8",
        ) as stdout_handle,
        stderr_path.open(
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

    if completed.returncode != 0:
        typer.echo(
            f"BinderRanker 执行失败，"
            f"退出码={completed.returncode}",
            err=True,
        )
        typer.echo(f"标准输出：{stdout_path}", err=True)
        typer.echo(f"错误日志：{stderr_path}", err=True)
        raise typer.Exit(code=completed.returncode)

    missing_outputs = [
        path
        for path in expected_output_files(output_prefix)
        if not path.exists()
    ]

    if missing_outputs:
        typer.echo(
            "程序退出码为 0，但缺少预期结果：",
            err=True,
        )
        for path in missing_outputs:
            typer.echo(f"- {path}", err=True)

        raise typer.Exit(code=5)

    typer.echo("BinderRanker 执行完成")
    typer.echo(f"标准输出：{stdout_path}")
    typer.echo(f"错误日志：{stderr_path}")

    for path in expected_output_files(output_prefix):
        typer.echo(f"结果：{path}")


if __name__ == "__main__":
    app()
