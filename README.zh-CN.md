# BinderRanker

[English](README.md)

**生成式蛋白骨架候选的可解释排序与分层筛选工具**

BinderRanker 用于在更昂贵的下游序列设计、结构/复合体预测、
分子模拟、人工结构检查和实验验证之前，对已经生成的大量蛋白骨架
候选进行优先级排序。

它解决的是蛋白设计流程中的一个中间问题：

> 当我们已经生成了大量候选骨架后，哪些候选更值得继续投入
> 计算和实验资源？

    RFdiffusion / 其他骨架生成方法
                    ↓
             候选骨架 PDB
                    ↓
               BinderRanker
                    ↓
          可解释多指标排序
          + 分层筛选
          + 失败原因分析
                    ↓
             优先候选
                    ↓
    ProteinMPNN / 复合体预测 / MD / 实验

BinderRanker 本身不负责生成候选骨架；它对已有的候选 PDB 集合进行
排序和筛选。

BinderRanker 是一个**候选优先级筛选层**。高分或进入严格筛选层，
都不能作为生物学成功的直接证明。

当前发布版本线：**v0.4.0 — 科学透明度**。

---

## 为什么需要 BinderRanker？

RFdiffusion 等骨架生成方法可以一次产生大量看起来合理的候选结构，
但后续验证的成本明显更高。

如果把所有候选都继续送入序列设计、复合体结构预测、分子模拟、
人工检查乃至实验验证，计算成本、实验成本以及结果审查成本都会快速增加。

BinderRanker 的目标就是在这一阶段缩小搜索空间。

它使用确定性的结构证据对当前候选批次进行排序，进一步执行逐级收紧的
分层筛选，并记录哪些指标帮助了某个候选、哪些指标拖累了它。

BinderRanker 的目标不是宣布某个候选是普适意义上的“最佳 binder”，
而是在当前 target、候选数据集和评分配置下，帮助用户找出更值得进入
后续验证的候选。

---

## 科学方法

一次 BinderRanker 运行针对同一个 target、链布局和评分配置，
评估一组候选 PDB 结构。

排序所使用的结构证据包括：

- target–binder 接触量与接触覆盖；
- 接触区域的空间跨度与局部方向关系；
- 接触场平滑性和接触图连续性；
- 接触壳层敏感性；
- 空间位阻与原子冲突（clash）风险；
- 可选的 design region 证据；
- 可选的 hotspot 诊断指标。

BinderRanker 的分数主要用于**当前候选批次内部的相对比较**。

不同 target、不同归一化环境或互不相关运行中的分数，
不应被直接解释为可以横向比较的绝对质量值。

### 形态自适应排序

BinderRanker 使用三种互补的界面接触模式：

- `score_line` —— 延展型接触模式；
- `score_plane` —— 局部平面型界面模式；
- `score_compact` —— 局部紧凑高密度接触模式。

根据当前 target 得到的形态权重，会将三种模式组合成：

`morphology_adaptive_score`

这些权重表示当前 target 更强调哪种界面模式，
并不表示 binder 的二级结构类别，也不是蛋白整体形状分类。

关闭 region scoring 时，主排序分数为：

    final_score_v4 =
        0.85 × morphology_adaptive_score
      + 0.10 × score_safety
      + 0.05 × score_roughness

启用 region scoring 后，最终分数会额外加入 `score_region`。

`score_hotspot` 当前仍作为诊断指标使用，而不是最终分数中的固定独立项。

完整方法说明见：

- [`SCIENTIFIC_METHOD.md`](docs/SCIENTIFIC_METHOD.md)
- [`METRICS.md`](docs/METRICS.md)

---

## 分层筛选

BinderRanker 提供三个逐渐收紧的筛选层：

| 层级 | 作用 |
|---|---|
| Broad | 宽松候选筛选 |
| Medium | 更强的多指标联合筛选 |
| Strict | 当前配置下最严格的筛选层 |

这些筛选层使用当前批次有效候选计算出的分位数，
因此它们是**动态的、批次相对的筛选规则**。

Broad、Medium 和 Strict 不是固定的生物物理阈值，
也不是普适的生物学类别。

一个没有进入 Strict 层的候选并不等于“不可用”。

应进一步查看它具体未通过哪些条件，以及距离相应阈值有多远，
从而判断候选究竟是在哪些结构特征上受到拖累。

---

## 输出与可解释性

根据当前运行及允许的分析范围，BinderRanker 可以提供：

- 候选排名及各组成分数；
- Broad / Medium / Strict 分层筛选结果；
- 候选优势和已记录的弱点；
- failed-gate 信息；
- threshold-gap 分析；
- 带封存科学解释契约的确定性结果摘要；
- 包含相邻排名分数差异的人类可读确定性分析报告；
- 配置、执行及文件的来源追踪（provenance）；
- 可选的、受证据约束的模型解释。

