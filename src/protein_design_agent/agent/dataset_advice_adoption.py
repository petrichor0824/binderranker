#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
将用户确认过的文件证据建议应用到不完整规划会话。

安全边界：
- 只采用 dataset_advice.json 中的条件建议；
- 只允许 input_layout 和 source_chain；
- 重新验证文件集合及 SHA256；
- 不调用大模型；
- 不批准或执行 BinderRanker。
"""

from __future__ import annotations

from pathlib import Path

from protein_design_agent.agent.dataset_advisor import (
    DatasetAdvisorError,
    load_dataset_advice,
    verify_dataset_advice_fresh,
)
from protein_design_agent.agent.planning_session_resume import (
    ResumePlanningError,
    ResumePlanningResult,
    SupplementExtraction,
    UserRequestPatch,
    apply_validated_request_patch,
    validate_incomplete_bundle,
)


class DatasetAdviceAdoptionError(RuntimeError):
    """文件建议无法被安全采用。"""


def adopt_dataset_advice(
    *,
    bundle_dir: Path,
) -> ResumePlanningResult:
    """
    采用已经由用户确认的文件建议。

    本函数只修改规划参数，不批准、不执行 Ranker。
    """
    bundle = bundle_dir.resolve()

    try:
        (
            session_path,
            manifest_path,
            old_session,
        ) = validate_incomplete_bundle(
            bundle
        )
    except ResumePlanningError as exc:
        raise DatasetAdviceAdoptionError(
            str(exc)
        ) from exc

    advice_path = (
        bundle
        / "chat"
        / "dataset_advice.json"
    )

    try:
        advice = load_dataset_advice(
            advice_path
        )

        verify_dataset_advice_fresh(
            advice
        )
    except DatasetAdvisorError as exc:
        raise DatasetAdviceAdoptionError(
            str(exc)
        ) from exc

    if advice.conditional_suggestion is None:
        raise DatasetAdviceAdoptionError(
            "该文件报告没有可供采用的条件建议"
        )

    request_input_dir = (
        old_session.request.input_dir
    )

    if request_input_dir is None:
        raise DatasetAdviceAdoptionError(
            "规划会话尚未记录 input_dir，"
            "无法确认建议对应当前任务"
        )

    if (
        request_input_dir.resolve()
        != advice.input_directory.resolve()
    ):
        raise DatasetAdviceAdoptionError(
            "建议报告的输入目录与当前任务不一致："
            f"任务={request_input_dir.resolve()}；"
            f"建议={advice.input_directory.resolve()}"
        )

    candidate = dict(
        advice.conditional_suggestion
        .candidate_patch
    )

    allowed_fields = {
        "input_layout",
        "source_chain",
    }

    unknown_fields = sorted(
        set(candidate) - allowed_fields
    )

    if unknown_fields:
        raise DatasetAdviceAdoptionError(
            "建议报告试图修改不允许的字段："
            f"{unknown_fields}"
        )

    if (
        candidate.get("input_layout")
        != "concatenated_single_chain"
    ):
        raise DatasetAdviceAdoptionError(
            "当前文件顾问只允许建议"
            " concatenated_single_chain 布局"
        )

    source_chain = candidate.get(
        "source_chain"
    )

    if (
        not isinstance(source_chain, str)
        or not source_chain.strip()
    ):
        raise DatasetAdviceAdoptionError(
            "建议报告缺少有效 source_chain"
        )

    old_explicit = set(
        old_session.request_explicit_fields
        or []
    )

    old_data = old_session.request.model_dump(
        mode="python"
    )

    applicable: dict[str, str] = {}

    for field_name, value in candidate.items():
        if field_name in old_explicit:
            if old_data.get(field_name) != value:
                raise DatasetAdviceAdoptionError(
                    "文件建议与用户已经确认的参数冲突："
                    f"{field_name!r}；"
                    f"已确认值={old_data.get(field_name)!r}，"
                    f"建议值={value!r}"
                )

            # 已确认且值相同，无需重复应用。
            continue

        applicable[field_name] = value

    if not applicable:
        raise DatasetAdviceAdoptionError(
            "文件建议中的参数已经全部存在，"
            "没有需要应用的新字段"
        )

    patch = UserRequestPatch.model_validate(
        applicable
    )

    confirmation_text = (
        "用户确认采用只读 PDB 文件检查建议："
        + ", ".join(
            f"{field_name}={value}"
            for field_name, value
            in sorted(applicable.items())
        )
    )

    extraction = SupplementExtraction(
        patch=patch,
        evidence={},
        notes=[
            "source=FILE_DERIVED",
            "confirmation=USER_CONFIRMED",
            f"dataset_advice={advice_path}",
            "file_sha256_verified=true",
        ],
    )

    try:
        return apply_validated_request_patch(
            bundle_dir=bundle,
            previous_session_path=session_path,
            previous_manifest_path=manifest_path,
            old_session=old_session,
            supplement_text=confirmation_text,
            extraction=extraction,
            runner=None,
        )
    except ResumePlanningError as exc:
        raise DatasetAdviceAdoptionError(
            str(exc)
        ) from exc
