import re
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (
        REPOSITORY_ROOT
        / relative_path
    ).read_text(encoding="utf-8")


def project_version() -> str:
    pyproject = read_text("pyproject.toml")
    match = re.search(
        r'^version = "([^"]+)"$',
        pyproject,
        flags=re.MULTILINE,
    )

    assert match is not None
    return match.group(1)


def test_release_version_metadata_is_consistent() -> None:
    version = project_version()
    citation = yaml.safe_load(
        read_text("CITATION.cff")
    )

    assert isinstance(citation, dict)
    assert str(citation["version"]) == version

    changelog = read_text("CHANGELOG.md")
    release_match = re.search(
        rf"^## {re.escape(version)} - "
        r"(\d{4}-\d{2}-\d{2})$",
        changelog,
        flags=re.MULTILINE,
    )

    assert release_match is not None
    assert str(
        citation["date-released"]
    ) == release_match.group(1)


def test_release_readmes_reference_current_wheel() -> None:
    version = project_version()
    wheel_name = (
        f"binderranker-{version}-"
        "py3-none-any.whl"
    )

    readme = read_text("README.md")
    readme_zh = read_text("README.zh-CN.md")

    assert f"**v{version} —" in readme
    assert wheel_name in readme
    assert f"**v{version} —" in readme_zh
    assert wheel_name in readme_zh


def test_release_governance_references_current_version() -> None:
    version = project_version()
    architecture = read_text(
        "docs/ARCHITECTURE_EVOLUTION.md"
    )
    roadmap = read_text(
        "docs/POST_V0_3_EXECUTION_ROADMAP.md"
    )

    assert (
        "Current package/release version: "
        f"`{version}`"
    ) in architecture
    assert (
        "current release-cut version: "
        f"`{version}`"
    ) in roadmap
