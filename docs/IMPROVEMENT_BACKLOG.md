# BinderRanker Improvement Backlog

本文件记录开发过程中发现的合理优化方向。

规则：
- 不因为暂缓实现就丢失问题。
- 每项记录问题、建议方向、暂缓原因和建议阶段。
- 本文件不自动扩大当前 Release Scope。
- 是否进入具体版本，以对应 Roadmap 为准。

长期优先级：

1. 科学排序与筛选能力。
2. 可复现性与验证。
3. 稳定 Tool/API 接口。
4. 外部 Agent 生态兼容。

BinderRanker 不是 Agent 产品。通用 chatbot、memory、personality、
planning 和 Agent infrastructure 只有在直接改善 BinderRanker 可用性时
才进入候选范围。

## Completed — v0.3.1 Scientific Result Stabilization

### Shared scientific-success semantics

- 原问题：冻结 Ranker 会将候选级异常写入结果行并正常结束进程；执行层和已安装 Wheel 冒烟测试此前主要依赖退出码及文件存在性，可能把“0 个有效候选”误判为成功。
- 已完成：新增共享结果验证层，统一验证四类输出、候选标识、候选级错误、必需字段、有限数值、连续唯一排名及分数降序关系。
- 已接入：本地执行完成门、结果解析/分析入口、已安装 Wheel 冒烟验证。
- 兼容性：冻结 BinderRanker 算法和 Tool API 未修改；仅收紧无效科学结果的成功语义。
- 完成版本：v0.3.1 stabilization。

## In progress — v0.4 Scientific Transparency

### Shared deterministic primary-score decomposition

- 原问题：候选主分贡献此前只在可选模型解释路径临时计算，离线确定性结果摘要没有公开统一的公式、权重、贡献和重建证据。
- 当前实现：从指标本体读取本次运行的审计权重；共享层计算候选直接主分项贡献，并验证其总和能重建记录的 `final_score_v4`。
- 接入范围：确定性结果解析与可选模型解释共用同一逻辑；新报告公开分解证据，旧报告以 `UNAVAILABLE` 明确降级且不推断缺失公式。
- 科学边界：贡献仅表示经验排序公式中的算术项，不是因果归因、结合能分解或跨靶点通用的重要性声明。
- 不变项：不修改评分、排名、筛选条件、Tool 授权边界或冻结 Ranker 资源。
- 目标阶段：v0.4.0 Workstream 7 第一切片。

### Sealed human-readable deterministic analysis report

- 原问题：`analyze-run` 已生成结构化结果摘要和失败差距 JSON，但离线用户仍需自行拼接多份产物才能审阅候选排名、分数贡献和允许公开的失败门槛证据。
- 当前实现：新增不依赖模型或网络的 Markdown 报告，只组合已经验证的结果摘要与失败分析，不重复计算评分、排名、筛选或阈值。
- 范围策略：`SMOKE_TEST_ONLY` 抑制不稳定的小样本动态阈值和差距；`EXPLORATORY` 与完整数据分析按各自权限展示批内差距，并明确其不代表生物机制。
- Provenance：完成清单记录报告路径和 SHA256；报告被修改后完整性校验失败；没有报告的旧版分析清单继续按 legacy 语义读取。
- 不变项：不修改评分、排名、筛选规则、Tool 授权边界或冻结 Ranker 资源。
- 目标阶段：v0.4.0 Workstream 7 第二切片。

### Deterministic adjacent-rank comparison evidence

- 原问题：已有主分分解能够解释单个候选的分数来源，但用户仍需手工相减才能回答“候选 A 为什么在经验评分公式中排在相邻候选 B 前面”。
- 当前实现：共享分解层逐项计算相邻候选的直接主分贡献差值，并要求差值之和精确重建记录的 `final_score_v4` 差；同时记录最大正向项、最大负向抵消项和重建误差。
- 规模边界：默认只比较相邻排名，产物数量为 `N-1`，避免生成所有候选两两比较的平方级数据。
- 兼容性：单候选明确标记为 `NOT_APPLICABLE`；旧结果或缺少分解证据明确标记为 `UNAVAILABLE`，不推断缺失比较。
- 科学边界：贡献差只解释经验排名公式中的算术差异，不代表因果、结合能分解或生物机制。
- 不变项：不修改评分、排名、筛选规则、Tool 授权边界或冻结 Ranker 资源。
- 目标阶段：v0.4.0 Workstream 7 第三切片。

