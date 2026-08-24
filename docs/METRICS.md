# BinderRanker Metrics

This document is generated from `metric_ontology.py`, which is the controlled source for externally exposed metric semantics.

BinderRanker metrics describe relative engineering ranking within the current target and candidate batch. They are not binding affinities, experimental success probabilities, folding guarantees, or universal scores that can be compared directly across unrelated targets.

## Primary-score formulas

When region scoring is disabled:

`final_score_v4 = 0.85 × morphology_adaptive_score + 0.10 × score_safety + 0.05 × score_roughness`

When region scoring is enabled:

`final_score_v4 = 0.78 × morphology_adaptive_score + 0.10 × score_safety + 0.05 × score_roughness + 0.07 × score_region`

The three morphology-mode scores are first combined through target-dependent dynamic weights to form `morphology_adaptive_score`.

## Deterministic contribution decomposition

For reports that record the active region-scoring flag and the corresponding primary-score formula, the deterministic result summary exposes:

- the recorded primary-score formula;
- the audited direct-component weights;
- each candidate's `weight × component score` contribution;
- the reconstructed `final_score_v4` and reconstruction error.

The reconstructed contributions must sum to the recorded `final_score_v4` within the parser tolerance. A mismatch is rejected instead of entering downstream explanation. Older reports that do not contain the required context remain readable, but their decomposition status is `UNAVAILABLE` and BinderRanker does not infer missing formula evidence.

A contribution is an arithmetic term in BinderRanker's empirical ranking formula. It is not a causal attribution, binding-energy decomposition, or statement of universal biophysical importance.

## Role definitions

- **Primary score**: the value used for final ranking.
- **Direct primary component**: enters the final score with an explicit run-dependent weight.
- **Indirect primary component**: contributes through another composite score.
- **Diagnostic metric**: supports interpretation but is not always an independent final-score term.
- **Raw metric**: a measured geometric quantity used by composite scores, filters, or diagnostics.

## Metric index

| Key | Label | Direction | Role when region off | Weight off | Role when region on | Weight on |
|---|---|---|---|---:|---|---:|
| `final_score_v4` | 主排序分数 | 越高越好 | 主排序分数 | — | 主排序分数 | — |
| `morphology_adaptive_score` | 形态自适应复合分 | 越高越好 | 直接主分项 | 0.85 | 直接主分项 | 0.78 |
| `score_line` | 延展型靶标模式复合分 | 越高越好 | 间接主分项 | — | 间接主分项 | — |
| `score_plane` | 平面型界面模式复合分 | 越高越好 | 间接主分项 | — | 间接主分项 | — |
| `score_compact` | 局部紧凑接触模式复合分 | 越高越好 | 间接主分项 | — | 间接主分项 | — |
| `score_roughness` | 接触场平滑与连续性复合分 | 越高越好 | 直接主分项 | 0.05 | 直接主分项 | 0.05 |
| `score_microfit` | 局部界面微几何复合分 | 越高越好 | 诊断指标 | — | 诊断指标 | — |
| `score_safety` | 几何风险抑制复合分 | 越高越好 | 直接主分项 | 0.10 | 直接主分项 | 0.10 |
| `score_region` | 设计区域命中复合分 | 越高越好 | 诊断指标 | — | 直接主分项 | 0.07 |
| `score_hotspot` | 热点邻域接触诊断分 | 越高越好 | 诊断指标 | — | 诊断指标 | — |
| `effective_weight_sum` | 有效软接触总量 | 越高越好 | 原始指标 | — | 原始指标 | — |
| `target_effective_coverage` | 靶标有效接触覆盖率 | 越高越好 | 原始指标 | — | 原始指标 | — |
| `target_contact_span_norm` | 靶标接触空间跨度 | 越高越好 | 原始指标 | — | 原始指标 | — |
| `backfacing_cb_far_weight_ratio` | 背向且CB远离的接触权重比例 | 越低越好 | 原始指标 | — | 原始指标 | — |
| `cb_closer_weight_ratio` | CB更靠近靶标的接触权重比例 | 越高越好 | 原始指标 | — | 原始指标 | — |
| `binder_field_active_roughness` | binder活跃接触场变化度 | 越低越好 | 原始指标 | — | 原始指标 | — |
| `contact_map_continuity_score` | 接触图连续性分数 | 越高越好 | 原始指标 | — | 原始指标 | — |
| `contact_map_jump_fraction` | 接触图跳跃比例 | 越低越好 | 原始指标 | — | 原始指标 | — |
| `shell_sensitivity_12_vs_8` | 宽松接触壳层敏感性 | 越低越好 | 原始指标 | — | 原始指标 | — |
| `clash_pairs` | 近距离原子对数量 | 越低越好 | 原始指标 | — | 原始指标 | — |

