"""Console entry point for the optional BinderRanker MCP dependency."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="binderranker-mcp",
        description=(
            "Run the read-only BinderRanker MCP server over stdio. "
            "The workspace must have been created by `binderranker init`."
        ),
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Initialized BinderRanker workspace containing the runs directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    try:
        from protein_design_agent.adapters.mcp_server import run_mcp_server
        from protein_design_agent.adapters.read_only import (
            ReadOnlyAdapterConfigurationError,
        )
    except ImportError as exc:
        if exc.name == "mcp" or (exc.name or "").startswith("mcp."):
            print(
                "BinderRanker MCP support is not installed. "
                "Install it with: pip install 'binderranker[mcp]'",
                file=sys.stderr,
            )
            raise SystemExit(2) from None
        raise

    try:
        run_mcp_server(args.workspace)
    except ReadOnlyAdapterConfigurationError as exc:
        print(f"BinderRanker MCP configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