## P1 — Stable Tool/API boundary

### Tool API adoption and runtime integration
- 当前状态：v0.3 已建立稳定、framework-independent 的 BinderRanker Tool API；legacy Chat 和部分 CLI 路径尚未统一迁移到这一边界。
- 后续方向：直接调用、可选 built-in Agent 和未来外部 adapter 统一复用 BinderRanker Tool API，不绕过 deterministic Core。
- 暂缓原因：v0.3 的目标是冻结稳定 domain boundary；后续只在实际调用方需要时继续收紧契约。
- 建议阶段：按科学工作流和外部集成的实际需要安排。

## P3 — Optional interaction and external-Agent integration

### Pydantic AI built-in Agent migration
- 问题：现有 LocalAgentOrchestrator / 手写自然语言路由维护成本较高。
- 方向：仅当独立评审证明能显著降低维护成本并直接改善 BinderRanker 可用性时，才考虑用 Pydantic AI 或其他成熟框架替换部分模型交互层。
- 原则：PlanningSession、审批、执行保护、provenance、BinderRanker 不迁入模型控制。
- 建议阶段：不绑定版本；需要独立 cost/benefit 与 parity review。

### Legacy Agent runtime retirement
- 方向：只有在另一个已批准交互层达到行为与安全 parity 后，才逐步废弃旧 runtime。
- 暂缓原因：不能在缺少 parity tests 时直接替换。
- 建议阶段：可选，且不是科学路线图前置条件。

### OpenClaw / MCP gateway
- 方向：把外部 Agent 接到同一 Tool API，而不是绕过 deterministic core。
- 建议阶段：科学能力、可复现性和 Tool/API 契约满足当前阶段要求后，再按真实集成需求安排。

## P2 — Error UX 后续增强

### Command-specific recovery guidance
- 当前：共享 format_error_guidance 已能安全隐藏技术异常并提供确定性兜底。
- 可优化：不同 CLI 命令提供更精确的恢复动作，而不是依赖通用 deterministic_actions。
- 暂缓条件：若 v0.3 已满足“事实 / 影响 / 恢复”标准，不阻塞发布。

### Error kind semantics
- 当前：部分 ChatSessionError / ChatDialogueError 统一按 REJECTED 展示。
- 可优化：进一步区分业务拒绝与真正运行失败。
- 风险：需要避免为展示语义重新扰动 deterministic state machine。
- 建议阶段：v0.4。

### Shared CLI error boundary helper
- 当前：各 CLI 命令显式调用 format_error_guidance。
- 可优化：抽取轻量 helper，减少重复代码。
- 为什么当前不做：4.6 已完成并通过完整回归；v0.3 发布前不再进行纯结构性的错误边界重构，避免扰动已经稳定的用户错误契约。
- 优先级：P2。
- 建议版本：v0.4。

### Persistent internal traceback audit
- 发现位置：`agent/error_guidance.py`、`agent/failure_evidence.py`、prepare / analyze 等失败审计路径。
- 当前问题：v0.3 会保留异常类型、内部错误消息、Python 异常链、任务状态、Manifest 路径、return code 和受限 stderr 等诊断证据，但不会把完整 Python traceback 持久化到失败审计文件。
- 建议方向：未来评估可选的内部 traceback / structured exception-chain 审计；需要同时定义路径和凭据脱敏、大小限制、保存位置、schema 兼容性，以及哪些信息绝不能进入模型上下文或普通用户 UI。
- 为什么当前不做：4.6 的目标是安全区分用户事实与内部诊断；新增完整 traceback 持久化会扩大 observability、隐私和审计 schema 范围，不应阻塞 v0.3。
- 优先级：P2。
- 建议版本：v0.4。

### Internal tool CLI error presentation

- 发现位置：`tools/check_project_input.py`、`tools/normalize_pdb_dataset.py`、`tools/run_binderranker.py`、`tools/validate_project_config.py`、`workflows/backbone_ranking_workflow.py`。
- 当前问题：这些内部/开发 Typer 入口仍有少量路径会直接显示底层 ValueError / ValidationError；其中 workflow stderr 同时承担内部失败诊断证据用途。
- 建议方向：如果未来将这些模块升级为正式公共命令，再统一接入 `UserFacingError` / `format_error_guidance()`；内部 workflow 应继续保留足够的原始诊断证据，由上层公共 CLI 负责安全展示。
- 为什么当前不做：当前 canonical public CLI 已是 `binderranker`，并暂时保留 `protein-design-agent` compatibility alias；这些内部 Typer 模块仍未作为普通用户入口公开。现在修改会扩大 v0.3 范围，并可能削弱 subprocess 失败审计。
- 优先级：P2。
- 建议版本：v0.4。

