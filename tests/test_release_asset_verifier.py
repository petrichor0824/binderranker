import importlib.util
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = (
    REPOSITORY_ROOT
    / "scripts"
    / "verify_release_assets.py"
)


def load_verifier_module():
    spec = importlib.util.spec_from_file_location(
        "binderranker_release_asset_verifier",
        VERIFIER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(
        spec
    )
    spec.loader.exec_module(module)
    return module


def test_citation_version_parser_reads_top_level_version() -> None:
    verifier = load_verifier_module()

    version = verifier.parse_citation_version(
        "cff-version: 1.2.0\n"
        "title: BinderRanker\n"
        "version: 0.4.0\n"
    )

    assert version == "0.4.0"


@pytest.mark.parametrize(
    "content",
    [
        "cff-version: 1.2.0\n",
        (
            "version: 0.4.0\n"
            "version: 9.9.9\n"
        ),
    ],
)
def test_citation_version_parser_rejects_ambiguous_metadata(
    content: str,
) -> None:
    verifier = load_verifier_module()

    with pytest.raises(
        verifier.ReleaseAssetError,
        match="exactly one top-level version",
    ):
        verifier.parse_citation_version(
            content
        )
