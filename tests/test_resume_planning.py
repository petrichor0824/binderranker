import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import protein_design_agent.agent.resume_planning as module
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.resume_planning import (
    ResumePlanningError,
    resume_planning_session,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


class FakeStructuredProvider:
    def __init__(
        self,
        payload: dict,
        *,
        name: str = "fake-provider",
    ) -> None:
        self.payload = payload
        self._name = name
        self.calls = 0
        self.last_messages = None
        self.all_messages = []

    @property
    def name(self) -> str:
        return self._name

    def generate_json(
        self,
        messages,
    ) -> dict:
        self.calls += 1
        self.last_messages = messages
        self.all_messages.append(messages)

        source_payload = self.payload

        if isinstance(
            source_payload,
            list,
        ):
            if not source_payload:
                raise AssertionError(
                    "FakeStructuredProvider payload 列表不能为空"
                )

            index = min(
                self.calls - 1,
                len(source_payload) - 1,
            )

            source_payload = (
                source_payload[index]
            )

        elif self.calls > 1:
            # 旧测试只为第一遍解析提供一个 payload。
            # 第二遍完整性审查默认表示“没有发现遗漏”。
            source_payload = {
                "patch": {},
                "evidence": {},
                "notes": [],
            }

        # 浅复制，避免测试代码修改原始 payload。
        payload = dict(source_payload)

        if (
            "patch" in payload
            and "evidence" not in payload
        ):
            context = json.loads(
                messages[-1]["content"]
            )

            # 第一遍提示词使用 supplement_text，
            # 第二遍审查提示词使用 conversation_text。
            evidence_text = str(
                context.get("supplement_text")
                or context.get("conversation_text")
                or ""
            )

            patch = payload["patch"]

            payload["evidence"] = {
                field_name: evidence_text
                for field_name, value
                in patch.items()
                if value is not None
            }

        return payload



def create_incomplete_bundle(
    tmp_path: Path,
    request: UserRequest,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    plan = build_agent_plan(request)

    assert plan.status == "NEEDS_INFORMATION"

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=plan,
        request_explicit_fields=sorted(
            field_name
            for field_name
            in request.model_fields_set
            if field_name != "raw_text"
        ),
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(indent=2),
        encoding="utf-8",
    )

    (
        bundle
        / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": (
                    "NEEDS_INFORMATION"
                ),
                "provider_name": (
                    "fake-provider"
                ),
                "bundle_directory": (
                    str(bundle)
                ),
                "planning_session": str(
                    bundle
                    / "planning_session.json"
                ),
                "missing_information": (
                    plan.missing_information
                ),
                "scientific_workflow_executed": (
                    False
                ),
                "binderranker_executed": False,
                "remote_backend_used": False,
            }
        ),
        encoding="utf-8",
    )

    return bundle


def test_still_missing_updates_session(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="分析骨架",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": (
                    str(tmp_path / "pdbs")
                )
            },
            "notes": [],
        }
    )

    result = resume_planning_session(
        bundle_dir=bundle,
        supplement_text=(
            f"输入目录是 {tmp_path / 'pdbs'}"
        ),
        provider=provider,
    )

    assert (
        result.status
        == "NEEDS_INFORMATION"
    )

    assert "input_layout" in (
        result.missing_information
    )

    assert (
        result.history_record.is_dir()
    )

    session = module.load_planning_session(
        bundle / "planning_session.json"
    )

    assert session.request.input_dir == (
        tmp_path / "pdbs"
    )

    assert (
        session.plan.status
        == "NEEDS_INFORMATION"
    )


def test_conflicting_confirmed_field_rejected(
    tmp_path: Path,
) -> None:
    original_dir = tmp_path / "original"

    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=original_dir,
        input_layout="existing_chains",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    original_session = (
        bundle / "planning_session.json"
    ).read_bytes()

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": (
                    str(tmp_path / "different")
                )
            }
        }
    )

    with pytest.raises(
        ResumePlanningError,
        match="已经确认",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text=(
                "输入目录改成 different"
            ),
            provider=provider,
        )

    assert (
        bundle / "planning_session.json"
    ).read_bytes() == original_session