## P2 — Capability / Scientific Claims

### Semantic capability claim validation

- 发现位置：`agent/capability_truth.py`、`agent/result_explainer.py`、`agent/chat_dialogue.py`。
- 当前问题：v0.3 已使用统一 Capability Truth 和经过回归测试的确定性 pattern guard 拦截亲和力、稳定性、溶解性、实验成功概率、binder 保证、任意结构编辑和替代下游验证等越界声明；但该 guard 仍基于受控自然语言模式，不是完整的语义断言系统，未来可能遇到新的同义改写、其他语言表达或复杂否定结构。
- 建议方向：后续考虑建立结构化 capability claim taxonomy，将“主体、能力动作、科学性质、极性/否定、保证程度”等规范化后再做确定性判定，并保持模型不能自行决定自身能力边界。
- 为什么当前不做：v0.3 的主要用户可见出口已经有事前 Capability Truth、事后 deterministic guard、Chat fallback 和 Result Explainer repair/revalidate，现有测试覆盖发布要求；继续扩展为通用语义判定器会明显扩大 NLP、国际化和误判控制范围，不属于本版本发布阻塞项。
- 优先级：P2。
- 建议版本：v0.4。

## P2 — Planning / Interaction

### plan-mock long-term role
- 问题：框架迁移后 plan-mock 是否仍作为正式公共能力需要重新评估。
- 建议：保留迁移测试价值，不为 v0.3 扩展功能。

### Natural conversation intent quality
- 方向：除 v0.3 必做的“闲聊不被 NEEDS_INFORMATION 劫持”之外，
  后续可扩展更自然的 conversational intent classification。
- 建议阶段：v0.4+。

### Multi-provider PlanningSession provenance

- 发现位置：`schemas/planning_session.py`、`agent/planning_session_resume.py`、`agent/resume_planning.py`、resume history / manifest provenance。
- 当前问题：`PlanningSession.provider_name` 目前只有一个字符串值，历史上同时承担“创建该会话的 Provider”和 legacy resume Provider 连续性判断。随着 Tool API 或其他可选 runtime 接入，同一任务未来可能跨不同模型或 Agent runtime 继续交互，单一 `provider_name` 无法准确表达逐轮 provenance。
- 建议方向：明确区分 session creation/original provider 与逐轮模型/runtime provenance；保留创建来源作为历史事实，并在 resume / Tool invocation history 中记录每次语义解析或 Agent runtime 的来源。Provider 身份不应成为 deterministic PlanningSession mutation 的授权条件。
- 为什么当前不做：本次 migration slice 的目标是先把 Provider semantic adapter 与 deterministic resume core 分离；修改 PlanningSession schema、manifest 和历史记录格式会同时扩大兼容性与迁移范围。当前 legacy Provider continuity 已被限制在 `resume_planning.py`，不会污染新的 provider-independent resume core。
- 优先级：P2。
- 建议版本：出现真实跨 runtime 需求时重新评估；不因框架迁移设定版本目标。

### Runtime authorization injection for mutating Tools

- 发现位置：`agent/tool_api.py` 的 `request_approval()` / `execute_ranker()`，以及未来任何外部 Tool runtime。
- 当前问题：framework-independent Tool API 目前通过 `approval_confirmed` 和 `execution_confirmed` 显式表达两次独立授权事实。这个契约适合当前 deterministic API，但未来若直接把这些布尔参数暴露给模型填写，LLM Tool Call 就可能被错误等同为真实用户授权。
- 建议方向：外部 Agent 接入时通过可信 runtime context 注入用户身份和授权状态；模型只能请求执行某个 Tool，不能自行生成 approval 或 execution authorization。继续保留“批准计划”和“确认真正执行”两个独立步骤。
- 为什么当前不做：当前 slice 只建立 framework-independent Tool boundary，尚未接入外部 Agent runtime。现在提前设计完整会话级授权容器会扩大范围；现有 Chat、CLI、approval core 和 local executor 已经完整执行双确认与一次性批准规则。
- 优先级：任何 Agent 获得修改或执行类 Tool 之前的安全 blocker；不是 Agent 框架迁移目标。
- 建议版本：首次开放此类外部 Tool 前完成。

