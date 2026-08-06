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

import json
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_MARKER_TEMPLATE = '''{
  "schema_version": "0.1",
  "workspace_type": "protein-design-agent"
}
'''


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

本目录由 `protein-design-agent init` 创建。

## 目录说明

- `configs/models`：模型 Provider 配置
- `data`：输入 PDB 数据
- `runs`：计划、批准、执行和分析结果

## 1. 检查安装和工作区

以下命令不会访问网络，也不会显示 API Key：

    protein-design-agent doctor \
      --model-config configs/models/deepseek.local.yaml \
      --profile deepseek_flash

## 2. 可选：启用自然语言模型

自然语言任务理解和模型解释需要配置 Provider 和 API Key。

在 Linux、WSL 或 macOS 终端中，复制并运行下面的整行命令：

    read -rsp '请粘贴真实 DeepSeek API Key，然后按回车（输入不会显示）：' DEEPSEEK_API_KEY && echo && export DEEPSEEK_API_KEY

操作说明：

1. 先复制上面的整行命令并按回车。
2. 终端出现提示后，粘贴真实 DeepSeek API Key。
3. 再按一次回车即可，不需要继续输入其他命令。
4. 粘贴 Key 时，屏幕不会显示星号或其他字符，这是正常的安全行为。

不要修改命令末尾的 `DEEPSEEK_API_KEY`。它是模型配置要求的环境变量名，不是填写 API Key 的位置。

不要把真实 API Key 写入 YAML、Git、截图、日志、共享 Bundle，或直接写入可能被 Shell 历史记录的命令。

未配置模型时，`doctor`、样例提取、状态查看和确定性结果分析仍可使用，但不能可靠地把新的自由文本科研需求转换成完整计划。

## 3. 提取内置 smoke 数据

    protein-design-agent extract-sample \
      --destination data/3c98_small

该样例包含 5 个 PDB，只用于安装和工程 smoke test，不能作为正式候选推荐。

## 4. 启动对话式 Agent

    protein-design-agent chat

配置和 API Key 已就绪时，Agent 会询问本次 Chat 是否允许调用模型 API。

选择 `yes` 才会启用模型，并可能产生网络请求和 API 费用；选择 `no` 仍可使用离线确定性功能。

高级用户和自动化脚本可以使用 `--allow-network` 跳过询问，普通用户无需记忆该参数。

模型可用且本次已经授权时，可以输入：

    分析 data/3c98_small，binder 是 B 链。
    这是五个候选的 smoke test，不启用 design region 和 hotspot。

Agent 应先检查 PDB、报告链布局并生成可审查计划，不会立即执行 BinderRanker。

## 5. 查看并批准计划

以下兼容命令已经过测试：

    状态
    查看计划
    批准计划并确认小样本限制

批准会冻结已审查的配置，但不会自动开始执行。

## 6. 执行已批准任务

    确认执行

执行会消费一次性批准。成功后会立即展示紧凑排名预览、主要优势和记录的拖累。

## 7. 分析和查看结果

不调用模型的确定性分析：

    分析结果

查看当前阶段、有效产物和下一步：

    状态

模型可用时，可以另外请求受证据约束的解释：

    分析并解释结果

## 安全边界

- 计划、批准和执行是不同阶段。
- 大模型不能自行批准或执行任务。
- 一次批准只能消费一次。
- 模型不能改写 BinderRanker 分数或确定性 provenance。
- 小样本结果不得作为正式实验候选推荐。
'''


MANAGED_DIRECTORIES = (
    Path("configs"),
    Path("configs/models"),
    Path("data"),
    Path("runs"),
)


MANAGED_FILES = {
    Path(
        ".pda-workspace.json"
    ): WORKSPACE_MARKER_TEMPLATE,
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
    status: str = "CREATED"
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


def detect_existing_workspace(
    destination: Path,
) -> str | None:
    """
    识别已经初始化的工作空间。

    新工作空间优先依据标识文件；
    旧版本工作空间按完整受管目录结构兼容识别。
    用户可以修改模型配置内容，不要求模板完全相同。
    """
    resolved = destination.expanduser().resolve()

    if not resolved.is_dir():
        return None

    marker = (
        resolved / ".pda-workspace.json"
    )

    if marker.is_file():
        try:
            value = json.loads(
                marker.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None

        if (
            isinstance(value, dict)
            and value.get("workspace_type")
            == "protein-design-agent"
            and value.get("schema_version")
            == "0.1"
        ):
            return "REUSED"

        return None

    legacy_files = tuple(
        relative
        for relative in MANAGED_FILES
        if relative
        != Path(".pda-workspace.json")
    )

    directories_exist = all(
        (resolved / relative).is_dir()
        for relative in MANAGED_DIRECTORIES
    )
    files_exist = all(
        (resolved / relative).is_file()
        for relative in legacy_files
    )

    if directories_exist and files_exist:
        return "REUSED_LEGACY"

    return None


def ensure_workspace(
    destination: Path,
) -> WorkspaceInitReport:
    """
    幂等地确保工作空间存在。

    完整工作空间直接复用；
    不完整或冲突结构仍由 initialize_workspace 拒绝，
    不会自动覆盖或修补用户文件。
    """
    resolved = destination.expanduser().resolve()
    existing_status = detect_existing_workspace(
        resolved
    )

    if existing_status is not None:
        return WorkspaceInitReport(
            destination=resolved,
            created_directories=(),
            created_files=(),
            status=existing_status,
            network_accessed=False,
            api_key_written=False,
            existing_files_overwritten=False,
        )

    return initialize_workspace(resolved)


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
            "",
            "  设置 DeepSeek API Key：",
            (
                "  复制并运行下一整行命令；"
                "出现提示后粘贴真实 Key 并按回车。"
            ),
            (
                "  输入时不会显示字符；"
                "命令末尾的 DEEPSEEK_API_KEY 不要修改。"
            ),
            (
                "  read -rsp "
                "'请粘贴真实 DeepSeek API Key，"
                "然后按回车（输入不会显示）：' "
                "DEEPSEEK_API_KEY && echo && "
                "export DEEPSEEK_API_KEY"
            ),
            "",
            (
                "  protein-design-agent doctor "
                "--model-config "
                "configs/models/deepseek.local.yaml "
                "--profile deepseek_flash"
            ),
            "  protein-design-agent chat",
            (
                "  Chat 启动后会询问本次会话"
                "是否允许调用模型 API。"
            ),
        ]
    )

    return "\n".join(lines)
