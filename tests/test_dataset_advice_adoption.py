import json
from pathlib import Path

import pytest

from protein_design_agent.agent.dataset_advice_adoption import (
    DatasetAdviceAdoptionError,
    adopt_dataset_advice,
)
from protein_design_agent.agent.dataset_advisor import (
    ConditionalDatasetSuggestion,
    DatasetFileEvidence,
    DatasetPlanningAdvice,
    save_dataset_advice,
    sha256_file,
)
from protein_design_agent.schemas.planning_session import (
    PlanningSession,
)
from protein_design_agent.agent.planner import (
    build_agent_plan,
)
from protein_design_agent.agent.resume_planning import (
    validate_incomplete_bundle,
)
from protein_design_agent.schemas.agent_models import (
    UserRequest,
)


def create_bundle(
    tmp_path: Path,
) -> tuple[Path, Path]:
    pdb_dir = tmp_path / "pdbs"
    pdb_dir.mkdir()

    pdb_path = pdb_dir / "one.pdb"
    pdb_path.write_text(
        "ATOM TEST\n",
        encoding="utf-8",
    )

    request = UserRequest(
        raw_text="分析这个 PDB 目录",
        input_dir=pdb_dir,
    )

    plan = build_agent_plan(request)

    assert plan.status == (
        "NEEDS_INFORMATION"
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    session = PlanningSession(
        provider_name="fake-provider",
        request=request,
        plan=plan,
        request_explicit_fields=[
            "input_dir",
        ],
    )

    (
        bundle / "planning_session.json"
    ).write_text(
        session.model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )

    (
        bundle
        / "agent_prepare_manifest.json"
    ).write_text(
        json.dumps(
            {
                "status": (
                    "NEEDS_INFORMATION"
                ),
                "missing_information": (
                    plan.missing_information
                ),
            }
        ),
        encoding="utf-8",
    )

    advice = DatasetPlanningAdvice(
        created_at_utc=(
            "2026-07-28T00:00:00+00:00"
        ),
        status="NEEDS_USER_CONFIRMATION",
        input_directory=pdb_dir,
        recursive=False,
        processed_file_count=1,
        valid_file_count=1,
        invalid_file_count=0,
        all_valid_files_are_single_chain=True,
        common_single_chain_id="A",
        file_evidence=[
            DatasetFileEvidence(
                file_name="one.pdb",
                file_path=pdb_path,
                sha256=sha256_file(
                    pdb_path
                ),
                valid=True,
                chain_count=1,
                chain_ids=["A"],
                total_residue_count=219,
                chain_signature="A:219",
            )
        ],
        conditional_suggestion=(
            ConditionalDatasetSuggestion(
                condition=(
                    "用户确认文件同时包含 target "
                    "和 binder"
                ),
                candidate_patch={
                    "input_layout": (
                        "concatenated_single_chain"
                    ),
                    "source_chain": "A",
                },
                evidence_summary=[
                    "1/1 个文件只有 A 链",
                ],
            )
        ),
        unresolved_questions=[
            (
                "这些单链 PDB 是否同时包含 "
                "target 和 binder？"
            )
        ],
        cautions=[
            (
                "单链本身不能证明同时包含"
                " target 和 binder"
            )
        ],
    )

    save_dataset_advice(
        bundle_dir=bundle,
        advice=advice,
    )

    return bundle, pdb_path


def test_chat_sidecar_is_allowed(
    tmp_path: Path,
) -> None:
    bundle, _ = create_bundle(
        tmp_path
    )

    _, _, session = (
        validate_incomplete_bundle(
            bundle
        )
    )

    assert session.plan.status == (
        "NEEDS_INFORMATION"
    )


def test_unknown_chat_file_is_rejected(
    tmp_path: Path,
) -> None:
    bundle, _ = create_bundle(
        tmp_path
    )

    (
        bundle
        / "chat"
        / "unknown.txt"
    ).write_text(
        "unsafe",
        encoding="utf-8",
    )

    with pytest.raises(
        Exception,
        match="Chat 辅助目录包含未知内容",
    ):
        validate_incomplete_bundle(
            bundle
        )


def test_adoption_updates_planning_session(
    tmp_path: Path,
) -> None:
    bundle, _ = create_bundle(
        tmp_path
    )

    result = adopt_dataset_advice(
        bundle_dir=bundle
    )

    assert result.status == (
        "NEEDS_INFORMATION"
    )

    data = json.loads(
        (
            bundle
            / "planning_session.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    request = data["request"]
    explicit = set(
        data["request_explicit_fields"]
    )

    assert (
        request["input_layout"]
        == "concatenated_single_chain"
    )
    assert request["source_chain"] == "A"

    assert "input_layout" in explicit
    assert "source_chain" in explicit

    history_files = list(
        (bundle / "history").glob(
            "resume_*/supplement_extraction.json"
        )
    )

    assert len(history_files) == 1

    extraction = json.loads(
        history_files[0].read_text(
            encoding="utf-8"
        )
    )

    assert (
        "source=FILE_DERIVED"
        in extraction["notes"]
    )
    assert (
        "confirmation=USER_CONFIRMED"
        in extraction["notes"]
    )


def test_changed_pdb_invalidates_advice(
    tmp_path: Path,
) -> None:
    bundle, pdb_path = create_bundle(
        tmp_path
    )

    pdb_path.write_text(
        "CHANGED\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DatasetAdviceAdoptionError,
        match="内容发生变化",
    ):
        adopt_dataset_advice(
            bundle_dir=bundle
        )
