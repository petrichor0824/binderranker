#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDB 数据集预检查器。

职责：
1. 扫描一个目录中的 PDB 文件；
2. 统计每个文件的链、残基数、原子数和编号范围；
3. 检查整批文件的格式是否一致；
4. 输出结构化 JSON 报告；
5. 只读，不修改任何原始 PDB。

当前版本不会自动判断哪条链是 binder，也不会自动拆链。
发现异常时只报告，后续由配置和人工确认决定如何处理。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import typer


app = typer.Typer(
    add_completion=False,
    help="检查一批 PDB 的链、残基数量及格式一致性。",
)


def collect_pdb_files(
    input_dir: Path,
    recursive: bool,
    max_files: Optional[int],
) -> list[Path]:
    """收集 PDB 文件，默认只处理输入目录顶层。"""
    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()

    pdb_files = sorted(
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() == ".pdb"
    )

    if max_files is not None:
        pdb_files = pdb_files[:max_files]

    return pdb_files


def count_numbering_gaps(residue_numbers: list[int]) -> int:
    """统计残基整数编号中缺失了多少个位置。"""
    unique_numbers = sorted(set(residue_numbers))

    if len(unique_numbers) < 2:
        return 0

    return sum(
        max(0, right - left - 1)
        for left, right in zip(unique_numbers, unique_numbers[1:])
    )


def inspect_one_pdb(pdb_path: Path) -> dict[str, Any]:
    """
    检查单个 PDB。

    只统计 ATOM 记录。
    对多模型 PDB，只统计第一个 MODEL 中的结构，避免重复计数。
    """
    residues_by_chain: dict[str, set[tuple[int, str, str]]] = {}
    residue_numbers_by_chain: dict[str, list[int]] = {}
    atoms_by_chain: Counter[str] = Counter()

    atom_record_count = 0
    malformed_atom_lines = 0
    model_count = 0
    in_first_model = True
    has_model_records = False

    errors: list[str] = []
    warnings: list[str] = []

    try:
        with pdb_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                record_name = line[0:6].strip()

                if record_name == "MODEL":
                    has_model_records = True
                    model_count += 1
                    in_first_model = model_count == 1
                    continue

                if record_name == "ENDMDL":
                    in_first_model = False
                    continue

                if record_name != "ATOM":
                    continue

                # 多模型文件只读取第一模型。
                if has_model_records and not in_first_model:
                    continue

                atom_record_count += 1

                try:
                    chain = line[21].strip() or "_"
                    residue_name = line[17:20].strip() or "UNK"
                    residue_number = int(line[22:26])
                    insertion_code = line[26].strip()
                except (ValueError, IndexError):
                    malformed_atom_lines += 1
                    continue

                residue_key = (
                    residue_number,
                    insertion_code,
                    residue_name,
                )

                residues_by_chain.setdefault(chain, set()).add(residue_key)
                residue_numbers_by_chain.setdefault(chain, []).append(
                    residue_number
                )
                atoms_by_chain[chain] += 1

    except OSError as exc:
        errors.append(f"cannot_read_file: {exc}")

    if atom_record_count == 0:
        errors.append("no_atom_records")

    if malformed_atom_lines > 0:
        warnings.append(
            f"malformed_atom_lines={malformed_atom_lines}"
        )

    chain_summaries: dict[str, dict[str, Any]] = {}

    for chain in sorted(residues_by_chain):
        residues = residues_by_chain[chain]
        numbers = sorted({item[0] for item in residues})
        gaps = count_numbering_gaps(numbers)

        chain_summaries[chain] = {
            "residue_count": len(residues),
            "atom_count": atoms_by_chain[chain],
            "min_residue_number": min(numbers) if numbers else None,
            "max_residue_number": max(numbers) if numbers else None,
            "numbering_gap_count": gaps,
        }

        if gaps > 0:
            warnings.append(
                f"chain_{chain}_numbering_gaps={gaps}"
            )

    chain_ids = sorted(chain_summaries)
    total_residue_count = sum(
        item["residue_count"] for item in chain_summaries.values()
    )

    if len(chain_ids) == 1:
        warnings.append("single_chain_only")

    if "_" in chain_ids:
        warnings.append("blank_chain_id")

    if model_count > 1:
        warnings.append(
            f"multiple_models={model_count}; only_first_model_counted"
        )

    signature_parts = [
        f"{chain}:{chain_summaries[chain]['residue_count']}"
        for chain in chain_ids
    ]
    chain_signature = "|".join(signature_parts) or "NO_VALID_CHAINS"

    return {
        "file_name": pdb_path.name,
        "file_path": str(pdb_path.resolve()),
        "file_size_bytes": pdb_path.stat().st_size,
        "chain_count": len(chain_ids),
        "chain_ids": chain_ids,
        "chain_signature": chain_signature,
        "total_residue_count": total_residue_count,
        "atom_record_count": atom_record_count,
        "model_count": model_count if has_model_records else 1,
        "chains": chain_summaries,
        "warnings": warnings,
        "errors": errors,
        "valid": len(errors) == 0,
    }