def test_provider_must_match_original(
    tmp_path: Path,
) -> None:
    request = UserRequest(
        raw_text="分析骨架",
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_dir": str(
                    tmp_path / "pdbs"
                )
            }
        },
        name="different-provider",
    )

    with pytest.raises(
        ResumePlanningError,
        match="Provider",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text="补充目录",
            provider=provider,
        )


def test_ready_session_is_promoted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = UserRequest(
        raw_text="分析已有分链数据",
        project_name="demo",
        input_dir=tmp_path / "pdbs",
        input_layout="existing_chains",
        binder_chain=None,
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "binder_chain": "B"
            }
        }
    )

    def fake_prepare_agent_run(
        *,
        session_path,
        bundle_dir,
        runner=None,
    ):
        bundle_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        session_copy = (
            bundle_dir
            / "planning_session.json"
        )
        session_copy.write_bytes(
            session_path.read_bytes()
        )

        project_config = (
            bundle_dir / "project.yaml"
        )
        project_config.write_text(
            "project_name: demo\n",
            encoding="utf-8",
        )

        provenance = (
            bundle_dir
            / "project.provenance.json"
        )
        provenance.write_text(
            "{}",
            encoding="utf-8",
        )

        workflow_directory = (
            bundle_dir / "workflow"
        )
        workflow_directory.mkdir()

        workflow_manifest = (
            workflow_directory
            / "workflow_manifest.json"
        )
        workflow_manifest.write_text(
            '{"status":"READY_FOR_REVIEW"}',
            encoding="utf-8",
        )

        prepare_manifest = (
            bundle_dir
            / "agent_prepare_manifest.json"
        )
        prepare_manifest.write_text(
            json.dumps(
                {
                    "status": (
                        "READY_FOR_REVIEW"
                    ),
                    "project_name": "demo",
                }
            ),
            encoding="utf-8",
        )

        return SimpleNamespace(
            project_name="demo",
            provider_name="fake-provider",
            bundle_directory=bundle_dir,
            session_copy=session_copy,
            project_config=project_config,
            project_provenance=provenance,
            workflow_directory=(
                workflow_directory
            ),
            workflow_manifest=(
                workflow_manifest
            ),
            stdout_log=(
                bundle_dir
                / "logs"
                / "stdout.log"
            ),
            stderr_log=(
                bundle_dir
                / "logs"
                / "stderr.log"
            ),
            prepare_manifest=(
                prepare_manifest
            ),
            scientific_workflow_executed=False,
            binderranker_executed=False,
            remote_backend_used=False,
        )

    monkeypatch.setattr(
        module,
        "prepare_agent_run",
        fake_prepare_agent_run,
    )

    result = resume_planning_session(
        bundle_dir=bundle,
        supplement_text="binder 链是 B",
        provider=provider,
    )

    assert (
        result.status
        == "READY_FOR_REVIEW"
    )

    assert (
        result.prepare_manifest.is_file()
    )

    assert (
        result.history_record.is_dir()
    )

    session = module.load_planning_session(
        bundle / "planning_session.json"
    )

    assert session.request.binder_chain == "B"
    assert (
        session.plan.status
        == "READY_FOR_REVIEW"
    )


