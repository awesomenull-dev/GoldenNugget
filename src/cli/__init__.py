"""CLI package for GoldenNugget.

Re-exports the unified CLI entry point so it can be used both from the
top-level ``nugget_cli.py`` shim and directly via ``src.cli.main``.
"""

from src.cli.main import USAGE, dispatch, main

__all__ = ["main", "dispatch", "USAGE"]
