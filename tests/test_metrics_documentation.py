from pathlib import Path

from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
)
from protein_design_agent.agent.metric_documentation import (
    render_metrics_markdown,
)


def test_generated_metrics_document_is_current() -> None:
    content = Path("docs/METRICS.md").read_text(
        encoding="utf-8"
    )

    assert content == render_metrics_markdown()


def test_generated_metrics_document_is_complete() -> None:
    content = Path("docs/METRICS.md").read_text(
        encoding="utf-8"
    )

    assert len(BASE_METRIC_ONTOLOGY) == 20

    for key in BASE_METRIC_ONTOLOGY:
        assert f"### `{key}`" in content


def test_generated_metrics_formulas_are_valid() -> None:
    content = Path("docs/METRICS.md").read_text(
        encoding="utf-8"
    )

    assert (
        "`final_score_v4 = "
        "0.85 × morphology_adaptive_score + "
        "0.10 × score_safety + "
        "0.05 × score_roughness`"
    ) in content

    assert (
        "`final_score_v4 = "
        "0.78 × morphology_adaptive_score + "
        "0.10 × score_safety + "
        "0.05 × score_roughness + "
        "0.07 × score_region`"
    ) in content

    assert "× `morphology_adaptive_score`" not in content
