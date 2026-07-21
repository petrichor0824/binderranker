#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
根据项目配置标准化 PDB 数据集。

支持：
1. existing_chains：
   PDB 已经正确分链，原样复制到标准化目录。

2. concatenated_single_chain：
   target 和 binder 拼接在同一条链；
   按“残基出现顺序”将前 N 个残基拆为 target，
   剩余残基拆为 binder，并重新设置链名与残基编号。

安全原则：
- 永远不修改原始 PDB；
- 配置与数据不匹配时拒绝执行；
- 默认不覆盖已有输出目录；
- 当前版本仅处理蛋白 ATOM 记录，不处理配体 HETATM。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import ValidationError

from protein_design_agent.schemas.project_config import (
    ProjectConfig,
    load_project_config,
)
from protein_design_agent.tools.check_project_input import (
    evaluate_project_input,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    collect_pdb_files,
    inspect_one_pdb,
)


app = typer.Typer(
    add_completion=False,
    help="根据项目配置标准化 PDB 数据集。",
)


def sha256_file(path: Path) -> str:
    """计算文件 SHA256。"""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def prepare_output_directory(
    output_dir: Path,
    *,
    allow_overwrite: bool,
) -> None:
    """安全地准备输出目录。"""
    if output_dir.exists():
        existing_items = list(output_dir.iterdir())

        if existing_items and not allow_overwrite:
            raise ValueError(
                f"输出目录非空，禁止覆盖：{output_dir}"
            )

        if allow_overwrite:
            shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)


def atom_residue_key(line: str) -> tuple[str, int, str, str]:
    """从 ATOM 行提取残基唯一标识。"""
    chain = line[21].strip() or "_"
    residue_name = line[17:20].strip() or "UNK"
    residue_number = int(line[22:26])
    insertion_code = line[26].strip()

    return (
        chain,
        residue_number,
        insertion_code,
        residue_name,
    )


def rewrite_atom_line(
    line: str,
    *,
    serial: int,
    chain: str,
    residue_number: int,
) -> str:
    """保持原坐标等字段，仅重写原子序号、链和残基编号。"""
    clean = line.rstrip("\n").ljust(80)

    return (
        clean[:6]
        + f"{serial:5d}"
        + clean[11:21]
        + chain
        + f"{residue_number:4d}"
        + " "
        + clean[27:]
        + "\n"
    )


def split_concatenated_pdb(
    input_path: Path,
    output_path: Path,
    project: ProjectConfig,
) -> dict[str, Any]:
    """将单链拼接结构拆成标准 target/binder 双链。"""
    source_chain = project.input.source_chain
    target_count = project.input.target_residue_count

    if source_chain is None or target_count is None:
        raise ValueError("单链拆分配置不完整")

    atom_lines: list[str] = []
    residue_order: list[tuple[str, int, str, str]] = []
    seen_residues: set[tuple[str, int, str, str]] = set()

    hetatm_count = 0
    model_count = 0

    with input_path.open(
        "r",
        encoding="utf-8",
        errors="ignore",
    ) as handle:
        for line in handle:
            record = line[0:6].strip()

            if record == "MODEL":
                model_count += 1

            if record == "HETATM":
                hetatm_count += 1
                continue

            if record != "ATOM":
                continue

            key = atom_residue_key(line)

            if key[0] != source_chain:
                raise ValueError(
                    f"发现非 source_chain 的 ATOM："
                    f"期望 {source_chain}，实际 {key[0]}"
                )

            atom_lines.append(line)

            if key not in seen_residues:
                seen_residues.add(key)
                residue_order.append(key)

    if model_count > 1:
        raise ValueError(
            "当前标准化器不处理多模型 PDB"
        )

    if hetatm_count > 0:
        raise ValueError(
            f"发现 {hetatm_count} 条 HETATM；"
            "当前版本禁止静默丢弃配体或辅因子"
        )

    if len(residue_order) <= target_count:
        raise ValueError(
            f"总残基数={len(residue_order)}，"
            f"target_residue_count={target_count}，"
            "没有剩余 binder 残基"
        )

    target_keys = set(residue_order[:target_count])
    binder_keys = set(residue_order[target_count:])

    target_number_map = {
        key: project.input.target_start_residue + index
        for index, key in enumerate(residue_order[:target_count])
    }

    binder_number_map = {
        key: index + 1
        for index, key in enumerate(residue_order[target_count:])
    }

    target_chain = project.input.normalized_target_chain
    binder_chain = project.input.normalized_binder_chain

    output_lines: list[str] = []
    serial = 1
    previous_group: str | None = None

    for line in atom_lines:
        key = atom_residue_key(line)

        if key in target_keys:
            current_group = "target"
            new_chain = target_chain
            new_residue_number = target_number_map[key]
        elif key in binder_keys:
            current_group = "binder"
            new_chain = binder_chain
            new_residue_number = binder_number_map[key]
        else:
            raise ValueError(
                f"内部错误：无法映射残基 {key}"
            )

        if (
            previous_group is not None
            and current_group != previous_group
        ):
            output_lines.append("TER\n")

        output_lines.append(
            rewrite_atom_line(
                line,
                serial=serial,
                chain=new_chain,
                residue_number=new_residue_number,
            )
        )

        serial += 1
        previous_group = current_group

    output_lines.extend(["TER\n", "END\n"])

    output_path.write_text(
        "".join(output_lines),
        encoding="utf-8",
    )

    return {
        "mode": "split_concatenated_single_chain",
        "source_chain": source_chain,
        "target_chain": target_chain,
        "binder_chain": binder_chain,
        "target_residue_count": target_count,
        "binder_residue_count": (
            len(residue_order) - target_count
        ),
        "target_start_residue": (
            project.input.target_start_residue
        ),
    }


