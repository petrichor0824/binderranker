"""
BinderRanker public identity constants.

This module is intentionally dependency-free so that public-facing
interfaces can share one canonical product identity without coupling
branding to Agent, workflow, or scientific runtime modules.
"""

PROJECT_NAME = "BinderRanker"
AGENT_NAME = "BinderRanker Agent"

CLI_NAME = "binderranker"
LEGACY_CLI_NAME = "protein-design-agent"

SHORT_DESCRIPTION_EN = (
    "Interpretable ranking and layered screening "
    "for generated protein backbone candidates."
)

SHORT_DESCRIPTION_ZH = (
    "面向生成式蛋白骨架候选的可解释排序与分层筛选工具。"
)
