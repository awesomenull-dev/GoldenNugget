"""GoldenNugget unified CLI dispatch logic.

Houses the subcommand routing and usage text for the bundled ``Nugget``
binary. The executable entry point (root ``nugget_cli.py``) is only a thin
shim that calls :func:`main` here; keeping the logic inside ``src/cli``
keeps the top-level script trivial and the dispatch logic unit-testable.
"""

import sys

USAGE = """\
GoldenNugget - unified CLI

Usage:
  Nugget                              Launch the GUI
  Nugget --usage | --help             Show this help

Device & target management:
  Nugget devices [--udid UDID]
      List connected devices (or show one device's details).

Tweaks:
  Nugget tweaks list [--section S] [--all]
  Nugget tweaks show ID
  Nugget tweaks enable ID... [--value X] [--no-save]
  Nugget tweaks disable ID... [--no-save]
  Nugget tweaks set ID VALUE [--no-save]
      Inspect and toggle the registry (plist) tweaks. Changes persist to the
      AutoSave preset (like the GUI) unless --no-save is used.

Daemons:
  Nugget daemons list | show
  Nugget daemons disable DAEMON... [--no-save]
  Nugget daemons enable DAEMON... [--no-save]
  Nugget daemons recommended [--enable] [--no-save]
  Nugget daemons master-on | master-off | screen-time on|off [--no-save]

Apply / Reset:
  Nugget apply [--udid UDID] [--preset NAME]
               [--enable ID --disable ID --set ID=VALUE]
               [--daemon-disable DAEMON --daemon-enable DAEMON]
               [--encrypted-backup] [--password PWD]
               [--no-skip-setup] [--no-reboot] [--continue-anyway]
      Apply the current tweak state (AutoSave preset + overrides) to the device.

  Nugget reset [--udid UDID] [--status-bar|--springboard|--daemons|--internal]
               [--no-skip-setup] [--no-reboot]
      Reset tweak sections back to stock (default: all resettable sections).

Presets:
  Nugget preset list | show NAME
  Nugget preset save NAME [--description ...] [--tags a,b]
  Nugget preset load NAME [--no-save]
  Nugget preset delete NAME
  Nugget preset export NAME [--out PATH] [--include ID,...]
  Nugget preset import PATH [--name NEW]

Safety rules (HotLoad):
  Nugget hotload status [--udid UDID]
  Nugget hotload refresh [--url URL]
  Nugget hotload enable | disable

Backups:
  Nugget backup create [--udid UDID] [--no-photos] [--no-posterboard]
  Nugget backup list [--udid UDID]

Standalone recovery / wallpapers:
  Nugget apply-wallpaper [TENDIE] [--udid UDID] [--list]
  Nugget restore-cache [--udid UDID] [--password PASSWORD]
                       [--cache-root DIR] [--timeout MINUTES]
                       [--no-skip-setup] [--no-reboot]
  Nugget restore [same options as restore-cache]
  Nugget skip-setup [--udid UDID]

Backward-compatible fallbacks (used internally by the app):
  Nugget -m <module> [args...]
  Nugget <script>.py [args...]

For per-command details run e.g.  Nugget apply --help
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


def _build_parser():
    import argparse
    from src.cli import cmd_devices, cmd_tweaks, cmd_daemons, cmd_preset
    from src.cli import cmd_apply, cmd_reset, cmd_hotload, cmd_backup

    parser = argparse.ArgumentParser(
        prog="Nugget",
        description="GoldenNugget unified CLI (GUI when run with no command).",
        add_help=True,
    )
    subp = parser.add_subparsers(dest="command", required=True)
    for module in (cmd_devices, cmd_tweaks, cmd_daemons, cmd_preset,
                   cmd_apply, cmd_reset, cmd_hotload, cmd_backup):
        module.add_parser(subp)
    return parser


def dispatch(argv: list) -> int:
    # Empty argv (e.g. double-clicking Nugget.exe on Windows) must fall through
    # to the GUI below — only an explicit help flag prints the usage.
    if argv and argv[0] in ("-h", "--help", "--usage"):
        print(USAGE)
        return 0

    known = {"apply-wallpaper", "restore-cache", "restore", "skip-setup",
             "devices", "tweaks", "daemons", "preset", "apply", "reset",
             "hotload", "backup"}
    if argv and argv[0] in known:
        if argv[0] in ("apply-wallpaper", "restore-cache", "restore",
                       "skip-setup"):
            code = _run_subcommand(argv[0], argv[1:])
            if code is not None:
                return code
            print(f"Unknown subcommand: {argv[0]}", file=sys.stderr)
            print(USAGE)
            return 2
        try:
            parser = _build_parser()
            args = parser.parse_args(argv)
        except SystemExit as e:
            return int(e.code or 0)
        return args.func(args)

    # Fall through to the classic GUI + dispatcher in main_app, which handles
    # ``-m <module>`` (background processes), ``<file>.py`` execution, and the
    # GUI when no recognized argument is present.
    from main_app import main
    return main()


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    return dispatch(list(sys.argv[1:]))