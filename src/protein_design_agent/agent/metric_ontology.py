#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BinderRanker 指标语义本体。

目的：
- 向大模型提供经过源码核对的指标含义；
- 区分主分、间接主分、诊断项和原始指标；
- 限制大模型从指标名称推断不存在的生物学含义；
- 根据 region_score_used 动态调整计分角色。

本模块不计算 Ranker 指标，也不改变原始排名。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MetricDirection = Literal[
    "higher_better",
    "lower_better",
    "context_dependent",
]

MetricRole = Literal[
    "primary_score",
    "direct_primary_component",
    "indirect_primary_component",
    "diagnostic",
    "raw_metric",
]


class MetricSemantics(BaseModel):
    """一个 BinderRanker 指标的受控语义。"""

    key: str = Field(min_length=1)
    label_zh: str = Field(min_length=1)

    direction: MetricDirection
    role: MetricRole

    definition: str = Field(min_length=1)
    value_interpretation: str = Field(
        min_length=1
    )

    direct_primary_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    allowed_interpretations: tuple[str, ...]
    forbidden_interpretations: tuple[str, ...]
    suggested_checks: tuple[str, ...]

    source_basis: str = Field(min_length=1)


def metric(
    *,
    key: str,
    label_zh: str,
    direction: MetricDirection,
    role: MetricRole,
    definition: str,
    value_interpretation: str,
    allowed: tuple[str, ...],
    forbidden: tuple[str, ...],
    checks: tuple[str, ...],
    source_basis: str,
    weight: float | None = None,
) -> MetricSemantics:
    return MetricSemantics(
        key=key,
        label_zh=label_zh,
        direction=direction,
        role=role,
        definition=definition,
        value_interpretation=value_interpretation,
        direct_primary_weight=weight,
        allowed_interpretations=allowed,
        forbidden_interpretations=forbidden,
        suggested_checks=checks,
        source_basis=source_basis,
    )


