#!/usr/bin/env python3
"""Validate BinderRanker through a real local MCP stdio subprocess."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from protein_design_agent.adapters.local_host_validation import (
    verify_local_mcp_host,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the installed BinderRanker MCP entry point as a real "
            "stdio subprocess and verify the local-host contract."
        )
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Initialized BinderRanker workspace used only by the subprocess.",
    )
    parser.add_argument(
        "--task-name",
        required=True,
        help="Existing empty task used for read-only fail-closed calls.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable containing BinderRanker and the MCP extra.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(
            verify_local_mcp_host(
                python_executable=args.python,
                workspace=args.workspace,
                task_name=args.task_name,
            )
        )
    except Exception as exc:
        print(
            "FAIL: BinderRanker local MCP host validation failed "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
