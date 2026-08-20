from pathlib import Path

from typer.testing import CliRunner

from protein_design_agent.cli import app


runner = CliRunner()


def test_extract_sample_creates_five_pdbs(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "sample"

    result = runner.invoke(
        app,
        [
            "extract-sample",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 0
    assert len(list(destination.glob("*.pdb"))) == 5
    assert "PDB 数量：5" in result.output
    assert "不得作为正式筛选结论" in result.output


def test_extract_sample_rejects_nonempty_directory(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "sample"
    destination.mkdir()
    (destination / "keep.txt").write_text(
        "keep",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "extract-sample",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 2
    assert "禁止覆盖" in result.output
    assert (destination / "keep.txt").is_file()


def test_extract_sample_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "sample"

    def fail_extract(**kwargs):
        raise OSError(
            "PRIVATE_SAMPLE_INTERNAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.agent.sample_resources."
        "extract_packaged_sample",
        fail_extract,
    )

    result = runner.invoke(
        app,
        [
            "extract-sample",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 2

    assert "当前操作没有完成" in result.output
    assert "样例提取未完成。" in result.output

    assert (
        "PRIVATE_SAMPLE_INTERNAL_DETAIL"
        not in result.output
    )
    assert "OSError" not in result.output


def test_extract_sample_hides_raw_oserror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "sample"

    def fail_extract(**kwargs):
        raise OSError(
            "PRIVATE_SAMPLE_INTERNAL_DETAIL"
        )

    monkeypatch.setattr(
        "protein_design_agent.agent.sample_resources."
        "extract_packaged_sample",
        fail_extract,
    )

    result = runner.invoke(
        app,
        [
            "extract-sample",
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 2

    assert "当前操作没有完成" in result.output
    assert "样例提取未完成。" in result.output

    assert (
        "PRIVATE_SAMPLE_INTERNAL_DETAIL"
        not in result.output
    )
    assert "OSError" not in result.output
