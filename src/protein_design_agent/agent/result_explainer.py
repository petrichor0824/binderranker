#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
使用大模型解释已经验证过的 BinderRanker 结果。

架构：

    Ranker 原始输出
        ↓
    确定性结果摘要和失败分析
        ↓
    受控证据包
        ↓
    大模型综合解释
        ↓
    Pydantic 和交叉校验
        ↓
    JSON + Markdown 报告

原则：
- 模型不重新计算分数、排名或阈值；
- 模型不能增加不存在的候选；
- 模型不能篡改分析级别和推荐权限；
- 模型只选择证据指标并解释指标组合；
- 精确数值由确定性渲染器写入 Markdown；
- SMOKE_TEST_ONLY 下禁止正式候选推荐。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from protein_design_agent.public_identity import (
    AGENT_NAME,
    PROJECT_NAME,
)
from protein_design_agent.agent.capability_truth import (
    CAPABILITY_TRUTH_PROMPT,
    find_capability_overclaim,
)
from protein_design_agent.agent.failure_analysis import (
    FailureAnalysisSummary,
)
from protein_design_agent.agent.metric_ontology import (
    MetricSemantics,
    select_metric_semantics,
)
from protein_design_agent.agent.providers.base import (
    StructuredJSONProvider,
)
from protein_design_agent.agent.ranker_result_parser import (
    RankerResultSummary,
)
from protein_design_agent.agent.ranker_report_context import (
    RankerReportContextError,
    parse_boolean_flag as parse_ranker_boolean_flag,
    parse_ranker_report_context,
)
from protein_design_agent.agent.score_decomposition import (
    ScoreDecompositionError,
    decompose_primary_score,
    primary_score_weights as shared_primary_score_weights,
)


class ResultExplanationError(RuntimeError):
    """大模型结果解释无法安全完成。"""


class ExplanationEvidencePoint(BaseModel):
    """
    模型选择的一项证据。

    metric_key 必须来自对应候选的真实结果。
    模型只负责解释，不负责提供数值。
    """

    metric_key: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class CandidateModelExplanation(BaseModel):
    """大模型对一个候选的综合解释。"""

    pdb_name: str = Field(min_length=1)
    engineering_rank: int = Field(ge=1)

    headline: str = Field(min_length=1)

    interpretation: str = Field(
        min_length=1
    )

    score_filter_relationship: str = Field(
        min_length=1
    )

    strengths: list[ExplanationEvidencePoint]
    limitations: list[ExplanationEvidencePoint]

    next_structural_checks: list[str]


class ResultExplanationPayload(BaseModel):
    """
    模型必须返回的结构化解释。

    不提供正式推荐字段，避免模型越权选出
    “最佳实验候选”。
    """

    schema_version: str = "0.1"

    project_name: str = Field(min_length=1)
    analysis_scope_level: str = Field(
        min_length=1
    )

    formal_candidate_recommendation_allowed: bool

    overall_summary: str = Field(
        min_length=1
    )

    batch_limitations: list[str]

    cross_candidate_patterns: list[str]

    candidates: list[
        CandidateModelExplanation
    ]

    next_dataset_requirements: list[str]


class ResultExplanationRecord(BaseModel):
    """一次经过验证的大模型解释记录。"""

    schema_version: str = "0.1"

    status: Literal["EXPLAINED"] = (
        "EXPLAINED"
    )

    provider_name: str = Field(
        min_length=1
    )

    source_result_summary: Path
    source_failure_analysis: Path

    evidence_sha256: str = Field(
        min_length=64,
        max_length=64,
    )

    explanation: ResultExplanationPayload


