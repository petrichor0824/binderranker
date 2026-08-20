#!/usr/bin/env python3
"""Verify BinderRanker release distribution assets."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
from configparser import ConfigParser
from email.message import Message
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile


PROJECT_NAME = "binderranker"

EXPECTED_SUMMARY = (
    "Interpretable ranking and layered screening "
    "for generated protein backbone candidates"
)

EXPECTED_LICENSE = "Apache-2.0"
EXPECTED_REQUIRES_PYTHON = ">=3.10"

CANONICAL_ENTRY_POINT = (
    "protein_design_agent.cli:app"
)
LEGACY_ENTRY_POINT = (
    "protein_design_agent.cli:app"
)

RANKER_SUFFIX = (
    "protein_design_agent/resources/"
    "binderranker/v0.1-expert/"
    "contact_field_rank_integrated_region.py"
)

RANKER_MANIFEST_SUFFIX = (
    "protein_design_agent/resources/"
    "binderranker/v0.1-expert/SHA256SUMS"
)

SAMPLE_PREFIX = (
    "protein_design_agent/resources/"
    "samples/3c98_small/"
)


class ReleaseAssetError(RuntimeError):
    """A release artifact failed validation."""


def require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise ReleaseAssetError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def parse_metadata(text: str) -> Message:
    return Parser().parsestr(text)


def require_metadata(
    metadata: Message,
    *,
    source: str,
) -> str:
    expected = {
        "Name": PROJECT_NAME,
        "Summary": EXPECTED_SUMMARY,
        "License-Expression": EXPECTED_LICENSE,
        "Requires-Python": EXPECTED_REQUIRES_PYTHON,
    }

    for field, value in expected.items():
        actual = metadata.get(field)

        require(
            actual == value,
            (
                f"{source}: {field} expected "
                f"{value!r}, got {actual!r}"
            ),
        )

    version = metadata.get("Version")

    require(
        isinstance(version, str)
        and bool(version.strip()),
        f"{source}: Version is missing",
    )

    return version


def inspect_wheel(
    wheel: Path,
) -> tuple[str, set[str]]:
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

        metadata_names = [
            name
            for name in names
            if name.endswith(
                ".dist-info/METADATA"
            )
        ]

        require(
            len(metadata_names) == 1,
            (
                "wheel: expected exactly one "
                f"METADATA, got {metadata_names}"
            ),
        )

        metadata = parse_metadata(
            archive.read(
                metadata_names[0]
            ).decode("utf-8")
        )

        version = require_metadata(
            metadata,
            source="wheel METADATA",
        )

        entry_point_names = [
            name
            for name in names
            if name.endswith(
                ".dist-info/entry_points.txt"
            )
        ]

        require(
            len(entry_point_names) == 1,
            (
                "wheel: expected exactly one "
                "entry_points.txt"
            ),
        )

        parser = ConfigParser()
        parser.optionxform = str
        parser.read_string(
            archive.read(
                entry_point_names[0]
            ).decode("utf-8")
        )

        require(
            parser.has_section(
                "console_scripts"
            ),
            (
                "wheel: console_scripts "
                "section is missing"
            ),
        )

        scripts = parser["console_scripts"]

        require(
            scripts.get("binderranker")
            == CANONICAL_ENTRY_POINT,
            (
                "wheel: canonical binderranker "
                "entry point is invalid"
            ),
        )

        require(
            scripts.get(
                "protein-design-agent"
            )
            == LEGACY_ENTRY_POINT,
            (
                "wheel: legacy CLI compatibility "
                "entry point is invalid"
            ),
        )

    required_suffixes = (
        RANKER_SUFFIX,
        RANKER_MANIFEST_SUFFIX,
        (
            SAMPLE_PREFIX
            + "README.md"
        ),
        ".dist-info/licenses/LICENSE",
    )

    for suffix in required_suffixes:
        matches = [
            name
            for name in names
            if name.endswith(suffix)
        ]

        require(
            len(matches) == 1,
            (
                "wheel: expected exactly one "
                f"{suffix!r}, got {matches}"
            ),
        )

    sample_pdbs = [
        name
        for name in names
        if (
            SAMPLE_PREFIX in name
            and name.endswith(".pdb")
        )
    ]

    require(
        len(sample_pdbs) == 5,
        (
            "wheel: expected five packaged "
            f"sample PDBs, got {sample_pdbs}"
        ),
    )

    return version, names


def inspect_sdist(
    sdist: Path,
) -> tuple[str, set[str]]:
    with tarfile.open(
        sdist,
        "r:gz",
    ) as archive:
        members = archive.getmembers()
        names = {
            member.name
            for member in members
        }

        metadata_members = [
            member
            for member in members
            if (
                member.isfile()
                and member.name.endswith(
                    "/PKG-INFO"
                )
                and member.name.count("/") == 1
            )
        ]

        require(
            len(metadata_members) == 1,
            (
                "sdist: expected exactly one "
                "root PKG-INFO"
            ),
        )

        handle = archive.extractfile(
            metadata_members[0]
        )

        require(
            handle is not None,
            (
                "sdist: could not read "
                "PKG-INFO"
            ),
        )

        metadata = parse_metadata(
            handle.read().decode("utf-8")
        )

        version = require_metadata(
            metadata,
            source="sdist PKG-INFO",
        )

    root = f"{PROJECT_NAME}-{version}"

    required_names = (
        f"{root}/LICENSE",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/src/{RANKER_SUFFIX}",
        (
            f"{root}/src/"
            f"{RANKER_MANIFEST_SUFFIX}"
        ),
        (
            f"{root}/src/"
            f"{SAMPLE_PREFIX}README.md"
        ),
    )

    for name in required_names:
        require(
            name in names,
            f"sdist: missing {name}",
        )

    sample_prefix = (
        f"{root}/src/{SAMPLE_PREFIX}"
    )

    sample_pdbs = [
        name
        for name in names
        if (
            name.startswith(sample_prefix)
            and name.endswith(".pdb")
        )
    ]

    require(
        len(sample_pdbs) == 5,
        (
            "sdist: expected five packaged "
            f"sample PDBs, got {sample_pdbs}"
        ),
    )

    return version, names


def verify_release_checksums(
    dist: Path,
    *,
    wheel: Path,
    sdist: Path,
) -> None:
    manifest = dist / "SHA256SUMS.txt"

    require(
        manifest.is_file(),
        "release SHA256SUMS.txt is missing",
    )

    lines = [
        line
        for line in manifest.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    require(
        len(lines) == 2,
        (
            "release SHA256SUMS.txt must "
            "contain exactly two entries"
        ),
    )

    recorded: dict[str, str] = {}

    for line in lines:
        parts = line.split(
            maxsplit=1
        )

        require(
            len(parts) == 2,
            (
                "invalid SHA256SUMS line: "
                f"{line!r}"
            ),
        )

        digest, filename = parts
        filename = filename.strip()

        require(
            "/" not in filename
            and "\\" not in filename,
            (
                "release checksum entries must "
                "use basenames only: "
                f"{filename!r}"
            ),
        )

        require(
            len(digest) == 64
            and all(
                char in "0123456789abcdef"
                for char in digest.lower()
            ),
            (
                "invalid SHA256 digest for "
                f"{filename!r}"
            ),
        )

        require(
            filename not in recorded,
            (
                "duplicate checksum entry: "
                f"{filename}"
            ),
        )

        recorded[filename] = digest.lower()

    expected_names = {
        wheel.name,
        sdist.name,
    }

    require(
        set(recorded) == expected_names,
        (
            "release checksum filenames "
            f"expected {sorted(expected_names)}, "
            f"got {sorted(recorded)}"
        ),
    )

    for filename, expected in recorded.items():
        artifact = dist / filename

        require(
            artifact.is_file(),
            (
                "checksum references missing "
                f"artifact: {filename}"
            ),
        )

        actual = sha256_file(
            artifact
        )

        require(
            actual == expected,
            (
                f"SHA256 mismatch for "
                f"{filename}: expected "
                f"{expected}, got {actual}"
            ),
        )


def verify_release_assets(
    dist: Path,
) -> None:
    require(
        dist.is_dir(),
        f"distribution directory missing: {dist}",
    )

    wheels = sorted(
        dist.glob(
            f"{PROJECT_NAME}-*.whl"
        )
    )

    sdists = sorted(
        dist.glob(
            f"{PROJECT_NAME}-*.tar.gz"
        )
    )

    require(
        len(wheels) == 1,
        (
            "expected exactly one BinderRanker "
            f"wheel, got {wheels}"
        ),
    )

    require(
        len(sdists) == 1,
        (
            "expected exactly one BinderRanker "
            f"sdist, got {sdists}"
        ),
    )

    wheel = wheels[0]
    sdist = sdists[0]

    wheel_version, _ = inspect_wheel(
        wheel
    )
    sdist_version, _ = inspect_sdist(
        sdist
    )

    require(
        wheel_version == sdist_version,
        (
            "wheel and sdist versions differ: "
            f"{wheel_version!r} != "
            f"{sdist_version!r}"
        ),
    )

    require(
        sdist.name
        == (
            f"{PROJECT_NAME}-"
            f"{sdist_version}.tar.gz"
        ),
        (
            "unexpected sdist filename: "
            f"{sdist.name}"
        ),
    )

    require(
        wheel.name.startswith(
            (
                f"{PROJECT_NAME}-"
                f"{wheel_version}-"
            )
        ),
        (
            "wheel filename does not match "
            f"metadata version: {wheel.name}"
        ),
    )

    verify_release_checksums(
        dist,
        wheel=wheel,
        sdist=sdist,
    )

    expected_files = {
        wheel.name,
        sdist.name,
        "SHA256SUMS.txt",
    }

    actual_files = {
        path.name
        for path in dist.iterdir()
        if path.is_file()
    }

    require(
        actual_files == expected_files,
        (
            "unexpected release files: "
            f"expected {sorted(expected_files)}, "
            f"got {sorted(actual_files)}"
        ),
    )

    print(
        "PASS: BinderRanker release assets "
        f"{wheel_version} are internally "
        "consistent"
    )
    print(f"wheel: {wheel.name}")
    print(f"sdist: {sdist.name}")
    print("checksums: SHA256SUMS.txt")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify BinderRanker wheel, sdist, "
            "metadata, packaged resources, "
            "entry points, and release checksums."
        )
    )

    parser.add_argument(
        "dist",
        nargs="?",
        type=Path,
        default=Path("dist"),
        help=(
            "Distribution directory "
            "(default: dist)"
        ),
    )

    args = parser.parse_args()

    try:
        verify_release_assets(
            args.dist.resolve()
        )
    except ReleaseAssetError as exc:
        raise SystemExit(
            f"ERROR: {exc}"
        ) from exc


if __name__ == "__main__":
    main()
