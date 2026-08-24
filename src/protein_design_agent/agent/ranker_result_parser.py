#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
解析一次已经完成的 BinderRanker 本地执行结果。

职责：
1. 确认执行记录为 COMPLETED；
2. 验证四个原始输出文件的大小和 SHA256；
3. 读取 scored.csv 中的候选、排名和过滤原因；
4. 从 report.txt 解析动态过滤阈值；
5. 应用 result_policy，防止小样本池结果被过度解释；
6. 生成派生的 Agent 结构化摘要。

本模块：
- 不修改 Ranker 原始文件；
- 不重新计算 BinderRanker 指标；
- 不调用大模型；
- 不进行正式实验候选推荐。
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from protein_design_agent.agent.approval import (
    FileFingerprint,
    fingerprint_file,
)
from protein_design_agent.agent.result_policy import (
    PoolReportingView,
    build_pool_reporting_view,
)
from protein_design_agent.agent.ranker_report_context import (
    RankerReportContextError,
    parse_boolean_flag as parse_ranker_boolean_flag,
    parse_ranker_report_context,
)
from protein_design_agent.agent.scientific_result_validation import (
    COMPONENT_SCORE_COLUMNS,
    KEY_METRIC_COLUMNS,
    REQUIRED_SCORED_COLUMNS,
    ScientificResultValidationError,
    validate_scientific_result,
)
from protein_design_agent.agent.score_decomposition import (
    ScoreDecompositionError,
    decompose_primary_score,
    validate_primary_score_formula,
)


class RankerResultParseError(RuntimeError):
    """Ranker 结果无法安全解析。"""


class FilterThreshold(BaseModel):
    """一个动态过滤阈值。"""

    metric: str
    direction: Literal["min", "max"]
    value: float
    quantile: float


class CandidateResult(BaseModel):
    """一个候选的确定性解析结果。"""

    pdb_name: str

    # 小样本中仍可用于工程检查的相对排序，
    # 但不能视为正式候选推荐。
    engineering_rank: int = Field(ge=1)
    final_score_v4: float

    raw_filter_level: str
    public_filter_level: str | None
    public_filter_status: str

    broad_pass: bool
    medium_pass: bool
    strict_pass: bool

    broad_reasons: list[str]
    medium_reasons: list[str]
    strict_reasons: list[str]

    filter_reasons_formally_interpretable: bool

    component_scores: dict[str, float]
    key_metrics: dict[str, float]

    primary_score_contributions: dict[
        str,
        float,
    ] = Field(default_factory=dict)
    reconstructed_final_score_v4: (
        float | None
    ) = None
    primary_score_reconstruction_error: (
        float | None
    ) = None

    row_error: str | None = None


class RankerResultSummary(BaseModel):
    """一次 Ranker 执行的安全结构化摘要。"""

    schema_version: str = "0.2"
    status: Literal["PARSED"] = "PARSED"

    project_name: str
    execution_manifest: Path

    analysis_scope: dict[str, Any]
    candidate_count: int = Field(ge=1)

    pool_reporting: PoolReportingView

    # 原始值只用于复现和工程调试。
    raw_filter_level_counts: dict[str, int]

    raw_filter_thresholds: dict[
        str,
        dict[str, FilterThreshold],
    ]
    thresholds_formally_interpretable: bool

    score_decomposition_status: Literal[
        "AVAILABLE",
        "UNAVAILABLE",
    ] = "UNAVAILABLE"
    score_decomposition_reason: str | None = None
    region_score_used: bool | None = None
    primary_score_formula: str | None = None
    primary_score_weights: dict[
        str,
        float,
    ] = Field(default_factory=dict)

    candidates_by_engineering_rank: list[
        CandidateResult
    ]

    formal_candidate_recommendation_allowed: bool
    result_use: str

    source_files: dict[str, Path]


POOL_HEADER_RE = re.compile(
    r"^\s*\[(broad|medium|strict)\]\s*$"
)