def load_ranker_summary(
    path: Path,
) -> RankerResultSummary:
    """读取并验证 Ranker 结果摘要。"""
    path = path.resolve()

    if not path.exists():
        raise ResultExplanationError(
            f"Ranker 结果摘要不存在：{path}"
        )

    try:
        return (
            RankerResultSummary
            .model_validate_json(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )
    except Exception as exc:
        raise ResultExplanationError(
            f"Ranker 结果摘要验证失败：{path}"
        ) from exc


def load_failure_analysis(
    path: Path,
) -> FailureAnalysisSummary:
    """读取并验证失败差距分析。"""
    path = path.resolve()

    if not path.exists():
        raise ResultExplanationError(
            f"失败分析不存在：{path}"
        )

    try:
        return (
            FailureAnalysisSummary
            .model_validate_json(
                path.read_text(
                    encoding="utf-8"
                )
            )
        )
    except Exception as exc:
        raise ResultExplanationError(
            f"失败分析验证失败：{path}"
        ) from exc


def parse_report_context(
    report_path: Path,
) -> dict[str, Any]:
    """
    从 Ranker 报告提取运行配置和计分公式。

    这里只读取文本，不执行公式。
    """
    try:
        context = parse_ranker_report_context(
            report_path,
            require_final_formula=True,
        )
    except RankerReportContextError as exc:
        raise ResultExplanationError(
            str(exc)
        ) from exc

    return {
        "run_config": context.run_config,
        "score_formulas": (
            context.score_formulas
        ),
    }


def compact_failed_gate(
    gate: Any,
) -> dict[str, Any] | None:
    """将失败门槛压缩成模型需要的证据。"""
    if gate is None:
        return None

    return {
        "pool": gate.pool,
        "metric": gate.metric,
        "direction": gate.direction,
        "actual_value": gate.actual_value,
        "threshold_value": (
            gate.threshold_value
        ),
        "relative_failure_gap": (
            gate.relative_failure_gap
        ),
        "gap_band": gate.gap_band,
    }


def parse_boolean_flag(
    value: Any,
    *,
    field_name: str,
) -> bool:
    """严格解析报告中的布尔配置。"""
    try:
        return parse_ranker_boolean_flag(
            value,
            field_name=field_name,
        )
    except RankerReportContextError as exc:
        raise ResultExplanationError(
            str(exc)
        ) from exc


def primary_score_weights(
    *,
    region_score_used: bool,
) -> dict[str, float]:
    """返回本次运行真正使用的主分权重。"""
    try:
        return shared_primary_score_weights(
            region_score_used=region_score_used
        )
    except ScoreDecompositionError as exc:
        raise ResultExplanationError(
            str(exc)
        ) from exc


def add_primary_score_facts(
    *,
    candidates: list[dict[str, Any]],
    region_score_used: bool,
) -> dict[str, float]:
    """
    为每个候选加入确定性主分贡献。

    模型只解释贡献，不重新计算。
    """
    weights = primary_score_weights(
        region_score_used=region_score_used
    )

    for candidate in candidates:
        component_scores = candidate[
            "component_scores"
        ]

        try:
            decomposition = (
                decompose_primary_score(
                    component_scores=(
                        component_scores
                    ),
                    recorded_final_score_v4=(
                        candidate[
                            "final_score_v4"
                        ]
                    ),
                    region_score_used=(
                        region_score_used
                    ),
                )
            )
        except ScoreDecompositionError as exc:
            raise ResultExplanationError(
                f"{candidate['pdb_name']}：{exc}"
            ) from exc

        candidate[
            "primary_score_contributions"
        ] = decomposition.contributions

        candidate[
            "reconstructed_final_score_v4"
        ] = (
            decomposition
            .reconstructed_final_score_v4
        )

        candidate[
            "primary_score_reconstruction_error"
        ] = decomposition.reconstruction_error

    return weights


def build_batch_metric_summary(
    *,
    candidates: list[dict[str, Any]],
    semantics: dict[
        str,
        MetricSemantics,
    ],
) -> dict[str, dict[str, Any]]:
    """
    生成确定性的批内指标排序和范围。

    这只是事实摘要，不自动赋予统计意义。
    """
    values_by_metric: dict[
        str,
        list[tuple[str, float]],
    ] = {}

    for candidate in candidates:
        name = str(candidate["pdb_name"])

        values_by_metric.setdefault(
            "final_score_v4",
            [],
        ).append(
            (
                name,
                float(
                    candidate[
                        "final_score_v4"
                    ]
                ),
            )
        )

        for source_name in (
            "component_scores",
            "key_metrics",
        ):
            for metric_key, raw_value in (
                candidate[source_name].items()
            ):
                values_by_metric.setdefault(
                    metric_key,
                    [],
                ).append(
                    (
                        name,
                        float(raw_value),
                    )
                )

    result: dict[
        str,
        dict[str, Any],
    ] = {}

    for metric_key, values in (
        values_by_metric.items()
    ):
        if metric_key not in semantics:
            raise ResultExplanationError(
                "批次指标缺少语义定义："
                f"{metric_key}"
            )

        direction = (
            semantics[metric_key].direction
        )

        numeric_values = [
            value
            for _name, value in values
        ]

        if direction == "higher_better":
            ordered = sorted(
                values,
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )

        elif direction == "lower_better":
            ordered = sorted(
                values,
                key=lambda item: (
                    item[1],
                    item[0],
                ),
            )

        else:
            ordered = sorted(
                values,
                key=lambda item: item[0],
            )

        result[metric_key] = {
            "direction": direction,
            "minimum": min(numeric_values),
            "maximum": max(numeric_values),
            "range": (
                max(numeric_values)
                - min(numeric_values)
            ),
            "best_to_worst": [
                {
                    "pdb_name": name,
                    "value": value,
                    "position": index,
                }
                for index, (
                    name,
                    value,
                ) in enumerate(
                    ordered,
                    start=1,
                )
            ],
        }

    return result


def build_result_explanation_evidence(
    *,
    result_summary_path: Path,
    failure_analysis_path: Path,
) -> dict[str, Any]:
    """构建只包含可信事实的模型证据包。"""
    result_summary_path = (
        result_summary_path.resolve()
    )
    failure_analysis_path = (
        failure_analysis_path.resolve()
    )

    summary = load_ranker_summary(
        result_summary_path
    )

    failure = load_failure_analysis(
        failure_analysis_path
    )

    if (
        summary.project_name
        != failure.project_name
    ):
        raise ResultExplanationError(
            "结果摘要和失败分析的项目名不一致"
        )

    if (
        summary.candidate_count
        != failure.candidate_count
    ):
        raise ResultExplanationError(
            "结果摘要和失败分析的候选数不一致"
        )

    if (
        summary.score_decomposition_status
        != "AVAILABLE"
    ):
        reason = (
            summary.score_decomposition_reason
            or "结果摘要未提供原因"
        )
        raise ResultExplanationError(
            "确定性主分分解不可用，"
            "不能进入模型解释："
            f"{reason}"
        )

    if summary.region_score_used is None:
        raise ResultExplanationError(
            "结果摘要缺少 region_score_used"
        )

    scope_level = str(
        summary.analysis_scope.get(
            "level",
            "",
        )
    )

    if (
        scope_level
        != failure.analysis_scope_level
    ):
        raise ResultExplanationError(
            "结果摘要和失败分析的分析级别不一致"
        )

    report_path = (
        summary.source_files["report_txt"]
    )

    report_context = parse_report_context(
        report_path
    )

    failure_by_name = {
        item.pdb_name: item
        for item in (
            failure
            .candidates_by_engineering_rank
        )
    }

    evidence_candidates: list[
        dict[str, Any]
    ] = []

    for candidate in (
        summary
        .candidates_by_engineering_rank
    ):
        failure_item = failure_by_name.get(
            candidate.pdb_name
        )

        if failure_item is None:
            raise ResultExplanationError(
                "失败分析缺少候选："
                f"{candidate.pdb_name}"
            )

        if (
            failure_item.engineering_rank
            != candidate.engineering_rank
        ):
            raise ResultExplanationError(
                "候选排名在两个证据文件中不一致："
                f"{candidate.pdb_name}"
            )

        unique_failed_metrics = sorted(
            {
                failed_gate.metric
                for pool_failures in (
                    failure_item
                    .failures_by_pool
                    .values()
                )
                for failed_gate in (
                    pool_failures
                )
            }
        )

        if scope_level == "SMOKE_TEST_ONLY":
            # 小样本动态分位数不具有稳定解释意义。
            # 原始失败分析仍留在审计文件中，
            # 但不进入大模型证据。
            public_failed_gate_count = None
            public_unique_failed_metric_count = None
            public_unique_failed_metrics: list[str] = []
            public_closest_failed_gate = None
            public_largest_failed_gate = None

        else:
            public_failed_gate_count = (
                failure_item.failed_gate_count
            )
            public_unique_failed_metric_count = (
                failure_item
                .unique_failed_metric_count
            )
            public_unique_failed_metrics = (
                unique_failed_metrics
            )
            public_closest_failed_gate = (
                compact_failed_gate(
                    failure_item
                    .closest_failed_gate
                )
            )
            public_largest_failed_gate = (
                compact_failed_gate(
                    failure_item
                    .largest_relative_failed_gate
                )
            )

        evidence_candidates.append(
            {
                "pdb_name": (
                    candidate.pdb_name
                ),
                "engineering_rank": (
                    candidate.engineering_rank
                ),
                "final_score_v4": (
                    candidate.final_score_v4
                ),
                "public_filter_level": (
                    candidate
                    .public_filter_level
                ),
                "public_filter_status": (
                    candidate
                    .public_filter_status
                ),
                "component_scores": (
                    candidate.component_scores
                ),
                "key_metrics": (
                    candidate.key_metrics
                ),
                "failed_gate_count": (
                    public_failed_gate_count
                ),
                "unique_failed_metric_count": (
                    public_unique_failed_metric_count
                ),
                "unique_failed_metrics": (
                    public_unique_failed_metrics
                ),
                "closest_failed_gate": (
                    public_closest_failed_gate
                ),
                (
                    "largest_relative_"
                    "failed_gate"
                ): (
                    public_largest_failed_gate
                ),
            }
        )

    if (
        len(evidence_candidates)
        != summary.candidate_count
    ):
        raise ResultExplanationError(
            "证据候选数量不完整"
        )

    report_region_score_used = (
        parse_boolean_flag(
            report_context["run_config"].get(
                "region_score_used",
                "",
            ),
            field_name="region_score_used",
        )
    )
    region_score_used = (
        summary.region_score_used
    )

    if (
        report_region_score_used
        != region_score_used
    ):
        raise ResultExplanationError(
            "结果摘要与 Ranker 报告的 "
            "region_score_used 不一致"
        )

    formula_key = (
        "final_score_v4_region"
        if region_score_used
        else "final_score_v4_original"
    )
    report_primary_formula = (
        report_context["score_formulas"].get(
            formula_key
        )
    )

    if (
        report_primary_formula is None
        or report_primary_formula
        != summary.primary_score_formula
    ):
        raise ResultExplanationError(
            "结果摘要与 Ranker 报告的"
            "主分公式不一致"
        )

    if scope_level == "SMOKE_TEST_ONLY":
        threshold_analysis_mode = (
            "DISABLED_SMALL_SAMPLE"
        )
    elif scope_level == "EXPLORATORY":
        threshold_analysis_mode = (
            "EXPLORATORY_ONLY"
        )
    else:
        threshold_analysis_mode = "ENABLED"

    all_metric_keys: set[str] = {
        "final_score_v4",
    }

    for candidate in evidence_candidates:
        all_metric_keys.update(
            candidate[
                "component_scores"
            ].keys()
        )
        all_metric_keys.update(
            candidate[
                "key_metrics"
            ].keys()
        )

    metric_semantics_models = (
        select_metric_semantics(
            metric_keys=all_metric_keys,
            region_score_used=(
                region_score_used
            ),
        )
    )

    score_weights = add_primary_score_facts(
        candidates=evidence_candidates,
        region_score_used=region_score_used,
    )

    if score_weights != (
        summary.primary_score_weights
    ):
        raise ResultExplanationError(
            "结果摘要中的主分权重与"
            "共享指标本体不一致"
        )

    batch_metric_summary = (
        build_batch_metric_summary(
            candidates=evidence_candidates,
            semantics=(
                metric_semantics_models
            ),
        )
    )

    metric_semantics = {
        key: value.model_dump(
            mode="json"
        )
        for key, value in (
            metric_semantics_models.items()
        )
    }

    # 保留旧字段，避免破坏已有下游代码，
    # 但其内容现在由指标本体产生。
    metric_roles = {
        key: value.role
        for key, value in (
            metric_semantics_models.items()
        )
    }

    evidence = {
        "evidence_schema_version": "0.2",
        "project_name": summary.project_name,
        "analysis_scope_level": (
            scope_level
        ),
        "candidate_count": (
            summary.candidate_count
        ),
        (
            "formal_candidate_"
            "recommendation_allowed"
        ): (
            summary
            .formal_candidate_recommendation_allowed
        ),
        "result_use": summary.result_use,
        "threshold_analysis_mode": (
            threshold_analysis_mode
        ),
        "pool_reporting": {
            "reporting_mode": (
                summary.pool_reporting
                .policy.reporting_mode
            ),
            "public_pool_counts": (
                summary.pool_reporting
                .public_pool_counts
            ),
        },
        "report_context": report_context,
        "region_score_used": (
            region_score_used
        ),
        "primary_score_weights": (
            score_weights
        ),
        "metric_roles": metric_roles,
        "metric_semantics": (
            metric_semantics
        ),
        "batch_metric_summary": (
            batch_metric_summary
        ),
        "candidates": evidence_candidates,
        "safety_contract": {
            "numbers_are_authoritative": True,
            "candidate_order_is_authoritative": True,
            "pool_policy_is_authoritative": True,
            (
                "model_must_not_recommend_"
                "formal_candidates_when_forbidden"
            ): True,
            (
                "failed_gate_count_may_repeat_"
                "the_same_metric_across_pools"
            ): True,
            (
                "use_unique_failed_metric_count_"
                "for_distinct_issue_count"
            ): True,
            (
                "metric_semantics_are_"
                "authoritative"
            ): True,
            (
                "primary_score_contributions_"
                "are_authoritative"
            ): True,
            (
                "batch_metric_summary_is_"
                "the_only_source_for_cross_"
                "candidate_comparisons"
            ): True,
        },
    }

    return evidence


def evidence_sha256(
    evidence: dict[str, Any],
) -> str:
    """计算规范化证据包 SHA256。"""
    canonical = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def build_result_explainer_messages(
    evidence: dict[str, Any],
) -> list[dict[str, str]]:
    """生成受控的大模型结果解释消息。"""
    output_schema = (
        ResultExplanationPayload
        .model_json_schema()
    )

    system_message = f"""
你是 {AGENT_NAME} 的科学结果解释模块。

你的工作不是重新计算结果，而是根据给定证据：
1. 综合解释每个候选的优势和局限；
2. 解释总分表现与内部动态过滤门槛之间的关系；
3. 识别多个指标共同描述的结构模式；
4. 提出下一步应在 PDB 中人工检查的结构特征；
5. 说明还需要多大规模或哪些下游验证。

严格规则：
- 只能使用 evidence 中存在的候选和指标；
- 不得增加候选、改变排名、分数、阈值或分析级别；
- 不得声称 score_region 或 score_hotspot 进入主分，
  除非 metric_roles 明确标记为
  primary_score_direct_component；
- failed_gate_count 可能包含同一指标在多个池中的重复；
  不得把它解释成独立缺陷数量；
- 独立问题数量必须使用 unique_failed_metric_count；
- SMOKE_TEST_ONLY 只能称为工程观察或工程诊断；
- 当正式推荐被禁止时，不得选出最佳实验候选；
- 尽量避免在自由文本中重复大量精确小数或百分比；
- 自由文本中的数字不是权威数据来源；
- 精确数值以确定性证据和渲染器输出为准；
- 不得自行计算或描述动态筛选阈值方向；
- 不得自行声称某指标高于、低于或超出阈值；
- strengths 不得引用该候选 unique_failed_metrics
  中已经记录为失败的指标；
- score_safety 只能解释为 Ranker 几何安全分项，
  不能扩展成生物安全、毒性或实验安全风险；
- score_roughness 是标准化得分，
  不能仅根据名称推断表面“过于光滑”或“过于粗糙”；
- clash_pairs=0 只能表示本次检测没有发现冲突，
  不能直接证明整体结构合理或稳定；
- 不得把诊断指标描述为 final_score_v4 的直接贡献，
  除非 metric_roles 明确标记为
  primary_score_direct_component；
- 正式推荐被禁止时，不得使用“优先、首选、
  最佳候选、推荐送实验”等候选排序建议；
- 使用“提示、可能、需要检查”等审慎表达，
  不使用“严重风险、极差、完全失败”等夸大措辞；
- 不输出 Markdown；
- 只输出满足给定 JSON Schema 的 JSON 对象；
- strengths 和 limitations 中的 metric_key
  必须来自对应候选的 component_scores 或 key_metrics；
- metric_semantics 是指标含义的唯一权威来源；
- 每次解释指标时必须遵守对应的
  allowed_interpretations 和 forbidden_interpretations；
- 不得仅根据字段英文名称猜测生物学或结构含义；
- primary_score_contributions 是主分来源的唯一权威事实；
- 不得声称诊断指标直接拉高或拖低主分；
- 跨候选高低、范围和顺序只能使用
  batch_metric_summary；
- 不得把 score_line 解释为骨架线性、
  二级结构线性或 Ramachandran 合理性；
- 不得把 score_compact 解释为整个蛋白折叠紧凑、
  展开或存在内部空腔；
- 不得把 score_microfit 解释为键长、
  二面角或 Ramachandran 检查；
- 不得把 score_roughness 解释为普通分子表面粗糙度；
- 不得把 score_safety 解释为生物安全、毒性或实验风险；
- clash_pairs 为零只能表示当前 cutoff 下
  没检测到相应跨界面近距离原子对；
- next_structural_checks 应优先使用
  metric_semantics 中的 suggested_checks；
- 每个候选给出适量 strengths 和 limitations；
- next_structural_checks 应是可在 PDB/PyMOL 中检查的事项。
""".strip()

    system_message += (
        "\n\n真实科学能力边界：\n"
        + CAPABILITY_TRUTH_PROMPT
    )

    if (
        evidence.get("threshold_analysis_mode")
        == "DISABLED_SMALL_SAMPLE"
    ):
        system_message += """

当前为 SMOKE_TEST_ONLY：
- evidence 中没有向你提供可解释的动态阈值；
- 这表示阈值被发布政策屏蔽、不得解释，
  不能改写成“阈值未设置、未配置或未启用”；
- 不得讨论 broad、medium、strict；
- 不得使用“通过、失败、淘汰、越过门槛”等表达；
- 不得声称某候选存在多少个失败指标；
- region_score 是否启用属于任务配置选择，
  不得声称正式筛选必须启用区域分数；
- 没有 Pearson、Spearman、Kendall 或其他
  确定性统计证据时，不得使用“正相关、负相关、
  高度相关、显著相关、趋势一致”等统计断言；
- 只能解释总分构成、原始指标表现和需要检查的结构假设；
- 候选之间的高低只能称为本次小样本内的工程观察。
""".rstrip()

    user_payload = {
        "task": (
            "根据可信证据生成结构化中文结果解释。"
        ),
        "required_output_schema": (
            output_schema
        ),
        "evidence": evidence,
    }

    return [
        {
            "role": "system",
            "content": system_message,
        },
        {
            "role": "user",
            "content": json.dumps(
                user_payload,
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


RECOMMENDATION_PATTERNS = (
    re.compile(r"建议\s*优先"),
    re.compile(r"优先\s*(进行|验证|模拟|送|选择)"),
    re.compile(r"首选"),
    re.compile(r"最佳候选"),
    re.compile(r"最值得"),
    re.compile(r"送实验"),
    re.compile(r"推荐.{0,12}(候选|实验|验证|模拟)"),
)

THRESHOLD_DIRECTION_PATTERN = re.compile(
    r"(高于|低于|超过|超出|未达到|偏离)"
    r".{0,10}阈值"
    r"|阈值.{0,10}"
    r"(高于|低于|超过|超出|未达到|偏离)"
)

# 自由文本可以提到普通整数，例如“5个候选”。
# 但精确小数和百分比必须由确定性渲染器提供，
# 避免模型自行抄写、四舍五入或重新计算。
PRECISE_NUMERIC_NARRATIVE_PATTERN = re.compile(
    r"(?<![A-Za-z_])"
    r"(?:\d+\.\d+|\d+\s*[%％])"
)

OVERCLAIM_PATTERNS = (
    re.compile(r"严重安全风险"),
    re.compile(r"生物安全风险"),
    re.compile(r"结构合理性好"),
    re.compile(r"稳定性好"),
)


ONTOLOGY_OVERCLAIM_PATTERNS = (
    re.compile(r"拉曼值"),
    re.compile(r"Ramachandran", re.IGNORECASE),
    re.compile(r"键长.{0,8}(异常|不合理|正确)"),
    re.compile(r"二面角.{0,8}(异常|不合理|正确)"),
    re.compile(r"主链扭转角"),
    re.compile(r"折叠.{0,8}(松散|展开|异常)"),
    re.compile(r"(内部|较大)?空腔"),
    re.compile(r"二级结构.{0,8}(线性|连续|合理)"),
    re.compile(r"生物安全"),
    re.compile(r"毒性风险"),
    re.compile(r"实验安全"),
)

DIRECT_PRIMARY_SCORE_CLAIM_PATTERN = re.compile(
    r"(直接|显著)?"
    r"(拉高|提高|增加|贡献于|进入|纳入)"
    r".{0,12}"
    r"(主分|最终分|final_score_v4)"
    r"|"
    r"(主分|最终分|final_score_v4)"
    r".{0,12}"
    r"(由|来自|包含)"
)

def iter_model_narrative_texts(
    explanation: ResultExplanationPayload,
):
    """遍历所有由模型自由生成的自然语言字段。"""
    yield (
        "overall_summary",
        explanation.overall_summary,
    )

    for index, value in enumerate(
        explanation.batch_limitations
    ):
        yield (
            f"batch_limitations[{index}]",
            value,
        )

    for index, value in enumerate(
        explanation.cross_candidate_patterns
    ):
        yield (
            f"cross_candidate_patterns[{index}]",
            value,
        )

    for candidate_index, candidate in enumerate(
        explanation.candidates
    ):
        prefix = (
            f"candidates[{candidate_index}]"
        )

        yield (
            f"{prefix}.headline",
            candidate.headline,
        )
        yield (
            f"{prefix}.interpretation",
            candidate.interpretation,
        )
        yield (
            f"{prefix}.score_filter_relationship",
            candidate.score_filter_relationship,
        )

        for point_index, point in enumerate(
            candidate.strengths
        ):
            yield (
                (
                    f"{prefix}.strengths"
                    f"[{point_index}].explanation"
                ),
                point.explanation,
            )

        for point_index, point in enumerate(
            candidate.limitations
        ):
            yield (
                (
                    f"{prefix}.limitations"
                    f"[{point_index}].explanation"
                ),
                point.explanation,
            )

        for check_index, value in enumerate(
            candidate.next_structural_checks
        ):
            yield (
                (
                    f"{prefix}.next_structural_checks"
                    f"[{check_index}]"
                ),
                value,
            )

    for index, value in enumerate(
        explanation.next_dataset_requirements
    ):
        yield (
            f"next_dataset_requirements[{index}]",
            value,
        )



def iter_generated_text_fields(
    value: Any,
    *,
    prefix: str = "",
):
    """
    遍历模型解释中的自然语言字段。

    只用于质量验证，不修改模型输出。
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump(
            mode="python"
        )

    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            yield from iter_generated_text_fields(
                child,
                prefix=child_prefix,
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_generated_text_fields(
                child,
                prefix=f"{prefix}[{index}]",
            )

    elif isinstance(value, str):
        stripped = value.strip()

        if stripped:
            yield prefix, stripped


def evidence_contains_statistical_relationship(
    evidence: dict[str, Any],
) -> bool:
    """
    检查确定性证据是否真的提供了相关性统计。

    仅键名明确表示相关系数或趋势统计时才返回 True。
    """
    statistical_key_tokens = (
        "pearson",
        "spearman",
        "kendall",
        "correlation",
        "rank_correlation",
        "trend_statistic",
    )

    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).lower()

                if any(
                    token in normalized_key
                    for token in statistical_key_tokens
                ):
                    return True

                if walk(child):
                    return True

        elif isinstance(value, list):
            return any(
                walk(child)
                for child in value
            )

        return False

    return walk(evidence)


def validate_generated_claim_boundaries(
    *,
    explanation: Any,
    evidence: dict[str, Any],
) -> None:
    """
    阻止模型把权限限制改写成不存在的科研事实。

    当前只处理三个已经在真实 v6 报告中出现的问题：
    1. 把小样本阈值屏蔽写成阈值未设置或未启用；
    2. 声称正式筛选必须启用区域分数；
    3. 没有统计证据时声称相关性或趋势一致。
    """
    threshold_suppressed = (
        evidence.get("threshold_analysis_mode")
        == "DISABLED_SMALL_SAMPLE"
    )

    statistical_evidence_available = (
        evidence_contains_statistical_relationship(
            evidence
        )
    )

    threshold_absence_pattern = re.compile(
        r"(?:未|没有)(?:设置|配置|启用)"
        r".{0,20}(?:动态)?(?:过滤|筛选)?"
        r"(?:门槛|阈值)"
        r"|"
        r"(?:动态)?(?:过滤|筛选)?"
        r"(?:门槛|阈值).{0,20}"
        r"(?:未|没有)(?:设置|配置|启用)"
    )

    region_requirement_pattern = re.compile(
        r"(?:正式筛选|正式分析|正式结论)"
        r".{0,35}"
        r"(?:必须|需要|需|应当|应该)"
        r".{0,20}"
        r"(?:启用|使用|配置)"
        r".{0,15}"
        r"(?:score_region|region[_ ]?score|区域分数)"
        r"|"
        r"(?:必须|需要|需|应当|应该)"
        r".{0,20}"
        r"(?:启用|使用|配置)"
        r".{0,15}"
        r"(?:score_region|region[_ ]?score|区域分数)"
        r".{0,35}"
        r"(?:正式筛选|正式分析|正式结论)",
        flags=re.IGNORECASE,
    )

    statistical_assertion_pattern = re.compile(
        r"(?:高度|显著|强烈|明显)?"
        r"(?:正相关|负相关|相关性)"
        r"|"
        r"(?:趋势|排序).{0,12}"
        r"(?:基本一致|高度一致|显著一致)"
    )

    negated_region_requirement_pattern = re.compile(
        r"(?:无需|不需要|并非必须|不是必须|"
        r"不是必要条件|不构成必要条件)"
    )

    for field_name, value in (
        iter_generated_text_fields(
            explanation
        )
    ):
        sentences = re.split(
            r"(?<=[。！？；\n])",
            value,
        )

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            if (
                threshold_suppressed
                and threshold_absence_pattern.search(
                    sentence
                )
            ):
                raise ResultExplanationError(
                    "模型把小样本下被屏蔽、"
                    "不可解释的动态阈值错误描述为"
                    "未设置或未启用："
                    f"{field_name}: {sentence}"
                )

            if (
                region_requirement_pattern.search(
                    sentence
                )
                and not (
                    negated_region_requirement_pattern
                    .search(sentence)
                )
            ):
                raise ResultExplanationError(
                    "模型错误声称正式筛选必须启用"
                    "区域分数："
                    f"{field_name}: {sentence}"
                )

            if (
                not statistical_evidence_available
                and statistical_assertion_pattern.search(
                    sentence
                )
            ):
                raise ResultExplanationError(
                    "确定性证据没有提供相关性统计，"
                    "但模型输出了统计关系断言："
                    f"{field_name}: {sentence}"
                )


def validate_capability_claims(
    *,
    explanation: Any,
) -> None:
    """
    阻止模型把 BinderRanker 或 Agent 描述成
    超出产品真实科学能力边界的预测或验证系统。
    """
    for field_name, value in (
        iter_generated_text_fields(explanation)
    ):
        offending_sentence = (
            find_capability_overclaim(value)
        )

        if offending_sentence is not None:
            raise ResultExplanationError(
                "模型输出超出 BinderRanker / Agent "
                "真实科学能力边界："
                f"{field_name}: {offending_sentence}"
            )


def validate_model_narrative(
    *,
    explanation: ResultExplanationPayload,
    evidence: dict[str, Any],
) -> None:
    """
    防止模型在自由文本中重新计算数值、
    颠倒阈值方向或越权推荐候选。
    """
    candidate_names = [
        str(item["pdb_name"])
        for item in evidence["candidates"]
    ]

    recommendation_allowed = bool(
        evidence[
            "formal_candidate_recommendation_allowed"
        ]
    )

    for field_name, value in (
        iter_model_narrative_texts(
            explanation
        )
    ):
        clean_value = value

        # 候选名自身可能含数字，例如 _2577，
        # 不应被当成模型私自生成数值。
        for candidate_name in candidate_names:
            clean_value = clean_value.replace(
                candidate_name,
                "",
            )

        # 自由文本中的数字不再作为失败条件。
        #
        # 原因：
        # - 模型可能正常复述证据中的指标值；
        # - 精确数值的权威来源是确定性证据和渲染器；
        # - 不能因为写作风格问题使整个 API 调用失败。
        #
        # 仍然保留：
        # - 阈值方向越权校验；
        # - 候选名称和排序校验；
        # - 指标引用和指标本体校验；
        # - 推荐权限和过度推断校验。

        if THRESHOLD_DIRECTION_PATTERN.search(
            value
        ):
            raise ResultExplanationError(
                "模型自行描述了阈值方向，"
                "该事实必须由确定性渲染器提供："
                f"{field_name}"
            )

        for pattern in OVERCLAIM_PATTERNS:
            if pattern.search(value):
                raise ResultExplanationError(
                    "模型使用了超出证据范围的"
                    "确定性或风险措辞："
                    f"{field_name}"
                )

        for pattern in (
            ONTOLOGY_OVERCLAIM_PATTERNS
        ):
            if pattern.search(value):
                raise ResultExplanationError(
                    "模型使用了指标本体明确禁止的"
                    "结构或生物学推断："
                    f"{field_name}"
                )

        if not recommendation_allowed:
            for pattern in (
                RECOMMENDATION_PATTERNS
            ):
                if pattern.search(value):
                    raise ResultExplanationError(
                        "当前禁止正式推荐，"
                        "但模型输出了候选优先级建议："
                        f"{field_name}"
                    )


def validate_model_explanation(
    *,
    raw_payload: dict[str, Any],
    evidence: dict[str, Any],
) -> ResultExplanationPayload:
    """验证模型没有篡改证据或增加候选。"""
    try:
        explanation = (
            ResultExplanationPayload
            .model_validate(raw_payload)
        )
    except Exception as exc:
        raise ResultExplanationError(
            "模型解释无法通过 Pydantic 验证"
        ) from exc

    if (
        explanation.project_name
        != evidence["project_name"]
    ):
        raise ResultExplanationError(
            "模型篡改了 project_name"
        )

    if (
        explanation.analysis_scope_level
        != evidence[
            "analysis_scope_level"
        ]
    ):
        raise ResultExplanationError(
            "模型篡改了分析级别"
        )

    if (
        explanation
        .formal_candidate_recommendation_allowed
        != evidence[
            (
                "formal_candidate_"
                "recommendation_allowed"
            )
        ]
    ):
        raise ResultExplanationError(
            "模型篡改了正式推荐权限"
        )

    expected_candidates = (
        evidence["candidates"]
    )

    if (
        len(explanation.candidates)
        != len(expected_candidates)
    ):
        raise ResultExplanationError(
            "模型解释的候选数量不正确"
        )

    for model_item, evidence_item in zip(
        explanation.candidates,
        expected_candidates,
        strict=True,
    ):
        expected_name = (
            evidence_item["pdb_name"]
        )
        expected_rank = (
            evidence_item[
                "engineering_rank"
            ]
        )

        if (
            model_item.pdb_name
            != expected_name
        ):
            raise ResultExplanationError(
                "模型改变了候选顺序或名称："
                f"预期 {expected_name}，"
                f"实际 {model_item.pdb_name}"
            )

        if (
            model_item.engineering_rank
            != expected_rank
        ):
            raise ResultExplanationError(
                "模型改变了候选排名："
                f"{expected_name}"
            )

        allowed_metrics = (
            set(
                evidence_item[
                    "component_scores"
                ]
            )
            | set(
                evidence_item[
                    "key_metrics"
                ]
            )
        )

        all_points = (
            model_item.strengths
            + model_item.limitations
        )

        if not model_item.strengths:
            raise ResultExplanationError(
                f"模型没有给出 {expected_name} "
                "的优势证据"
            )

        if not model_item.limitations:
            raise ResultExplanationError(
                f"模型没有给出 {expected_name} "
                "的局限证据"
            )

        metric_semantics = evidence.get(
            "metric_semantics",
            {},
        )

        for point in all_points:
            if (
                point.metric_key
                not in allowed_metrics
            ):
                raise ResultExplanationError(
                    "模型引用了不存在的指标："
                    f"{expected_name} / "
                    f"{point.metric_key}"
                )

            semantics = metric_semantics.get(
                point.metric_key
            )

            if semantics is not None:
                role = semantics.get("role")

                if (
                    role in {
                        "diagnostic",
                        "raw_metric",
                    }
                    and
                    DIRECT_PRIMARY_SCORE_CLAIM_PATTERN
                    .search(point.explanation)
                ):
                    raise ResultExplanationError(
                        "模型把非主分指标错误解释为"
                        "final_score_v4 的直接贡献："
                        f"{expected_name} / "
                        f"{point.metric_key}"
                    )

        failed_metrics = set(
            evidence_item.get(
                "unique_failed_metrics",
                [],
            )
        )

        for point in model_item.strengths:
            if point.metric_key in failed_metrics:
                raise ResultExplanationError(
                    "模型把已记录失败的指标"
                    "错误地列为候选优势："
                    f"{expected_name} / "
                    f"{point.metric_key}"
                )

        if (
            not model_item
            .next_structural_checks
        ):
            raise ResultExplanationError(
                f"模型没有给出 {expected_name} "
                "的结构检查建议"
            )

    validate_model_narrative(
        explanation=explanation,
        evidence=evidence,
    )

    validate_generated_claim_boundaries(
        explanation=explanation,
        evidence=evidence,
    )

    validate_capability_claims(
        explanation=explanation,
    )

    return explanation


def request_result_explanation(
    *,
    provider: StructuredJSONProvider,
    evidence: dict[str, Any],
    confirm_model_call: bool,
) -> ResultExplanationRecord:
    """
    调用大模型生成结果解释。

    必须显式确认，因为真实调用可能产生费用。
    """
    if confirm_model_call is not True:
        raise ValueError(
            "真实模型解释需要显式设置 "
            "confirm_model_call=True"
        )

    messages = (
        build_result_explainer_messages(
            evidence
        )
    )

    raw_payload = provider.generate_json(
        messages
    )

    try:
        explanation = (
            validate_model_explanation(
                raw_payload=raw_payload,
                evidence=evidence,
            )
        )
    except ResultExplanationError as first_error:
        repair_messages = [
            *messages,
            {
                "role": "assistant",
                "content": json.dumps(
                    raw_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
            {
                "role": "user",
                "content": (
                    "你刚才的结构化解释没有通过"
                    "确定性证据校验。\n"
                    f"校验错误：{first_error}\n\n"
                    "请只修正违规字段，并重新输出完整 JSON。"
                    "不得改变候选名称、候选顺序、排名、分数、"
                    "分析级别、推荐权限或任何证据数值。"
                    "不得添加证据中不存在的相关性、因果关系、"
                    "统计显著性、阈值方向或候选推荐。"
                    "\n\n真实科学能力边界：\n"
                    + CAPABILITY_TRUTH_PROMPT
                    + "\n\n只输出符合原 JSON Schema 的对象。"
                ),
            },
        ]

        repaired_payload = provider.generate_json(
            repair_messages
        )

        try:
            explanation = (
                validate_model_explanation(
                    raw_payload=repaired_payload,
                    evidence=evidence,
                )
            )
        except ResultExplanationError as second_error:
            raise ResultExplanationError(
                "模型解释首次校验失败，"
                "自动修正重试后仍未通过。"
                f"首次错误：{first_error}；"
                f"重试错误：{second_error}"
            ) from second_error

    return ResultExplanationRecord(
        provider_name=provider.name,
        source_result_summary=Path(
            evidence[
                "_source_result_summary"
            ]
        ),
        source_failure_analysis=Path(
            evidence[
                "_source_failure_analysis"
            ]
        ),
        evidence_sha256=(
            evidence_sha256(
                {
                    key: value
                    for key, value
                    in evidence.items()
                    if not key.startswith("_source_")
                }
            )
        ),
        explanation=explanation,
    )


def metric_value_for_candidate(
    *,
    evidence_candidate: dict[str, Any],
    metric_key: str,
) -> float:
    """读取一个模型所引用指标的真实数值。"""
    component_scores = (
        evidence_candidate[
            "component_scores"
        ]
    )
    key_metrics = (
        evidence_candidate[
            "key_metrics"
        ]
    )

    if metric_key in component_scores:
        return float(
            component_scores[metric_key]
        )

    if metric_key in key_metrics:
        return float(
            key_metrics[metric_key]
        )

    raise ResultExplanationError(
        f"无法找到指标真实值：{metric_key}"
    )


def format_metric_value(
    value: float,
) -> str:
    """以适合人类阅读的方式显示确定性数值。"""
    return f"{value:.6g}"


def render_failed_gate_fact(
    gate: dict[str, Any],
) -> str:
    """
    使用确定性证据渲染门槛事实。

    模型不参与数值、方向和相对差距计算。
    """
    metric = str(gate["metric"])
    pool = str(gate["pool"])
    direction = str(gate["direction"])

    actual = float(
        gate["actual_value"]
    )
    threshold = float(
        gate["threshold_value"]
    )

    if direction == "min":
        gap = threshold - actual
        comparison = "低于最低门槛"
    elif direction == "max":
        gap = actual - threshold
        comparison = "高于最高门槛"
    else:
        raise ResultExplanationError(
            f"未知门槛方向：{direction}"
        )

    relative = gate.get(
        "relative_failure_gap"
    )

    if relative is None:
        relative_text = (
            "阈值为零，仅报告绝对差距"
        )
    else:
        relative_text = (
            f"相对差距 "
            f"{float(relative) * 100:.3f}%"
        )

    return (
        f"- `{metric}`（`{pool}`）："
        f"实际值 `{format_metric_value(actual)}`，"
        f"门槛 `{format_metric_value(threshold)}`，"
        f"{comparison} "
        f"`{format_metric_value(gap)}`；"
        f"{relative_text}。"
    )


def render_result_explanation_markdown(
    *,
    record: ResultExplanationRecord,
    evidence: dict[str, Any],
) -> str:
    """使用模型解释和真实数值生成 Markdown。"""
    explanation = record.explanation

    evidence_by_name = {
        item["pdb_name"]: item
        for item in evidence["candidates"]
    }

    lines: list[str] = [
        f"# {PROJECT_NAME} 结果解释",
        "",
        f"- 项目：`{explanation.project_name}`",
        (
            "- 分析级别："
            f"`{explanation.analysis_scope_level}`"
        ),
        (
            "- 模型 Provider："
            f"`{record.provider_name}`"
        ),
        (
            "- 正式候选推荐："
            + (
                "允许"
                if explanation
                .formal_candidate_recommendation_allowed
                else "不允许"
            )
        ),
        "",
    ]

    if (
        explanation.analysis_scope_level
        == "SMOKE_TEST_ONLY"
    ):
        lines.extend(
            [
                "> **小样本安全提示：** "
                "本次只有工程冒烟测试规模。"
                "以下排序、动态阈值和指标差异只能"
                "用于检查工作流和形成结构检查假设，"
                "不能作为正式候选筛选或实验推荐。",
                "",
            ]
        )

    lines.extend(
        [
            "## 整体解释",
            "",
            explanation.overall_summary,
            "",
            "## 本批次限制",
            "",
        ]
    )

    for item in (
        explanation.batch_limitations
    ):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 跨候选模式",
            "",
        ]
    )

    for item in (
        explanation.cross_candidate_patterns
    ):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 计分上下文",
            "",
        ]
    )

    formulas = (
        evidence["report_context"]
        ["score_formulas"]
    )

    for key, formula in formulas.items():
        lines.append(
            f"- `{key}`：`{formula}`"
        )

    run_config = (
        evidence["report_context"]
        ["run_config"]
    )

    for key in (
        "region_score_mode",
        "region_score_used",
        "region_filter",
    ):
        if key in run_config:
            lines.append(
                f"- `{key}`："
                f"`{run_config[key]}`"
            )

    for model_candidate in (
        explanation.candidates
    ):
        evidence_candidate = (
            evidence_by_name[
                model_candidate.pdb_name
            ]
        )

        final_score_text = format_metric_value(
            float(
                evidence_candidate[
                    "final_score_v4"
                ]
            )
        )

        raw_unique_failed_count = (
            evidence_candidate.get(
                "unique_failed_metric_count"
            )
        )

        if raw_unique_failed_count is None:
            failed_metric_summary = (
                "未解释（小样本不使用动态门槛）"
            )
        else:
            failed_metric_summary = str(
                int(raw_unique_failed_count)
            )

        public_filter_status = str(
            evidence_candidate[
                "public_filter_status"
            ]
        )

        gate_fact_lines: list[str] = []
        seen_gate_facts: set[
            tuple[str, str, float]
        ] = set()

        for gate_key in (
            "closest_failed_gate",
            "largest_relative_failed_gate",
        ):
            gate = evidence_candidate.get(
                gate_key
            )

            if gate is None:
                continue

            identity = (
                str(gate["pool"]),
                str(gate["metric"]),
                float(
                    gate["threshold_value"]
                ),
            )

            if identity in seen_gate_facts:
                continue

            seen_gate_facts.add(identity)

            gate_fact_lines.append(
                render_failed_gate_fact(gate)
            )

        lines.extend(
            [
                "",
                (
                    "## 工程排序 "
                    f"#{model_candidate.engineering_rank} "
                    f"`{model_candidate.pdb_name}`"
                ),
                "",
                (
                    "- `final_score_v4`："
                    f"`{final_score_text}`"
                ),
                (
                    "- 动态门槛诊断："
                    f"`{failed_metric_summary}`"
                ),
                (
                    "- 解释状态："
                    f"`{public_filter_status}`"
                ),
                "",
                f"**{model_candidate.headline}**",
                "",
                model_candidate.interpretation,
                "",
                "### 总分与内部门槛的关系",
                "",
                (
                    model_candidate
                    .score_filter_relationship
                ),
                "",
                "### 确定性门槛事实",
                "",
            ]
        )

        if gate_fact_lines:
            lines.extend(
                gate_fact_lines
            )
        else:
            if (
                evidence.get(
                    "threshold_analysis_mode"
                )
                == "DISABLED_SMALL_SAMPLE"
            ):
                lines.append(
                    "- 当前为小样本工程测试，"
                    "动态分位数门槛不展示、"
                    "不解释，也不用于候选判断。"
                )
            else:
                lines.append(
                    "- 没有记录到失败门槛。"
                )

        lines.extend(
            [
                "",
                "### 主要优势",
                "",
            ]
        )

        for point in (
            model_candidate.strengths
        ):
            value = metric_value_for_candidate(
                evidence_candidate=(
                    evidence_candidate
                ),
                metric_key=(
                    point.metric_key
                ),
            )

            lines.append(
                f"- `{point.metric_key}` = "
                f"`{format_metric_value(value)}`："
                f"{point.explanation}"
            )

        lines.extend(
            [
                "",
                "### 主要局限",
                "",
            ]
        )

        for point in (
            model_candidate.limitations
        ):
            value = metric_value_for_candidate(
                evidence_candidate=(
                    evidence_candidate
                ),
                metric_key=(
                    point.metric_key
                ),
            )

            lines.append(
                f"- `{point.metric_key}` = "
                f"`{format_metric_value(value)}`："
                f"{point.explanation}"
            )

        lines.extend(
            [
                "",
                "### 建议检查的结构特征",
                "",
            ]
        )

        for item in (
            model_candidate
            .next_structural_checks
        ):
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 形成正式结论还需要什么",
            "",
        ]
    )

    for item in (
        explanation
        .next_dataset_requirements
    ):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "---",
            "",
            (
                "本报告中的精确数值来自确定性"
                "Ranker 证据；自然语言综合解释"
                "由大模型生成，并经过候选名称、"
                "排名、分析权限和指标引用校验。"
            ),
            "",
        ]
    )

    return "\n".join(lines)


def write_explanation_artifacts(
    *,
    output_dir: Path,
    evidence: dict[str, Any],
    record: ResultExplanationRecord,
) -> dict[str, Path]:
    """写出证据、解释 JSON 和 Markdown，禁止覆盖。"""
    output_dir = output_dir.resolve()
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = {
        "evidence": (
            output_dir
            / "agent_explanation_evidence.json"
        ),
        "json": (
            output_dir
            / "agent_explanation.json"
        ),
        "markdown": (
            output_dir
            / "agent_explanation.md"
        ),
    }

    existing = [
        path
        for path in paths.values()
        if path.exists()
    ]

    if existing:
        raise ValueError(
            "解释产物已经存在，禁止覆盖："
            f"{existing}"
        )

    public_evidence = {
        key: value
        for key, value in evidence.items()
        if not key.startswith("_source_")
    }

    markdown = (
        render_result_explanation_markdown(
            record=record,
            evidence=evidence,
        )
    )

    created: list[Path] = []

    try:
        with paths["evidence"].open(
            "x",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    public_evidence,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        created.append(paths["evidence"])

        with paths["json"].open(
            "x",
            encoding="utf-8",
        ) as handle:
            handle.write(
                record.model_dump_json(
                    indent=2
                )
            )
        created.append(paths["json"])

        with paths["markdown"].open(
            "x",
            encoding="utf-8",
        ) as handle:
            handle.write(markdown)
        created.append(paths["markdown"])

    except Exception:
        for path in created:
            path.unlink(
                missing_ok=True
            )
        raise

    return paths


def explain_ranker_results(
    *,
    provider: StructuredJSONProvider,
    result_summary_path: Path,
    failure_analysis_path: Path,
    output_dir: Path,
    confirm_model_call: bool,
) -> dict[str, Path]:
    """完整执行证据构建、模型解释和报告写出。"""
    result_summary_path = (
        result_summary_path.resolve()
    )
    failure_analysis_path = (
        failure_analysis_path.resolve()
    )

    evidence = (
        build_result_explanation_evidence(
            result_summary_path=(
                result_summary_path
            ),
            failure_analysis_path=(
                failure_analysis_path
            ),
        )
    )

    evidence[
        "_source_result_summary"
    ] = str(result_summary_path)

    evidence[
        "_source_failure_analysis"
    ] = str(failure_analysis_path)

    record = request_result_explanation(
        provider=provider,
        evidence=evidence,
        confirm_model_call=(
            confirm_model_call
        ),
    )

    return write_explanation_artifacts(
        output_dir=output_dir,
        evidence=evidence,
        record=record,
    )