### Dataset observation / advice separation

- 发现位置：`agent/dataset_advisor.py`、`agent/tool_api.py`。
- 当前问题：`inspect_dataset_for_planning()` 是只读、deterministic 的稳定能力，但其返回类型 `DatasetPlanningAdvice` 同时包含 PDB 可验证事实、conditional suggestion、unresolved questions 和 cautions。v0.3 的 `inspect_dataset` Tool 直接复用该能力，因此 Tool 名义上的“检查结果”仍混有确定性规划建议。
- 建议方向：未来评估拆分纯 observation/report schema 与 planning-advice schema；底层 inspection 只描述文件和结构事实，上层再从 observation 构造建议。adoption 仍必须保持独立、需要确认的 mutation boundary。
- 为什么当前不做：现有 advisor 已只读、不调用模型、不修改 PlanningSession，且 advice adoption 已有独立的 freshness / confirmation 边界。为首个 BinderRanker 用户闭环重构 schema 会扩大调用方、持久化和兼容测试范围，没有直接发布收益。
- 优先级：P2。
- 建议版本：Tool contract 出现真实需求时重新评估。

### Semantic request-evidence validation

- 发现位置：`agent/request_evidence.py`、`agent/planning_session_builder.py`、`agent/tool_api.py`。
- 当前问题：当前 deterministic evidence validator 可以证明字段 evidence 引用真实存在于可信用户原文中，也可以检查 patch/evidence 字段一致性，但纯字符串校验不能证明引用内容在语义上一定支持模型提取出的具体字段和值。
- 建议方向：在未来 Tool runtime 集成时评估更强的结构化 extraction contract、框架级 tool argument 约束和用户 review 机制；不得通过不断增加关键词、正则或特殊句式补丁重新实现手写 NLU。
- 为什么当前不做：v0.3 已通过原文绑定、typed schema、deterministic planner、READY_FOR_REVIEW 用户审核以及 approval/execution guard 建立多层边界。实现通用语义蕴含验证会显著扩大模型评估和 NLU 范围，不应阻塞首个确定性 BinderRanker 闭环。
- 优先级：P2。
- 建议版本：出现真实 Tool runtime 需求时重新评估。

### Legacy request-evidence compatibility names

- 发现位置：`agent/planning_session_resume.py`、`agent/resume_planning.py`。
- 当前问题：共享的请求字段与原文证据规则已经迁移到 `agent/request_evidence.py`，但 legacy resume 路径仍保留 `SupplementExtraction` 和 `validate_supplement_evidence` 等历史名称作为 compatibility facade。
- 建议方向：在 legacy resume / handwritten Agent runtime 收缩或删除时，将剩余调用方迁移到中性的 `RequestExtraction` / `validate_request_evidence` API，并删除旧兼容名称；不要长期维护两套公共术语。
- 为什么当前不做：当前 migration slice 的目标是先建立唯一的共享 schema 和 validator，同时保持现有 resume、dataset advice 与 Tool API 行为兼容。现在同步重命名所有 legacy 调用方会扩大非必要改动范围。
- 优先级：P2。
- 建议版本：legacy runtime 获得独立迁移批准时清理。

## P2 — Domain error model

### Domain error taxonomy

- 发现位置：PackagedSampleError、WorkspaceInitError、ExecutionGuardError，以及其他领域异常。
- 当前问题：部分领域异常同时承载用户可知业务事实和内部技术诊断，历史 CLI 会直接使用 str(exc) 展示。
- 建议方向：逐步统一采用 UserFacingError / public_message 契约，将公开事实与内部诊断分离。
- 原则：不能为了隐藏技术细节而丢失“禁止覆盖”“批准不可复用”等真实业务事实。
- 为什么当前不全部重构：v0.3 只迁移实际用户入口涉及的领域错误；全局异常体系重构会扩大 Release Scope。
- 优先级：P2。
- 建议版本：v0.3 按需迁移，v0.4 评估统一 taxonomy。

### Structured model configuration errors