BASE_METRIC_ONTOLOGY = {
    "final_score_v4": metric(
        key="final_score_v4",
        label_zh="主排序分数",
        direction="higher_better",
        role="primary_score",
        definition=(
            "当前运行用于候选排序的主分。"
            "具体公式由 region_score_used 决定。"
        ),
        value_interpretation=(
            "较高值仅表示在当前 Ranker 公式和"
            "当前批次归一化下获得更高工程排序。"
        ),
        allowed=(
            "描述当前工程排序的相对高低",
            "解释直接计分分项的加权贡献",
        ),
        forbidden=(
            "等同于结合亲和力",
            "等同于实验成功概率",
            "等同于结构稳定性",
            "跨不同靶点直接比较绝对质量",
        ),
        checks=(
            "结合各直接分项检查总分来源",
        ),
        source_basis=(
            "compute_scores 中的 final_score_v4 公式"
        ),
    ),
    "morphology_adaptive_score": metric(
        key="morphology_adaptive_score",
        label_zh="形态自适应复合分",
        direction="higher_better",
        role="direct_primary_component",
        definition=(
            "根据靶标形态动态权重混合 "
            "score_line、score_plane 和 "
            "score_compact 得到的复合分。"
        ),
        value_interpretation=(
            "较高值表示候选在当前靶标形态加权的"
            "三种界面模式指标上综合表现较高。"
        ),
        allowed=(
            "称为当前形态模式下的综合接触几何分",
            "分析 line、plane、compact 三项来源",
        ),
        forbidden=(
            "直接称为蛋白折叠质量",
            "直接称为整体稳定性",
            "直接称为结合自由能",
        ),
        checks=(
            "检查候选与靶标接触区域的整体空间分布",
        ),
        source_basis=(
            "mode_weight_line/plane/compact 加权公式"
        ),
    ),
    "score_line": metric(
        key="score_line",
        label_zh="延展型靶标模式复合分",
        direction="higher_better",
        role="indirect_primary_component",
        definition=(
            "面向延展型靶标的复合分，综合有效接触量、"
            "覆盖、接触跨度、接触有效数、接触图连续性、"
            "接触场平滑性及方向相关指标。"
        ),
        value_interpretation=(
            "较高值表示这些延展型界面指标的加权组合"
            "在当前批次归一化后较高。"
        ),
        allowed=(
            "描述延展型接触模式的综合表现",
            "追溯覆盖、跨度和连续性等组成指标",
        ),
        forbidden=(
            "称为 binder 骨架本身的线性程度",
            "称为二级结构线性",
            "称为 Ramachandran 合理性",
            "称为通用骨架质量",
        ),
        checks=(
            "检查接触区域是否沿靶标表面连续延展",
        ),
        source_basis=(
            "get_component_weights 中 score_line 的组成"
        ),
    ),
    "score_plane": metric(
        key="score_plane",
        label_zh="平面型界面模式复合分",
        direction="higher_better",
        role="indirect_primary_component",
        definition=(
            "面向较平坦界面的复合分，综合局部微拟合、"
            "平面对齐、局部平面性、中心距离、覆盖、"
            "接触量和接触图连续性等指标。"
        ),
        value_interpretation=(
            "较高值表示局部平面互补相关指标的加权组合"
            "在当前批次归一化后较高。"
        ),
        allowed=(
            "描述局部平面界面互补模式",
            "追溯局部对齐和微拟合组成项",
        ),
        forbidden=(
            "称为整个蛋白是平面的",
            "称为二级结构平面性",
            "称为主链构象正确",
        ),
        checks=(
            "检查局部界面法向和表面贴合情况",
        ),
        source_basis=(
            "get_component_weights 中 score_plane 的组成"
        ),
    ),
    "score_compact": metric(
        key="score_compact",
        label_zh="局部紧凑接触模式复合分",
        direction="higher_better",
        role="indirect_primary_component",
        definition=(
            "面向局部斑块或口袋型界面的复合分，综合"
            "有效接触量、接触密度、覆盖、微拟合、"
            "接触区域紧凑性、方向和平滑性指标。"
        ),
        value_interpretation=(
            "较高值表示局部密集接触模式的加权组合"
            "在当前批次归一化后较高。"
        ),
        allowed=(
            "描述局部接触斑块的密集程度和综合几何表现",
        ),
        forbidden=(
            "称为整个蛋白折叠紧凑性",
            "推断存在或不存在内部空腔",
            "推断蛋白是否展开",
        ),
        checks=(
            "检查界面接触是否形成集中局部斑块",
        ),
        source_basis=(
            "get_component_weights 中 score_compact 的组成"
        ),
    ),
    "score_roughness": metric(
        key="score_roughness",
        label_zh="接触场平滑与连续性复合分",
        direction="higher_better",
        role="direct_primary_component",
        definition=(
            "名称虽为 roughness，但其组成主要奖励 binder"
            "和 target 接触场平滑性及接触图连续性，并惩罚"
            "接触跳跃和背向接触。"
        ),
        value_interpretation=(
            "较高值表示接触场变化和平滑连续相关指标的"
            "加权组合较好。"
        ),
        allowed=(
            "称为接触场平滑与连续性复合分",
            "分析接触场是否存在突变",
        ),
        forbidden=(
            "直接称为真实分子表面粗糙度",
            "根据高低断言表面过粗或过光滑",
            "推断蛋白折叠状态",
        ),
        checks=(
            "检查相邻界面残基的接触强度是否突变",
        ),
        source_basis=(
            "score_roughness 实际由 smoothness、continuity、"
            "jump 和 backfacing 指标构成"
        ),
    ),
    "score_microfit": metric(
        key="score_microfit",
        label_zh="局部界面微几何复合分",
        direction="higher_better",
        role="diagnostic",
        definition=(
            "综合局部微拟合、局部平面对齐、局部平面性、"
            "中心距离、有效接触量和覆盖等指标。"
        ),
        value_interpretation=(
            "较高值表示当前定义下的局部界面几何组合较高。"
        ),
        allowed=(
            "描述局部界面几何匹配的复合趋势",
            "建议检查局部接触面贴合",
        ),
        forbidden=(
            "推断共价键长正确",
            "推断二面角正确",
            "推断 Ramachandran 合格",
            "推断侧链构象已经优化",
        ),
        checks=(
            "检查局部界面距离、法向和接触面贴合",
        ),
        source_basis=(
            "get_component_weights 中 score_microfit 的组成"
        ),
    ),
    "score_safety": metric(
        key="score_safety",
        label_zh="几何风险抑制复合分",
        direction="higher_better",
        role="direct_primary_component",
        definition=(
            "由背向接触、CB方向支持、接触跳跃、"
            "接触场平滑性、紧接触比例、壳层敏感性、"
            "正向接触和原子冲突组成的启发式复合分。"
        ),
        value_interpretation=(
            "较高值表示这些几何风险控制指标的组合较好。"
        ),
        allowed=(
            "称为 Ranker 几何风险抑制分",
            "追溯方向、跳跃、壳层敏感性和冲突组成项",
        ),
        forbidden=(
            "称为生物安全性",
            "称为毒性风险",
            "称为实验安全风险",
            "保证结构稳定或可表达",
        ),
        checks=(
            "检查界面方向、局部跳跃和近距离冲突",
        ),
        source_basis=(
            "get_component_weights 中 score_safety 的组成"
        ),
    ),
    "score_region": metric(
        key="score_region",
        label_zh="设计区域命中复合分",
        direction="higher_better",
        role="diagnostic",
        definition=(
            "综合 desired 区域接触权重、覆盖、平均场、"
            "有效数、hotspot 邻域命中，并惩罚 undesired"
            "区域接触的弱区域分数。"
        ),
        value_interpretation=(
            "较高值表示接触更集中于用户指定的目标区域。"
        ),
        allowed=(
            "描述设计区域和热点邻域的命中趋势",
        ),
        forbidden=(
            "等同于结合亲和力",
            "等同于热点能量贡献",
            "在 region_score_used=False 时称其拉高主分",
        ),
        checks=(
            "检查指定区域周围是否存在真实接触",
        ),
        source_basis=(
            "get_component_weights 中 score_region 的组成"
        ),
    ),
    "score_hotspot": metric(
        key="score_hotspot",
        label_zh="热点邻域接触诊断分",
        direction="higher_better",
        role="diagnostic",
        definition=(
            "由 hotspot 及其邻域的接触权重占比和有效覆盖"
            "组成的独立诊断分。"
        ),
        value_interpretation=(
            "较高值表示更多软接触权重和覆盖落在指定热点"
            "及其邻域。"
        ),
        allowed=(
            "描述指定热点邻域的接触命中情况",
        ),
        forbidden=(
            "等同于热点残基结合能",
            "等同于实验热点贡献",
            "称为主分直接组成项",
        ),
        checks=(
            "检查指定热点残基附近的接触距离和空间覆盖",
        ),
        source_basis=(
            "score_hotspot 的四项 hotspot 接触组成"
        ),
    ),
    "effective_weight_sum": metric(
        key="effective_weight_sum",
        label_zh="有效软接触总量",
        direction="higher_better",
        role="raw_metric",
        definition="软接触矩阵 W 中所有有效权重之和。",
        value_interpretation=(
            "同一靶点、同一参数和相近尺寸条件下，较高值"
            "表示模型计入的软接触总量更多。"
        ),
        allowed=(
            "比较同批候选的有效软接触总量",
        ),
        forbidden=(
            "直接等同于接触面积",
            "直接等同于结合能",
            "跨不同体系无校准比较",
        ),
        checks=(
            "检查接触是否集中于少数残基或分布较广",
        ),
        source_basis="effective_weight_sum = sum(W)",
    ),
    "target_effective_coverage": metric(
        key="target_effective_coverage",
        label_zh="靶标有效接触覆盖率",
        direction="higher_better",
        role="raw_metric",
        definition=(
            "靶标残基中接触场超过 contact_threshold 的比例。"
        ),
        value_interpretation=(
            "较高值表示更多靶标残基达到有效接触阈值；"
            "当靶标是完整大蛋白时必须结合设计区域解释。"
        ),
        allowed=(
            "描述当前定义下靶标残基的有效接触比例",
        ),
        forbidden=(
            "等同于界面覆盖完整",
            "认为覆盖整个大蛋白越多必然越好",
            "等同于结合稳定性",
        ),
        checks=(
            "检查有效接触是否落在预期目标区域",
        ),
        source_basis=(
            "mean(target_contact_field > contact_threshold)"
        ),
    ),
    "target_contact_span_norm": metric(
        key="target_contact_span_norm",
        label_zh="靶标接触空间跨度",
        direction="higher_better",
        role="raw_metric",
        definition=(
            "已接触靶标残基的最大空间跨度，除以整个靶标"
            "CA 坐标的最大空间跨度。"
        ),
        value_interpretation=(
            "较高值表示接触区域在靶标空间上分布得更广。"
        ),
        allowed=(
            "描述接触区域相对于整个靶标的空间延展",
        ),
        forbidden=(
            "等同于覆盖率",
            "等同于接触完整性",
            "推断结合稳定性",
        ),
        checks=(
            "检查接触是否形成单个连续区域或多个远隔区域",
        ),
        source_basis=(
            "max_pairwise_distance(contacted_target) / "
            "max_pairwise_distance(full_target)"
        ),
    ),
    "backfacing_cb_far_weight_ratio": metric(
        key="backfacing_cb_far_weight_ratio",
        label_zh="背向且CB远离的接触权重比例",
        direction="lower_better",
        role="raw_metric",
        definition=(
            "距离加权接触中，同时被标记为背向且估计CB"
            "位置较远的权重比例。"
        ),
        value_interpretation=(
            "较低值表示此类方向不利接触所占权重更少。"
        ),
        allowed=(
            "描述界面方向启发式中的背向且CB远离比例",
        ),
        forbidden=(
            "等同于侧链 rotamer 错误率",
            "等同于真实侧链能量",
        ),
        checks=(
            "检查相关残基的估计侧链方向是否朝向界面",
        ),
        source_basis=(
            "weighted_ratio(backfacing_cb_far_mask)"
        ),
    ),
    "cb_closer_weight_ratio": metric(
        key="cb_closer_weight_ratio",
        label_zh="CB更靠近靶标的接触权重比例",
        direction="higher_better",
        role="raw_metric",
        definition=(
            "距离加权接触中，估计CB比CA更靠近对侧界面的"
            "权重比例。"
        ),
        value_interpretation=(
            "较高值表示更多接触获得估计侧链朝向支持。"
        ),
        allowed=(
            "描述估计侧链方向对界面接触的支持比例",
        ),
        forbidden=(
            "称为权重分配平衡性",
            "等同于侧链构象正确率",
        ),
        checks=(
            "检查相关残基侧链方向是否指向靶标界面",
        ),
        source_basis="weighted_ratio(cb_closer_mask)",
    ),
    "binder_field_active_roughness": metric(
        key="binder_field_active_roughness",
        label_zh="binder活跃接触场变化度",
        direction="lower_better",
        role="raw_metric",
        definition=(
            "binder 活跃接触区域中，相邻残基接触场数值的"
            "局部变化程度。"
        ),
        value_interpretation=(
            "较低值表示活跃接触场沿相邻残基变化更平缓。"
        ),
        allowed=(
            "描述接触场沿 binder 序列或邻接边的变化程度",
        ),
        forbidden=(
            "等同于真实分子表面粗糙度",
            "推断存在异常凸起",
            "推断蛋白折叠松散",
        ),
        checks=(
            "检查相邻界面残基的接触强度是否突然变化",
        ),
        source_basis=(
            "binder_rough['active_roughness']"
        ),
    ),
    "contact_map_continuity_score": metric(
        key="contact_map_continuity_score",
        label_zh="接触图连续性分数",
        direction="higher_better",
        role="raw_metric",
        definition=(
            "衡量相邻 binder 残基是否映射到空间上相近的"
            "靶标区域。"
        ),
        value_interpretation=(
            "较高值表示相邻 binder 残基的靶标接触映射"
            "更加连续。"
        ),
        allowed=(
            "描述接触映射的连续性",
        ),
        forbidden=(
            "等同于二级结构连续性",
            "等同于主链无断裂",
            "直接推断结合稳定性",
        ),
        checks=(
            "检查相邻 binder 残基接触的靶标位置是否跳跃",
        ),
        source_basis=(
            "Adjacent binder residues map to nearby target regions"
        ),
    ),
    "contact_map_jump_fraction": metric(
        key="contact_map_jump_fraction",
        label_zh="接触图跳跃比例",
        direction="lower_better",
        role="raw_metric",
        definition=(
            "相邻 binder 残基的靶标接触映射出现较大空间"
            "跳跃的比例。"
        ),
        value_interpretation=(
            "较低值表示接触映射中的大跳跃更少。"
        ),
        allowed=(
            "描述接触图局部跳跃比例",
        ),
        forbidden=(
            "等同于主链断裂",
            "等同于缺失残基",
            "等同于二级结构中断",
        ),
        checks=(
            "检查产生跳跃的相邻 binder 残基及其靶标接触点",
        ),
        source_basis="contact-map continuity calculation",
    ),
    "shell_sensitivity_12_vs_8": metric(
        key="shell_sensitivity_12_vs_8",
        label_zh="宽松接触壳层敏感性",
        direction="lower_better",
        role="raw_metric",
        definition=(
            "比较12 Å宽松接触壳与8 Å紧接触壳的贡献差异。"
        ),
        value_interpretation=(
            "较高值表示接触量更依赖较宽松的12 Å壳层。"
        ),
        allowed=(
            "描述接触是否依赖较远距离壳层",
        ),
        forbidden=(
            "等同于分子动力学稳定性",
            "等同于结合距离",
            "等同于亲和力",
        ),
        checks=(
            "检查界面是否主要由较远距离接触构成",
        ),
        source_basis=(
            "12 Å shell contribution relative to 8 Å shell"
        ),
    ),
    "clash_pairs": metric(
        key="clash_pairs",
        label_zh="近距离原子对数量",
        direction="lower_better",
        role="raw_metric",
        definition=(
            "目标链与 binder 原子距离小于 clash_cutoff 的"
            "原子对数量。"
        ),
        value_interpretation=(
            "零表示在当前原子集合和 cutoff 下未检测到"
            "跨界面近距离原子对。"
        ),
        allowed=(
            "报告当前 clash_cutoff 下检测到的原子对数量",
        ),
        forbidden=(
            "据零值证明整体结构合理",
            "据零值证明无任何立体冲突",
            "据零值证明结构稳定",
        ),
        checks=(
            "在结构查看器中检查最短跨界面原子距离",
        ),
        source_basis=(
            "sum(distance_matrix < clash_cutoff)"
        ),
    ),
}


