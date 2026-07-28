from pathlib import Path

import protein_design_agent.agent.dataset_advisor as module
from protein_design_agent.agent.dataset_advisor import (
    build_planning_advice,
    inspect_dataset_for_planning,
    save_dataset_advice,
)


def report(
    *,
    name: str,
    path: Path,
    chain_ids: list[str],
    residues: int,
    valid: bool = True,
) -> dict:
    return {
        "file_name": name,
        "file_path": str(path),
        "valid": valid,
        "chain_count": len(chain_ids),
        "chain_ids": chain_ids,
        "chain_signature": (
            ",".join(chain_ids)
            + f":{residues}"
        ),
        "total_residue_count": residues,
        "warnings": [],
        "errors": [],
    }


def test_consistent_single_chain_creates_conditional_advice(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one.pdb"
    second = tmp_path / "two.pdb"

    first.write_text(
        "PDB one",
        encoding="utf-8",
    )
    second.write_text(
        "PDB two",
        encoding="utf-8",
    )

    file_reports = [
        report(
            name="one.pdb",
            path=first,
            chain_ids=["A"],
            residues=219,
        ),
        report(
            name="two.pdb",
            path=second,
            chain_ids=["A"],
            residues=224,
        ),
    ]

    advice = build_planning_advice(
        input_dir=tmp_path,
        recursive=False,
        pdb_files=[
            first,
            second,
        ],
        file_reports=file_reports,
        dataset_report={
            "valid_file_count": 2,
            "invalid_file_count": 0,
            "all_valid_files_are_single_chain": True,
            "chain_count_patterns": {
                "1": 2,
            },
            "chain_signature_counts": {
                "A:219": 1,
                "A:224": 1,
            },
            "total_residue_count_patterns": {
                "219": 1,
                "224": 1,
            },
            "warnings": [
                "inconsistent_chain_signatures",
                "inconsistent_total_residue_counts",
            ],
        },
    )

    assert advice.status == (
        "NEEDS_USER_CONFIRMATION"
    )
    assert advice.common_single_chain_id == "A"

    suggestion = advice.conditional_suggestion

    assert suggestion is not None

    assert suggestion.candidate_patch == {
        "input_layout": (
            "concatenated_single_chain"
        ),
        "source_chain": "A",
    }

    assert any(
        "不能证明" in caution
        for caution in advice.cautions
    )

    assert len(advice.file_evidence) == 2
    assert advice.file_evidence[0].sha256


def test_mixed_chain_layout_is_inconclusive(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one.pdb"
    second = tmp_path / "two.pdb"

    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    advice = build_planning_advice(
        input_dir=tmp_path,
        recursive=False,
        pdb_files=[
            first,
            second,
        ],
        file_reports=[
            report(
                name="one.pdb",
                path=first,
                chain_ids=["A"],
                residues=200,
            ),
            report(
                name="two.pdb",
                path=second,
                chain_ids=["A", "B"],
                residues=250,
            ),
        ],
        dataset_report={
            "valid_file_count": 2,
            "invalid_file_count": 0,
            "all_valid_files_are_single_chain": False,
            "chain_count_patterns": {
                "1": 1,
                "2": 1,
            },
            "warnings": [],
        },
    )

    assert advice.status == "INCONCLUSIVE"
    assert advice.common_single_chain_id is None
    assert advice.conditional_suggestion is None


def test_real_inspection_wrapper_can_be_mocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdb_path = tmp_path / "one.pdb"
    pdb_path.write_text(
        "mock pdb",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "collect_pdb_files",
        lambda **kwargs: [
            pdb_path
        ],
    )

    monkeypatch.setattr(
        module,
        "inspect_one_pdb",
        lambda path: report(
            name=path.name,
            path=path,
            chain_ids=["A"],
            residues=219,
        ),
    )

    monkeypatch.setattr(
        module,
        "build_dataset_report",
        lambda **kwargs: {
            "valid_file_count": 1,
            "invalid_file_count": 0,
            "all_valid_files_are_single_chain": True,
            "chain_count_patterns": {
                "1": 1,
            },
            "chain_signature_counts": {
                "A:219": 1,
            },
            "total_residue_count_patterns": {
                "219": 1,
            },
            "warnings": [
                "all_valid_files_are_single_chain",
            ],
        },
    )

    advice = inspect_dataset_for_planning(
        input_dir=tmp_path,
    )

    assert advice.valid_file_count == 1
    assert advice.common_single_chain_id == "A"


def test_advice_can_be_saved_without_modifying_session(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    pdb_path = tmp_path / "one.pdb"
    pdb_path.write_text(
        "mock pdb",
        encoding="utf-8",
    )

    advice = build_planning_advice(
        input_dir=tmp_path,
        recursive=False,
        pdb_files=[
            pdb_path
        ],
        file_reports=[
            report(
                name="one.pdb",
                path=pdb_path,
                chain_ids=["A"],
                residues=219,
            )
        ],
        dataset_report={
            "valid_file_count": 1,
            "invalid_file_count": 0,
            "all_valid_files_are_single_chain": True,
            "chain_count_patterns": {
                "1": 1,
            },
            "warnings": [],
        },
    )

    output = save_dataset_advice(
        bundle_dir=bundle,
        advice=advice,
    )

    assert output.is_file()
    assert not (
        bundle
        / "planning_session.json"
    ).exists()