- 发现位置：schemas/provider_config.py、agent/provider_factory.py、validate-model-config CLI。
- 当前问题：配置读取、YAML 解析、Pydantic schema 验证和 Profile 解析目前主要通过 ValueError / ValidationError 表达，领域语义与内部诊断尚未完全结构化分离。
- 建议方向：未来评估 ModelConfigError / ProfileResolutionError 等结构化领域错误，记录 reason、field/profile 等安全字段，并继续保留原始 Pydantic/YAML 诊断作为内部证据。
- 为什么当前不做：v0.3 已可在 CLI 边界安全区分读取/基础格式、字段验证和 Profile 不存在；全面迁移会影响多个 Provider、planning 和 readiness 调用点。
- 优先级：P2。
- 建议版本：v0.4。

### Shared integrity utilities

- 发现位置：agent/approval.py、execution_guard.py、local_executor.py、ranker_result_parser.py。
- 当前问题：fingerprint_file、snapshot_pdb_dataset、load_json_object、resolve_recorded_path 等完整性/记录辅助能力定义在 approval.py，但已被审批之外的执行保护和结果解析代码复用。
- 建议方向：未来迁移到独立的 integrity / provenance utility 模块，由 approval、execution、analysis 等领域共同依赖；各领域在自己的边界将底层错误翻译为对应领域错误。
- 为什么当前不做：移动这些共享函数会扩大 import、兼容性和回归测试范围；当前 4.6 只需要保证用户错误边界正确。
- 优先级：P2。
- 建议版本：v0.4。

### Structured preparation failure stages

- 发现位置：`agent/prepare_pipeline.py` 的 `prepare_agent_run()` 原子准备流程。
- 当前问题：准备流程已经包含 PlanningSession 验证、Bundle 保护、staging 创建、会话复制、配置落地、workflow 运行、结果验证、正式发布、失败证据记录和 staging 清理等多个阶段，但 `AgentPreparationError` 目前只携带内部错误文本和 `public_message`，没有结构化记录失败阶段、失败证据位置或清理结果。
- 建议方向：未来为准备领域错误增加结构化 `failure_stage`，并视需要记录 `failure_evidence_path`、`cleanup_attempted`、`cleanup_complete` 等审计字段。
- 为什么当前不做：v0.3 的错误展示分层已经可以通过 `public_message` 安全完成；现在重构整个 prepare pipeline 会扩大回归范围，不应阻塞 4.6 和 v0.3 发布。
- 优先级：P2。
- 建议版本：v0.4。

## P2 — Preparation API naming

### Provider-agnostic preparation type names

- 发现位置：`agent/planning_session_prepare.py`。
- 当前问题：稳定的 PlanningSession preparation service 已不依赖自然语言 Provider，但仍沿用历史名称 `NaturalLanguagePreparationError` 和 `NaturalLanguagePrepareResult`，名称与当前职责不完全一致。
- 建议方向：迁移为 provider-agnostic preparation 命名，并通过 compatibility alias 暂时保留旧名称，再逐步迁移现有调用方。
- 为什么当前不做：当前 migration slice 专门解决 legacy Agent runtime 与 deterministic preparation 的依赖边界；同时进行公共类型重命名会把架构解耦和 API 命名迁移混在一个 commit 中，扩大回归范围。
- 优先级：P2。
- 建议版本：出现真实 API 命名维护需求时重新评估，不绑定 Agent runtime 迁移。

## P2 — Cross-platform path portability

### Explicit cross-platform path mapping

- 发现位置：`path_semantics.py`、CLI `--input-dir` 边界、Manifest / approval / execution 中的持久化路径恢复。
- 当前问题：v0.3 已能检测并拒绝当前平台无法正确解释的其他平台绝对路径，避免例如 Windows `C:\\...` 在 POSIX / WSL 中被静默拼接成错误本地路径；但不会自动完成 Windows、WSL 与 POSIX 之间的路径映射或历史 Bundle 路径迁移。
- 建议方向：未来如确有跨平台迁移需求，评估显式、用户可审计的路径映射配置，例如由用户声明 Windows 路径前缀与 WSL 挂载点之间的对应关系；不得依赖隐式猜测自动把 `C:\\...` 转换为 `/mnt/c/...`。
- 为什么当前不做：自动映射具有明显的平台和机器特异性，错误转换可能比明确拒绝更危险；它不属于 BinderRanker 的科学核心。v0.3 的发布目标是保证外平台路径不会被静默错误解释，而不是提供通用跨操作系统路径迁移系统。
- 优先级：P2。
- 建议版本：v0.4+，仅在真实用户需求证明有必要时实现。

## Recording template

后续新增项目使用：

### <Title>
- 发现位置：
- 当前问题：
- 建议方向：
- 为什么当前不做：
- 优先级：
- 建议版本：
