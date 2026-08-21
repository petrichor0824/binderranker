from pathlib import Path

import pytest

from protein_design_agent.schemas.project_config import (
    ProjectConfig,
)
from protein_design_agent.tools.run_binderranker import (
    load_expected_sha256,
    region_settings,
    resolve_ranker,
    sha256_file,
    validate_ranker_input,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_ranker_matches_sha256_manifest() -> None:
    """冻结 Ranker 必须与 SHA256SUMS 完全一致。"""
    ranker_path, resolved_sha256 = resolve_ranker(
        "v0.1-expert"
    )

    assert ranker_path.exists()
    assert resolved_sha256 == sha256_file(ranker_path)
    assert len(resolved_sha256) == 64


def test_sha256_manifest_is_read_by_filename(
    tmp_path: Path,
) -> None:
    """程序应从清单读取哈希，而不是依赖手抄常量。"""
    ranker = tmp_path / "ranker.py"
    ranker.write_text(
        "print('test')\n",
        encoding="utf-8",
    )

    expected = sha256_file(ranker)

    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(
        f"{expected}  {ranker.name}\n",
        encoding="utf-8",
    )

    actual = load_expected_sha256(
        manifest_path=manifest,
        ranker_path=ranker,
    )

    assert actual == expected


def test_invalid_sha256_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    """损坏的校验清单必须阻止运行。"""
    ranker = tmp_path / "ranker.py"
    ranker.write_text(
        "print('test')\n",
        encoding="utf-8",
    )

    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(
        f"not-a-valid-hash  {ranker.name}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="SHA256 长度错误",
    ):
        load_expected_sha256(
            manifest_path=manifest,
            ranker_path=ranker,
        )


def test_diagnostic_region_policy_preserves_original_score() -> None:
    """
    diagnostic 模式应传入 region 信息，
    但 Ranker 的主分仍使用原始评分。
    """
    project = ProjectConfig.model_validate(
        {
            "project_name": "diagnostic_test",
            "input": {
                "pdb_dir": "sample_data/test_two_chain",
                "layout": "existing_chains",
                "binder_chain": "A",
            },
            "regions": {
                "desired": ["B:1-2"],
                "undesired": ["B:3-4"],
                "hotspots": ["B:1"],
            },
            "ranking": {
                "region_policy": "diagnostic",
                "region_filter": "off",
            },
        }
    )

    settings = region_settings(project)

    assert settings["desired_regions"] == "B:1-2"
    assert settings["undesired_regions"] == "B:3-4"
    assert settings["hotspot_regions"] == "B:1"

    # 冻结 Ranker 中 score_mode=off 表示主分使用原始评分。
    assert settings["region_score_mode"] == "off"
    assert settings["region_filter"] == "off"


def test_missing_binder_chain_fails_fast(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "normalized"
    input_dir.mkdir()
    (input_dir / "candidate_1.pdb").write_text(
        (
            "ATOM      1  CA  ALA A   1"
            "       0.000   0.000   0.000"
            "  1.00 20.00           C\n"
            "END\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="binder_chain_missing",
    ):
        validate_ranker_input(
            input_dir,
            binder_chain="B",
            recursive=False,
            max_files=None,
        )
