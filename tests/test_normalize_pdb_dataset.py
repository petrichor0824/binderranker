from pathlib import Path

import pytest

from protein_design_agent.schemas.project_config import (
    ProjectConfig,
)
from protein_design_agent.tools.inspect_pdb_dataset import (
    inspect_one_pdb,
)
from protein_design_agent.tools.normalize_pdb_dataset import (
    normalize_one_pdb,
    prepare_output_directory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_single_chain_project() -> ProjectConfig:
    """创建适用于本地单链测试 PDB 的项目配置。"""
    return ProjectConfig.model_validate(
        {
            "schema_version": "0.1",
            "project_name": "single_chain_test",
            "input": {
                "pdb_dir": (
                    PROJECT_ROOT
                    / "sample_data"
                    / "test_single_chain"
                ),
                "recursive": False,
                "layout": "concatenated_single_chain",
                "source_chain": "A",
                "target_residue_count": 2,
                "target_start_residue": 1,
                "normalized_target_chain": "A",
                "normalized_binder_chain": "B",
            },
            "ranking": {
                "region_policy": "diagnostic",
                "region_filter": "off",
            },
        }
    )


def make_existing_chain_project() -> ProjectConfig:
    """创建适用于正常双链 PDB 的项目配置。"""
    return ProjectConfig.model_validate(
        {
            "schema_version": "0.1",
            "project_name": "two_chain_test",
            "input": {
                "pdb_dir": (
                    PROJECT_ROOT
                    / "sample_data"
                    / "test_two_chain"
                ),
                "recursive": False,
                "layout": "existing_chains",
                "binder_chain": "A",
                "target_chains": ["B"],
            },
            "ranking": {
                "region_policy": "diagnostic",
                "region_filter": "off",
            },
        }
    )


def test_split_single_chain_into_target_and_binder(
    tmp_path: Path,
) -> None:
    """单链拼接结构应被正确拆成 A、B 两条链。"""
    project = make_single_chain_project()

    source = (
        PROJECT_ROOT
        / "sample_data"
        / "test_single_chain"
        / "single_chain_concat.pdb"
    )
    output = tmp_path / "normalized.pdb"

    original_content = source.read_text(encoding="utf-8")

    details = normalize_one_pdb(
        input_path=source,
        output_path=output,
        project=project,
    )

    report = inspect_one_pdb(output)

    assert output.exists()
    assert report["valid"] is True
    assert report["chain_signature"] == "A:2|B:2"

    assert report["chains"]["A"]["residue_count"] == 2
    assert report["chains"]["A"]["min_residue_number"] == 1
    assert report["chains"]["A"]["max_residue_number"] == 2

    assert report["chains"]["B"]["residue_count"] == 2
    assert report["chains"]["B"]["min_residue_number"] == 1
    assert report["chains"]["B"]["max_residue_number"] == 2

    assert details["target_residue_count"] == 2
    assert details["binder_residue_count"] == 2
    assert details["target_chain"] == "A"
    assert details["binder_chain"] == "B"

    # 标准化过程绝不能修改原始文件。
    assert source.read_text(encoding="utf-8") == original_content


def test_existing_chain_pdb_is_copied_without_changes(
    tmp_path: Path,
) -> None:
    """已经正确分链的数据应原样复制。"""
    project = make_existing_chain_project()

    source = (
        PROJECT_ROOT
        / "sample_data"
        / "test_two_chain"
        / "normal_two_chain.pdb"
    )
    output = tmp_path / "copied.pdb"

    details = normalize_one_pdb(
        input_path=source,
        output_path=output,
        project=project,
    )

    assert output.exists()
    assert output.read_bytes() == source.read_bytes()
    assert details["mode"] == "copied_existing_chains"
    assert details["chain_signature"] == "A:2|B:2"


def test_nonempty_output_directory_is_protected(
    tmp_path: Path,
) -> None:
    """默认不能覆盖已有输出目录。"""
    output_dir = tmp_path / "existing_results"
    output_dir.mkdir()
    existing_file = output_dir / "important.txt"
    existing_file.write_text(
        "do not overwrite",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="输出目录非空",
    ):
        prepare_output_directory(
            output_dir,
            allow_overwrite=False,
        )

    assert existing_file.exists()


def test_overwrite_mode_recreates_output_directory(
    tmp_path: Path,
) -> None:
    """明确允许覆盖时，应重建输出目录。"""
    output_dir = tmp_path / "old_results"
    output_dir.mkdir()
    old_file = output_dir / "old.txt"
    old_file.write_text("old", encoding="utf-8")

    prepare_output_directory(
        output_dir,
        allow_overwrite=True,
    )

    assert output_dir.exists()
    assert list(output_dir.iterdir()) == []
