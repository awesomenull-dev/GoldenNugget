from .tweaks import tweaks, TweakID
from .registry import SPECS
from .basic_plist_locations import FileLocation
from .tweak_classes import BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak
from .daemons_tweak import DANGEROUS_KEYS, INTERFACE_KEYS


def _build_spec(spec):
    if spec.factory is not None:
        return spec.factory()
    return BasicPlistTweak(spec.location, spec.key, value=spec.value)


def load_plist_tweaks():
    """Register every registry-defined tweak that isn't loaded yet (idempotent).

    Specs marked ``disabled`` are cut off entirely: they are never registered,
    so they neither render nor apply.
    """
    tweaks.update({spec.id: _build_spec(spec) for spec in SPECS
                   if spec.id not in tweaks and not spec.disabled})


def load_daemons():
    if TweakID.Daemons in tweaks:
        return
    # Daemons start empty; each interface toggle adds its own keys. Only
    # interface-visible keys (INTERFACE_KEYS) survive filtering, so unrelated
    # or hidden daemons can never leak into the apply pass or a stored preset.
    defaults = {}
    tweaks.update({
        TweakID.Daemons: AdvancedPlistTweak(
            FileLocation.disabledDaemons,
            defaults,
            owner=0, group=0,
            never_enable=DANGEROUS_KEYS,
            allowed_keys=INTERFACE_KEYS,
        ),
        TweakID.ClearScreenTimeAgentPlist: NullifyFileTweak(FileLocation.screentime),
    })