THRESHOLD_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+):\s+"
    r"(min|max)\s+\1\s+"
    r"([-+0-9.eE]+)\s+"
    r"\(q=([-+0-9.eE]+)\)\s*$"
)


def load_json_object(
    path: Path,
    *,
    description: str,
) -> dict[str, Any]:
    """读取最外层必须为对象的 JSON。"""
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise RankerResultParseError(
            f"无法读取{description}：{exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RankerResultParseError(
            f"{description}不是合法 JSON："
            f"第 {exc.lineno} 行，第 {exc.colno} 列"
        ) from exc

    if not isinstance(value, dict):
        raise RankerResultParseError(
            f"{description}最外层必须是对象"
        )

    return value


def parse_float(
    row: dict[str, str],
    column: str,
    *,
    pdb_name: str,
) -> float:
    """读取候选行中的必需浮点数。"""
    raw = row.get(column, "")

    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RankerResultParseError(
            f"候选 {pdb_name} 的 {column} "
            f"不是有效数值：{raw!r}"
        ) from exc

    if not math.isfinite(value):
        raise RankerResultParseError(
            f"候选 {pdb_name} 的 {column} "
            f"必须是有限数值，实际为 {raw!r}"
        )

    return value


def parse_int(
    row: dict[str, str],
    column: str,
    *,
    pdb_name: str,
) -> int:
    """读取候选行中的必需整数。"""
    raw = row.get(column, "")

    try:
        numeric = float(raw)
    except (TypeError, ValueError) as exc:
        raise RankerResultParseError(
            f"候选 {pdb_name} 的 {column} "
            f"不是有效整数：{raw!r}"
        ) from exc

    if (
        not math.isfinite(numeric)
        or not numeric.is_integer()
    ):
        raise RankerResultParseError(
            f"候选 {pdb_name} 的 {column} "
            f"不是有效整数：{raw!r}"
        )

    return int(numeric)


def parse_yes_no(
    row: dict[str, str],
    column: str,
    *,
    pdb_name: str,
) -> bool:
    """严格解析 YES / NO。"""
    raw = str(
        row.get(column, "")
    ).strip().upper()

    if raw == "YES":
        return True

    if raw == "NO":
        return False

    raise RankerResultParseError(
        f"候选 {pdb_name} 的 {column} "
        f"必须是 YES 或 NO，实际为 {raw!r}"
    )


def split_reasons(value: str | None) -> list[str]:
    """拆分分号分隔的失败原因。"""
    if value is None:
        return []

    return [
        item.strip()
        for item in value.split(";")
        if item.strip()
    ]


def verify_output_fingerprints(
    execution: dict[str, Any],
) -> dict[str, Path]:
    """
    验证执行记录中的四个 Ranker 输出。

    返回：
    - metrics_csv
    - scored_csv
    - ranking_xlsx
    - report_txt
    """
    raw_outputs = execution.get(
        "output_files"
    )

    if (
        not isinstance(raw_outputs, list)
        or len(raw_outputs) != 4
    ):
        raise RankerResultParseError(
            "执行记录必须包含四个输出文件指纹"
        )

    fingerprints: list[
        FileFingerprint
    ] = []

    for raw in raw_outputs:
        try:
            fingerprints.append(
                FileFingerprint.model_validate(
                    raw
                )
            )
        except Exception as exc:
            raise RankerResultParseError(
                "执行记录包含无效输出文件指纹"
            ) from exc

    for recorded in fingerprints:
        try:
            current = fingerprint_file(
                recorded.path
            )
        except ValueError as exc:
            raise RankerResultParseError(
                str(exc)
            ) from exc

        if (
            current.sha256 != recorded.sha256
            or current.size_bytes
            != recorded.size_bytes
        ):
            raise RankerResultParseError(
                "Ranker 原始输出在执行后发生变化：\n"
                f"文件：{recorded.path}\n"
                f"记录 SHA256：{recorded.sha256}\n"
                f"当前 SHA256：{current.sha256}"
            )

    result: dict[str, Path] = {}

    for item in fingerprints:
        name = item.path.name

        if name.endswith("_metrics.csv"):
            key = "metrics_csv"
        elif name.endswith("_scored.csv"):
            key = "scored_csv"
        elif name.endswith("_ranking.xlsx"):
            key = "ranking_xlsx"
        elif name.endswith("_report.txt"):
            key = "report_txt"
        else:
            raise RankerResultParseError(
                f"无法识别 Ranker 输出文件：{item.path}"
            )

        if key in result:
            raise RankerResultParseError(
                f"检测到重复的 Ranker 输出类型：{key}"
            )

        result[key] = item.path.resolve()

    required = {
        "metrics_csv",
        "scored_csv",
        "ranking_xlsx",
        "report_txt",
    }

    if set(result) != required:
        raise RankerResultParseError(
            "四个 Ranker 输出类型不完整："
            f"{sorted(result)}"
        )

    return result


