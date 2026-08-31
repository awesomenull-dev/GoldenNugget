"""GoldenNugget CLI entry shim.

The unified CLI logic lives in :mod:`src.cli`; this top-level script is only
a thin executable shim so PyInstaller and ``python nugget_cli.py ...`` keep
working unchanged. See ``src/cli/main.py`` for the dispatcher.
"""

from src.cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
