"""``Nugget tweaks`` — inspect and flip the registry (plist) tweaks.

State lives in the same in-memory ``tweaks`` dict the GUI uses. Every change
is persisted to the ``AutoSave`` preset unless ``--no-save`` is given, so a
later ``Nugget apply`` (which starts from AutoSave) sees it.
"""

import argparse
import sys

from src.tweaks.registry import SPECS_BY_SECTION, SPECS_BY_ID, Kind, Section

_SECTION_ALIASES = {}
for _member in Section:
    _SECTION_ALIASES[_member.value.lower()] = _member
    _SECTION_ALIASES[_member.name.lower()] = _member


def _parse_section(text: str):
    section = _SECTION_ALIASES.get(text.strip().lower())
    if section is None:
        raise argparse.ArgumentTypeError(
            f"unknown section '{text}' (use {', '.join(s.value for s in Section)})")
    return section


def _print_list_section(section, only_enabled=True):
    from src.tweaks.tweaks import tweaks
    for spec in SPECS_BY_SECTION[section]:
        tweak = tweaks.get(spec.id)
        state = "on " if tweak is not None and tweak.enabled else "off"
        if only_enabled and tweak is not None and not tweak.enabled:
            continue
        kind = spec.kind.value
        val = ""
        if tweak is not None and tweak.enabled:
            val = f"  value={tweak.value!r}"
        print(f"  {state} {spec.id.name:<40} [{kind}]{val}")


def add_parser(subp):
    parser = subp.add_parser(
        "tweaks",
        help="Inspect and toggle registry tweaks",
        description="View the plist-based tweak registry and enable/disable/"
                    "set tweak values. Changes are saved to the AutoSave "
                    "preset (like the GUI) unless --no-save is used.",
    )
    sub = parser.add_subparsers(dest="tweaks_sub", required=True)

    p = sub.add_parser("list", help="List registry tweaks")
    p.add_argument("--section", type=_parse_section, default=None,
                   help="only this section (Liquid Glass / SpringBoard / Internal Options)")
    p.add_argument("--all", action="store_true",
                   help="show disabled tweaks too (default: only enabled)")
    p.set_defaults(func=_run_list)

    p = sub.add_parser("show", help="Show one tweak's specs + current state")
    p.add_argument("id", metavar="ID")
    p.set_defaults(func=_run_show)

    p = sub.add_parser("enable", help="Enable tweaks (all specs of the given IDs)")
    p.add_argument("ids", nargs="+", metavar="ID")
    p.add_argument("--value", default=None,
                   help="override the value written when enabled")
    p.add_argument("--no-save", action="store_true", help="don't touch AutoSave")
    p.set_defaults(func=_run_enable)

    p = sub.add_parser("disable", help="Disable tweaks")
    p.add_argument("ids", nargs="+", metavar="ID")
    p.add_argument("--no-save", action="store_true", help="don't touch AutoSave")
    p.set_defaults(func=_run_disable)

    p = sub.add_parser("set", help="Set a tweak's value (enables it)")
    p.add_argument("id", metavar="ID")
    p.add_argument("value", help="value (text or number)")
    p.add_argument("--no-save", action="store_true", help="don't touch AutoSave")
    p.set_defaults(func=_run_set)

    return parser


def _resolve_specs(ids):
    from src.cli.common import load_core_tweaks, resolve_tweak_id
    load_core_tweaks()
    resolved = []
    for name in ids:
        tid = resolve_tweak_id(name)
        spec = SPECS_BY_ID.get(tid)
        if spec is None:
            print(f"ERROR: unknown tweak '{name}'. Use 'Nugget tweaks list' "
                  f"for valid IDs.", file=sys.stderr)
            raise SystemExit(1)
        resolved.append(spec)
    return resolved


def _save_if(args, dm=None):
    if not getattr(args, "no_save", False):
        from src.cli.common import autosave_preset
        if not autosave_preset(dm):
            print("note: nothing serializable, AutoSave not written.")


