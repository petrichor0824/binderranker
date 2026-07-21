#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""蛋白设计项目的统一配置模型。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


InputLayout = Literal[
    "existing_chains",
    "concatenated_single_chain",
]

RegionPolicy = Literal[
    "off",
    "diagnostic",
    "weak",
    "constraint",
]

RegionFilter = Literal[
    "off",
    "soft",
    "strict",
]

UnknownSituationPolicy = Literal[
    "stop",
    "ask",
]


class InputConfig(BaseModel):
    """输入 PDB 数据集及其链结构描述。"""

    pdb_dir: Path
    recursive: bool = False

    layout: InputLayout

    # 已经正确分链时使用。
    binder_chain: str | None = None
    target_chains: list[str] = Field(default_factory=list)

    # target 和 binder 拼接在一条链时使用。
    source_chain: str | None = None
    target_residue_count: int | None = Field(
        default=None,
        ge=1,
    )
    target_start_residue: int = 1
    normalized_target_chain: str = "A"
    normalized_binder_chain: str = "B"

    @model_validator(mode="after")
    def validate_layout_fields(self) -> "InputConfig":
        if self.layout == "existing_chains":
            if not self.binder_chain:
                raise ValueError(
                    "layout=existing_chains 时必须填写 binder_chain"
                )

        if self.layout == "concatenated_single_chain":
            if not self.source_chain:
                raise ValueError(
                    "layout=concatenated_single_chain 时"
                    "必须填写 source_chain"
                )

            if self.target_residue_count is None:
                raise ValueError(
                    "layout=concatenated_single_chain 时"
                    "必须填写 target_residue_count"
                )

            if (
                self.normalized_target_chain
                == self.normalized_binder_chain
            ):
                raise ValueError(
                    "标准化后的 target 链与 binder 链不能相同"
                )

        return self


class RegionsConfig(BaseModel):
    """设计区域、排斥区域和 hotspot。"""

    desired: list[str] = Field(default_factory=list)
    undesired: list[str] = Field(default_factory=list)
    hotspots: list[str] = Field(default_factory=list)
    hotspot_expand_radius: float = Field(
        default=8.0,
        gt=0,
    )


class RankingConfig(BaseModel):
    """BinderRanker 的排名策略。"""

    ranker_version: str = "v0.1-expert"

    # 建议第一版默认 diagnostic：
    # 计算 region 指标，但不改变主排名。
    region_policy: RegionPolicy = "diagnostic"
    region_filter: RegionFilter = "off"

    top_k_report: int = Field(default=30, ge=1)
    top_n_sheets: int = Field(default=500, ge=1)


class SafetyConfig(BaseModel):
    """对异常、覆盖和大任务的安全限制。"""

    unknown_situation: UnknownSituationPolicy = "stop"
    allow_overwrite: bool = False

    # 本地测试时可以限制文件数量。
    max_files: int | None = Field(
        default=None,
        ge=1,
    )


class ProjectConfig(BaseModel):
    """一个完整蛋白设计/骨架排名项目。"""

    schema_version: str = "0.1"
    project_name: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    description: str = ""

    input: InputConfig
    regions: RegionsConfig = Field(
        default_factory=RegionsConfig
    )
    ranking: RankingConfig = Field(
        default_factory=RankingConfig
    )
    safety: SafetyConfig = Field(
        default_factory=SafetyConfig
    )


def load_project_config(path: Path) -> ProjectConfig:
    """读取 YAML，并使用 Pydantic 进行严格验证。"""
    try:
        raw = yaml.safe_load(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ValueError(
            f"无法读取配置文件：{exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(
            f"YAML 格式错误：{exc}"
        ) from exc

    if raw is None:
        raise ValueError("配置文件为空")

    if not isinstance(raw, dict):
        raise ValueError(
            "配置文件最外层必须是键值对象"
        )

    return ProjectConfig.model_validate(raw)
