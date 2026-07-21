from pathlib import Path

from protein_design_agent.tools.inspect_pdb_dataset import (
    build_dataset_report,
    collect_pdb_files,
    inspect_one_pdb,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_normal_two_chain_pdb() -> None:
    pdb_path = (
        PROJECT_ROOT
        / "sample_data"
        / "test_two_chain"
        / "normal_two_chain.pdb"
    )

    report = inspect_one_pdb(pdb_path)

    assert report["valid"] is True
    assert report["chain_count"] == 2
    assert report["chain_ids"] == ["A", "B"]
    assert report["chain_signature"] == "A:2|B:2"
    assert report["total_residue_count"] == 4
    assert report["chains"]["A"]["residue_count"] == 2
    assert report["chains"]["B"]["residue_count"] == 2
    assert "single_chain_only" not in report["warnings"]


def test_single_chain_pdb_requires_review() -> None:
    pdb_path = (
        PROJECT_ROOT
        / "sample_data"
        / "test_single_chain"
        / "single_chain_concat.pdb"
    )

    report = inspect_one_pdb(pdb_path)

    assert report["valid"] is True
    assert report["chain_count"] == 1
    assert report["chain_ids"] == ["A"]
    assert report["chain_signature"] == "A:4"
    assert report["total_residue_count"] == 4
    assert "single_chain_only" in report["warnings"]


def test_two_chain_dataset_status_is_ok() -> None:
    input_dir = (
        PROJECT_ROOT
        / "sample_data"
        / "test_two_chain"
    )

    pdb_files = collect_pdb_files(
        input_dir=input_dir,
        recursive=False,
        max_files=None,
    )

    file_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    report = build_dataset_report(
        input_dir=input_dir,
        pdb_files=pdb_files,
        file_reports=file_reports,
        recursive=False,
        detail_limit=100,
    )

    assert report["status"] == "OK"
    assert report["dataset_consistent"] is True
    assert report["all_valid_files_are_single_chain"] is False
    assert report["chain_signature_counts"] == {
        "A:2|B:2": 1
    }


def test_single_chain_dataset_status_is_review() -> None:
    input_dir = (
        PROJECT_ROOT
        / "sample_data"
        / "test_single_chain"
    )

    pdb_files = collect_pdb_files(
        input_dir=input_dir,
        recursive=False,
        max_files=None,
    )

    file_reports = [
        inspect_one_pdb(path)
        for path in pdb_files
    ]

    report = build_dataset_report(
        input_dir=input_dir,
        pdb_files=pdb_files,
        file_reports=file_reports,
        recursive=False,
        detail_limit=100,
    )

    assert report["status"] == "REVIEW"
    assert report["dataset_consistent"] is True
    assert report["all_valid_files_are_single_chain"] is True
    assert "all_valid_files_are_single_chain" in report["warnings"]