def _run_list(args):
    from src.cli.common import load_core_tweaks, seed_from_autosave
    load_core_tweaks()
    seed_from_autosave()
    if args.section is not None:
        sections = [args.section]
    else:
        sections = list(Section)
    for section in sections:
        title = section.value
        specs = SPECS_BY_SECTION[section]
        if not specs:
            continue
        print(f"[{title}]")
        _print_list_section(section, only_enabled=not args.all)
    return 0


def _run_show(args):
    from src.cli.common import seed_from_autosave
    seed_from_autosave()
    specs = _resolve_specs([args.id])
    from src.tweaks.tweaks import tweaks
    spec = specs[0]
    tweak = tweaks.get(spec.id)
    print(f"id:        {spec.id.name}")
    print(f"section:   {spec.section.value}")
    print(f"kind:      {spec.kind.value}")
    print(f"plist:     {spec.location.value}")
    print(f"key:       {spec.key or '<factory>'}")
    print(f"default:   {spec.value!r}")
    if spec.min_version:
        print(f"min ios:   {spec.min_version}")
    if spec.max_version:
        print(f"max ios:   {spec.max_version}")
    flags = []
    if spec.iphone_only:
        flags.append("iPhone only")
    if spec.ipad_only:
        flags.append("iPad only")
    if spec.disabled:
        flags.append("DISABLED (cut off)")
    if flags:
        print(f"flags:     {', '.join(flags)}")
    print(f"enabled:   {tweak.enabled if tweak else False}")
    print(f"value:     {tweak.value!r}" if tweak is not None else "value:     <not loaded>")
    return 0


def _run_enable(args):
    from src.cli.common import seed_from_autosave
    seed_from_autosave()
    for spec in _resolve_specs(args.ids):
        from src.tweaks.tweaks import tweaks
        tweak = tweaks[spec.id]
        if args.value is not None:
            tweak.set_value(args.value, toggle_enabled=True)
        elif spec.factory is not None:
            # factory tweaks (watchOS compatibility) are just toggles
            tweak.set_enabled(True)
        else:
            tweak.set_enabled(True)
        print(f"enabled {spec.id.name}")
    _save_if(args)
    return 0


def _run_disable(args):
    from src.cli.common import seed_from_autosave
    seed_from_autosave()
    for spec in _resolve_specs(args.ids):
        from src.tweaks.tweaks import tweaks
        tweaks[spec.id].set_enabled(False)
        print(f"disabled {spec.id.name}")
    _save_if(args)
    return 0


def _run_set(args):
    from src.cli.common import seed_from_autosave
    seed_from_autosave()
    spec = _resolve_specs([args.id])[0]
    from src.tweaks.tweaks import tweaks
    tweak = tweaks[spec.id]
    if spec.kind == Kind.NUMBER:
        # Integral ranges keep strict int parsing; a fractional step
        # (spec.step, e.g. the Liquid Glass tint's 0.5) accepts floats.
        integral = float(spec.step or 1).is_integer()
        try:
            value = int(args.value) if integral else float(args.value)
        except ValueError:
            print(f"ERROR: {spec.id.name} needs a number, got '{args.value}'.",
                  file=sys.stderr)
            return 1
        if spec.min_value is not None and value < spec.min_value:
            print(f"ERROR: value below minimum {spec.min_value}.", file=sys.stderr)
            return 1
        if spec.max_value is not None and value > spec.max_value:
            print(f"ERROR: value above maximum {spec.max_value}.", file=sys.stderr)
            return 1
    else:
        value = args.value
    tweak.set_value(value, toggle_enabled=True)
    print(f"set {spec.id.name} = {value!r}")
    _save_if(args)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(func=None)
    sub = parser.add_subparsers(dest="sub", required=True)
    add_parser(sub)
    args = parser.parse_args(argv)
    return args.func(args) if args.func else parser.print_help() or 0


if __name__ == "__main__":
    sys.exit(main())