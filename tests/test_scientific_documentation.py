from pathlib import Path


DOCS = (
    "docs/SCIENTIFIC_METHOD.md",
    "docs/METRICS.md",
    "docs/RESULT_INTERPRETATION.md",
)


def test_readme_links_scientific_documents() -> None:
    readme = Path("README.md").read_text(
        encoding="utf-8"
    )

    for relative_path in DOCS:
        assert Path(relative_path).is_file()
        assert f"({relative_path})" in readme


def test_scientific_boundaries_are_documented() -> None:
    method = Path(
        "docs/SCIENTIFIC_METHOD.md"
    ).read_text(encoding="utf-8")

    interpretation = Path(
        "docs/RESULT_INTERPRETATION.md"
    ).read_text(encoding="utf-8")

    required_method_text = (
        "SMOKE_TEST_ONLY",
        "EXPLORATORY",
        "FULL_DATASET_ANALYSIS",
        "dynamic batch-relative filters",
        "score_hotspot",
        "not a replacement",
    )

    for value in required_method_text:
        assert value in method

    required_interpretation_text = (
        "batch-relative",
        "filter_strict_reasons",
        "region_score_used",
        "Model-generated explanation is optional",
    )

    for value in required_interpretation_text:
        assert value in interpretation