## Detailed semantics

### `final_score_v4` — 主排序分数

- **Direction:** 越高越好
- **Base role:** 主排序分数
- **Definition:** 当前运行用于候选排序的主分。具体公式由 region_score_used 决定。
- **Interpretation:** 较高值仅表示在当前 Ranker 公式和当前批次归一化下获得更高工程排序。
- **Allowed interpretations:** 描述当前工程排序的相对高低；解释直接计分分项的加权贡献
- **Forbidden interpretations:** 等同于结合亲和力；等同于实验成功概率；等同于结构稳定性；跨不同靶点直接比较绝对质量
- **Suggested checks:** 结合各直接分项检查总分来源
- **Source basis:** compute_scores 中的 final_score_v4 公式

### `morphology_adaptive_score` — 形态自适应复合分

- **Direction:** 越高越好
- **Base role:** 直接主分项
- **Definition:** 根据靶标形态动态权重混合 score_line、score_plane 和 score_compact 得到的复合分。
- **Interpretation:** 较高值表示候选在当前靶标形态加权的三种界面模式指标上综合表现较高。
- **Allowed interpretations:** 称为当前形态模式下的综合接触几何分；分析 line、plane、compact 三项来源
- **Forbidden interpretations:** 直接称为蛋白折叠质量；直接称为整体稳定性；直接称为结合自由能
- **Suggested checks:** 检查候选与靶标接触区域的整体空间分布
- **Source basis:** mode_weight_line/plane/compact 加权公式

### `score_line` — 延展型靶标模式复合分

- **Direction:** 越高越好
- **Base role:** 间接主分项
- **Definition:** 面向延展型靶标的复合分，综合有效接触量、覆盖、接触跨度、接触有效数、接触图连续性、接触场平滑性及方向相关指标。
- **Interpretation:** 较高值表示这些延展型界面指标的加权组合在当前批次归一化后较高。
- **Allowed interpretations:** 描述延展型接触模式的综合表现；追溯覆盖、跨度和连续性等组成指标
- **Forbidden interpretations:** 称为 binder 骨架本身的线性程度；称为二级结构线性；称为 Ramachandran 合理性；称为通用骨架质量
- **Suggested checks:** 检查接触区域是否沿靶标表面连续延展
- **Source basis:** get_component_weights 中 score_line 的组成

### `score_plane` — 平面型界面模式复合分

- **Direction:** 越高越好
- **Base role:** 间接主分项
- **Definition:** 面向较平坦界面的复合分，综合局部微拟合、平面对齐、局部平面性、中心距离、覆盖、接触量和接触图连续性等指标。
- **Interpretation:** 较高值表示局部平面互补相关指标的加权组合在当前批次归一化后较高。
- **Allowed interpretations:** 描述局部平面界面互补模式；追溯局部对齐和微拟合组成项
- **Forbidden interpretations:** 称为整个蛋白是平面的；称为二级结构平面性；称为主链构象正确
- **Suggested checks:** 检查局部界面法向和表面贴合情况
- **Source basis:** get_component_weights 中 score_plane 的组成

### `score_compact` — 局部紧凑接触模式复合分

- **Direction:** 越高越好
- **Base role:** 间接主分项
- **Definition:** 面向局部斑块或口袋型界面的复合分，综合有效接触量、接触密度、覆盖、微拟合、接触区域紧凑性、方向和平滑性指标。
- **Interpretation:** 较高值表示局部密集接触模式的加权组合在当前批次归一化后较高。
- **Allowed interpretations:** 描述局部接触斑块的密集程度和综合几何表现
- **Forbidden interpretations:** 称为整个蛋白折叠紧凑性；推断存在或不存在内部空腔；推断蛋白是否展开
- **Suggested checks:** 检查界面接触是否形成集中局部斑块
- **Source basis:** get_component_weights 中 score_compact 的组成

### `score_roughness` — 接触场平滑与连续性复合分

- **Direction:** 越高越好
- **Base role:** 直接主分项
- **Definition:** 名称虽为 roughness，但其组成主要奖励 binder和 target 接触场平滑性及接触图连续性，并惩罚接触跳跃和背向接触。
- **Interpretation:** 较高值表示接触场变化和平滑连续相关指标的加权组合较好。
- **Allowed interpretations:** 称为接触场平滑与连续性复合分；分析接触场是否存在突变
- **Forbidden interpretations:** 直接称为真实分子表面粗糙度；根据高低断言表面过粗或过光滑；推断蛋白折叠状态
- **Suggested checks:** 检查相邻界面残基的接触强度是否突变
- **Source basis:** score_roughness 实际由 smoothness、continuity、jump 和 backfacing 指标构成

### `score_microfit` — 局部界面微几何复合分

