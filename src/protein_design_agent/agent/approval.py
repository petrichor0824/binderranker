#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 执行批准记录。

作用：
1. 检查 Agent 准备任务是否处于 READY_FOR_REVIEW；
2. 检查工作流和 Ranker 计划是否一致；
3. 记录关键配置、脚本和所有标准化 PDB 的 SHA256；
4. 生成一次性的、可追溯的执行批准记录；
5. 本模块只批准，不执行 BinderRanker。

注意：
普通 SHA256 可以验证文件完整性，但不能证明批准者的真实身份。
后续如需多用户服务，可再加入数字签名和账户认证。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


ApprovalStatus = Literal["APPROVED"]
ApprovalScope = Literal["execute_binderranker_once"]


class FileFingerprint(BaseModel):
    """一个文件的完整性指纹。"""

    path: Path
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    size_bytes: int = Field(ge=0)


class DatasetSnapshot(BaseModel):
    """批准时标准化 PDB 数据集的完整快照。"""

    root: Path
    pdb_count: int = Field(ge=1)
    combined_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    files: list[FileFingerprint]


class ApprovalRecord(BaseModel):
    """一次 BinderRanker 执行批准记录。"""

    schema_version: str = "0.1"
    status: ApprovalStatus = "APPROVED"
    approval_scope: ApprovalScope = (
        "execute_binderranker_once"
    )

    approval_id: str
    approval_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    approved_at_utc: str
    approved_by: str = Field(min_length=1)
    approval_note: str = ""

    prepare_manifest: Path
    project_name: str
    provider_name: str

    analysis_scope_level: str
    smoke_test_acknowledged: bool = False

    critical_files: list[FileFingerprint]
    normalized_dataset: DatasetSnapshot

    ranker_path: Path
    ranker_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    binderranker_executed_at_approval: bool = False
    remote_backend_used_at_approval: bool = False


