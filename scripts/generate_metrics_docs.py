from pathlib import Path

from protein_design_agent.agent.metric_ontology import (
    BASE_METRIC_ONTOLOGY,
    ontology_for_run,
)


ROLE_LABELS = {
    "primary_score": "主排序分数",
    "direct_primary_component": "直接主分项",
    "indirect_primary_component": "间接主分项",
    "diagnostic": "诊断指标",
    "raw_metric": "原始指标",
}

DIRECTION_LABELS = {
    "higher_better": "越高越好",
    "lower_better": "越低越好",
    "context_dependent": "依赖上下文",
}


def clean(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def weight_text(item) -> str:
    value = item.direct_primary_weight
    return "—" if value is None else f"{value:.2f}"


def formula_text(ontology: dict) -> str:
    keys = (
        "morphology_adaptive_score",
        "score_safety",
        "score_roughness",
        "score_region",
    )
    terms = []

    for key in keys:
        item = ontology[key]
        weight = item.direct_primary_weight

        if weight is not None:
            terms.append(f"{weight:.2f} × {key}")

    return " + ".join(terms)


def render_metrics_markdown() -> str:
    """Render the complete controlled metrics reference."""
    region_off = ontology_for_run(
        region_score_used=False
    )
    region_on = ontology_for_run(
        region_score_used=True
    )

    lines = [
        "# BinderRanker Metrics",
        "",
        "This document is generated from "
        "`metric_ontology.py`, which is the controlled "
        "source for externally exposed metric semantics.",
        "",
        "BinderRanker metrics describe relative engineering "
        "ranking within the current target and candidate batch. "
        "They are not binding affinities, experimental success "
        "probabilities, folding guarantees, or universal scores "
        "that can be compared directly across unrelated targets.",
        "",
        "## Primary-score formulas",
        "",
        "When region scoring is disabled:",
        "",
        f"`final_score_v4 = {formula_text(region_off)}`",
        "",
        "When region scoring is enabled:",
        "",
        f"`final_score_v4 = {formula_text(region_on)}`",
        "",
        "The three morphology-mode scores are first combined "
        "through target-dependent dynamic weights to form "
        "`morphology_adaptive_score`.",
        "",
        "## Deterministic contribution decomposition",
        "",
        "For reports that record the active region-scoring flag and "
        "the corresponding primary-score formula, the deterministic "
        "result summary exposes:",
        "",
        "- the recorded primary-score formula;",
        "- the audited direct-component weights;",
        "- each candidate's `weight × component score` contribution;",
        "- the reconstructed `final_score_v4` and reconstruction error.",
        "",
        "The reconstructed contributions must sum to the recorded "
        "`final_score_v4` within the parser tolerance. A mismatch is "
        "rejected instead of entering downstream explanation. Older "
        "reports that do not contain the required context remain "
        "readable, but their decomposition status is `UNAVAILABLE` "
        "and BinderRanker does not infer missing formula evidence.",
        "",
        "A contribution is an arithmetic term in BinderRanker's "
        "empirical ranking formula. It is not a causal attribution, "
        "binding-energy decomposition, or statement of universal "
        "biophysical importance.",
        "",
        "## Machine-readable interpretation contract",
        "",
        "Current result summaries seal the run-specific metric ontology, "
        "metric directions and roles, batch-relative score and threshold "
        "boundaries, prohibited claims, and required downstream validation "
        "in `scientific_interpretation_contract`. The deterministic "
        "Markdown report and optional evidence-bound explanation validate "
        "and reuse that same contract.",
        "",
        "Summaries created before this contract existed remain readable. "
        "They report `scientific_interpretation_status=UNAVAILABLE` instead "
        "of inventing missing run-bound interpretation evidence.",
        "",
        "## Role definitions",
        "",
        "- **Primary score**: the value used for final ranking.",
        "- **Direct primary component**: enters the final score "
        "with an explicit run-dependent weight.",
        "- **Indirect primary component**: contributes through "
        "another composite score.",
        "- **Diagnostic metric**: supports interpretation but is "
        "not always an independent final-score term.",
        "- **Raw metric**: a measured geometric quantity used by "
        "composite scores, filters, or diagnostics.",
        "",
        "## Metric index",
        "",
        "| Key | Label | Direction | Role when region off | "
        "Weight off | Role when region on | Weight on |",
        "|---|---|---|---|---:|---|---:|",
    ]

    for key, base in BASE_METRIC_ONTOLOGY.items():
        off = region_off[key]
        on = region_on[key]

        lines.append(
            f"| `{key}` | {clean(base.label_zh)} | "
            f"{DIRECTION_LABELS[base.direction]} | "
            f"{ROLE_LABELS[off.role]} | {weight_text(off)} | "
            f"{ROLE_LABELS[on.role]} | {weight_text(on)} |"
        )

    lines.extend(
        [
            "",
            "## Detailed semantics",
            "",
        ]
    )

    for key, item in BASE_METRIC_ONTOLOGY.items():
        lines.extend(
            [
                f"### `{key}` — {item.label_zh}",
                "",
                f"- **Direction:** "
                f"{DIRECTION_LABELS[item.direction]}",
                f"- **Base role:** {ROLE_LABELS[item.role]}",
                f"- **Definition:** {clean(item.definition)}",
                f"- **Interpretation:** "
                f"{clean(item.value_interpretation)}",
                "- **Allowed interpretations:** "
                + "；".join(
                    clean(value)
                    for value in item.allowed_interpretations
                ),
                "- **Forbidden interpretations:** "
                + "；".join(
                    clean(value)
                    for value in item.forbidden_interpretations
                ),
                "- **Suggested checks:** "
                + "；".join(
                    clean(value)
                    for value in item.suggested_checks
                ),
                f"- **Source basis:** "
                f"{clean(item.source_basis)}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


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