def build_dataset_report(
    input_dir: Path,
    pdb_files: list[Path],
    file_reports: list[dict[str, Any]],
    recursive: bool,
    detail_limit: int,
) -> dict[str, Any]:
    """汇总整批 PDB 的检查结果。"""
    valid_reports = [
        report for report in file_reports if report["valid"]
    ]
    invalid_reports = [
        report for report in file_reports if not report["valid"]
    ]

    signature_counts = Counter(
        report["chain_signature"] for report in valid_reports
    )
    residue_count_patterns = Counter(
        report["total_residue_count"] for report in valid_reports
    )
    chain_count_patterns = Counter(
        report["chain_count"] for report in valid_reports
    )

    all_single_chain = bool(valid_reports) and all(
        report["chain_count"] == 1 for report in valid_reports
    )

    dataset_warnings: list[str] = []

    if len(signature_counts) > 1:
        dataset_warnings.append(
            "inconsistent_chain_signatures"
        )

    if len(residue_count_patterns) > 1:
        dataset_warnings.append(
            "inconsistent_total_residue_counts"
        )

    if all_single_chain:
        dataset_warnings.append(
            "all_valid_files_are_single_chain"
        )

    if invalid_reports:
        dataset_warnings.append(
            f"invalid_files={len(invalid_reports)}"
        )

    if not valid_reports:
        status = "ERROR"
    elif dataset_warnings:
        status = "REVIEW"
    else:
        status = "OK"

    return {
        "schema_version": "0.1",
        "status": status,
        "input_directory": str(input_dir.resolve()),
        "recursive": recursive,
        "processed_file_count": len(pdb_files),
        "valid_file_count": len(valid_reports),
        "invalid_file_count": len(invalid_reports),
        "dataset_consistent": (
            len(signature_counts) <= 1
            and len(residue_count_patterns) <= 1
            and not invalid_reports
        ),
        "all_valid_files_are_single_chain": all_single_chain,
        "chain_signature_counts": dict(signature_counts),
        "chain_count_patterns": {
            str(key): value
            for key, value in sorted(chain_count_patterns.items())
        },
        "total_residue_count_patterns": {
            str(key): value
            for key, value in sorted(residue_count_patterns.items())
        },
        "warnings": dataset_warnings,
        "file_details_included": min(
            detail_limit,
            len(file_reports),
        ),
        "file_details": file_reports[:detail_limit],
    }


@app.command()
def inspect(
    input_dir: Path = typer.Option(
        ...,
        "--input-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="待检查的 PDB 文件夹。",
    ),
    output: Path = typer.Option(
        Path("runs/pdb_inspection.json"),
        "--output",
        help="JSON 报告输出路径。",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        help="递归搜索子目录；默认只检查顶层。",
    ),
    max_files: Optional[int] = typer.Option(
        None,
        "--max-files",
        min=1,
        help="测试时最多处理前 N 个 PDB。",
    ),
    detail_limit: int = typer.Option(
        100,
        "--detail-limit",
        min=0,
        help="JSON 中最多保存多少个逐文件详情。",
    ),
) -> None:
    """检查一个 PDB 数据集，不修改原始文件。"""
    pdb_files = collect_pdb_files(
        input_dir=input_dir,
        recursive=recursive,
        max_files=max_files,
    )

    if not pdb_files:
        typer.echo(
            f"ERROR: 在 {input_dir} 中没有找到 PDB 文件。",
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo(f"找到 PDB 文件：{len(pdb_files)} 个")
    typer.echo("开始检查……")

    file_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    report = build_dataset_report(
        input_dir=input_dir,
        pdb_files=pdb_files,
        file_reports=file_reports,
        recursive=recursive,
        detail_limit=detail_limit,
    )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    typer.echo("")
    typer.echo("检查完成")
    typer.echo(f"状态：{report['status']}")
    typer.echo(
        f"有效/总数："
        f"{report['valid_file_count']}/"
        f"{report['processed_file_count']}"
    )
    typer.echo(
        f"链模式：{report['chain_signature_counts']}"
    )
    typer.echo(
        "总残基数模式："
        f"{report['total_residue_count_patterns']}"
    )

    if report["warnings"]:
        typer.echo(
            f"警告：{report['warnings']}"
        )

    typer.echo(f"JSON 报告：{output}")


if __name__ == "__main__":
    app()