确定性计算结果始终是权威证据。

模型生成的文字不能修改 BinderRanker 的分数、筛选层归属、
执行证据或已经记录的 provenance。

结果解读说明见：

[`RESULT_INTERPRETATION.md`](docs/RESULT_INTERPRETATION.md)

---

## 分析范围保护

BinderRanker 根据输入候选数量限制结果可以被解释到什么程度：

| 候选数量 | Scope | 允许的解释范围 |
|---:|---|---|
| 1–29 | `SMOKE_TEST_ONLY` | 仅用于工程和安装验证 |
| 30–199 | `EXPLORATORY` | 当前批次内的探索性比较 |
| 200+ | `FULL_DATASET_ANALYSIS` | 允许完整工作流层面的结果解释 |

这些边界是为了防止过度解读而设置的工程保护规则，
并不代表统计功效或数据代表性的证明。

随安装包提供的 5 个 PDB 示例只是**工程冒烟测试（smoke test）**，
不能作为 BinderRanker 生物学预测能力的科学验证。

---

## 快速开始

### 环境要求

- Python 3.10+
- Linux、WSL2，或其他能够运行相关科学计算依赖的环境
- 只有在使用可选 Agent 功能或模型生成解释时，
  才需要 OpenAI-compatible 模型端点

确定性的排序、筛选和结果分析流程本身并不依赖模型 API Key。

### 安装

创建独立 Python 环境：

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip

安装 BinderRanker v0.4.0 wheel：

    python -m pip install ./binderranker-0.4.0-py3-none-any.whl

检查安装：

    binderranker --help
    binderranker doctor

### 创建工作区和 smoke-test 数据

    binderranker init --destination ~/binderranker-workspace
    cd ~/binderranker-workspace

提取安装包内置示例：

    binderranker extract-sample \
      --destination data/3c98_small

运行本地环境检查：

    binderranker doctor

该示例包含 5 个候选 PDB，
只用于打包、安装和端到端工程冒烟测试。

### 开发环境安装

从源码仓库进行开发时：

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

运行测试：

    python -m pytest -q

---

## BinderRanker Agent

**BinderRanker Agent 是可选的交互层，不是科学排序算法本身。**

它可以辅助完成：

- 自然语言任务准备；
- 引导式工作流操作；
- 基于确定性证据的结果解释。

BinderRanker Core 仍负责确定性的任务准备、批准、执行保护、
来源追踪（provenance）和结果分析。

启动 Agent：

    binderranker chat

在不发起网络请求的情况下验证模型配置：

    binderranker validate-model-config \
      --config configs/models/deepseek.local.yaml \
      --profile deepseek_flash

API Key 应通过配置所指定的环境变量提供，
不应写入 YAML、Git 历史、日志、截图或共享的运行 bundle。

---

## 确定性工作流

BinderRanker 将任务准备、人工检查、批准、执行和结果分析分开。

核心行为包括：

- prepare 和 approval 阶段不会执行 BinderRanker；
- approval 会冻结已经检查过的配置和关键文件指纹；
- 批准后的 bundle 不能在执行前被静默修改；
- 一次 approval 只能被消费一次；
- 本地执行使用固定参数列表，而不是由模型生成任意 Shell；
- 确定性证据的优先级高于模型生成的文字解释。

常用命令：

| 命令 | 作用 |
|---|---|
| `prepare` | 检查、标准化、验证并准备运行 |
| `approve-run` | 冻结已审核配置和关键文件 |
| `execute-run` | 消费有效 approval 并运行 BinderRanker |
| `analyze-run` | 构建确定性结果证据 |
| `run-status` | 查看当前生命周期状态 |
| `chat` | 使用 BinderRanker Agent |

具体参数请使用：

    binderranker <command> --help

---

## 可复现性与来源追踪（Provenance）

BinderRanker 的运行包（run bundle）会保存不同阶段的重要证据，包括：

- 结构化任务信息；
- dataset inspection 结果；
- 标准化输入的文件指纹；
- workflow plan；
- approval 记录；
- execution manifest；
- 输出文件指纹；
- 确定性分析结果。

已经完成或已经消费 approval 的运行包（bundle），
应被视为不可随意修改的审计记录。

安装包中的 BinderRanker Engine 以冻结资源形式分发，
并会在计划（planning）或执行（execution）前进行完整性校验。

---

## 科学适用范围与限制

BinderRanker **不能**被解释为直接预测：

- 实验结合是否成功；
- binding affinity；
- 热力学稳定性或折叠稳定性；
- 溶解性；
- 普适意义上的 binder 质量；
- 实验成功概率。

BinderRanker 也不能替代：