def parse_filter_thresholds(
    report_path: Path,
) -> dict[
    str,
    dict[str, FilterThreshold],
]:
    """从 Ranker TXT 报告解析动态过滤阈值。"""
    lines = report_path.read_text(
        encoding="utf-8",
        errors="strict",
    ).splitlines()

    result: dict[
        str,
        dict[str, FilterThreshold],
    ] = {
        "broad": {},
        "medium": {},
        "strict": {},
    }

    current_pool: str | None = None

    for line in lines:
        pool_match = POOL_HEADER_RE.match(line)

        if pool_match:
            current_pool = pool_match.group(1)
            continue

        if current_pool is None:
            continue

        threshold_match = THRESHOLD_RE.match(
            line
        )

        if not threshold_match:
            continue

        metric = threshold_match.group(1)
        direction = threshold_match.group(2)
        value = float(
            threshold_match.group(3)
        )
        quantile = float(
            threshold_match.group(4)
        )

        if not (
            math.isfinite(value)
            and math.isfinite(quantile)
        ):
            raise RankerResultParseError(
                "报告中的过滤阈值必须是有限数值："
                f"{current_pool}.{metric}"
            )

        if metric in result[current_pool]:
            raise RankerResultParseError(
                f"报告中重复出现阈值："
                f"{current_pool}.{metric}"
            )

        result[current_pool][metric] = (
            FilterThreshold(
                metric=metric,
                direction=direction,
                value=value,
                quantile=quantile,
            )
        )

    empty_pools = [
        pool
        for pool, thresholds in result.items()
        if not thresholds
    ]

    if empty_pools:
        raise RankerResultParseError(
            "无法从报告解析完整过滤阈值："
            f"{empty_pools}"
        )

    return result


def read_scored_rows(
    path: Path,
) -> list[dict[str, str]]:
    """读取并验证 scored CSV。"""
    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            headers = set(
                reader.fieldnames or []
            )

            missing = sorted(
                REQUIRED_SCORED_COLUMNS
                - headers
            )

            if missing:
                raise RankerResultParseError(
                    "scored CSV 缺少必需列："
                    f"{missing}"
                )

            rows = list(reader)

    except OSError as exc:
        raise RankerResultParseError(
            f"无法读取 scored CSV：{exc}"
        ) from exc

    if not rows:
        raise RankerResultParseError(
            "scored CSV 没有候选数据"
        )

    return rows


def find_execution_manifest(
    bundle_dir: Path,
) -> Path:
    """任务目录中必须只有一个执行记录。"""
    records = sorted(
        bundle_dir.glob(
            "execution_apr_*.json"
        )
    )

    if len(records) != 1:
        raise RankerResultParseError(
            "任务目录中必须正好存在一个执行记录；"
            f"实际为 {len(records)} 个"
        )

    return records[0].resolve()


