import csv
import json
from pathlib import Path

import pytest

from protein_design_agent.agent.approval import (
    fingerprint_file,
)
from protein_design_agent.agent.ranker_result_parser import (
    RankerResultParseError,
    parse_completed_ranker_run,
    write_ranker_result_summary,
)


HEADERS = [
    "pdb_name",
    "filter_level",
    "filter_broad_pass",
    "filter_broad_reasons",
    "filter_medium_pass",
    "filter_medium_reasons",
    "filter_strict_pass",
    "filter_strict_reasons",
    "final_score_v4",
    "rank_final_score_v4",
    "morphology_adaptive_score",
    "score_line",
    "score_plane",
    "score_compact",
    "score_roughness",
    "score_microfit",
    "score_safety",
    "score_region",
    "score_hotspot",
    "effective_weight_sum",
    "target_effective_coverage",
    "target_contact_span_norm",
    "backfacing_cb_far_weight_ratio",
    "cb_closer_weight_ratio",
    "binder_field_active_roughness",
    "contact_map_continuity_score",
    "contact_map_jump_fraction",
    "shell_sensitivity_12_vs_8",
    "clash_pairs",
    "error",
]


def candidate_row(
    *,
    name: str,
    rank: int,
    level: str,
    broad: str,
    medium: str,
    strict: str,
) -> dict[str, str]:
    final_score = str(
        1.0 - rank * 0.1
    )
    row = {
        header: "0.5"
        for header in HEADERS
    }

    row.update(
        {
            "pdb_name": name,
            "filter_level": level,
            "filter_broad_pass": broad,
            "filter_broad_reasons": (
                ""
                if broad == "YES"
                else "low_effective_weight_sum"
            ),
            "filter_medium_pass": medium,
            "filter_medium_reasons": (
                ""
                if medium == "YES"
                else "low_effective_weight_sum"
            ),
            "filter_strict_pass": strict,
            "filter_strict_reasons": (
                ""
                if strict == "YES"
                else "low_score_safety"
            ),
            "final_score_v4": final_score,
            "rank_final_score_v4": str(rank),
            "morphology_adaptive_score": (
                final_score
            ),
            "score_safety": final_score,
            "score_roughness": final_score,
            "score_region": final_score,
            "clash_pairs": "0",
            "error": "",
        }
    )

    return row


