#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PlanningSession 的确定性续接服务。

本模块负责：
- 不完整 Bundle 的安全验证；
- 请求补丁的确定性合并；
- 用户文本证据校验；
- PlanningSession 重建；
- 历史记录与原子持久化；
- READY_FOR_REVIEW 安全晋升。

本模块不依赖模型 Provider。
不同来源必须在进入
apply_validated_request_patch() 前完成各自的来源可信性验证。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.prepare_pipeline import (
    load_planning_session,
    prepare_agent_run,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


WorkflowRunner = Callable[
    [list[str], Path, Path],
    int,
]


class ResumePlanningError(RuntimeError):
    """规划会话续接失败。"""


class UserRequestPatch(BaseModel):
    """
    本轮补充文本中明确出现的字段。

    所有字段默认 None，模型必须省略未提及字段。
    不允许模型修改 raw_text、task_type，
    也不允许通过补充文本直接批准执行。
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


class SupplementExtraction(BaseModel):
    """
    模型对本轮补充文本的结构化提取。

    evidence 的键必须对应 patch 中实际提取的字段，
    值必须引用用户本轮原话中的依据。
    """

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


class ResumePlanningResult(BaseModel):
    """一次规划续接的公开返回结果。"""

    schema_version: str = "0.1"

    status: Literal[
        "NEEDS_INFORMATION",
        "READY_FOR_REVIEW",
    ]

    provider_name: str
    bundle_directory: Path

    planning_session: Path
    prepare_manifest: Path
    history_record: Path

    missing_information: list[str] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(
        default_factory=list
    )

    project_name: str | None = None
    project_config: Path | None = None
    workflow_directory: Path | None = None
    workflow_manifest: Path | None = None

    scientific_workflow_executed: bool = False
    binderranker_executed: bool = False
    remote_backend_used: bool = False


MISSING_FIELD_OVERRIDE_MAP: dict[
    str,
    set[str],
] = {
    "input_dir": {
        "input_dir",
    },
    "input_layout": {
        "input_layout",
    },
    "binder_chain": {
        "binder_chain",
    },
    "source_chain": {
        "source_chain",
    },
    "target_residue_count": {
        "target_residue_count",
    },
    "distinct_normalized_chain_ids": {
        "normalized_target_chain",
        "normalized_binder_chain",
    },
    "desired_regions_or_hotspots": {
        "desired_regions",
        "hotspots",
    },
    "region_filter_soft_or_strict": {
        "region_filter",
    },
}


ALLOWED_INCOMPLETE_BUNDLE_ITEMS = {
    "planning_session.json",
    "agent_prepare_manifest.json",
    "history",
    "chat",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(
    path: Path,
    content: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_bytes_atomically(
    path: Path,
    content: bytes,
) -> None:
    """在同一目录中写临时文件后原子替换。"""
    temporary = path.with_name(
        path.name
        + f".tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )

    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            path,
        )

    finally:
        temporary.unlink(
            missing_ok=True
        )


def validate_incomplete_chat_directory(
    bundle_dir: Path,
) -> None:
    """
    校验不完整任务中的 Chat 辅助目录。

    只允许已知的对话侧车文件，避免任意内容绕过
    不完整 Bundle 的覆盖保护。
    """
    chat_dir = (
        bundle_dir.resolve()
        / "chat"
    )

    if not chat_dir.exists():
        return

    if not chat_dir.is_dir():
        raise ResumePlanningError(
            f"Chat 辅助路径不是目录：{chat_dir}"
        )

    allowed_items = {
        "dataset_advice.json",
        "pending_action.json",
    }

    unknown_items = sorted(
        item.name
        for item in chat_dir.iterdir()
        if item.name not in allowed_items
    )

    if unknown_items:
        raise ResumePlanningError(
            "Chat 辅助目录包含未知内容，"
            "为避免覆盖或采用未经审计的数据，"
            "拒绝续接："
            + ", ".join(unknown_items)
        )

    for item in chat_dir.iterdir():
        if not item.is_file():
            raise ResumePlanningError(
                "Chat 辅助目录只允许普通文件："
                f"{item}"
            )


def validate_incomplete_bundle(
    bundle_dir: Path,
) -> tuple[Path, Path, PlanningSession]:
    """验证该目录确实是可续接的不完整任务。"""
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        raise ResumePlanningError(
            f"任务目录不存在：{bundle}"
        )

    unknown_items = sorted(
        item.name
        for item in bundle.iterdir()
        if item.name
        not in ALLOWED_INCOMPLETE_BUNDLE_ITEMS
    )

    if unknown_items:
        raise ResumePlanningError(
            "任务目录包含不属于不完整规划会话的内容，"
            "为避免覆盖正式任务，拒绝续接："
            + ", ".join(unknown_items)
        )

    validate_incomplete_chat_directory(
        bundle
    )

    session_path = (
        bundle / "planning_session.json"
    )
    manifest_path = (
        bundle / "agent_prepare_manifest.json"
    )

    if not session_path.is_file():
        raise ResumePlanningError(
            f"缺少规划会话：{session_path}"
        )

    if not manifest_path.is_file():
        raise ResumePlanningError(
            f"缺少准备清单：{manifest_path}"
        )

    try:
        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        raise ResumePlanningError(
            f"无法读取准备清单：{exc}"
        ) from exc

    if not isinstance(manifest, dict):
        raise ResumePlanningError(
            "准备清单必须是 JSON 对象"
        )

    if manifest.get("status") != (
        "NEEDS_INFORMATION"
    ):
        raise ResumePlanningError(
            "只有 NEEDS_INFORMATION 任务"
            "可以续接；当前准备清单状态为 "
            f"{manifest.get('status')!r}"
        )

    try:
        session = load_planning_session(
            session_path
        )
    except ValueError as exc:
        raise ResumePlanningError(
            str(exc)
        ) from exc

    if session.plan.status != (
        "NEEDS_INFORMATION"
    ):
        raise ResumePlanningError(
            "规划会话本身不是 "
            "NEEDS_INFORMATION 状态"
        )

    if session.request_explicit_fields is None:
        raise ResumePlanningError(
            "该任务来自旧版规划会话，"
            "没有字段来源记录，不能安全续接。"
            "请保留该目录作为历史记录，"
            "并使用新的 bundle 重新开始。"
        )

    return (
        session_path,
        manifest_path,
        session,
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


def validate_supplement_evidence(
    *,
    extraction: SupplementExtraction,
    supplement_text: str,
) -> None:
    """
    确认每个提取字段都有用户原话依据。

    该校验不判断科研含义，只判断：
    - evidence 与 patch 字段一致；
    - 引用文字确实来自本轮用户输入。
    """
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
        raise ResumePlanningError(
            "模型提取字段缺少用户原文依据："
            f"{missing_evidence}"
        )

    unexpected_evidence = sorted(
        evidence_fields - patch_fields
    )

    if unexpected_evidence:
        raise ResumePlanningError(
            "模型为未提取字段提供了多余依据："
            f"{unexpected_evidence}"
        )

    normalized_source = (
        normalize_evidence_text(
            supplement_text
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
        raise ResumePlanningError(
            "模型提供的依据不是用户本轮原话："
            f"{sorted(invalid_quotes)}"
        )


def is_empty_value(value: Any) -> bool:
    return (
        value is None
        or value == ""
        or value == []
    )


def normalized_value(value: Any) -> Any:
    """仅用于确定性相等判断。"""
    if isinstance(value, Path):
        return value.expanduser().resolve()

    if isinstance(value, list):
        return tuple(value)

    return value


def allowed_override_fields(
    missing_information: list[str],
) -> set[str]:
    allowed: set[str] = set()

    for missing in missing_information:
        allowed.update(
            MISSING_FIELD_OVERRIDE_MAP.get(
                missing,
                set(),
            )
        )

    return allowed


def merge_request_patch(
    *,
    old_request: UserRequest,
    old_missing_information: list[str],
    old_explicit_fields: set[str],
    patch: UserRequestPatch,
    supplement_text: str,
) -> tuple[UserRequest, list[str]]:
    """
    合并用户本轮明确提供的补充字段。

    安全与来源规则：
    - 空字段或当前缺失字段可以补充；
    - 系统默认值可以被用户明确覆盖；
    - 用户给出的值即使与系统默认值相同，
      也必须登记为新的显式来源；
    - 已经由用户确认的非空字段不能被静默修改；
    - 已确认字段的同值重复不会产生伪更新。
    """
    merged = old_request.model_dump(
        mode="python"
    )

    overrides = allowed_override_fields(
        old_missing_information
    )

    accepted_fields: list[str] = []
    conflicts: list[str] = []

    for field_name in sorted(
        patch.model_fields_set
    ):
        new_value = getattr(
            patch,
            field_name
        )

        if new_value is None:
            continue

        old_value = getattr(
            old_request,
            field_name
        )

        values_equal = (
            normalized_value(old_value)
            == normalized_value(new_value)
        )

        if values_equal:
            if field_name not in old_explicit_fields:
                # 数值虽然与系统默认值相同，
                # 但用户已经在本轮明确确认该值。
                #
                # 必须将该字段加入 accepted_fields，
                # 使 request_explicit_fields 的来源从
                # SYSTEM_DEFAULT 升级为 USER_EXPLICIT。
                merged[field_name] = new_value
                accepted_fields.append(
                    field_name
                )

            # 如果该字段此前已经由用户明确确认，
            # 本轮只是同值重复，不制造伪更新。
            continue

        if (
            field_name not in old_explicit_fields
            or field_name in overrides
            or is_empty_value(old_value)
        ):
            merged[field_name] = new_value
            accepted_fields.append(
                field_name
            )
            continue

        conflicts.append(
            (
                f"{field_name}: "
                f"旧值={old_value!r}, "
                f"补充值={new_value!r}"
            )
        )

    if conflicts:
        raise ResumePlanningError(
            "补充内容试图修改已经确认的字段；"
            "当前版本不允许静默覆盖：\n- "
            + "\n- ".join(conflicts)
        )

    if not accepted_fields:
        raise ResumePlanningError(
            "补充文本没有提供新的可用字段。"
            "请回答当前缺失的问题；"
            "修改已确认参数需要重新建立任务。"
        )

    merged["raw_text"] = (
        old_request.raw_text.rstrip()
        + "\n\n[补充信息]\n"
        + supplement_text.strip()
    )

    try:
        request = UserRequest.model_validate(
            merged
        )
    except ValidationError as exc:
        raise ResumePlanningError(
            "合并后的用户请求无法通过结构验证：\n"
            f"{exc}"
        ) from exc

    return request, accepted_fields


def next_history_directory(
    history_root: Path,
) -> Path:
    history_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    indexes: list[int] = []

    for path in history_root.glob(
        "resume_*"
    ):
        suffix = path.name.removeprefix(
            "resume_"
        )

        if suffix.isdigit():
            indexes.append(int(suffix))

    next_index = (
        max(indexes, default=0) + 1
    )

    return (
        history_root
        / f"resume_{next_index:04d}"
    )


def save_history_record(
    *,
    destination_bundle: Path,
    previous_bundle: Path,
    supplement_text: str,
    extraction: SupplementExtraction,
    merged_session: PlanningSession,
    accepted_fields: list[str],
) -> Path:
    """保存本轮续接的完整审计记录。"""
    history_directory = (
        next_history_directory(
            destination_bundle / "history"
        )
    )

    history_directory.mkdir(
        parents=False,
        exist_ok=False,
    )

    previous_session = (
        previous_bundle
        / "planning_session.json"
    )
    previous_manifest = (
        previous_bundle
        / "agent_prepare_manifest.json"
    )

    shutil.copy2(
        previous_session,
        history_directory
        / "previous_planning_session.json",
    )

    shutil.copy2(
        previous_manifest,
        history_directory
        / "previous_prepare_manifest.json",
    )

    (
        history_directory / "supplement.txt"
    ).write_text(
        supplement_text.strip() + "\n",
        encoding="utf-8",
    )

    write_json(
        history_directory
        / "supplement_extraction.json",
        extraction.model_dump(
            mode="json",
            exclude_none=True,
        ),
    )

    (
        history_directory
        / "merged_planning_session.json"
    ).write_text(
        merged_session.model_dump_json(
            indent=2
        )
        + "\n",
        encoding="utf-8",
    )

    write_json(
        history_directory
        / "resume_record.json",
        {
            "schema_version": "0.1",
            "status": (
                merged_session.plan.status
            ),
            "provider_name": (
                merged_session.provider_name
            ),
            "accepted_fields": (
                accepted_fields
            ),
            "missing_information": (
                merged_session.plan
                .missing_information
            ),
            "binderranker_executed": False,
            "remote_backend_used": False,
        },
    )

    return history_directory


def update_incomplete_bundle(
    *,
    bundle_dir: Path,
    previous_session_path: Path,
    previous_manifest_path: Path,
    merged_session: PlanningSession,
    supplement_text: str,
    extraction: SupplementExtraction,
    accepted_fields: list[str],
) -> ResumePlanningResult:
    """原子更新仍然缺少信息的会话。"""
    old_session_bytes = (
        previous_session_path.read_bytes()
    )
    old_manifest_bytes = (
        previous_manifest_path.read_bytes()
    )

    history_record = save_history_record(
        destination_bundle=bundle_dir,
        previous_bundle=bundle_dir,
        supplement_text=supplement_text,
        extraction=extraction,
        merged_session=merged_session,
        accepted_fields=accepted_fields,
    )

    session_bytes = (
        merged_session.model_dump_json(
            indent=2
        )
        + "\n"
    ).encode("utf-8")

    manifest = {
        "schema_version": "0.2",
        "status": "NEEDS_INFORMATION",
        "provider_name": (
            merged_session.provider_name
        ),
        "bundle_directory": str(
            bundle_dir
        ),
        "planning_session": str(
            previous_session_path
        ),
        "planning_session_sha256": (
            sha256_bytes(session_bytes)
        ),
        "missing_information": (
            merged_session.plan
            .missing_information
        ),
        "warnings": (
            merged_session.plan.warnings
        ),
        "scientific_workflow_executed": False,
        "binderranker_executed": False,
        "remote_backend_used": False,
    }

    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    try:
        write_bytes_atomically(
            previous_session_path,
            session_bytes,
        )

        write_bytes_atomically(
            previous_manifest_path,
            manifest_bytes,
        )

    except BaseException:
        write_bytes_atomically(
            previous_session_path,
            old_session_bytes,
        )

        write_bytes_atomically(
            previous_manifest_path,
            old_manifest_bytes,
        )

        raise

    return ResumePlanningResult(
        status="NEEDS_INFORMATION",
        provider_name=(
            merged_session.provider_name
        ),
        bundle_directory=bundle_dir,
        planning_session=(
            previous_session_path
        ),
        prepare_manifest=(
            previous_manifest_path
        ),
        history_record=history_record,
        missing_information=(
            merged_session.plan
            .missing_information
        ),
        warnings=(
            merged_session.plan.warnings
        ),
        scientific_workflow_executed=False,
        binderranker_executed=False,
        remote_backend_used=False,
    )


def promote_to_ready_for_review(
    *,
    bundle_dir: Path,
    merged_session: PlanningSession,
    supplement_text: str,
    extraction: SupplementExtraction,
    accepted_fields: list[str],
    runner: WorkflowRunner | None,
) -> ResumePlanningResult:
    """
    先暂存旧 bundle，再使用原路径进行完整 prepare。

    因 prepare 清单记录绝对路径，不能在 staging 路径中
    prepare 后直接改名；必须让 prepare 从一开始就在最终路径运行。
    """
    parent = bundle_dir.parent

    transaction_id = uuid.uuid4().hex

    backup_bundle = (
        parent
        / (
            f".{bundle_dir.name}."
            f"resume-backup.{transaction_id}"
        )
    )

    if backup_bundle.exists():
        raise ResumePlanningError(
            f"事务备份目录意外存在：{backup_bundle}"
        )

    with tempfile.TemporaryDirectory(
        prefix="protein-design-resume-",
        dir=parent,
    ) as temporary_directory:
        temporary_session = (
            Path(temporary_directory)
            / "planning_session.json"
        )

        temporary_session.write_text(
            merged_session.model_dump_json(
                indent=2
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            bundle_dir,
            backup_bundle,
        )

        try:
            prepared = prepare_agent_run(
                session_path=temporary_session,
                bundle_dir=bundle_dir,
                runner=runner,
            )

            previous_history = (
                backup_bundle / "history"
            )

            if previous_history.is_dir():
                shutil.copytree(
                    previous_history,
                    bundle_dir / "history",
                    dirs_exist_ok=True,
                )

            previous_advice = (
                backup_bundle
                / "chat"
                / "dataset_advice.json"
            )

            if previous_advice.is_file():
                destination_advice = (
                    bundle_dir
                    / "chat"
                    / "dataset_advice.json"
                )

                destination_advice.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                shutil.copy2(
                    previous_advice,
                    destination_advice,
                )

            history_record = save_history_record(
                destination_bundle=bundle_dir,
                previous_bundle=backup_bundle,
                supplement_text=(
                    supplement_text
                ),
                extraction=extraction,
                merged_session=merged_session,
                accepted_fields=accepted_fields,
            )

        except BaseException as exc:
            if bundle_dir.exists():
                shutil.rmtree(
                    bundle_dir,
                    ignore_errors=True,
                )

            os.replace(
                backup_bundle,
                bundle_dir,
            )

            if isinstance(
                exc,
                ResumePlanningError,
            ):
                raise

            raise ResumePlanningError(
                "完整准备失败，原不完整任务已恢复："
                f"{exc}"
            ) from exc

        else:
            shutil.rmtree(
                backup_bundle
            )

    return ResumePlanningResult(
        status="READY_FOR_REVIEW",
        provider_name=prepared.provider_name,
        bundle_directory=(
            prepared.bundle_directory
        ),
        planning_session=(
            prepared.session_copy
        ),
        prepare_manifest=(
            prepared.prepare_manifest
        ),
        history_record=history_record,
        missing_information=[],
        warnings=(
            merged_session.plan.warnings
        ),
        project_name=prepared.project_name,
        project_config=prepared.project_config,
        workflow_directory=(
            prepared.workflow_directory
        ),
        workflow_manifest=(
            prepared.workflow_manifest
        ),
        scientific_workflow_executed=False,
        binderranker_executed=False,
        remote_backend_used=False,
    )


def conversation_evidence_text(
    *,
    session: PlanningSession,
    supplement_text: str,
) -> str:
    """
    构造只包含用户原话的审查文本。

    不把系统默认值、模型解释或 Planner 结论
    混入证据文本。
    """
    parts = [
        session.request.raw_text.strip(),
        supplement_text.strip(),
    ]

    return "\n\n".join(
        part
        for part in parts
        if part
    )


def apply_validated_request_patch(
    *,
    bundle_dir: Path,
    previous_session_path: Path,
    previous_manifest_path: Path,
    old_session: PlanningSession,
    supplement_text: str,
    extraction: SupplementExtraction,
    runner: WorkflowRunner | None = None,
) -> ResumePlanningResult:
    """
    应用已经由上层来源验证过的结构化请求补丁。

    本函数不判断补丁来自用户文本、文件证据或其他来源；
    调用方必须先完成对应的来源可信性验证。
    """
    bundle = bundle_dir.resolve()

    merged_request, accepted_fields = (
        merge_request_patch(
            old_request=old_session.request,
            old_missing_information=(
                old_session.plan
                .missing_information
            ),
            old_explicit_fields=set(
                old_session.request_explicit_fields
            ),
            patch=extraction.patch,
            supplement_text=(
                supplement_text
            ),
        )
    )

    merged_plan = build_agent_plan(
        merged_request
    )

    merged_explicit_fields = sorted(
        set(old_session.request_explicit_fields)
        | set(accepted_fields)
    )

    merged_session = PlanningSession(
        provider_name=old_session.provider_name,
        request=merged_request,
        plan=merged_plan,
        request_explicit_fields=(
            merged_explicit_fields
        ),
    )

    if merged_plan.status == (
        "NEEDS_INFORMATION"
    ):
        return update_incomplete_bundle(
            bundle_dir=bundle,
            previous_session_path=(
                previous_session_path
            ),
            previous_manifest_path=(
                previous_manifest_path
            ),
            merged_session=merged_session,
            supplement_text=supplement_text,
            extraction=extraction,
            accepted_fields=accepted_fields,
        )

    if merged_plan.status == (
        "READY_FOR_REVIEW"
    ):
        return promote_to_ready_for_review(
            bundle_dir=bundle,
            merged_session=merged_session,
            supplement_text=supplement_text,
            extraction=extraction,
            accepted_fields=accepted_fields,
            runner=runner,
        )

    raise ResumePlanningError(
        "续接后的计划状态不受支持："
        f"{merged_plan.status}"
    )


def resume_planning_session_from_extraction(
    *,
    bundle_dir: Path,
    supplement_text: str,
    extraction: SupplementExtraction,
    runner: WorkflowRunner | None = None,
) -> ResumePlanningResult:
    """
    使用结构化补充信息确定性续接规划会话。

    该入口不依赖模型 Provider，并会重新验证
    Bundle 状态与用户原文证据。
    """
    bundle = bundle_dir.resolve()

    (
        session_path,
        manifest_path,
        old_session,
    ) = validate_incomplete_bundle(bundle)

    evidence_text = conversation_evidence_text(
        session=old_session,
        supplement_text=supplement_text,
    )

    validate_supplement_evidence(
        extraction=extraction,
        supplement_text=evidence_text,
    )

    return apply_validated_request_patch(
        bundle_dir=bundle,
        previous_session_path=session_path,
        previous_manifest_path=manifest_path,
        old_session=old_session,
        supplement_text=supplement_text,
        extraction=extraction,
        runner=runner,
    )