- RFdiffusion 或其他骨架生成方法；
- ProteinMPNN 或其他序列设计系统；
- AlphaFold、Boltz 或其他结构/复合体预测方法；
- 分子动力学或自由能计算；
- 人工结构检查；
- 生化、功能或其他实验验证。

更合适的描述包括：

- 排名更高的 backbone；
- 优先候选；
- 值得进一步研究的候选；
- 通过当前配置筛选层的候选。

只有获得独立的下游证据后，才可以使用：

- best binder；
- highest-affinity candidate；
- guaranteed binder；
- validated hit

等更强的结论。

---

## 架构

    CLI / Python 直接使用 ────────┐
    内置 Agent（可选）────────────┼──> BinderRanker Tool API
    外部 Agent（可选）────────────┘              ↓
                                         BinderRanker Core
                                                   ↓
                                         BinderRanker Engine

- **BinderRanker Engine**：科学排序与分层筛选核心。
- **BinderRanker Core**：确定性工作流、安全边界、provenance、
  结果解析和分析。
- **BinderRanker Tool API**：直接使用和外部集成共享的稳定受控接口。
- **BinderRanker Agent**：可选的自然语言交互层。

无论通过哪一种入口，底层使用的都是同一个 BinderRanker 科学能力。
Agent 接口只改善可访问性与集成体验，不拥有也不重新定义科学行为。

为保持向后兼容，内部 Python namespace 继续使用：

`protein_design_agent`

这是兼容性实现细节，不是项目的公开品牌名称。

---

## 验证状态

BinderRanker 明确区分**工程验证**与**科学验证**。

工程验证包括：

- 确定性回归测试；
- 执行完整性检查；
- 打包资源（package resource）校验；
- provenance 验证；
- 安装测试；
- smoke-test 工作流。

这些验证可以证明软件和工作流行为符合预期，
但**不能证明 BinderRanker 具有生物学预测准确性**。

科学验证需要独立证据，例如：

- 真实设计任务的回顾性比较；
- 下游复合体结构预测比较；
- 富集分析（enrichment analysis）；
- 前瞻性实验验证。

v0.4 之后的开发首先建立带 SHA256 封存、并显式防止 target 泄漏的
benchmark 输入契约，以及确定性的固定预算 BinderRanker/baseline 对照。
对照指标排除 calibration 数据，并显式保留无法定义的 campaign 统计量。
这些能力用于审计回顾性证据；合成数据或仅通过契约验证，不表示
BinderRanker 已被证明能够改善真实下游结果。

---

## 文档

- [科学方法](docs/SCIENTIFIC_METHOD.md)
- [指标说明](docs/METRICS.md)
- [结果解读](docs/RESULT_INTERPRETATION.md)
- [验证状态与边界](docs/VALIDATION.md)
- [Benchmark 输入契约](docs/BENCHMARK_CONTRACT.md)
- [固定预算 Benchmark 指标](docs/BENCHMARK_METRICS.md)
- [公开身份与科学表述边界](docs/PUBLIC_IDENTITY.md)
- [v0.3 架构](docs/V0.3_ARCHITECTURE.md)
- [架构演进与开发原则](docs/ARCHITECTURE_EVOLUTION.md)
- [v0.3 之后的执行路线图](docs/POST_V0_3_EXECUTION_ROADMAP.md)
- [历史 v0.3 路线图](docs/V0.3_ROADMAP.md)
- [改进 backlog](docs/IMPROVEMENT_BACKLOG.md)

历史 v0.2 规划文档继续保留，用于追踪项目演进过程。

---

## 路线图（Roadmap）

后续开发依次优先考虑科学排序与筛选能力、可复现性与验证、稳定
Tool/API 接口，最后才是可选的外部 Agent 生态兼容。Agent 框架扩张
不是独立产品目标。

当前路线图：

[`docs/POST_V0_3_EXECUTION_ROADMAP.md`](docs/POST_V0_3_EXECUTION_ROADMAP.md)

历史 v0.3 执行记录：

[`docs/V0.3_ROADMAP.md`](docs/V0.3_ROADMAP.md)

暂缓但已经记录的改进：

[`docs/IMPROVEMENT_BACKLOG.md`](docs/IMPROVEMENT_BACKLOG.md)

---

## 引用、贡献与许可证

贡献指南见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

机器可读的引用信息见 [`CITATION.cff`](CITATION.cff)，GitHub 的
**Cite this repository** 功能可直接使用这些 metadata。

主要软件作者：

- **Zheng Hu**
- ORCID：[0009-0006-7368-613X](https://orcid.org/0009-0006-7368-613X)

在论文、报告或分析中使用 BinderRanker 时，请同时注明实际使用的
软件版本。

Copyright 2026 BinderRanker contributors.

本项目基于 Apache License 2.0 发布。详见 [`LICENSE`](LICENSE)。