- **Direction:** 越高越好
- **Base role:** 诊断指标
- **Definition:** 综合局部微拟合、局部平面对齐、局部平面性、中心距离、有效接触量和覆盖等指标。
- **Interpretation:** 较高值表示当前定义下的局部界面几何组合较高。
- **Allowed interpretations:** 描述局部界面几何匹配的复合趋势；建议检查局部接触面贴合
- **Forbidden interpretations:** 推断共价键长正确；推断二面角正确；推断 Ramachandran 合格；推断侧链构象已经优化
- **Suggested checks:** 检查局部界面距离、法向和接触面贴合
- **Source basis:** get_component_weights 中 score_microfit 的组成

### `score_safety` — 几何风险抑制复合分

- **Direction:** 越高越好
- **Base role:** 直接主分项
- **Definition:** 由背向接触、CB方向支持、接触跳跃、接触场平滑性、紧接触比例、壳层敏感性、正向接触和原子冲突组成的启发式复合分。
- **Interpretation:** 较高值表示这些几何风险控制指标的组合较好。
- **Allowed interpretations:** 称为 Ranker 几何风险抑制分；追溯方向、跳跃、壳层敏感性和冲突组成项
- **Forbidden interpretations:** 称为生物安全性；称为毒性风险；称为实验安全风险；保证结构稳定或可表达
- **Suggested checks:** 检查界面方向、局部跳跃和近距离冲突
- **Source basis:** get_component_weights 中 score_safety 的组成

### `score_region` — 设计区域命中复合分

- **Direction:** 越高越好
- **Base role:** 诊断指标
- **Definition:** 综合 desired 区域接触权重、覆盖、平均场、有效数、hotspot 邻域命中，并惩罚 undesired区域接触的弱区域分数。
- **Interpretation:** 较高值表示接触更集中于用户指定的目标区域。
- **Allowed interpretations:** 描述设计区域和热点邻域的命中趋势
- **Forbidden interpretations:** 等同于结合亲和力；等同于热点能量贡献；在 region_score_used=False 时称其拉高主分
- **Suggested checks:** 检查指定区域周围是否存在真实接触
- **Source basis:** get_component_weights 中 score_region 的组成

### `score_hotspot` — 热点邻域接触诊断分

- **Direction:** 越高越好
- **Base role:** 诊断指标
- **Definition:** 由 hotspot 及其邻域的接触权重占比和有效覆盖组成的独立诊断分。
- **Interpretation:** 较高值表示更多软接触权重和覆盖落在指定热点及其邻域。
- **Allowed interpretations:** 描述指定热点邻域的接触命中情况
- **Forbidden interpretations:** 等同于热点残基结合能；等同于实验热点贡献；称为主分直接组成项
- **Suggested checks:** 检查指定热点残基附近的接触距离和空间覆盖
- **Source basis:** score_hotspot 的四项 hotspot 接触组成

### `effective_weight_sum` — 有效软接触总量

- **Direction:** 越高越好
- **Base role:** 原始指标
- **Definition:** 软接触矩阵 W 中所有有效权重之和。
- **Interpretation:** 同一靶点、同一参数和相近尺寸条件下，较高值表示模型计入的软接触总量更多。
- **Allowed interpretations:** 比较同批候选的有效软接触总量
- **Forbidden interpretations:** 直接等同于接触面积；直接等同于结合能；跨不同体系无校准比较
- **Suggested checks:** 检查接触是否集中于少数残基或分布较广
- **Source basis:** effective_weight_sum = sum(W)

### `target_effective_coverage` — 靶标有效接触覆盖率

- **Direction:** 越高越好
- **Base role:** 原始指标
- **Definition:** 靶标残基中接触场超过 contact_threshold 的比例。
- **Interpretation:** 较高值表示更多靶标残基达到有效接触阈值；当靶标是完整大蛋白时必须结合设计区域解释。
- **Allowed interpretations:** 描述当前定义下靶标残基的有效接触比例
- **Forbidden interpretations:** 等同于界面覆盖完整；认为覆盖整个大蛋白越多必然越好；等同于结合稳定性
- **Suggested checks:** 检查有效接触是否落在预期目标区域
- **Source basis:** mean(target_contact_field > contact_threshold)

### `target_contact_span_norm` — 靶标接触空间跨度

- **Direction:** 越高越好
- **Base role:** 原始指标
- **Definition:** 已接触靶标残基的最大空间跨度，除以整个靶标CA 坐标的最大空间跨度。
- **Interpretation:** 较高值表示接触区域在靶标空间上分布得更广。
- **Allowed interpretations:** 描述接触区域相对于整个靶标的空间延展
- **Forbidden interpretations:** 等同于覆盖率；等同于接触完整性；推断结合稳定性
- **Suggested checks:** 检查接触是否形成单个连续区域或多个远隔区域
- **Source basis:** max_pairwise_distance(contacted_target) / max_pairwise_distance(full_target)

