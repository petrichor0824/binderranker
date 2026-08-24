from pathlib import Path

import pytest

from protein_design_agent.agent.ranker_report_context import (
    RankerReportContextError,
    parse_boolean_flag,
    parse_ranker_report_context,
)


def test_report_context_is_parsed(
    tmp_path: Path,
) -> None:
    report = tmp_path / "ranker_report.txt"
    report.write_text(
        "\n".join(
            [
                "binder_chain = B",
                "region_score_used = True",
                (
                    "final_score_v4_region = "
                    "0.78*morphology_adaptive_score + "
                    "0.10*score_safety + "
                    "0.05*score_roughness + "
                    "0.07*score_region"
                ),
                (
                    "final_score_v4 = primary ranking "
                    "score; equals region-aware score "
                    "if region_score_used=True"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    context = parse_ranker_report_context(
        report
    )

    assert context.run_config == {
        "binder_chain": "B",
        "region_score_used": "True",
    }
    assert (
        context.score_formulas[
            "final_score_v4_region"
        ].startswith("0.78*")
    )


def test_missing_formula_can_be_legacy_compatible(
    tmp_path: Path,
) -> None:
    report = tmp_path / "ranker_report.txt"
    report.write_text(
        "region_score_used = False\n",
        encoding="utf-8",
    )

    context = parse_ranker_report_context(
        report,
        require_final_formula=False,
    )

    assert context.score_formulas == {}


def test_missing_formula_is_rejected_when_required(
    tmp_path: Path,
) -> None:
    report = tmp_path / "ranker_report.txt"
    report.write_text(
        "region_score_used = False\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RankerReportContextError,
        match="final_score_v4",
    ):
        parse_ranker_report_context(report)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        ("yes", True),
        ("0", False),
    ],
)
def test_boolean_flag_is_parsed(
    value: object,
    expected: bool,
) -> None:
    assert (
        parse_boolean_flag(
            value,
            field_name="region_score_used",
        )
        is expected
    )


def test_invalid_boolean_flag_is_rejected() -> None:
    with pytest.raises(
        RankerReportContextError,
        match="无法解析布尔配置",
    ):
        parse_boolean_flag(
            "maybe",
            field_name="region_score_used",
        )


def test_empty_boolean_flag_is_rejected() -> None:
    with pytest.raises(
        RankerReportContextError,
        match="无法解析布尔配置",
    ):
        parse_boolean_flag(
            "",
            field_name="region_score_used",
        )
