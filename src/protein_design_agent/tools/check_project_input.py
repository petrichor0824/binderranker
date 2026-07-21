#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
检查项目配置是否与实际 PDB 数据集一致。

本工具只读，不修改 PDB。

状态：
- PASS：配置与数据匹配，可以进入下一步；
- REVIEW：主体匹配，但存在需要注意的非致命情况；
- BLOCKED：配置与数据冲突，禁止继续。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import ValidationError

from protein_design_agent.schemas.project_config import (
    ProjectConfig,
    load_project_config,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    build_dataset_report,
    collect_pdb_files,
    inspect_one_pdb,
)


app = typer.Typer(
    add_completion=False,
    help="对照项目 YAML 配置和真实 PDB 数据集。",
)


def add_example(
    examples: list[dict[str, Any]],
    *,
    file_name: str,
    code: str,
    message: str,
    limit: int = 20,
) -> None:
    """限制异常示例数量，避免大型数据集报告过长。"""
    if len(examples) >= limit:
        return

    examples.append(
        {
            "file_name": file_name,
            "code": code,
            "message": message,
        }
    )


def evaluate_existing_chains(
    project: ProjectConfig,
    file_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """检查已经正确分链的数据集。"""
    binder_chain = project.input.binder_chain
    configured_targets = set(project.input.target_chains)

    blockers: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    binder_lengths: list[int] = []
    target_lengths: list[int] = []
    target_chain_sets: list[tuple[str, ...]] = []

    if binder_chain is None:
        blockers["binder_chain_not_configured"] += 1

        return {
            "blockers": dict(blockers),
            "warnings": dict(warnings),
            "examples": examples,
            "binder_length_patterns": {},
            "target_length_patterns": {},
            "target_chain_set_patterns": {},
        }

    if binder_chain in configured_targets:
        blockers["binder_chain_also_listed_as_target"] += 1

    for report in file_reports:
        if not report["valid"]:
            blockers["invalid_pdb_file"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="invalid_pdb_file",
                message="PDB 文件无法正常解析。",
            )
            continue

        chain_ids = set(report["chain_ids"])

        if binder_chain not in chain_ids:
            blockers["binder_chain_missing"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="binder_chain_missing",
                message=(
                    f"配置指定 binder={binder_chain}，"
                    f"但实际链为 {sorted(chain_ids)}。"
                ),
            )
            continue

        if configured_targets:
            missing_targets = configured_targets - chain_ids

            if missing_targets:
                blockers["configured_target_chain_missing"] += 1
                add_example(
                    examples,
                    file_name=report["file_name"],
                    code="configured_target_chain_missing",
                    message=(
                        "缺少配置指定的 target 链："
                        f"{sorted(missing_targets)}。"
                    ),
                )
                continue

            actual_target_chains = tuple(
                sorted(configured_targets)
            )
        else:
            actual_target_chains = tuple(
                sorted(chain_ids - {binder_chain})
            )

            if not actual_target_chains:
                blockers["no_target_chain_found"] += 1
                add_example(
                    examples,
                    file_name=report["file_name"],
                    code="no_target_chain_found",
                    message=(
                        "除 binder 链外没有剩余链，"
                        "无法建立 target。"
                    ),
                )
                continue

        binder_length = report["chains"][binder_chain][
            "residue_count"
        ]

        target_length = sum(
            report["chains"][chain]["residue_count"]
            for chain in actual_target_chains
        )

        binder_lengths.append(binder_length)
        target_lengths.append(target_length)
        target_chain_sets.append(actual_target_chains)

        extra_chains = (
            chain_ids
            - {binder_chain}
            - set(actual_target_chains)
        )

        if configured_targets and extra_chains:
            warnings["unconfigured_extra_chains"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="unconfigured_extra_chains",
                message=(
                    "发现未配置的额外链："
                    f"{sorted(extra_chains)}。"
                ),
            )

    binder_length_patterns = Counter(binder_lengths)
    target_length_patterns = Counter(target_lengths)
    target_chain_set_patterns = Counter(target_chain_sets)

    # Binder 长度变化在 RFdiffusion 设计中通常是允许的。
    if len(binder_length_patterns) > 1:
        warnings["variable_binder_lengths"] += 1

    # Target 通常应该在整批设计中保持不变。
    if len(target_length_patterns) > 1:
        blockers["inconsistent_target_lengths"] += 1

    if len(target_chain_set_patterns) > 1:
        blockers["inconsistent_target_chain_sets"] += 1

    return {
        "blockers": dict(blockers),
        "warnings": dict(warnings),
        "examples": examples,
        "binder_length_patterns": {
            str(key): value
            for key, value in sorted(
                binder_length_patterns.items()
            )
        },
        "target_length_patterns": {
            str(key): value
            for key, value in sorted(
                target_length_patterns.items()
            )
        },
        "target_chain_set_patterns": {
            ",".join(key): value
            for key, value in sorted(
                target_chain_set_patterns.items()
            )
        },
    }


def evaluate_concatenated_single_chain(
    project: ProjectConfig,
    file_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """检查 target 与 binder 拼接在同一条链的数据集。"""
    source_chain = project.input.source_chain
    target_count = project.input.target_residue_count

    blockers: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    binder_lengths: list[int] = []
    total_lengths: list[int] = []

    if source_chain is None or target_count is None:
        blockers[
            "single_chain_split_rule_incomplete"
        ] += 1

        return {
            "blockers": dict(blockers),
            "warnings": dict(warnings),
            "examples": examples,
            "binder_length_patterns": {},
            "total_length_patterns": {},
        }

    for report in file_reports:
        if not report["valid"]:
            blockers["invalid_pdb_file"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="invalid_pdb_file",
                message="PDB 文件无法正常解析。",
            )
            continue

        if report["chain_count"] != 1:
            blockers["expected_exactly_one_chain"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="expected_exactly_one_chain",
                message=(
                    "配置声明为单链拼接，但实际链为 "
                    f"{report['chain_ids']}。"
                ),
            )
            continue

        actual_chain = report["chain_ids"][0]

        if actual_chain != source_chain:
            blockers["source_chain_mismatch"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="source_chain_mismatch",
                message=(
                    f"配置指定 source_chain={source_chain}，"
                    f"实际为 {actual_chain}。"
                ),
            )
            continue

        total_count = report["chains"][source_chain][
            "residue_count"
        ]

        total_lengths.append(total_count)

        if total_count <= target_count:
            blockers["no_residues_left_for_binder"] += 1
            add_example(
                examples,
                file_name=report["file_name"],
                code="no_residues_left_for_binder",
                message=(
                    f"总残基数={total_count}，"
                    f"target_residue_count={target_count}，"
                    "拆分后没有 binder 残基。"
                ),
            )
            continue

        binder_lengths.append(total_count - target_count)

    binder_length_patterns = Counter(binder_lengths)
    total_length_patterns = Counter(total_lengths)

    # 设计 binder 长度本来就可能不同，因此只给提示，不阻止。
    if len(binder_length_patterns) > 1:
        warnings["variable_binder_lengths"] += 1

    return {
        "blockers": dict(blockers),
        "warnings": dict(warnings),
        "examples": examples,
        "configured_source_chain": source_chain,
        "configured_target_residue_count": target_count,
        "binder_length_patterns": {
            str(key): value
            for key, value in sorted(
                binder_length_patterns.items()
            )
        },
        "total_length_patterns": {
            str(key): value
            for key, value in sorted(
                total_length_patterns.items()
            )
        },
    }


def evaluate_project_input(
    project: ProjectConfig,
    file_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """根据 layout 选择对应检查规则。"""
    if project.input.layout == "existing_chains":
        result = evaluate_existing_chains(
            project,
            file_reports,
        )
    else:
        result = evaluate_concatenated_single_chain(
            project,
            file_reports,
        )

    blocker_count = sum(result["blockers"].values())
    warning_count = sum(result["warnings"].values())

    if blocker_count > 0:
        status = "BLOCKED"
    elif warning_count > 0:
        status = "REVIEW"
    else:
        status = "PASS"

    result["status"] = status
    result["blocker_count"] = blocker_count
    result["warning_count"] = warning_count

    return result


@app.command()
def check(
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
        help=(
            "可选：临时覆盖 YAML 中的 pdb_dir，"
            "便于本地测试。"
        ),
    ),
    output: Path = typer.Option(
        Path("runs/project_input_check.json"),
        "--output",
        help="JSON 报告输出路径。",
    ),
) -> None:
    """检查配置与真实 PDB 是否匹配。"""
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
    )

    if not effective_input_dir.exists():
        typer.echo(
            f"ERROR: PDB 目录不存在：{effective_input_dir}",
            err=True,
        )
        raise typer.Exit(code=2)

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

    typer.echo(f"项目：{project.project_name}")
    typer.echo(f"输入布局：{project.input.layout}")
    typer.echo(f"PDB 数量：{len(pdb_files)}")
    typer.echo("正在检查……")

    file_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    dataset_report = build_dataset_report(
        input_dir=effective_input_dir,
        pdb_files=pdb_files,
        file_reports=file_reports,
        recursive=project.input.recursive,
        detail_limit=min(len(file_reports), 100),
    )

    compatibility = evaluate_project_input(
        project,
        file_reports,
    )

    final_report = {
        "schema_version": "0.1",
        "project_name": project.project_name,
        "config_path": str(config),
        "effective_input_directory": str(
            effective_input_dir.resolve()
        ),
        "layout": project.input.layout,
        "status": compatibility["status"],
        "compatibility": compatibility,
        "dataset_summary": {
            "processed_file_count": dataset_report[
                "processed_file_count"
            ],
            "valid_file_count": dataset_report[
                "valid_file_count"
            ],
            "invalid_file_count": dataset_report[
                "invalid_file_count"
            ],
            "chain_signature_counts": dataset_report[
                "chain_signature_counts"
            ],
            "total_residue_count_patterns": dataset_report[
                "total_residue_count_patterns"
            ],
        },
    }

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            final_report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    typer.echo("")
    typer.echo(f"最终状态：{compatibility['status']}")
    typer.echo(
        f"阻止项：{compatibility['blockers']}"
    )
    typer.echo(
        f"警告项：{compatibility['warnings']}"
    )

    if compatibility["examples"]:
        typer.echo("异常示例：")
        for item in compatibility["examples"][:5]:
            typer.echo(
                f"  - {item['file_name']}: "
                f"{item['code']} | "
                f"{item['message']}"
            )

    typer.echo(f"报告：{output}")

    if compatibility["status"] == "BLOCKED":
        raise typer.Exit(code=3)


if __name__ == "__main__":
    app()