def test_prepare_failure_restores_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=tmp_path / "pdbs",
        input_layout="existing_chains",
        binder_chain=None,
    )

    bundle = create_incomplete_bundle(
        tmp_path,
        request,
    )

    original_session = (
        bundle / "planning_session.json"
    ).read_bytes()

    original_manifest = (
        bundle
        / "agent_prepare_manifest.json"
    ).read_bytes()

    provider = FakeStructuredProvider(
        {
            "patch": {
                "binder_chain": "B"
            }
        }
    )

    def failing_prepare(
        *,
        session_path,
        bundle_dir,
        runner=None,
    ):
        bundle_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        (
            bundle_dir / "partial.txt"
        ).write_text(
            "partial",
            encoding="utf-8",
        )

        raise RuntimeError(
            "simulated prepare failure"
        )

    monkeypatch.setattr(
        module,
        "prepare_agent_run",
        failing_prepare,
    )

    with pytest.raises(
        ResumePlanningError,
        match="原不完整任务已恢复",
    ):
        resume_planning_session(
            bundle_dir=bundle,
            supplement_text="binder 链是 B",
            provider=provider,
        )

    assert (
        bundle / "planning_session.json"
    ).read_bytes() == original_session

    assert (
        bundle
        / "agent_prepare_manifest.json"
    ).read_bytes() == original_manifest

    assert not (
        bundle / "partial.txt"
    ).exists()


def test_system_default_can_be_overridden() -> None:
    from protein_design_agent.agent.resume_planning import (
        UserRequestPatch,
        merge_request_patch,
    )

    request = UserRequest(
        raw_text="分析已有分链数据",
        input_dir=Path("/tmp/pdbs"),
        input_layout="existing_chains",
        binder_chain=None,
    )

    # target_start_residue=1 来自系统默认，
    # 不在旧 Provider 的显式字段集合中。
    merged, accepted = merge_request_patch(
        old_request=request,
        old_missing_information=[
            "binder_chain",
        ],
        old_explicit_fields={
            "input_dir",
            "input_layout",
        },
        patch=UserRequestPatch(
            binder_chain="B",
            target_start_residue=4,
        ),
        supplement_text=(
            "binder 链是 B，"
            "target 从第 4 号残基开始"
        ),
    )

    assert merged.binder_chain == "B"
    assert merged.target_start_residue == 4

    assert set(accepted) == {
        "binder_chain",
        "target_start_residue",
    }


def create_extraction_session() -> PlanningSession:
    request = UserRequest(
        raw_text="分析这个 PDB 目录",
        input_dir=Path("/tmp/pdbs"),
    )

    return PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[
            "input_dir",
        ],
    )


def test_semantic_extraction_can_capture_layout_and_source_chain() -> None:
    """
    一句话可以同时表达多个字段，不能只提取布局。
    """
    supplement = (
        "这些结构里的 target 和 binder "
        "现在拼在同一条 A 链中。"
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_layout": (
                    "concatenated_single_chain"
                ),
                "source_chain": "A",
            },
            "evidence": {
                "input_layout": (
                    "target 和 binder "
                    "现在拼在同一条 A 链中"
                ),
                "source_chain": (
                    "同一条 A 链中"
                ),
            },
        }
    )

    extraction = module.extract_supplement_patch(
        provider=provider,
        supplement_text=supplement,
        session=create_extraction_session(),
    )

    assert (
        extraction.patch.input_layout
        == "concatenated_single_chain"
    )
    assert extraction.patch.source_chain == "A"

    system_prompt = (
        provider.last_messages[0]["content"]
    )

    assert "不是做关键词匹配" in system_prompt
    assert "一句话可能同时明确表达多个字段" in (
        system_prompt
    )
    assert (
        "source_chain=A"
        in system_prompt
    )


def test_semantic_extraction_can_capture_count_and_start() -> None:
    """
    数量和起始编号在同一句中出现时应同时提取。
    """
    supplement = (
        "target 从第 4 号残基开始，"
        "共有 132 个残基。"
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "target_start_residue": 4,
                "target_residue_count": 132,
            },
            "evidence": {
                "target_start_residue": (
                    "从第 4 号残基开始"
                ),
                "target_residue_count": (
                    "共有 132 个残基"
                ),
            },
        }
    )

    extraction = module.extract_supplement_patch(
        provider=provider,
        supplement_text=supplement,
        session=create_extraction_session(),
    )

    assert (
        extraction.patch.target_start_residue
        == 4
    )
    assert (
        extraction.patch.target_residue_count
        == 132
    )


