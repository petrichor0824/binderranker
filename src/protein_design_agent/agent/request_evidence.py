#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDA 请求字段的确定性原文证据模型。

本模块不负责自然语言理解，也不依赖模型 Provider。
它只验证：
- 结构化 patch 中的显式字段是否都有原文依据；
- evidence 是否包含多余字段；
- 引用是否真实出现在可信用户文本中。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class RequestEvidenceError(RuntimeError):
    """结构化请求字段无法通过原文证据校验。"""


class UserRequestPatch(BaseModel):
    """
    用户文本中明确出现的可修改请求字段。

    所有字段默认 None，未明确出现的字段必须省略。
    不允许修改 raw_text、task_type，
    也不把执行批准作为普通请求字段。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    project_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )

    input_dir: Path | None = None

    input_layout: (
        Literal[
            "existing_chains",
            "concatenated_single_chain",
        ]
        | None
    ) = None

    binder_chain: str | None = None
    target_chains: list[str] | None = None

    source_chain: str | None = None

    target_residue_count: int | None = Field(
        default=None,
        ge=1,
    )

    target_start_residue: int | None = Field(
        default=None,
        ge=1,
    )

    normalized_target_chain: str | None = None
    normalized_binder_chain: str | None = None

    desired_regions: list[str] | None = None
    undesired_regions: list[str] | None = None
    hotspots: list[str] | None = None

    region_policy: (
        Literal[
            "off",
            "diagnostic",
            "weak",
            "constraint",
        ]
        | None
    ) = None

    region_filter: (
        Literal[
            "off",
            "soft",
            "strict",
        ]
        | None
    ) = None

    requested_top_k: int | None = Field(
        default=None,
        ge=1,
    )


class RequestExtraction(BaseModel):
    """结构化请求字段及其用户原文依据。"""

    model_config = ConfigDict(
        extra="forbid"
    )

    patch: UserRequestPatch

    evidence: dict[str, str] = Field(
        default_factory=dict
    )

    notes: list[str] = Field(
        default_factory=list
    )


def normalize_evidence_text(
    value: str,
) -> str:
    """
    用于核对原文引用。

    仅忽略空白差异，不做同义词替换，
    防止模型用改写后的内容冒充用户原话。
    """
    return "".join(
        value.split()
    )


def validate_request_evidence(
    *,
    extraction: RequestExtraction,
    evidence_text: str,
) -> None:
    """确定性验证结构化字段与可信用户原文的一致性。"""
    patch_fields = {
        field_name
        for field_name
        in extraction.patch.model_fields_set
        if getattr(
            extraction.patch,
            field_name,
        ) is not None
    }

    evidence_fields = set(
        extraction.evidence
    )

    missing_evidence = sorted(
        patch_fields - evidence_fields
    )

    if missing_evidence:
        raise RequestEvidenceError(
            "模型提取字段缺少用户原文依据："
            f"{missing_evidence}"
        )

    unexpected_evidence = sorted(
        evidence_fields - patch_fields
    )

    if unexpected_evidence:
        raise RequestEvidenceError(
            "模型为未提取字段提供了多余依据："
            f"{unexpected_evidence}"
        )

    normalized_source = (
        normalize_evidence_text(
            evidence_text
        )
    )

    invalid_quotes: list[str] = []

    for field_name, quote in (
        extraction.evidence.items()
    ):
        clean_quote = quote.strip()

        if (
            not clean_quote
            or normalize_evidence_text(
                clean_quote
            )
            not in normalized_source
        ):
            invalid_quotes.append(
                field_name
            )

    if invalid_quotes:
        raise RequestEvidenceError(
            "模型提供的依据不是用户本轮原话："
            f"{sorted(invalid_quotes)}"
        )