def parse_completed_ranker_run(
    bundle_dir: Path,
) -> RankerResultSummary:
    """解析一次已经完成的 Ranker 任务。"""
    bundle_dir = bundle_dir.resolve()

    if not bundle_dir.exists():
        raise RankerResultParseError(
            f"任务目录不存在：{bundle_dir}"
        )

    execution_path = find_execution_manifest(
        bundle_dir
    )

    execution = load_json_object(
        execution_path,
        description="Execution Manifest",
    )

    if execution.get("status") != "COMPLETED":
        raise RankerResultParseError(
            "只有 COMPLETED 执行可以解析；"
            f"当前状态为 {execution.get('status')}"
        )

    if execution.get("return_code") != 0:
        raise RankerResultParseError(
            "Execution Manifest 的退出码不是 0"
        )

    if (
        execution.get(
            "binderranker_executed"
        )
        is not True
    ):
        raise RankerResultParseError(
            "执行记录未确认 BinderRanker 已执行"
        )

    source_files = verify_output_fingerprints(
        execution
    )

    workflow_manifest_path = (
        bundle_dir
        / "workflow"
        / "workflow_manifest.json"
    )

    workflow = load_json_object(
        workflow_manifest_path,
        description="Workflow Manifest",
    )

    analysis_scope = workflow.get(
        "analysis_scope"
    )

    if not isinstance(
        analysis_scope,
        dict,
    ):
        raise RankerResultParseError(
            "Workflow Manifest 缺少 analysis_scope"
        )

    rows = read_scored_rows(
        source_files["scored_csv"]
    )

    expected_count = analysis_scope.get(
        "pdb_count"
    )

    if (
        not isinstance(expected_count, int)
        or expected_count < 1
    ):
        raise RankerResultParseError(
            "analysis_scope.pdb_count 无效"
        )

    try:
        validate_scientific_result(
            tuple(source_files.values()),
            expected_candidate_count=(
                expected_count
            ),
        )
    except ScientificResultValidationError as exc:
        raise RankerResultParseError(
            "BinderRanker 原始结果未通过科学语义验证："
            f"{exc}"
        ) from exc

    names = [
        str(row["pdb_name"]).strip()
        for row in rows
    ]

    if any(not name for name in names):
        raise RankerResultParseError(
            "scored CSV 中存在空候选名"
        )

    if len(set(names)) != len(names):
        raise RankerResultParseError(
            "scored CSV 中存在重复候选名"
        )

    raw_pool_counts = {
        "broad": sum(
            parse_yes_no(
                row,
                "filter_broad_pass",
                pdb_name=str(
                    row["pdb_name"]
                ),
            )
            for row in rows
        ),
        "medium": sum(
            parse_yes_no(
                row,
                "filter_medium_pass",
                pdb_name=str(
                    row["pdb_name"]
                ),
            )
            for row in rows
        ),
        "strict": sum(
            parse_yes_no(
                row,
                "filter_strict_pass",
                pdb_name=str(
                    row["pdb_name"]
                ),
            )
            for row in rows
        ),
    }

    pool_reporting = (
        build_pool_reporting_view(
            analysis_scope=analysis_scope,
            raw_pool_counts=raw_pool_counts,
        )
    )

    filter_level_counts = dict(
        Counter(
            str(row["filter_level"]).strip()
            for row in rows
        )
    )

    try:
        report_context = (
            parse_ranker_report_context(
                source_files["report_txt"],
                require_final_formula=False,
            )
        )
    except RankerReportContextError as exc:
        raise RankerResultParseError(
            "Ranker 报告上下文无法解析："
            f"{exc}"
        ) from exc

    region_score_used: bool | None = None
    primary_formula: str | None = None
    score_weights: dict[str, float] = {}
    decomposition_status: Literal[
        "AVAILABLE",
        "UNAVAILABLE",
    ] = "UNAVAILABLE"
    decomposition_reason: str | None = None

    raw_region_score_used = (
        report_context.run_config.get(
            "region_score_used"
        )
    )

    if raw_region_score_used is None:
        decomposition_reason = (
            "Ranker 报告未记录 region_score_used；"
            "保留旧结果兼容性，不推断主分公式"
        )
    else:
        try:
            region_score_used = (
                parse_ranker_boolean_flag(
                    raw_region_score_used,
                    field_name=(
                        "region_score_used"
                    ),
                )
            )
        except RankerReportContextError as exc:
            raise RankerResultParseError(
                "主分分解上下文无效："
                f"{exc}"
            ) from exc

        formula_key = (
            "final_score_v4_region"
            if region_score_used
            else "final_score_v4_original"
        )
        primary_formula = (
            report_context.score_formulas.get(
                formula_key
            )
        )

        if primary_formula is None:
            decomposition_reason = (
                "Ranker 报告未记录本次运行使用的"
                f" {formula_key} 公式；"
                "保留旧结果兼容性，不推断主分公式"
            )
        else:
            try:
                score_weights = (
                    validate_primary_score_formula(
                        primary_formula,
                        region_score_used=(
                            region_score_used
                        )
                    )
                )
            except ScoreDecompositionError as exc:
                raise RankerResultParseError(
                    "主分分解上下文无效："
                    f"{exc}"
                ) from exc

            decomposition_status = "AVAILABLE"

    candidates: list[
        CandidateResult
    ] = []

    for row in rows:
        pdb_name = str(
            row["pdb_name"]
        ).strip()

        engineering_rank = parse_int(
            row,
            "rank_final_score_v4",
            pdb_name=pdb_name,
        )

        raw_filter_level = str(
            row["filter_level"]
        ).strip()

        if (
            pool_reporting.policy.reporting_mode
            == "SUPPRESSED"
        ):
            public_filter_level = None
            public_filter_status = (
                "NOT_AVAILABLE_SMALL_SAMPLE"
            )
        elif (
            pool_reporting.policy.reporting_mode
            == "EXPLORATORY"
        ):
            public_filter_level = (
                raw_filter_level
            )
            public_filter_status = (
                "EXPLORATORY_ONLY"
            )
        else:
            public_filter_level = (
                raw_filter_level
            )
            public_filter_status = (
                "REPORTABLE"
            )

        component_scores = {
            column: parse_float(
                row,
                column,
                pdb_name=pdb_name,
            )
            for column in (
                COMPONENT_SCORE_COLUMNS
            )
        }

        key_metrics = {
            column: parse_float(
                row,
                column,
                pdb_name=pdb_name,
            )
            for column in (
                KEY_METRIC_COLUMNS
            )
        }

        raw_error = str(
            row.get("error", "")
            or ""
        ).strip()

        final_score_v4 = parse_float(
            row,
            "final_score_v4",
            pdb_name=pdb_name,
        )

        decomposition = None
        if decomposition_status == "AVAILABLE":
            try:
                decomposition = (
                    decompose_primary_score(
                        component_scores=(
                            component_scores
                        ),
                        recorded_final_score_v4=(
                            final_score_v4
                        ),
                        region_score_used=bool(
                            region_score_used
                        ),
                    )
                )
            except ScoreDecompositionError as exc:
                raise RankerResultParseError(
                    "候选主分无法重建："
                    f"{pdb_name} / {exc}"
                ) from exc

        candidates.append(
            CandidateResult(
                pdb_name=pdb_name,
                engineering_rank=(
                    engineering_rank
                ),
                final_score_v4=(
                    final_score_v4
                ),
                raw_filter_level=(
                    raw_filter_level
                ),
                public_filter_level=(
                    public_filter_level
                ),
                public_filter_status=(
                    public_filter_status
                ),
                broad_pass=parse_yes_no(
                    row,
                    "filter_broad_pass",
                    pdb_name=pdb_name,
                ),
                medium_pass=parse_yes_no(
                    row,
                    "filter_medium_pass",
                    pdb_name=pdb_name,
                ),
                strict_pass=parse_yes_no(
                    row,
                    "filter_strict_pass",
                    pdb_name=pdb_name,
                ),
                broad_reasons=split_reasons(
                    row.get(
                        "filter_broad_reasons"
                    )
                ),
                medium_reasons=split_reasons(
                    row.get(
                        "filter_medium_reasons"
                    )
                ),
                strict_reasons=split_reasons(
                    row.get(
                        "filter_strict_reasons"
                    )
                ),
                filter_reasons_formally_interpretable=(
                    pool_reporting.policy
                    .formal_interpretation_allowed
                ),
                component_scores=(
                    component_scores
                ),
                key_metrics=key_metrics,
                primary_score_contributions=(
                    {}
                    if decomposition is None
                    else decomposition.contributions
                ),
                reconstructed_final_score_v4=(
                    None
                    if decomposition is None
                    else (
                        decomposition
                        .reconstructed_final_score_v4
                    )
                ),
                primary_score_reconstruction_error=(
                    None
                    if decomposition is None
                    else (
                        decomposition
                        .reconstruction_error
                    )
                ),
                row_error=(
                    raw_error or None
                ),
            )
        )

    candidates.sort(
        key=lambda item: (
            item.engineering_rank,
            item.pdb_name,
        )
    )

    actual_ranks = [
        item.engineering_rank
        for item in candidates
    ]

    expected_ranks = list(
        range(1, len(candidates) + 1)
    )

    if actual_ranks != expected_ranks:
        raise RankerResultParseError(
            "rank_final_score_v4 必须形成"
            "连续且唯一的 1..N 排名；"
            f"实际为 {actual_ranks}"
        )

    thresholds = parse_filter_thresholds(
        source_files["report_txt"]
    )

    result_use = str(
        analysis_scope.get(
            "result_use",
            "unknown",
        )
    )

    return RankerResultSummary(
        project_name=str(
            execution.get(
                "project_name",
                "",
            )
        ).strip(),
        execution_manifest=(
            execution_path
        ),
        analysis_scope=analysis_scope,
        candidate_count=len(candidates),
        pool_reporting=pool_reporting,
        raw_filter_level_counts=(
            filter_level_counts
        ),
        raw_filter_thresholds=thresholds,
        thresholds_formally_interpretable=(
            pool_reporting.policy
            .formal_interpretation_allowed
        ),
        score_decomposition_status=(
            decomposition_status
        ),
        score_decomposition_reason=(
            decomposition_reason
        ),
        region_score_used=region_score_used,
        primary_score_formula=primary_formula,
        primary_score_weights=score_weights,
        candidates_by_engineering_rank=(
            candidates
        ),
        formal_candidate_recommendation_allowed=(
            pool_reporting.policy
            .formal_candidate_recommendation_allowed
        ),
        result_use=result_use,
        source_files=source_files,
    )


def write_ranker_result_summary(
    *,
    bundle_dir: Path,
    output_path: Path | None = None,
) -> Path:
    """
    解析并写出派生摘要。

    默认禁止覆盖已有摘要。
    """
    bundle_dir = bundle_dir.resolve()

    if output_path is None:
        output_path = (
            bundle_dir
            / "agent_result_summary.json"
        )
    else:
        output_path = output_path.resolve()

    if output_path.exists():
        raise ValueError(
            f"结果摘要已经存在，禁止覆盖："
            f"{output_path}"
        )

    summary = parse_completed_ranker_run(
        bundle_dir
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # 写回后重新验证。
    reloaded = (
        RankerResultSummary
        .model_validate_json(
            output_path.read_text(
                encoding="utf-8"
            )
        )
    )

    if reloaded != summary:
        output_path.unlink(
            missing_ok=True
        )
        raise RankerResultParseError(
            "结果摘要写入前后不一致，"
            "已删除不可靠文件"
        )

    return output_path
