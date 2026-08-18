# Protein Design Agent Improvement Backlog

本文件记录开发过程中发现的合理优化方向。

规则：
- 不因为暂缓实现就丢失问题。
- 每项记录问题、建议方向、暂缓原因和建议阶段。
- 本文件不自动扩大当前 Release Scope。
- 是否进入具体版本，以对应 Roadmap 为准。

## P1 — v0.4 候选

### Tool API
- 问题：当前 Chat 与 CLI 仍较直接地调用 deterministic core。
- 方向：建立稳定 PDA Tool API，供内置 Agent、OpenClaw 和未来 MCP 共用。
- 暂缓原因：架构已定义，但不是 v0.3 release blocker。
- 建议阶段：v0.4。

### Pydantic AI built-in Agent migration
- 问题：现有 LocalAgentOrchestrator / 手写自然语言路由维护成本较高。
- 方向：在 deterministic Tool API 稳定后，用 Pydantic AI 承担模型交互层。
- 原则：PlanningSession、审批、执行保护、provenance、BinderRanker 不迁入模型控制。
- 建议阶段：v0.4。

### Legacy Agent runtime retirement
- 方向：Pydantic AI 达到行为 parity 后，再逐步废弃旧 runtime。
- 暂缓原因：不能在缺少 parity tests 时直接替换。
- 建议阶段：v0.4+。

### OpenClaw / MCP gateway
- 方向：把外部 Agent 接到同一 Tool API，而不是绕过 deterministic core。
- 建议阶段：Tool API 稳定之后。

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
- 为什么当前不做：当前 package 只注册 `protein-design-agent` 为正式 CLI，这些模块未在 README / docs 中作为普通用户入口公开；现在修改会扩大 v0.3 范围，并可能削弱 subprocess 失败审计。
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
- 当前问题：`PlanningSession.provider_name` 目前只有一个字符串值，历史上同时承担“创建该会话的 Provider”和 legacy resume Provider 连续性判断。随着 Tool API、Pydantic AI 或其他 runtime 接入，同一任务未来可能跨不同模型或 Agent runtime 继续交互，单一 `provider_name` 无法准确表达逐轮 provenance。
- 建议方向：明确区分 session creation/original provider 与逐轮模型/runtime provenance；保留创建来源作为历史事实，并在 resume / Tool invocation history 中记录每次语义解析或 Agent runtime 的来源。Provider 身份不应成为 deterministic PlanningSession mutation 的授权条件。
- 为什么当前不做：本次 migration slice 的目标是先把 Provider semantic adapter 与 deterministic resume core 分离；修改 PlanningSession schema、manifest 和历史记录格式会同时扩大兼容性与迁移范围。当前 legacy Provider continuity 已被限制在 `resume_planning.py`，不会污染新的 provider-independent resume core。
- 优先级：P2。
- 建议版本：Tool API / Pydantic AI migration 时重新评估；若需要扩大兼容 schema 范围，则延后到 v0.4。

### Semantic request-evidence validation

- 发现位置：`agent/request_evidence.py`、`agent/planning_session_builder.py`、`agent/tool_api.py`。
- 当前问题：当前 deterministic evidence validator 可以证明字段 evidence 引用真实存在于可信用户原文中，也可以检查 patch/evidence 字段一致性，但纯字符串校验不能证明引用内容在语义上一定支持模型提取出的具体字段和值。
- 建议方向：在 Pydantic AI / Tool runtime 迁移时评估更强的结构化 extraction contract、框架级 tool argument约束和用户 review 机制；不得通过不断增加关键词、正则或特殊句式补丁重新实现手写 NLU。
- 为什么当前不做：v0.3 已通过原文绑定、typed schema、deterministic planner、READY_FOR_REVIEW 用户审核以及 approval/execution guard 建立多层边界。实现通用语义蕴含验证会显著扩大模型评估和 NLU 范围，不应阻塞首个确定性 BinderRanker 闭环。
- 优先级：P2。
- 建议版本：Pydantic AI migration 时重新评估；若仍需独立能力则 v0.4。

### Legacy request-evidence compatibility names

- 发现位置：`agent/planning_session_resume.py`、`agent/resume_planning.py`。
- 当前问题：共享的请求字段与原文证据规则已经迁移到 `agent/request_evidence.py`，但 legacy resume 路径仍保留 `SupplementExtraction` 和 `validate_supplement_evidence` 等历史名称作为 compatibility facade。
- 建议方向：在 legacy resume / handwritten Agent runtime 收缩或删除时，将剩余调用方迁移到中性的 `RequestExtraction` / `validate_request_evidence` API，并删除旧兼容名称；不要长期维护两套公共术语。
- 为什么当前不做：当前 migration slice 的目标是先建立唯一的共享 schema 和 validator，同时保持现有 resume、dataset advice 与 Tool API 行为兼容。现在同步重命名所有 legacy 调用方会扩大非必要改动范围。
- 优先级：P2。
- 建议版本：Pydantic AI / legacy runtime migration 时清理；若未完成则 v0.4。

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
- 建议版本：v0.3 Tool API migration 时重新评估；若会扩大当前发布范围则延后到 v0.4。

## Recording template

后续新增项目使用：

### <Title>
- 发现位置：
- 当前问题：
- 建议方向：
- 为什么当前不做：
- 优先级：
- 建议版本：