def test_supplement_evidence_must_quote_user_text() -> None:
    """
    模型不能用自己编造或改写的文本冒充用户依据。
    """
    supplement = (
        "target 和 binder 拼在同一条 A 链中。"
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_layout": (
                    "concatenated_single_chain"
                ),
                "source_chain": "A",
            },
            "evidence": {
                "input_layout": (
                    "拼在同一条 A 链中"
                ),
                # 用户原话没有 B 链，这条依据应被拒绝。
                "source_chain": "原始链是 B 链",
            },
        }
    )

    with pytest.raises(
        ResumePlanningError,
        match="不是用户本轮原话",
    ):
        module.extract_supplement_patch(
            provider=provider,
            supplement_text=supplement,
            session=create_extraction_session(),
        )


def test_completeness_audit_recovers_omitted_source_chain() -> None:
    """
    第一遍只提取布局时，第二遍应能从同一句原话中
    找回 source_chain=A。
    """
    session = create_extraction_session()

    supplement = (
        "这些结构里的 target 和 binder "
        "拼在同一条 A 链中。"
    )

    provider = FakeStructuredProvider(
        [
            {
                "patch": {
                    "input_layout": (
                        "concatenated_single_chain"
                    ),
                },
                "evidence": {
                    "input_layout": (
                        "target 和 binder "
                        "拼在同一条 A 链中"
                    ),
                },
            },
            {
                "patch": {
                    "source_chain": "A",
                },
                "evidence": {
                    "source_chain": (
                        "同一条 A 链中"
                    ),
                },
                "notes": [
                    (
                        "第一遍遗漏了用户明确提供的"
                        " source_chain"
                    ),
                ],
            },
        ]
    )

    primary = module.extract_supplement_patch(
        provider=provider,
        supplement_text=supplement,
        session=session,
    )

    audit = module.audit_omitted_explicit_fields(
        provider=provider,
        supplement_text=supplement,
        session=session,
        primary_extraction=primary,
    )

    combined = (
        module.combine_supplement_extractions(
            session=session,
            primary=primary,
            audit=audit,
        )
    )

    assert (
        combined.patch.input_layout
        == "concatenated_single_chain"
    )
    assert combined.patch.source_chain == "A"

    assert (
        combined.evidence["source_chain"]
        == "同一条 A 链中"
    )

    assert provider.calls == 2


def test_completeness_audit_can_recover_from_earlier_user_text() -> None:
    """
    第一遍解析器漏掉初始请求中的明确参数时，
    审查器可以引用此前用户原话恢复。
    """
    request = UserRequest(
        raw_text=(
            "原始结构只有 A 链，"
            "target 和 binder 还没有拆开。"
        ),
        input_dir=Path("/tmp/pdbs"),
    )

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[
            "input_dir",
        ],
    )

    primary = module.SupplementExtraction(
        patch=module.UserRequestPatch(),
        evidence={},
    )

    provider = FakeStructuredProvider(
        {
            "patch": {
                "input_layout": (
                    "concatenated_single_chain"
                ),
                "source_chain": "A",
            },
            "evidence": {
                "input_layout": (
                    "target 和 binder 还没有拆开"
                ),
                "source_chain": (
                    "原始结构只有 A 链"
                ),
            },
        }
    )

    audit = module.audit_omitted_explicit_fields(
        provider=provider,
        supplement_text=(
            "我还需要提供什么信息？"
        ),
        session=session,
        primary_extraction=primary,
    )

    assert (
        audit.patch.input_layout
        == "concatenated_single_chain"
    )
    assert audit.patch.source_chain == "A"


