from pathlib import Path

from protein_design_agent.agent.metric_documentation import (
    render_metrics_markdown,
)
from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
)


def main() -> None:
    output = Path("docs/METRICS.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_metrics_markdown(),
        encoding="utf-8",
        newline="\n",
    )

    print(
        f"[METRICS-DOC-GENERATED] "
        f"{len(BASE_METRIC_ONTOLOGY)} metrics"
    )


if __name__ == "__main__":
    main()