### `backfacing_cb_far_weight_ratio` — 背向且CB远离的接触权重比例

- **Direction:** 越低越好
- **Base role:** 原始指标
- **Definition:** 距离加权接触中，同时被标记为背向且估计CB位置较远的权重比例。
- **Interpretation:** 较低值表示此类方向不利接触所占权重更少。
- **Allowed interpretations:** 描述界面方向启发式中的背向且CB远离比例
- **Forbidden interpretations:** 等同于侧链 rotamer 错误率；等同于真实侧链能量
- **Suggested checks:** 检查相关残基的估计侧链方向是否朝向界面
- **Source basis:** weighted_ratio(backfacing_cb_far_mask)

### `cb_closer_weight_ratio` — CB更靠近靶标的接触权重比例

- **Direction:** 越高越好
- **Base role:** 原始指标
- **Definition:** 距离加权接触中，估计CB比CA更靠近对侧界面的权重比例。
- **Interpretation:** 较高值表示更多接触获得估计侧链朝向支持。
- **Allowed interpretations:** 描述估计侧链方向对界面接触的支持比例
- **Forbidden interpretations:** 称为权重分配平衡性；等同于侧链构象正确率
- **Suggested checks:** 检查相关残基侧链方向是否指向靶标界面
- **Source basis:** weighted_ratio(cb_closer_mask)

### `binder_field_active_roughness` — binder活跃接触场变化度

- **Direction:** 越低越好
- **Base role:** 原始指标
- **Definition:** binder 活跃接触区域中，相邻残基接触场数值的局部变化程度。
- **Interpretation:** 较低值表示活跃接触场沿相邻残基变化更平缓。
- **Allowed interpretations:** 描述接触场沿 binder 序列或邻接边的变化程度
- **Forbidden interpretations:** 等同于真实分子表面粗糙度；推断存在异常凸起；推断蛋白折叠松散
- **Suggested checks:** 检查相邻界面残基的接触强度是否突然变化
- **Source basis:** binder_rough['active_roughness']

### `contact_map_continuity_score` — 接触图连续性分数

- **Direction:** 越高越好
- **Base role:** 原始指标
- **Definition:** 衡量相邻 binder 残基是否映射到空间上相近的靶标区域。
- **Interpretation:** 较高值表示相邻 binder 残基的靶标接触映射更加连续。
- **Allowed interpretations:** 描述接触映射的连续性
- **Forbidden interpretations:** 等同于二级结构连续性；等同于主链无断裂；直接推断结合稳定性
- **Suggested checks:** 检查相邻 binder 残基接触的靶标位置是否跳跃
- **Source basis:** Adjacent binder residues map to nearby target regions

### `contact_map_jump_fraction` — 接触图跳跃比例

- **Direction:** 越低越好
- **Base role:** 原始指标
- **Definition:** 相邻 binder 残基的靶标接触映射出现较大空间跳跃的比例。
- **Interpretation:** 较低值表示接触映射中的大跳跃更少。
- **Allowed interpretations:** 描述接触图局部跳跃比例
- **Forbidden interpretations:** 等同于主链断裂；等同于缺失残基；等同于二级结构中断
- **Suggested checks:** 检查产生跳跃的相邻 binder 残基及其靶标接触点
- **Source basis:** contact-map continuity calculation

### `shell_sensitivity_12_vs_8` — 宽松接触壳层敏感性

- **Direction:** 越低越好
- **Base role:** 原始指标
- **Definition:** 比较12 Å宽松接触壳与8 Å紧接触壳的贡献差异。
- **Interpretation:** 较高值表示接触量更依赖较宽松的12 Å壳层。
- **Allowed interpretations:** 描述接触是否依赖较远距离壳层
- **Forbidden interpretations:** 等同于分子动力学稳定性；等同于结合距离；等同于亲和力
- **Suggested checks:** 检查界面是否主要由较远距离接触构成
- **Source basis:** 12 Å shell contribution relative to 8 Å shell

### `clash_pairs` — 近距离原子对数量

- **Direction:** 越低越好
- **Base role:** 原始指标
- **Definition:** 目标链与 binder 原子距离小于 clash_cutoff 的原子对数量。
- **Interpretation:** 零表示在当前原子集合和 cutoff 下未检测到跨界面近距离原子对。
- **Allowed interpretations:** 报告当前 clash_cutoff 下检测到的原子对数量
- **Forbidden interpretations:** 据零值证明整体结构合理；据零值证明无任何立体冲突；据零值证明结构稳定
- **Suggested checks:** 在结构查看器中检查最短跨界面原子距离
- **Source basis:** sum(distance_matrix < clash_cutoff)
