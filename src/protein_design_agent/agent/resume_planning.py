#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NEEDS_INFORMATION 的 legacy 语义提取适配层。

本模块保留旧 StructuredJSONProvider 路径：
1. 第一遍补充信息提取；
2. 第二遍完整性审查；
3. 确定性合并两遍模型结果；
4. 委托 planning_session_resume 完成可信状态修改。

确定性的 PlanningSession 续接逻辑不再由本模块拥有。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.agent.planning_session_resume import (
    WorkflowRunner,
    ResumePlanningError,
    ResumePlanningResult,
    SupplementExtraction,
    UserRequestPatch,
    conversation_evidence_text,
    resume_planning_session_from_extraction,
    validate_incomplete_bundle,
    validate_supplement_evidence,
)


def extract_supplement_patch(
    *,
    provider: StructuredJSONProvider,
    supplement_text: str,
    session: PlanningSession,
) -> SupplementExtraction:
    """让模型只提取本轮明确给出的补充字段。"""
    clean_text = supplement_text.strip()

    if not clean_text:
        raise ResumePlanningError(
            "补充文本不能为空"
        )

    schema = (
        SupplementExtraction.model_json_schema()
    )

    current_request = (
        session.request.model_dump(
            mode="json"
        )
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是蛋白设计任务的受控语义解析器。"
                "请阅读并理解用户完整句子的含义，"
                "不是做关键词匹配。"

                "只提取用户在本轮文本中明确表达的信息，"
                "不得根据生物学常识、文件名或旧值猜测。"

                "一句话可能同时明确表达多个字段，"
                "必须把所有明确字段完整提取，不能只取一个。"

                "语义示例："
                "‘target 和 binder 拼在同一条 A 链中’"
                "同时表示 input_layout="
                "concatenated_single_chain，"
                "以及 source_chain=A。"

                "‘前 132 个残基是 target，从第 4 号开始’"
                "同时表示 target_residue_count=132，"
                "以及 target_start_residue=4。"

                "‘原文件已经分成 A、B 两条链，B 是 binder’"
                "表示 input_layout=existing_chains、"
                "binder_chain=B；"
                "只有用户明确说 A 是 target 时，"
                "才提取 target_chains=[A]。"

                "不同措辞只要语义相同，也应正确理解；"
                "不得要求用户使用字段名、固定短语或命令格式。"

                "patch 中每个实际提取的字段，"
                "都必须在 evidence 中给出一段用户原话。"
                "evidence 的键必须与 patch 字段完全一致，"
                "引用内容必须逐字来自 supplement_text。"

                "未提及字段必须省略，不要输出 null。"
                "不得输出 raw_text、task_type、"
                "execute_requested 或任何 Shell 命令。"
                "输出必须严格符合给定 JSON Schema。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_request": (
                        current_request
                    ),
                    "currently_missing": (
                        session.plan
                        .missing_information
                    ),
                    "supplement_text": (
                        clean_text
                    ),
                    "required_schema": schema,
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]

    try:
        payload = provider.generate_json(
            messages
        )
    except Exception as exc:
        raise ResumePlanningError(
            f"补充信息模型解析失败：{exc}"
        ) from exc

    try:
        extraction = (
            SupplementExtraction.model_validate(
                payload
            )
        )
    except ValidationError as exc:
        raise ResumePlanningError(
            "补充信息没有通过结构验证：\n"
            f"{exc}"
        ) from exc

    validate_supplement_evidence(
        extraction=extraction,
        supplement_text=clean_text,
    )

    return extraction


def audit_omitted_explicit_fields(
    *,
    provider: StructuredJSONProvider,
    supplement_text: str,
    session: PlanningSession,
    primary_extraction: SupplementExtraction,
) -> SupplementExtraction:
    """
    第二遍语义审查。

    目标不是重新修改所有参数，而是检查：
    用户原话中是否存在第一遍遗漏的明确字段。
    """
    conversation_text = conversation_evidence_text(
        session=session,
        supplement_text=supplement_text,
    )

    explicit_fields = set(
        session.request_explicit_fields
        or []
    )

    request_data = session.request.model_dump(
        mode="json"
    )

    confirmed_information = {
        field_name: request_data.get(
            field_name
        )
        for field_name in sorted(
            explicit_fields
        )
    }

    primary_patch = (
        primary_extraction.patch.model_dump(
            mode="json",
            exclude_none=True,
        )
    )

    schema = (
        SupplementExtraction.model_json_schema()
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是蛋白设计任务的第二遍语义完整性审查器。"
                "请重新阅读全部用户原话，检查第一遍解析"
                "是否遗漏了用户已经明确表达的参数。"

                "这不是关键词匹配。"
                "你需要理解完整句子的语义关系。"

                "只能补充用户原话明确表达、"
                "但 confirmed_information 和 primary_patch "
                "中尚未记录的字段。"

                "不得修改或覆盖已经确认的字段。"
                "不得根据系统默认值、生物学常识、文件名、"
                "目录内容或模型猜测补参数。"

                "一句话可能表达多个字段。"
                "例如‘target 和 binder 拼在同一条 A 链中’"
                "同时表达 input_layout="
                "concatenated_single_chain 和 source_chain=A。"

                "例如‘target 从第 4 个残基开始，共 132 个’"
                "同时表达 target_start_residue=4 和"
                " target_residue_count=132。"

                "若没有遗漏字段，patch 输出空对象。"

                "patch 中每个字段都必须在 evidence 中"
                "提供逐字来自 conversation_text 的原文依据。"
                "未提及字段必须省略，不要输出 null。"

                "不得输出 raw_text、task_type、"
                "execute_requested、批准指令、执行指令"
                "或任何 Shell 命令。"

                "输出必须严格符合 JSON Schema。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "conversation_text": (
                        conversation_text
                    ),
                    "confirmed_information": (
                        confirmed_information
                    ),
                    "primary_patch": (
                        primary_patch
                    ),
                    "currently_missing": (
                        session.plan
                        .missing_information
                    ),
                    "required_schema": schema,
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]

    try:
        payload = provider.generate_json(
            messages
        )
    except Exception as exc:
        raise ResumePlanningError(
            f"补充信息完整性审查失败：{exc}"
        ) from exc

    try:
        extraction = (
            SupplementExtraction.model_validate(
                payload
            )
        )
    except ValidationError as exc:
        raise ResumePlanningError(
            "完整性审查结果没有通过结构验证：\n"
            f"{exc}"
        ) from exc

    validate_supplement_evidence(
        extraction=extraction,
        supplement_text=conversation_text,
    )

    return extraction


