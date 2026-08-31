"""GoldenNugget unified CLI + GUI entry.

This is the single executable entry for the bundled ``Nugget`` binary. It
dispatches to the GUI by default and exposes the bundled helper tools as
subcommands:

    Nugget                          launch the GUI (default)
    Nugget --usage | --help         print this help
    Nugget apply-wallpaper [path] [--udid U] [--list]
    Nugget restore-cache [--udid U] [--password P] [--cache-root R] [--timeout M]
    Nugget restore [--udid U] [--password P] [--cache-root R] [--timeout M]
    Nugget skip-setup [--udid U]

Anything else falls through to the classic dispatcher (GUI, ``-m <module>``
for background processes, ``<file>.py`` script execution) for full backward
compatibility.
"""

import sys

USAGE = """\
GoldenNugget - unified CLI

Usage:
  Nugget                              Launch the GUI
  Nugget --usage | --help             Show this help

  Nugget apply-wallpaper [TENDIE] [--udid UDID] [--list]
      Apply a .tendies wallpaper to a connected device.

  Nugget restore-cache [--udid UDID] [--password PASSWORD]
                       [--cache-root DIR] [--timeout MINUTES]
                       [--no-skip-setup] [--no-reboot]
      Restore the last protective backup cache after a failed/wedged apply,
      then apply skip-setup and reboot (Phase 5). Add --no-skip-setup /
      --no-reboot to skip those steps.

  Nugget restore [same options as restore-cache]
      Alias for restore-cache (safe, manifest-pruned protective restore).

  Nugget skip-setup [--udid UDID]
      Mark all iOS setup panes as already completed (skip setup).

Backward-compatible fallbacks (used internally by the app):
  Nugget -m <module> [args...]
  Nugget <script>.py [args...]

For per-command details run e.g.  Nugget restore-cache --help
"""


def _run_subcommand(name: str, argv: list) -> int:
    if name == "apply-wallpaper":
        from apply_wallpaper import main
    elif name == "restore-cache":
        from restore_cache import main
    elif name == "restore":
        from restore import main
    elif name == "skip-setup":
        from skip_setup import main
    else:
        return None
    return main(argv)


def dispatch(argv: list) -> int:
    # Empty argv (e.g. double-clicking Nugget.exe on Windows) must fall through
    # to the GUI below — only an explicit help flag prints the usage.
    if argv and argv[0] in ("-h", "--help", "--usage"):
        print(USAGE)
        return 0

    known = {"apply-wallpaper", "restore-cache", "restore", "skip-setup"}
    if argv and argv[0] in known:
        first = argv[0]
        code = _run_subcommand(first, argv[1:])
        if code is not None:
            return code
        print(f"Unknown subcommand: {first}", file=sys.stderr)
        print(USAGE)
        return 2

    # Fall through to the classic GUI + dispatcher in main_app, which handles
    # ``-m <module>`` (background processes), ``<file>.py`` execution, and the
    # GUI when no recognized argument is present.
    from main_app import main
    return main()


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    return dispatch(list(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