def ontology_for_run(
    *,
    region_score_used: bool,
) -> dict[str, MetricSemantics]:
    """
    返回适配本次运行计分公式的指标本体。
    """
    result = {
        key: value.model_copy(deep=True)
        for key, value in (
            BASE_METRIC_ONTOLOGY.items()
        )
    }

    if region_score_used:
        result["morphology_adaptive_score"] = (
            result[
                "morphology_adaptive_score"
            ].model_copy(
                update={
                    "direct_primary_weight": 0.78,
                }
            )
        )

        result["score_safety"] = (
            result["score_safety"].model_copy(
                update={
                    "direct_primary_weight": 0.10,
                }
            )
        )

        result["score_roughness"] = (
            result["score_roughness"].model_copy(
                update={
                    "direct_primary_weight": 0.05,
                }
            )
        )

        result["score_region"] = (
            result["score_region"].model_copy(
                update={
                    "role": (
                        "direct_primary_component"
                    ),
                    "direct_primary_weight": 0.07,
                }
            )
        )

        result["final_score_v4"] = (
            result["final_score_v4"].model_copy(
                update={
                    "definition": (
                        "本次使用区域感知主分："
                        "0.78×morphology_adaptive_score "
                        "+ 0.10×score_safety "
                        "+ 0.05×score_roughness "
                        "+ 0.07×score_region。"
                    ),
                }
            )
        )

    else:
        result["morphology_adaptive_score"] = (
            result[
                "morphology_adaptive_score"
            ].model_copy(
                update={
                    "direct_primary_weight": 0.85,
                }
            )
        )

        result["score_safety"] = (
            result["score_safety"].model_copy(
                update={
                    "direct_primary_weight": 0.10,
                }
            )
        )

        result["score_roughness"] = (
            result["score_roughness"].model_copy(
                update={
                    "direct_primary_weight": 0.05,
                }
            )
        )

        result["score_region"] = (
            result["score_region"].model_copy(
                update={
                    "role": "diagnostic",
                    "direct_primary_weight": None,
                }
            )
        )

        result["final_score_v4"] = (
            result["final_score_v4"].model_copy(
                update={
                    "definition": (
                        "本次主分为："
                        "0.85×morphology_adaptive_score "
                        "+ 0.10×score_safety "
                        "+ 0.05×score_roughness。"
                    ),
                }
            )
        )

    return result


def select_metric_semantics(
    *,
    metric_keys: set[str],
    region_score_used: bool,
) -> dict[str, MetricSemantics]:
    """
    为模型证据选择需要的指标语义。

    遇到未知指标时直接失败，禁止模型凭名称解释。
    """
    ontology = ontology_for_run(
        region_score_used=region_score_used
    )

    missing = sorted(
        metric_keys - set(ontology)
    )

    if missing:
        raise ValueError(
            "指标本体缺少以下字段："
            f"{missing}"
        )

    return {
        key: ontology[key]
        for key in sorted(metric_keys)
    }