def combine_supplement_extractions(
    *,
    session: PlanningSession,
    primary: SupplementExtraction,
    audit: SupplementExtraction,
) -> SupplementExtraction:
    """
    确定性合并第一遍提取和第二遍审查。

    安全规则：
    - 审查不能修改旧的显式字段；
    - 审查不能与第一遍提取发生冲突；
    - 相同的重复字段可以忽略；
    - 只有带原文证据的新字段才能加入。
    """
    explicit_fields = set(
        session.request_explicit_fields
        or []
    )

    current_request = (
        session.request.model_dump(
            mode="python"
        )
    )

    primary_data = (
        primary.patch.model_dump(
            mode="python",
            exclude_none=True,
        )
    )

    audit_data = (
        audit.patch.model_dump(
            mode="python",
            exclude_none=True,
        )
    )

    combined_data = dict(
        primary_data
    )

    combined_evidence = dict(
        primary.evidence
    )

    for field_name, audit_value in (
        audit_data.items()
    ):
        if field_name in explicit_fields:
            current_value = (
                current_request.get(
                    field_name
                )
            )

            if current_value != audit_value:
                raise ResumePlanningError(
                    "完整性审查试图修改用户已经确认的字段："
                    f"{field_name!r}；"
                    f"旧值={current_value!r}，"
                    f"审查值={audit_value!r}"
                )

            # 同值重复，不需要再次加入。
            continue

        if field_name in primary_data:
            primary_value = (
                primary_data[field_name]
            )

            if primary_value != audit_value:
                raise ResumePlanningError(
                    "两遍语义提取结果发生冲突："
                    f"{field_name!r}；"
                    f"第一遍={primary_value!r}，"
                    f"第二遍={audit_value!r}"
                )

            # 同值重复，保留第一遍结果。
            continue

        combined_data[field_name] = (
            audit_value
        )

        combined_evidence[field_name] = (
            audit.evidence[field_name]
        )

    combined_notes = [
        *primary.notes,
        *[
            f"completeness_audit: {note}"
            for note in audit.notes
        ],
    ]

    return SupplementExtraction(
        patch=UserRequestPatch.model_validate(
            combined_data
        ),
        evidence=combined_evidence,
        notes=combined_notes,
    )


def resume_planning_session(
    *,
    bundle_dir: Path,
    supplement_text: str,
    provider: StructuredJSONProvider,
    runner: WorkflowRunner | None = None,
) -> ResumePlanningResult:
    """
    续接一个 NEEDS_INFORMATION 任务。

    该函数不会执行 BinderRanker。
    """
    bundle = bundle_dir.resolve()

    if not isinstance(
        provider,
        StructuredJSONProvider,
    ):
        raise ResumePlanningError(
            "Provider 不支持受控结构化 JSON 生成"
        )

    (
        session_path,
        manifest_path,
        old_session,
    ) = validate_incomplete_bundle(bundle)

    if provider.name != (
        old_session.provider_name
    ):
        raise ResumePlanningError(
            "续接 Provider 与原会话不一致："
            f"原={old_session.provider_name!r}, "
            f"当前={provider.name!r}"
        )

    primary_extraction = (
        extract_supplement_patch(
            provider=provider,
            supplement_text=supplement_text,
            session=old_session,
        )
    )

    audit_extraction = (
        audit_omitted_explicit_fields(
            provider=provider,
            supplement_text=supplement_text,
            session=old_session,
            primary_extraction=(
                primary_extraction
            ),
        )
    )

    extraction = (
        combine_supplement_extractions(
            session=old_session,
            primary=primary_extraction,
            audit=audit_extraction,
        )
    )

    return resume_planning_session_from_extraction(
        bundle_dir=bundle,
        supplement_text=supplement_text,
        extraction=extraction,
        runner=runner,
    )
