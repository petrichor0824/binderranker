import csv
import json
from pathlib import Path

import pytest

from protein_design_agent.agent.approval import (
    fingerprint_file,
)
from protein_design_agent.agent.analyze_run import (
    run_analyze_run,
)
from protein_design_agent.agent.ranker_result_parser import (
    RankerResultParseError,
    RankerResultSummary,
    parse_completed_ranker_run,
    write_ranker_result_summary,
)
from protein_design_agent.agent.result_explainer import (
    build_result_explanation_evidence,
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
    assert summary.schema_version == "0.4"
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
    assert (
        summary.scientific_interpretation_status
        == "AVAILABLE"
    )
    assert (
        summary.scientific_interpretation_reason
        is None
    )
    interpretation_contract = (
        summary.scientific_interpretation_contract
    )
    assert interpretation_contract is not None
    assert (
        interpretation_contract.ranking_scope
        == "CURRENT_TARGET_AND_CANDIDATE_BATCH"
    )
    assert (
        interpretation_contract
        .threshold_interpretation_mode
        == "SUPPRESSED"
    )
    assert len(
        interpretation_contract.metric_semantics
    ) == 20
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
        summary.candidate_comparison_status
        == "AVAILABLE"
    )
    assert summary.candidate_comparison_reason is None
    assert len(
        summary
        .adjacent_candidate_score_comparisons
    ) == 1
    comparison = (
        summary
        .adjacent_candidate_score_comparisons[0]
    )
    assert comparison.higher_ranked_candidate == (
        "candidate_1"
    )
    assert comparison.lower_ranked_candidate == (
        "candidate_2"
    )
    assert comparison.recorded_score_delta == (
        pytest.approx(0.1)
    )
    assert comparison.reconstructed_score_delta == (
        pytest.approx(0.1)
    )
    assert (
        comparison
        .largest_positive_contribution_delta
        .metric_key
        == "morphology_adaptive_score"
    )
    assert (
        comparison
        .largest_negative_contribution_delta
        is None
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


def test_analyze_run_writes_real_deterministic_report(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    ranker = bundle / "workflow" / "ranker"
    scored = ranker / "backbone_rank_scored.csv"

    with scored.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    rows[0]["effective_weight_sum"] = "25"
    rows[1]["effective_weight_sum"] = "0.5"

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
        writer.writerows(rows)

    report_txt = ranker / "backbone_rank_report.txt"
    report_txt.write_text(
        report_txt.read_text(
            encoding="utf-8"
        ).replace(
            "score_safety 0.6",
            "score_safety 0.95",
        ),
        encoding="utf-8",
    )
    refresh_output_fingerprints(bundle)

    result = run_analyze_run(
        bundle_dir=bundle,
        analysis_dir=Path(
            "analyses/integration"
        ),
        with_model=False,
    )

    report = result.deterministic_report_path.read_text(
        encoding="utf-8"
    )
    manifest = json.loads(
        result.manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert "without a language model" in report
    assert "morphology_adaptive_score=0.765" in report
    assert "## Scientific interpretation contract" in report
    assert "CURRENT_TARGET_AND_CANDIDATE_BATCH" in report
    assert "Cross-target score comparison allowed: `false`" in report
    assert "higher is better within this batch" in report
    assert "## Adjacent rank differences" in report
    assert "#1 candidate_1 → #2 candidate_2" in report
    assert "morphology_adaptive_score=+0.085" in report
    assert "intentionally suppressed" in report
    assert (
        "Obtain experimental validation before biological claims."
        in report
    )
    assert manifest["deterministic_report_path"] == str(
        result.deterministic_report_path
    )
    assert len(
        manifest["deterministic_report_sha256"]
    ) == 64

    evidence = build_result_explanation_evidence(
        result_summary_path=(
            result.result_summary_path
        ),
        failure_analysis_path=(
            result.failure_analysis_path
        ),
    )

    assert evidence["evidence_schema_version"] == "0.3"
    sealed_contract = evidence[
        "scientific_interpretation_contract"
    ]
    assert sealed_contract is not None
    assert (
        sealed_contract["ranking_scope"]
        == "CURRENT_TARGET_AND_CANDIDATE_BATCH"
    )
    assert (
        evidence["metric_semantics"]
        == sealed_contract["metric_semantics"]
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


def test_single_candidate_comparison_is_not_applicable(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    ranker = bundle / "workflow" / "ranker"
    scored = ranker / "backbone_rank_scored.csv"

    with scored.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        first = next(reader)

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
        writer.writerow(first)

    (
        ranker / "backbone_rank_metrics.csv"
    ).write_text(
        "pdb_name\ncandidate_1\n",
        encoding="utf-8",
    )

    workflow_manifest = (
        bundle
        / "workflow"
        / "workflow_manifest.json"
    )
    workflow = json.loads(
        workflow_manifest.read_text(
            encoding="utf-8"
        )
    )
    workflow["analysis_scope"]["pdb_count"] = 1
    workflow_manifest.write_text(
        json.dumps(workflow),
        encoding="utf-8",
    )
    refresh_output_fingerprints(bundle)

    summary = parse_completed_ranker_run(
        bundle
    )

    assert summary.candidate_count == 1
    assert (
        summary.candidate_comparison_status
        == "NOT_APPLICABLE"
    )
    assert summary.candidate_comparison_reason
    assert (
        summary
        .adjacent_candidate_score_comparisons
        == []
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
    assert (
        summary.scientific_interpretation_status
        == "UNAVAILABLE"
    )
    assert summary.scientific_interpretation_reason
    assert (
        summary.scientific_interpretation_contract
        is None
    )
    assert (
        summary.candidate_comparison_status
        == "UNAVAILABLE"
    )
    assert summary.candidate_comparison_reason
    assert (
        summary
        .adjacent_candidate_score_comparisons
        == []
    )
    assert all(
        not candidate.primary_score_contributions
        for candidate in (
            summary
            .candidates_by_engineering_rank
        )
    )


def test_legacy_summary_without_comparison_fields_is_compatible(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload["schema_version"] = "0.2"
    payload.pop("candidate_comparison_status")
    payload.pop("candidate_comparison_reason")
    payload.pop(
        "adjacent_candidate_score_comparisons"
    )
    payload.pop(
        "scientific_interpretation_status"
    )
    payload.pop(
        "scientific_interpretation_reason"
    )
    payload.pop(
        "scientific_interpretation_contract"
    )

    loaded = RankerResultSummary.model_validate(
        payload
    )

    assert loaded.schema_version == "0.2"
    assert (
        loaded.candidate_comparison_status
        == "UNAVAILABLE"
    )
    assert loaded.candidate_comparison_reason
    assert (
        loaded
        .adjacent_candidate_score_comparisons
        == []
    )
    assert (
        loaded.scientific_interpretation_status
        == "UNAVAILABLE"
    )
    assert loaded.scientific_interpretation_reason
    assert (
        loaded.scientific_interpretation_contract
        is None
    )


def test_released_v031_summary_schema_is_compatible(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload["schema_version"] = "0.1"

    for field in (
        "score_decomposition_status",
        "score_decomposition_reason",
        "region_score_used",
        "primary_score_formula",
        "primary_score_weights",
        "candidate_comparison_status",
        "candidate_comparison_reason",
        "adjacent_candidate_score_comparisons",
        "scientific_interpretation_status",
        "scientific_interpretation_reason",
        "scientific_interpretation_contract",
    ):
        payload.pop(field)

    for candidate in payload[
        "candidates_by_engineering_rank"
    ]:
        candidate.pop(
            "primary_score_contributions"
        )
        candidate.pop(
            "reconstructed_final_score_v4"
        )
        candidate.pop(
            "primary_score_reconstruction_error"
        )

    loaded = RankerResultSummary.model_validate(
        payload
    )

    assert loaded.schema_version == "0.1"
    assert (
        loaded.score_decomposition_status
        == "UNAVAILABLE"
    )
    assert (
        loaded.candidate_comparison_status
        == "UNAVAILABLE"
    )
    assert (
        loaded.scientific_interpretation_status
        == "UNAVAILABLE"
    )
    assert all(
        candidate.primary_score_contributions
        == {}
        for candidate in (
            loaded.candidates_by_engineering_rank
        )
    )


def test_schema_03_without_interpretation_fields_is_compatible(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload["schema_version"] = "0.3"
    payload.pop(
        "scientific_interpretation_status"
    )
    payload.pop(
        "scientific_interpretation_reason"
    )
    payload.pop(
        "scientific_interpretation_contract"
    )

    loaded = RankerResultSummary.model_validate(
        payload
    )

    assert loaded.schema_version == "0.3"
    assert loaded.score_decomposition_status == (
        "AVAILABLE"
    )
    assert loaded.candidate_comparison_status == (
        "AVAILABLE"
    )
    assert (
        loaded.scientific_interpretation_status
        == "UNAVAILABLE"
    )


def test_current_summary_schema_rejects_missing_contract_fields(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload.pop(
        "scientific_interpretation_contract"
    )

    with pytest.raises(
        ValueError,
        match="schema 0.4.*必需字段",
    ):
        RankerResultSummary.model_validate(
            payload
        )


def test_current_summary_schema_rejects_partial_candidate_fields(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload[
        "candidates_by_engineering_rank"
    ][0].pop(
        "primary_score_contributions"
    )

    with pytest.raises(
        ValueError,
        match="候选 0.*必需字段",
    ):
        RankerResultSummary.model_validate(
            payload
        )


def test_unknown_result_summary_schema_is_rejected(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload["schema_version"] = "0.5"

    with pytest.raises(ValueError):
        RankerResultSummary.model_validate(
            payload
        )


@pytest.mark.parametrize(
    "location",
    [
        "candidate_score",
        "component_score",
        "key_metric",
        "primary_weight",
        "filter_threshold",
    ],
)
@pytest.mark.parametrize(
    "non_finite",
    [float("nan"), float("inf"), float("-inf")],
)
def test_summary_rejects_non_finite_derived_numbers(
    tmp_path: Path,
    location: str,
    non_finite: float,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    candidate = payload[
        "candidates_by_engineering_rank"
    ][0]

    if location == "candidate_score":
        candidate["final_score_v4"] = (
            non_finite
        )
    elif location == "component_score":
        candidate["component_scores"][
            "score_safety"
        ] = non_finite
    elif location == "key_metric":
        candidate["key_metrics"][
            "effective_weight_sum"
        ] = non_finite
    elif location == "primary_weight":
        payload["primary_score_weights"][
            "score_safety"
        ] = non_finite
    else:
        first_threshold = next(
            iter(
                payload[
                    "raw_filter_thresholds"
                ]["broad"].values()
            )
        )
        first_threshold["value"] = (
            non_finite
        )

    with pytest.raises(ValueError):
        RankerResultSummary.model_validate(
            payload
        )


def test_summary_rejects_tampered_candidate_comparison(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload[
        "adjacent_candidate_score_comparisons"
    ][0]["recorded_score_delta"] = 0.2

    with pytest.raises(
        ValueError,
        match="候选比较记录与共享算术结果不一致",
    ):
        RankerResultSummary.model_validate(
            payload
        )


def test_summary_rejects_tampered_interpretation_contract(
    tmp_path: Path,
) -> None:
    summary = parse_completed_ranker_run(
        build_bundle(tmp_path)
    )
    payload = summary.model_dump(
        mode="json"
    )
    payload[
        "scientific_interpretation_contract"
    ]["metric_semantics"][
        "score_safety"
    ]["direction"] = "lower_better"

    with pytest.raises(
        ValueError,
        match="共享指标本体或结果策略不一致",
    ):
        RankerResultSummary.model_validate(
            payload
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