def test_completeness_audit_cannot_change_confirmed_field() -> None:
    """
    第二遍审查只能补遗漏，不能修改用户已确认字段。
    """
    request = UserRequest(
        raw_text=(
            "binder 是 B 链。"
        ),
        input_dir=Path("/tmp/pdbs"),
        input_layout="existing_chains",
        binder_chain="B",
    )

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=build_agent_plan(request),
        request_explicit_fields=[
            "input_dir",
            "input_layout",
            "binder_chain",
        ],
    )

    primary = module.SupplementExtraction(
        patch=module.UserRequestPatch(),
        evidence={},
    )

    audit = module.SupplementExtraction(
        patch=module.UserRequestPatch(
            binder_chain="C",
        ),
        evidence={
            "binder_chain": (
                "binder 是 C 链"
            ),
        },
    )

    with pytest.raises(
        ResumePlanningError,
        match="修改用户已经确认的字段",
    ):
        module.combine_supplement_extractions(
            session=session,
            primary=primary,
            audit=audit,
        )


def test_completeness_audit_detects_pass_conflict() -> None:
    """
    两遍模型对同一字段给出不同值时必须停止，
    不能静默选择其中一个。
    """
    session = create_extraction_session()

    primary = module.SupplementExtraction(
        patch=module.UserRequestPatch(
            source_chain="A",
        ),
        evidence={
            "source_chain": "A 链",
        },
    )

    audit = module.SupplementExtraction(
        patch=module.UserRequestPatch(
            source_chain="B",
        ),
        evidence={
            "source_chain": "B 链",
        },
    )

    with pytest.raises(
        ResumePlanningError,
        match="两遍语义提取结果发生冲突",
    ):
        module.combine_supplement_extractions(
            session=session,
            primary=primary,
            audit=audit,
        )


def test_same_default_values_are_promoted_to_explicit_provenance() -> None:
    """
    用户明确给出的值即使恰好等于系统默认值，
    也必须登记为新的显式来源。
    """
    request = UserRequest(
        raw_text="分析拼接链数据",
        input_dir=Path("/tmp/pdbs"),
        input_layout=(
            "concatenated_single_chain"
        ),
        source_chain="A",
        target_residue_count=132,
        target_start_residue=4,
    )

    # 以下四个值由 UserRequest 默认产生，
    # 不在此前用户明确提供的字段集合中。
    assert request.normalized_target_chain == "A"
    assert request.normalized_binder_chain == "B"
    assert request.region_policy == "diagnostic"
    assert request.region_filter == "off"

    patch = module.UserRequestPatch(
        normalized_target_chain="A",
        normalized_binder_chain="B",
        region_policy="diagnostic",
        region_filter="off",
    )

    merged, accepted_fields = (
        module.merge_request_patch(
            old_request=request,
            old_missing_information=[],
            old_explicit_fields={
                "input_dir",
                "input_layout",
                "source_chain",
                "target_residue_count",
                "target_start_residue",
            },
            patch=patch,
            supplement_text=(
                "拆分后 target 叫 A 链，"
                "binder 叫 B 链。"
                "区域信息只用于诊断，不做过滤。"
            ),
        )
    )

    assert set(accepted_fields) == {
        "normalized_target_chain",
        "normalized_binder_chain",
        "region_policy",
        "region_filter",
    }

    assert (
        merged.normalized_target_chain
        == "A"
    )
    assert (
        merged.normalized_binder_chain
        == "B"
    )
    assert merged.region_policy == "diagnostic"
    assert merged.region_filter == "off"


def test_same_already_explicit_value_is_not_a_false_update() -> None:
    """
    已经明确确认的字段再次收到同值时，
    不应制造新的历史更新。
    """
    request = UserRequest(
        raw_text="标准化 target 链是 A",
        input_dir=Path("/tmp/pdbs"),
        normalized_target_chain="A",
    )

    patch = module.UserRequestPatch(
        normalized_target_chain="A",
    )

    with pytest.raises(
        ResumePlanningError,
        match="没有提供新的可用字段",
    ):
        module.merge_request_patch(
            old_request=request,
            old_missing_information=[],
            old_explicit_fields={
                "input_dir",
                "normalized_target_chain",
            },
            patch=patch,
            supplement_text=(
                "target 仍然叫 A 链"
            ),
        )
