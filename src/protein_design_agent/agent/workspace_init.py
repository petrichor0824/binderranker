#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
创建可移植的 Protein Design Agent 工作区。

安全原则：
- 不访问网络；
- 不读取或写入真实 API Key；
- 不覆盖已有受管文件；
- 不写入当前电脑的绝对路径；
- 写入失败时回滚本次创建的内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MODEL_CONFIG_TEMPLATE = '''schema_version: "0.1"

active_profile: deepseek_flash

profiles:
  deepseek_flash:
    kind: openai_compatible
    base_url: https://api.deepseek.com
    model: deepseek-v4-flash

    # 这里只保存环境变量名称，不保存真实 API Key。
    api_key_env: DEEPSEEK_API_KEY
    require_api_key: true

    timeout_seconds: 120
    max_output_tokens: 4096
    max_tokens_field: "max_tokens"
    temperature: 0.0
'''


ENV_EXAMPLE_TEMPLATE = '''# 请复制为 .env 后填写。
# 不要把包含真实 API Key 的 .env 提交到 Git。

DEEPSEEK_API_KEY=
'''


GITIGNORE_TEMPLATE = '''# Local secrets
.env

# Generated data
runs/
data/

# Python
__pycache__/
*.py[cod]
.pytest_cache/

# Editors
.vscode/
.idea/

# Operating systems
.DS_Store
Thumbs.db
'''


QUICKSTART_TEMPLATE = '''# Protein Design Agent 工作区

本目录由 protein-design-agent init 创建。

目录说明：

- configs/models：模型 Provider 配置
- data：输入 PDB 数据
- runs：计划、审批、执行和分析结果

第一步：设置 API Key

在 Linux、WSL 或 macOS 中运行：

    export DEEPSEEK_API_KEY="你的真实 API Key"

不要把真实 API Key 写入 YAML 或提交到 Git。

第二步：检查安装

    protein-design-agent doctor --model-config configs/models/deepseek.local.yaml --profile deepseek_flash

Doctor 默认不会访问网络，也不会显示 API Key。

第三步：放入输入数据

把待分析的 PDB 文件复制到 data 目录。

例如：

    cp /path/to/pdb_files/*.pdb data/

第四步：查看交互式 Agent 用法

    protein-design-agent chat --help

安全边界：

- 模型只负责自然语言理解和受控解释。
- 确定性 Planner 负责生成结构化计划。
- 执行前必须完成人工审批。
- 审批会冻结配置和关键文件摘要。
- 一次审批只能消费一次。
- 模型不会直接生成任意 Shell 命令并自动执行。
'''


MANAGED_DIRECTORIES = (
    Path("configs"),
    Path("configs/models"),
    Path("data"),
    Path("runs"),
)


MANAGED_FILES = {
    Path(
        "configs/models/deepseek.local.yaml"
    ): MODEL_CONFIG_TEMPLATE,
    Path(".env.example"): ENV_EXAMPLE_TEMPLATE,
    Path(".gitignore"): GITIGNORE_TEMPLATE,
    Path("QUICKSTART.md"): QUICKSTART_TEMPLATE,
}


class WorkspaceInitError(RuntimeError):
    """工作区无法安全初始化。"""

    def __init__(
        self,
        message: str,
        *,
        conflicts: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(message)
        self.conflicts = conflicts


@dataclass(frozen=True)
class WorkspaceInitReport:
    """工作区初始化报告。"""

    destination: Path
    created_directories: tuple[Path, ...]
    created_files: tuple[Path, ...]
    network_accessed: bool = False
    api_key_written: bool = False
    existing_files_overwritten: bool = False


def find_conflicts(
    destination: Path,
) -> tuple[Path, ...]:
    """在写入前检查所有受管路径。"""
    conflicts: list[Path] = []

    if (
        destination.exists()
        and not destination.is_dir()
    ):
        return (destination,)

    for relative_path in MANAGED_DIRECTORIES:
        path = destination / relative_path

        if path.exists() and not path.is_dir():
            conflicts.append(path)

    for relative_path in MANAGED_FILES:
        path = destination / relative_path

        if path.exists():
            conflicts.append(path)

    return tuple(conflicts)


def initialize_workspace(
    destination: Path,
) -> WorkspaceInitReport:
    """
    创建工作区。

    已存在的无关文件不会被删除。
    受管文件存在时，在任何写入发生前停止。
    """
    resolved_destination = (
        destination.expanduser().resolve()
    )

    conflicts = find_conflicts(
        resolved_destination
    )

    if conflicts:
        rendered = ", ".join(
            str(path)
            for path in conflicts
        )

        raise WorkspaceInitError(
            "工作区中存在不可覆盖的路径："
            f"{rendered}",
            conflicts=conflicts,
        )

    created_directories: list[Path] = []
    created_files: list[Path] = []

    try:
        if not resolved_destination.exists():
            resolved_destination.mkdir(
                parents=True,
                exist_ok=False,
            )
            created_directories.append(
                resolved_destination
            )

        for relative_path in MANAGED_DIRECTORIES:
            path = (
                resolved_destination
                / relative_path
            )

            if not path.exists():
                path.mkdir(
                    parents=True,
                    exist_ok=False,
                )
                created_directories.append(path)

        for relative_path, content in (
            MANAGED_FILES.items()
        ):
            path = (
                resolved_destination
                / relative_path
            )

            with path.open(
                "x",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                handle.write(content)

            created_files.append(path)

    except Exception:
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass

        for path in reversed(
            created_directories
        ):
            try:
                path.rmdir()
            except OSError:
                pass

        raise

    return WorkspaceInitReport(
        destination=resolved_destination,
        created_directories=tuple(
            created_directories
        ),
        created_files=tuple(created_files),
        network_accessed=False,
        api_key_written=False,
        existing_files_overwritten=False,
    )


def render_workspace_init_report(
    report: WorkspaceInitReport,
) -> str:
    """生成终端报告。"""
    lines = [
        "=" * 72,
        "Protein Design Agent Workspace",
        "=" * 72,
        f"工作区：{report.destination}",
        "",
        "已创建文件：",
    ]

    for path in report.created_files:
        relative_path = path.relative_to(
            report.destination
        )
        lines.append(
            f"  - {relative_path}"
        )

    lines.extend(
        [
            "",
            "安全状态：",
            "  网络访问：否",
            "  写入真实 API Key：否",
            "  覆盖已有文件：否",
            "",
            "下一步：",
            f"  cd {report.destination}",
            (
                "  export "
                'DEEPSEEK_API_KEY="你的真实 API Key"'
            ),
            (
                "  protein-design-agent doctor "
                "--model-config "
                "configs/models/deepseek.local.yaml "
                "--profile deepseek_flash"
            ),
            "  protein-design-agent chat --help",
        ]
    )

    return "\n".join(lines)
