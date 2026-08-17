#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Legacy natural-language preparation adapter."""

from __future__ import annotations

from pathlib import Path

from protein_design_agent.agent.orchestrator import (
    LocalAgentOrchestrator,
)
from protein_design_agent.agent.planning_session_prepare import (
    NaturalLanguagePreparationError,
    NaturalLanguagePrepareResult,
    check_bundle_is_available,
    prepare_planning_session,
)
from protein_design_agent.agent.prepare_pipeline import (
    WorkflowRunner,
)
from protein_design_agent.agent.providers.base import (
    RequestParserProvider,
)


def prepare_from_natural_language(
    *,
    raw_text: str,
    provider: RequestParserProvider,
    bundle_dir: Path,
    runner: WorkflowRunner | None = None,
) -> NaturalLanguagePrepareResult:
    """通过 legacy Provider 将自然语言任务交给稳定 preparation service。"""
    clean_text = raw_text.strip()

    if not clean_text:
        raise NaturalLanguagePreparationError(
            "用户请求不能为空",
            public_message="用户请求不能为空。",
        )

    bundle_dir = bundle_dir.resolve()

    # Provider 调用前的 preflight，避免无效模型调用。
    check_bundle_is_available(bundle_dir)

    orchestrator = LocalAgentOrchestrator(
        provider
    )

    session = orchestrator.plan_from_text(
        clean_text
    )

    return prepare_planning_session(
        session=session,
        bundle_dir=bundle_dir,
        runner=runner,
    )