def normalize_one_pdb(
    input_path: Path,
    output_path: Path,
    project: ProjectConfig,
) -> dict[str, Any]:
    """按项目 layout 标准化一个 PDB。"""
    if project.input.layout == "existing_chains":
        shutil.copy2(input_path, output_path)

        inspection = inspect_one_pdb(output_path)

        return {
            "mode": "copied_existing_chains",
            "chain_signature": inspection[
                "chain_signature"
            ],
            "total_residue_count": inspection[
                "total_residue_count"
            ],
        }

    return split_concatenated_pdb(
        input_path=input_path,
        output_path=output_path,
        project=project,
    )


@app.command()
def normalize(
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
        help="临时覆盖配置中的 pdb_dir。",
    ),
    output_dir: Path = typer.Option(
        Path("runs/normalized_pdbs"),
        "--output-dir",
        help="标准化 PDB 输出目录。",
    ),
) -> None:
    """检查配置与数据后，生成标准化 PDB 数据集。"""
    try:
        project = load_project_config(config)
    except (ValueError, ValidationError) as exc:
        typer.echo("配置加载失败：", err=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    effective_input_dir = (
        input_dir
        if input_dir is not None
        else project.input.pdb_dir
    ).resolve()

    pdb_files = collect_pdb_files(
        input_dir=effective_input_dir,
        recursive=project.input.recursive,
        max_files=project.safety.max_files,
    )

    if not pdb_files:
        typer.echo(
            f"ERROR: 没有找到 PDB：{effective_input_dir}",
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo("预检查配置与数据……")

    file_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    compatibility = evaluate_project_input(
        project,
        file_reports,
    )

    typer.echo(
        f"输入兼容状态：{compatibility['status']}"
    )

    if compatibility["status"] == "BLOCKED":
        typer.echo(
            f"阻止项：{compatibility['blockers']}",
            err=True,
        )
        raise typer.Exit(code=3)

    output_dir = output_dir.resolve()

    try:
        prepare_output_directory(
            output_dir,
            allow_overwrite=project.safety.allow_overwrite,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    manifest_items: list[dict[str, Any]] = []

    typer.echo(f"开始标准化 {len(pdb_files)} 个 PDB……")

    try:
        for index, input_path in enumerate(
            pdb_files,
            start=1,
        ):
            output_path = output_dir / input_path.name

            details = normalize_one_pdb(
                input_path=input_path,
                output_path=output_path,
                project=project,
            )

            output_inspection = inspect_one_pdb(output_path)

            if not output_inspection["valid"]:
                raise ValueError(
                    f"标准化结果无效：{output_path.name}"
                )

            manifest_items.append(
                {
                    "source_path": str(
                        input_path.resolve()
                    ),
                    "output_path": str(
                        output_path.resolve()
                    ),
                    "source_sha256": sha256_file(
                        input_path
                    ),
                    "output_sha256": sha256_file(
                        output_path
                    ),
                    "output_chain_signature": (
                        output_inspection[
                            "chain_signature"
                        ]
                    ),
                    "details": details,
                }
            )

            typer.echo(
                f"[{index}/{len(pdb_files)}] "
                f"{input_path.name} -> "
                f"{output_inspection['chain_signature']}"
            )

    except Exception as exc:
        typer.echo(
            f"标准化失败：{exc}",
            err=True,
        )
        typer.echo(
            "已生成的部分文件保留用于排查，"
            "请勿作为正式结果使用。",
            err=True,
        )
        raise typer.Exit(code=5) from exc

    manifest = {
        "schema_version": "0.1",
        "project_name": project.project_name,
        "layout": project.input.layout,
        "source_directory": str(effective_input_dir),
        "output_directory": str(output_dir),
        "processed_file_count": len(manifest_items),
        "files": manifest_items,
    }

    manifest_path = (
        output_dir / "normalization_manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    typer.echo("")
    typer.echo("标准化完成")
    typer.echo(f"输出目录：{output_dir}")
    typer.echo(f"Manifest：{manifest_path}")


if __name__ == "__main__":
    app()
