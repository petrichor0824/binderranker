from pathlib import Path

import protein_design_agent.tools.run_binderranker as module
from protein_design_agent.tools.run_binderranker import (
    resolve_ranker,
    sha256_file,
)


EXPECTED_SHA256 = (
    "92d6c02f8ca8f500917f5fa61676fe93"
    "a0acdbb59d49f2cac0c7a74a4a553ed7"
)


def test_resolve_ranker_uses_packaged_resource(
) -> None:
    ranker_path, expected_sha256 = (
        resolve_ranker("v0.1-expert")
    )

    package_root = (
        Path(module.__file__)
        .resolve()
        .parents[1]
    )

    expected_path = (
        package_root
        / "resources"
        / "binderranker"
        / "v0.1-expert"
        / "contact_field_rank_integrated_region.py"
    )

    assert ranker_path.resolve() == (
        expected_path.resolve()
    )

    assert ranker_path.is_file()
    assert expected_sha256 == EXPECTED_SHA256
    assert (
        sha256_file(ranker_path)
        == EXPECTED_SHA256
    )


def test_packaged_ranker_matches_audit_source(
) -> None:
    repository_root = (
        Path(__file__).resolve().parents[1]
    )

    canonical = (
        repository_root
        / "algorithms"
        / "binderranker"
        / "v0.1-expert"
        / "contact_field_rank_integrated_region.py"
    )

    packaged, _ = resolve_ranker(
        "v0.1-expert"
    )

    assert canonical.is_file()
    assert packaged.is_file()

    assert (
        canonical.read_bytes()
        == packaged.read_bytes()
    )
