#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""只读采集最近一次失败所需的最小诊断证据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAX_STDERR_LINES = 40
MAX_STDERR_CHARS = 8000


def path_is_inside_bundle(
    path: Path,
    bundle_dir: Path,
) -> bool:
    """只允许读取 Bundle 内部文件。"""
    try:
        path.resolve().relative_to(
            bundle_dir.resolve()
        )
    except ValueError:
        return False

    return True


def read_json_object(
    path: Path,
) -> dict[str, Any] | None:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return None

    return value if isinstance(value, dict) else None


def safe_basename_list(
    value: Any,
) -> list[str]:
    """只保留文件名，不向模型发送完整本地路径。"""
    if not isinstance(value, list):
        return []

    result: list[str] = []

    for item in value[:20]:
        if isinstance(item, str):
            result.append(Path(item).name)

    return result


def read_stderr_tail(
    *,
    manifest: dict[str, Any],
    bundle_dir: Path,
) -> list[str]:
    raw_path = manifest.get("stderr_log")

    if not isinstance(raw_path, str):
        return []

    stderr_path = Path(raw_path)

    if not stderr_path.is_absolute():
        stderr_path = bundle_dir / stderr_path

    stderr_path = stderr_path.resolve()

    if (
        not path_is_inside_bundle(
            stderr_path,
            bundle_dir,
        )
        or not stderr_path.is_file()
    ):
        return []

    try:
        text = stderr_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return []

    lines = text.splitlines()[
        -MAX_STDERR_LINES:
    ]

    joined = "\n".join(lines)

    if len(joined) > MAX_STDERR_CHARS:
        joined = joined[-MAX_STDERR_CHARS:]
        lines = joined.splitlines()

    return lines


def candidate_manifests(
    *,
    bundle_dir: Path,
    error: Exception | None,
) -> list[Path]:
    """显式异常清单优先，其次检查已知清单位置。"""
    candidates: list[Path] = []

    explicit = getattr(
        error,
        "execution_manifest",
        None,
    )

    if isinstance(explicit, Path):
        candidates.append(explicit.resolve())

    candidates.extend(
        bundle_dir.glob("execution_*.json")
    )
    candidates.extend(
        (
            bundle_dir / "analyses"
        ).glob("**/analyze_run_manifest.json")
    )

    unique: dict[Path, None] = {}

    for path in candidates:
        resolved = path.resolve()

        if (
            path_is_inside_bundle(
                resolved,
                bundle_dir,
            )
            and resolved.is_file()
        ):
            unique[resolved] = None

    explicit_path = (
        explicit.resolve()
        if isinstance(explicit, Path)
        else None
    )

    remaining = [
        path
        for path in unique
        if path != explicit_path
    ]

    remaining.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if explicit_path in unique:
        return [explicit_path, *remaining]

    return remaining


def extract_failure_evidence(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    bundle_dir: Path,
) -> dict[str, Any]:
    source_kind = (
        "analysis"
        if manifest_path.name
        == "analyze_run_manifest.json"
        else "execution"
    )

    evidence: dict[str, Any] = {
        "source_kind": source_kind,
        "manifest_path": (
            manifest_path.relative_to(
                bundle_dir
            ).as_posix()
        ),
        "status": manifest.get("status"),
        "error_type": manifest.get(
            "error_type"
        ),
        "error_message": manifest.get(
            "error_message"
        ),
        "return_code": manifest.get(
            "return_code"
        ),
        "execution_attempted": manifest.get(
            "execution_attempted"
        ),
        "process_started": manifest.get(
            "process_started"
        ),
        "binderranker_executed": manifest.get(
            "binderranker_executed"
        ),
        "approval_reusable": manifest.get(
            "approval_reusable"
        ),
        "missing_outputs": safe_basename_list(
            manifest.get("missing_outputs")
        ),
        "empty_outputs": safe_basename_list(
            manifest.get("empty_outputs")
        ),
    }

    stderr_tail = read_stderr_tail(
        manifest=manifest,
        bundle_dir=bundle_dir,
    )

    if stderr_tail:
        evidence["stderr_tail"] = stderr_tail

    return {
        key: value
        for key, value in evidence.items()
        if value not in (None, [], "")
    }


def collect_failure_evidence(
    *,
    bundle_dir: Path,
    error: Exception | None = None,
) -> dict[str, Any]:
    """
    返回最近一份 FAILED 清单的最小证据。

    不读取 traceback、PDB、完整日志或 Bundle 外文件。
    """
    bundle = bundle_dir.resolve()

    if not bundle.is_dir():
        return {}

    for manifest_path in candidate_manifests(
        bundle_dir=bundle,
        error=error,
    ):
        manifest = read_json_object(
            manifest_path
        )

        if (
            manifest is None
            or manifest.get("status") != "FAILED"
        ):
            continue

        return extract_failure_evidence(
            manifest_path=manifest_path,
            manifest=manifest,
            bundle_dir=bundle,
        )

    return {}
