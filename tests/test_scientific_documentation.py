from pathlib import Path


DOCS = (
    "docs/SCIENTIFIC_METHOD.md",
    "docs/METRICS.md",
    "docs/RESULT_INTERPRETATION.md",
    "docs/BENCHMARK_CONTRACT.md",
    "docs/BENCHMARK_METRICS.md",
    "docs/BENCHMARK_SENSITIVITY.md",
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


def test_benchmark_contract_preserves_scientific_boundaries() -> None:
    contract = Path(
        "docs/BENCHMARK_CONTRACT.md"
    ).read_text(encoding="utf-8")

    required_contract_text = (
        "CALIBRATION",
        "EVALUATION",
        "SHA256",
        "COMPUTATIONAL_PROXY",
        "does not by itself establish",
        "ValidatedBenchmarkBundle",
    )

    for value in required_contract_text:
        assert value in contract


def test_benchmark_metrics_preserve_scientific_boundaries() -> None:
    metrics = Path(
        "docs/BENCHMARK_METRICS.md"
    ).read_text(encoding="utf-8")

    required_metric_text = (
        "EVALUATION",
        "CALIBRATION",
        "enrichment_factor_at_k",
        "NO_POSITIVE_OUTCOMES_IN_CAMPAIGN",
        "DESCRIPTIVE_RETROSPECTIVE_ONLY",
        "generalization_established=false",
        "does not by itself establish",
    )

    for value in required_metric_text:
        assert value in metrics


def test_benchmark_sensitivity_preserves_scientific_boundaries() -> None:
    sensitivity = Path(
        "docs/BENCHMARK_SENSITIVITY.md"
    ).read_text(encoding="utf-8")

    required_sensitivity_text = (
        "LEAVE_ONE_TARGET_OUT",
        "NO_POSITIVE_OUTCOMES_IN_TARGET",
        "FEWER_THAN_TWO_TARGETS_WITH_DEFINED_METRIC",
        "not a confidence",
        "DESCRIPTIVE_TARGET_SENSITIVITY_ONLY",
        "statistical_significance_established=false",
        "generalization_established=false",
    )

    for value in required_sensitivity_text:
        assert value in sensitivity