def sha256_file(path: Path) -> str:
    """计算文件 SHA256。"""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def fingerprint_file(path: Path) -> FileFingerprint:
    """读取一个文件的大小和 SHA256。"""
    path = path.resolve()

    if not path.exists():
        raise ValueError(
            f"批准所需文件不存在：{path}"
        )

    if not path.is_file():
        raise ValueError(
            f"批准对象不是普通文件：{path}"
        )

    return FileFingerprint(
        path=path,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def load_json_object(
    path: Path,
    *,
    description: str,
) -> dict[str, Any]:
    """读取一个最外层必须为对象的 JSON 文件。"""
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ValueError(
            f"无法读取{description}：{exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{description}不是合法 JSON："
            f"第 {exc.lineno} 行，第 {exc.colno} 列"
        ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            f"{description}最外层必须是对象"
        )

    return value


def resolve_recorded_path(
    value: Any,
    *,
    base_directory: Path,
    field_name: str,
) -> Path:
    """解析 Manifest 中保存的文件路径。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Manifest 缺少有效路径字段：{field_name}"
        )

    path = Path(value)

    if not path.is_absolute():
        path = base_directory / path

    return path.resolve()


def snapshot_pdb_dataset(
    root: Path,
) -> DatasetSnapshot:
    """
    对标准化 PDB 目录建立确定性快照。

    combined_sha256 同时依赖：
    - 相对路径；
    - 每个文件的 SHA256；
    - 每个文件的字节数。
    """
    root = root.resolve()

    if not root.exists() or not root.is_dir():
        raise ValueError(
            f"标准化 PDB 目录不存在：{root}"
        )

    pdb_paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() == ".pdb"
        ),
        key=lambda item: item.relative_to(
            root
        ).as_posix(),
    )

    if not pdb_paths:
        raise ValueError(
            f"标准化目录中没有 PDB：{root}"
        )

    combined = hashlib.sha256()
    files: list[FileFingerprint] = []

    for path in pdb_paths:
        fingerprint = fingerprint_file(path)
        relative_path = path.relative_to(
            root
        ).as_posix()

        files.append(fingerprint)

        combined.update(
            relative_path.encode("utf-8")
        )
        combined.update(b"\0")
        combined.update(
            fingerprint.sha256.encode("ascii")
        )
        combined.update(b"\0")
        combined.update(
            str(
                fingerprint.size_bytes
            ).encode("ascii")
        )
        combined.update(b"\n")

    return DatasetSnapshot(
        root=root,
        pdb_count=len(files),
        combined_sha256=combined.hexdigest(),
        files=files,
    )


def protect_output_file(path: Path) -> None:
    """默认禁止覆盖已有批准记录。"""
    if path.exists():
        raise ValueError(
            f"批准记录已经存在，禁止覆盖：{path}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def create_approval_record(
    *,
    prepare_manifest_path: Path,
    output_path: Path,
    approved_by: str,
    approval_note: str = "",
    acknowledge_smoke_test: bool = False,
) -> ApprovalRecord:
    """
    为一个 READY_FOR_REVIEW 任务生成执行批准记录。

    本函数不会执行 BinderRanker。
    """
    approved_by = approved_by.strip()

    if not approved_by:
        raise ValueError(
            "approved_by 不能为空"
        )

    prepare_manifest_path = (
        prepare_manifest_path.resolve()
    )
    output_path = output_path.resolve()

    protect_output_file(output_path)

    prepare_manifest = load_json_object(
        prepare_manifest_path,
        description="Agent Prepare Manifest",
    )

    if (
        prepare_manifest.get("status")
        != "READY_FOR_REVIEW"
    ):
        raise ValueError(
            "只有 READY_FOR_REVIEW 任务可以批准；"
            f"当前状态为 "
            f"{prepare_manifest.get('status')}"
        )

    if (
        prepare_manifest.get(
            "binderranker_executed"
        )
        is not False
    ):
        raise ValueError(
            "Manifest 未明确证明 "
            "BinderRanker 尚未执行"
        )

    if (
        prepare_manifest.get(
            "remote_backend_used"
        )
        is not False
    ):
        raise ValueError(
            "当前批准模块只支持本地未执行任务"
        )

    base_directory = (
        prepare_manifest_path.parent
    )

    required_path_fields = [
        "session_copy",
        "project_config",
        "project_provenance",
        "workflow_manifest",
        "ranker_plan",
    ]

    resolved_paths = {
        field: resolve_recorded_path(
            prepare_manifest.get(field),
            base_directory=base_directory,
            field_name=field,
        )
        for field in required_path_fields
    }

    workflow_manifest = load_json_object(
        resolved_paths["workflow_manifest"],
        description="Workflow Manifest",
    )

    if (
        workflow_manifest.get("status")
        != "READY_FOR_REVIEW"
    ):
        raise ValueError(
            "工作流不处于 READY_FOR_REVIEW；"
            f"当前状态为 "
            f"{workflow_manifest.get('status')}"
        )

    ranker_plan = load_json_object(
        resolved_paths["ranker_plan"],
        description="Ranker Execution Plan",
    )

    if ranker_plan.get("execute_requested") is True:
        raise ValueError(
            "Ranker 计划已经标记为请求执行，"
            "不符合审核前状态"
        )

    analysis_scope = (
        workflow_manifest.get(
            "analysis_scope"
        )
        or ranker_plan.get(
            "analysis_scope"
        )
        or {}
    )

    if not isinstance(analysis_scope, dict):
        raise ValueError(
            "analysis_scope 格式错误"
        )

    analysis_level = str(
        analysis_scope.get(
            "level",
            "UNKNOWN",
        )
    )

    if (
        analysis_level == "SMOKE_TEST_ONLY"
        and not acknowledge_smoke_test
    ):
        raise ValueError(
            "当前任务是 SMOKE_TEST_ONLY。"
            "必须显式确认该结果仅用于工程验证，"
            "不能作为正式科研排名。"
        )

    input_directory = resolve_recorded_path(
        ranker_plan.get("input_directory"),
        base_directory=base_directory,
        field_name="input_directory",
    )

    normalized_snapshot = (
        snapshot_pdb_dataset(
            input_directory
        )
    )

    ranker_path = resolve_recorded_path(
        ranker_plan.get("ranker_path"),
        base_directory=base_directory,
        field_name="ranker_path",
    )

    recorded_ranker_sha = ranker_plan.get(
        "ranker_sha256"
    )

    if (
        not isinstance(
            recorded_ranker_sha,
            str,
        )
        or len(recorded_ranker_sha) != 64
    ):
        raise ValueError(
            "Ranker 计划缺少有效 ranker_sha256"
        )

    actual_ranker_sha = sha256_file(
        ranker_path
    )

    if actual_ranker_sha != recorded_ranker_sha:
        raise ValueError(
            "冻结 Ranker 已发生变化：\n"
            f"计划记录：{recorded_ranker_sha}\n"
            f"当前文件：{actual_ranker_sha}"
        )

    critical_paths = [
        prepare_manifest_path,
        resolved_paths["session_copy"],
        resolved_paths["project_config"],
        resolved_paths["project_provenance"],
        resolved_paths["workflow_manifest"],
        resolved_paths["ranker_plan"],
    ]

    critical_files = [
        fingerprint_file(path)
        for path in critical_paths
    ]

    project_name = str(
        prepare_manifest.get(
            "project_name",
            "",
        )
    ).strip()

    provider_name = str(
        prepare_manifest.get(
            "provider_name",
            "",
        )
    ).strip()

    if not project_name:
        raise ValueError(
            "Prepare Manifest 缺少 project_name"
        )

    if not provider_name:
        raise ValueError(
            "Prepare Manifest 缺少 provider_name"
        )

    approved_at = datetime.now(
        timezone.utc
    ).isoformat()

    unsigned_payload = {
        "schema_version": "0.1",
        "status": "APPROVED",
        "approval_scope": (
            "execute_binderranker_once"
        ),
        "approved_at_utc": approved_at,
        "approved_by": approved_by,
        "approval_note": approval_note,
        "prepare_manifest": str(
            prepare_manifest_path
        ),
        "project_name": project_name,
        "provider_name": provider_name,
        "analysis_scope_level": (
            analysis_level
        ),
        "smoke_test_acknowledged": (
            acknowledge_smoke_test
        ),
        "critical_files": [
            item.model_dump(mode="json")
            for item in critical_files
        ],
        "normalized_dataset": (
            normalized_snapshot.model_dump(
                mode="json"
            )
        ),
        "ranker_path": str(ranker_path),
        "ranker_sha256": actual_ranker_sha,
        "binderranker_executed_at_approval": (
            False
        ),
        "remote_backend_used_at_approval": (
            False
        ),
    }

    canonical = json.dumps(
        unsigned_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    approval_digest = hashlib.sha256(
        canonical
    ).hexdigest()

    record = ApprovalRecord(
        approval_id=(
            "apr_" + approval_digest[:16]
        ),
        approval_digest=approval_digest,
        **unsigned_payload,
    )

    output_path.write_text(
        record.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # 写回后再次验证文件，防止序列化错误。
    try:
        reloaded = ApprovalRecord.model_validate_json(
            output_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        ValidationError,
    ) as exc:
        output_path.unlink(
            missing_ok=True
        )
        raise ValueError(
            f"批准记录写入后验证失败：{exc}"
        ) from exc

    if reloaded != record:
        output_path.unlink(
            missing_ok=True
        )
        raise ValueError(
            "批准记录写入前后不一致，"
            "已删除不可靠文件"
        )

    return record