def build_bundle(
    tmp_path: Path,
) -> Path:
    bundle = tmp_path / "bundle"
    workflow = bundle / "workflow"
    ranker = workflow / "ranker"

    ranker.mkdir(
        parents=True
    )

    workflow_manifest = (
        workflow
        / "workflow_manifest.json"
    )

    workflow_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "READY_FOR_REVIEW",
                "analysis_scope": {
                    "level": "SMOKE_TEST_ONLY",
                    "pdb_count": 2,
                    (
                        "workflow_allows_"
                        "formal_interpretation"
                    ): False,
                    "pool_labels_reliable": False,
                    (
                        "dynamic_quantile_"
                        "stability"
                    ): "very_low",
                    "result_use": (
                        "engineering_validation_only"
                    ),
                    "message": "test",
                },
            }
        ),
        encoding="utf-8",
    )

    scored = (
        ranker / "backbone_rank_scored.csv"
    )

    with scored.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=HEADERS,
        )
        writer.writeheader()
        writer.writerow(
            candidate_row(
                name="candidate_1",
                rank=1,
                level="MEDIUM",
                broad="YES",
                medium="YES",
                strict="NO",
            )
        )
        writer.writerow(
            candidate_row(
                name="candidate_2",
                rank=2,
                level="FAIL",
                broad="NO",
                medium="NO",
                strict="NO",
            )
        )

    metrics = (
        ranker / "backbone_rank_metrics.csv"
    )
    metrics.write_text(
        "pdb_name\ncandidate_1\ncandidate_2\n",
        encoding="utf-8",
    )

    ranking = (
        ranker / "backbone_rank_ranking.xlsx"
    )
    ranking.write_bytes(
        b"synthetic non-empty xlsx"
    )

    report = (
        ranker / "backbone_rank_report.txt"
    )
    report.write_text(
        """
region_score_used = False
final_score_v4_original = 0.85*morphology_adaptive_score + 0.10*score_safety + 0.05*score_roughness
final_score_v4_region = 0.78*morphology_adaptive_score + 0.10*score_safety + 0.05*score_roughness + 0.07*score_region
final_score_v4 = primary ranking score; equals region-aware score if region_score_used=True
Filter thresholds:
  [broad]
    effective_weight_sum: min effective_weight_sum 10.0  (q=0.1)
  [medium]
    effective_weight_sum: min effective_weight_sum 20.0  (q=0.4)
  [strict]
    score_safety: min score_safety 0.6  (q=0.35)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    outputs = [
        metrics,
        scored,
        ranking,
        report,
    ]

    execution = {
        "schema_version": "0.1",
        "status": "COMPLETED",
        "project_name": "parser_test",
        "return_code": 0,
        "binderranker_executed": True,
        "output_files": [
            fingerprint_file(path).model_dump(
                mode="json"
            )
            for path in outputs
        ],
    }

    (
        bundle
        / "execution_apr_test.json"
    ).write_text(
        json.dumps(
            execution,
            indent=2,
        ),
        encoding="utf-8",
    )

    return bundle


def refresh_output_fingerprints(
    bundle: Path,
) -> None:
    execution_path = next(
        bundle.glob("execution_apr_*.json")
    )
    execution = json.loads(
        execution_path.read_text(
            encoding="utf-8"
        )
    )
    execution["output_files"] = [
        fingerprint_file(Path(item["path"]))
        .model_dump(mode="json")
        for item in execution["output_files"]
    ]
    execution_path.write_text(
        json.dumps(execution, indent=2),
        encoding="utf-8",
    )


def test_smoke_test_results_are_suppressed(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)

    summary = parse_completed_ranker_run(
        bundle
    )

    assert summary.status == "PARSED"
    assert summary.schema_version == "0.2"
    assert summary.candidate_count == 2
    assert (
        summary.score_decomposition_status
        == "AVAILABLE"
    )
    assert summary.region_score_used is False
    assert summary.primary_score_weights == {
        "morphology_adaptive_score": 0.85,
        "score_safety": 0.10,
        "score_roughness": 0.05,
    }
    assert summary.primary_score_formula == (
        "0.85*morphology_adaptive_score + "
        "0.10*score_safety + "
        "0.05*score_roughness"
    )

    first = (
        summary
        .candidates_by_engineering_rank[0]
    )
    assert first.primary_score_contributions == (
        pytest.approx(
            {
                "morphology_adaptive_score": (
                    0.765
                ),
                "score_safety": 0.09,
                "score_roughness": 0.045,
            }
        )
    )
    assert (
        first.reconstructed_final_score_v4
        == pytest.approx(0.9)
    )
    assert (
        first.primary_score_reconstruction_error
        == pytest.approx(0.0)
    )

    assert (
        summary.pool_reporting
        .policy.reporting_mode
        == "SUPPRESSED"
    )

    assert (
        summary.pool_reporting
        .raw_pool_counts
        == {
            "broad": 1,
            "medium": 1,
            "strict": 0,
        }
    )

    assert (
        summary.pool_reporting
        .public_pool_counts
        == {
            "broad": None,
            "medium": None,
            "strict": None,
        }
    )

    assert (
        summary
        .formal_candidate_recommendation_allowed
        is False
    )

    assert (
        summary
        .candidates_by_engineering_rank[0]
        .public_filter_level
        is None
    )


def test_thresholds_are_parsed(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)

    summary = parse_completed_ranker_run(
        bundle
    )

    broad = (
        summary
        .raw_filter_thresholds
        ["broad"]
        ["effective_weight_sum"]
    )

    assert broad.direction == "min"
    assert broad.value == 10.0
    assert broad.quantile == 0.1

    assert (
        summary.thresholds_formally_interpretable
        is False
    )


def test_region_aware_score_is_decomposed(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    report = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_report.txt"
    )
    report.write_text(
        report.read_text(
            encoding="utf-8"
        ).replace(
            "region_score_used = False",
            "region_score_used = True",
            1,
        ),
        encoding="utf-8",
    )
    refresh_output_fingerprints(bundle)

    summary = parse_completed_ranker_run(
        bundle
    )

    assert summary.region_score_used is True
    assert summary.primary_score_weights == {
        "morphology_adaptive_score": 0.78,
        "score_safety": 0.10,
        "score_roughness": 0.05,
        "score_region": 0.07,
    }
    assert summary.primary_score_formula == (
        "0.78*morphology_adaptive_score + "
        "0.10*score_safety + "
        "0.05*score_roughness + "
        "0.07*score_region"
    )
    first = (
        summary
        .candidates_by_engineering_rank[0]
    )
    assert (
        first.reconstructed_final_score_v4
        == pytest.approx(0.9)
    )


def test_changed_output_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)

    scored = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_scored.csv"
    )

    scored.write_text(
        scored.read_text(encoding="utf-8")
        + "\nchanged\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RankerResultParseError,
        match="原始输出在执行后发生变化",
    ):
        parse_completed_ranker_run(
            bundle
        )


def test_non_completed_execution_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)

    execution = next(
        bundle.glob("execution_apr_*.json")
    )

    data = json.loads(
        execution.read_text(
            encoding="utf-8"
        )
    )
    data["status"] = "FAILED"

    execution.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    with pytest.raises(
        RankerResultParseError,
        match="只有 COMPLETED",
    ):
        parse_completed_ranker_run(
            bundle
        )


def test_summary_file_is_protected(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)

    output = write_ranker_result_summary(
        bundle_dir=bundle
    )

    assert output.exists()

    data = json.loads(
        output.read_text(
            encoding="utf-8"
        )
    )

    assert data["status"] == "PARSED"

    with pytest.raises(
        ValueError,
        match="禁止覆盖",
    ):
        write_ranker_result_summary(
            bundle_dir=bundle
        )


@pytest.mark.parametrize(
    "non_finite",
    ["NaN", "Inf", "-Inf"],
)
def test_parser_rejects_non_finite_scores(
    tmp_path: Path,
    non_finite: str,
) -> None:
    bundle = build_bundle(tmp_path)
    scored = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_scored.csv"
    )

    with scored.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    rows[0]["score_safety"] = non_finite

    with scored.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=headers,
        )
        writer.writeheader()
        writer.writerows(rows)

    refresh_output_fingerprints(bundle)

    with pytest.raises(
        RankerResultParseError,
        match="必须是有限数值",
    ):
        parse_completed_ranker_run(bundle)


def test_legacy_report_without_formula_is_compatible(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    report = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_report.txt"
    )
    lines = [
        line
        for line in report.read_text(
            encoding="utf-8"
        ).splitlines()
        if not line.startswith(
            (
                "region_score_used =",
                "final_score_v4 =",
                "final_score_v4_original =",
                "final_score_v4_region =",
            )
        )
    ]
    report.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    refresh_output_fingerprints(bundle)

    summary = parse_completed_ranker_run(
        bundle
    )

    assert (
        summary.score_decomposition_status
        == "UNAVAILABLE"
    )
    assert summary.score_decomposition_reason
    assert summary.region_score_used is None
    assert summary.primary_score_weights == {}
    assert all(
        not candidate.primary_score_contributions
        for candidate in (
            summary
            .candidates_by_engineering_rank
        )
    )


def test_parser_rejects_inconsistent_primary_score(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    scored = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_scored.csv"
    )

    with scored.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    rows[0]["score_safety"] = "0.1"

    with scored.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=headers,
        )
        writer.writeheader()
        writer.writerows(rows)

    refresh_output_fingerprints(bundle)

    with pytest.raises(
        RankerResultParseError,
        match="候选主分无法重建",
    ):
        parse_completed_ranker_run(bundle)


def test_parser_rejects_inconsistent_report_formula(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    report = (
        bundle
        / "workflow"
        / "ranker"
        / "backbone_rank_report.txt"
    )
    content = report.read_text(
        encoding="utf-8"
    ).replace(
        "0.85*morphology_adaptive_score",
        "0.84*morphology_adaptive_score",
        1,
    )
    report.write_text(
        content,
        encoding="utf-8",
    )
    refresh_output_fingerprints(bundle)

    with pytest.raises(
        RankerResultParseError,
        match="主分公式与审计指标本体不一致",
    ):
        parse_completed_ranker_run(bundle)
