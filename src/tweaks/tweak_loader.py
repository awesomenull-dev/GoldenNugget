from .tweaks import tweaks, TweakID
from .registry import SPECS
from .basic_plist_locations import FileLocation
from .tweak_classes import BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak
from .daemons_tweak import DANGEROUS_KEYS


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


# Kept as thin aliases — classic pages and preset_manager call the per-group names.
def load_internal():
    load_plist_tweaks()
def load_liquidglass():
    load_plist_tweaks()
def load_springboard():
    load_plist_tweaks()


def load_daemons():
    if TweakID.Daemons in tweaks:
        return
    defaults = {
        "com.apple.magicswitchd.companion": True,
        "com.apple.security.otpaird": True,
        "com.apple.dhcp6d": True,
        "com.apple.bootpd": True,
        "com.apple.ftp-proxy-embedded": False,
        "com.apple.relevanced": True
    }
    # Dangerous daemons never ship as disabled, even from a stored preset.
    defaults = {k: v for k, v in defaults.items() if k not in DANGEROUS_KEYS}
    tweaks.update({
        TweakID.Daemons: AdvancedPlistTweak(
            FileLocation.disabledDaemons,
            defaults,
            owner=0, group=0,
            never_enable=DANGEROUS_KEYS,
        ),
        TweakID.ClearScreenTimeAgentPlist: NullifyFileTweak(FileLocation.screentime),
    })