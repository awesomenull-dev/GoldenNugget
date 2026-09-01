"""Single source of truth for the plist-based tweaks.

Every tweak's definition (id, section, title, plist location, key, default
value, UI kind) lives here exactly once. ``tweak_loader`` builds the runtime
instances from these specs and the iOS tweaks page renders its rows from
them — adding a tweak means adding one entry here.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QT_TRANSLATE_NOOP

from .basic_plist_locations import FileLocation
from .tweak_names import TweakID


class Section(Enum):
    LIQUID_GLASS = "Liquid Glass"
    SPRINGBOARD = "SpringBoard"
    INTERNAL = "Internal Options"


class Kind(Enum):
    SWITCH = "switch"   # boolean toggle
    TEXT = "text"       # free-form text value
    NUMBER = "number"   # numeric value


@dataclass(frozen=True)
class TweakSpec:
    id: TweakID
    section: Section
    title: str
    location: FileLocation
    key: str
    value: any = True          # value written when the tweak is enabled
    kind: Kind = Kind.SWITCH
    min_value: int = 0         # NUMBER kind only
    max_value: int = 999       # NUMBER kind only
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    iphone_only: bool = False
    ipad_only: bool = False
    factory: Optional[Callable[[], object]] = None  # overrides BasicPlistTweak
    description: Optional[str] = None  # detailed "what it does" tooltip


def _t(id_: TweakID, section: Section, title: str, location: FileLocation,
       key: str, description: str = "", **kwargs) -> TweakSpec:
    # QT_TRANSLATE_NOOP marks the title for pyside6-lupdate; the actual
    # translation happens at render time (translators are not installed yet
    # when this module is imported).
    return TweakSpec(id=id_, section=section,
                     title=QT_TRANSLATE_NOOP("Nugget", title),
                     description=QT_TRANSLATE_NOOP("Nugget", description) if description else None,
                     location=location, key=key, **kwargs)


def _watchos_compatibility():
    from .tweak_classes import AdvancedPlistTweak
    return AdvancedPlistTweak(
        FileLocation.nanoregistry,
        keyValues={
            "IOS_PAIRING_EOL_MIN_PAIRING_COMPATIBILITY_VERSION_CHIPIDS": "",
            "maxPairingCompatibilityVersion": 37,
            "lastRestoreIdentifier": "CD97EEB8-BCD2-486B-BC13-C384E6B916C4",  # not sure if this is needed
            "minPairingCompatibilityVersionWithChipID": 1,
            "lastRestoreIdentifier_state": 0,
            "AdvertisingIdentifierSeed": "85E70251-1960-4DA0-A321-B68AC118FAB5",  # this prolly isn't needed either
            "minPairingCompatibilityVersion": 1
        })


GP = FileLocation.globalPreferences

SPECS: tuple[TweakSpec, ...] = (
    # --- Liquid Glass ---
    _t(TweakID.ForceSolariumFallback, Section.LIQUID_GLASS, "Force Solarium Fallback", GP, "SolariumForceFallback",
       description=QT_TRANSLATE_NOOP("Nugget", "Forces the older Solarium rendering path instead of the newer one. Useful for troubleshooting or for devices where the current Solarium engine misbehaves on iOS 26."),
       min_version="26.0", max_version="26.99"),
    _t(TweakID.IgnoreSolariumLinkedOnCheck, Section.LIQUID_GLASS, "Ignore Solarium Linked-On Check", GP, "com.apple.SwiftUI.IgnoreSolariumLinkedOnCheck",
       description=QT_TRANSLATE_NOOP("Nugget", "Ignores the compile-time (linked-on) SDK version check for Solarium, allowing Liquid Glass features to run that would otherwise be gated by the SDK an app was built with."),
       min_version="26.0"),
    _t(TweakID.ForceSolariumIntelligence, Section.LIQUID_GLASS, "Force Solarium Intelligence", GP, "SolariumForceIntelligence",
       description=QT_TRANSLATE_NOOP("Nugget", "Forces the experimental Solarium 'Intelligence' rendering features (adaptive, machine-driven effects) on iOS 27 where they are not enabled by default."),
       min_version="27.0"),
    _t(TweakID.ForceEnhancedSpeculars, Section.LIQUID_GLASS, "Force Enhanced Speculars", GP, "SolariumForceEnhancedSpeculars",
       description=QT_TRANSLATE_NOOP("Nugget", "Enables the enhanced specular (highlight and reflection) rendering pass that is normally only used on the most capable devices."),
       min_version="27.0"),
    _t(TweakID.UISolariumFallback, Section.LIQUID_GLASS, "UI Solarium Fallback", GP, "UISolariumForceFallback",
       description=QT_TRANSLATE_NOOP("Nugget", "Forces UIKit to use the fallback Solarium path when rendering UI. Can fix broken or glitchy system UI on some iOS 27 devices."),
       min_version="27.0"),
    _t(TweakID.IgnoreSolariumHardwareCheck, Section.LIQUID_GLASS, "Ignore Solarium Hardware Check", GP, "com.apple.SwiftUI.IgnoreSolariumHardwareCheck",
       description=QT_TRANSLATE_NOOP("Nugget", "Disables the hardware capability check for Solarium, enabling Liquid Glass effects on devices officially considered too weak."),
       min_version="27.0"),
    _t(TweakID.IgnoreSolariumOptOut, Section.LIQUID_GLASS, "Ignore Solarium Opt-Out", GP, "com.apple.SwiftUI.IgnoreSolariumOptOut",
       description=QT_TRANSLATE_NOOP("Nugget", "Ignores the system opt-out flag for Solarium, re-enabling Liquid Glass on devices or firmware that have it switched off."),
       min_version="27.0"),
    _t(TweakID.DisallowGlassButtons, Section.LIQUID_GLASS, "Disallow Glass Buttons", GP, "SBDisallowGlassButtons",
       description=QT_TRANSLATE_NOOP("Nugget", "Prevents the Liquid Glass material from being applied to system buttons, keeping the old solid button style."),
       min_version="27.0"),
    _t(TweakID.DisallowGlassLockScreen, Section.LIQUID_GLASS, "Disallow Glass Lock Screen", GP, "SBDisallowGlassLockScreen",
       description=QT_TRANSLATE_NOOP("Nugget", "Prevents the Liquid Glass material from being applied to the Lock Screen, keeping the old lock screen look."),
       min_version="27.0"),
    _t(TweakID.DisableSpecularEverywhere, Section.LIQUID_GLASS, "Disable Specular Everywhere", GP, "SBDisableSpecularEverywhere",
       description=QT_TRANSLATE_NOOP("Nugget", "Disables the specular (glossy reflection) rendering everywhere, removing the shiny glass highlight from Liquid Glass surfaces."),
       min_version="27.0"),
    _t(TweakID.NoLiquidClock, Section.LIQUID_GLASS, "Disable Liquid Glass on LS Clock", GP, "SBDisallowGlassTime",
       description=QT_TRANSLATE_NOOP("Nugget", "Renders the Lock Screen clock in the old solid style instead of with the Liquid Glass / dew effect."),
       min_version="26.0"),
    _t(TweakID.NoLiquidDock, Section.LIQUID_GLASS, "Disable Liquid Glass on Dock", GP, "SBDisableGlassDock",
       description=QT_TRANSLATE_NOOP("Nugget", "Renders the Home Screen dock in the old solid style instead of with the Liquid Glass material."),
       min_version="26.0"),
    _t(TweakID.DisableSpecularMotion, Section.LIQUID_GLASS, "Disable Specular Motion", GP, "SBDisableSpecularEverywhereUsingLSSAssertion",
       description=QT_TRANSLATE_NOOP("Nugget", "Disables the motion-based specular effect on the Lock Screen, so the moving light reflection no longer shifts as you tilt your device."),
       min_version="26.0"),
    _t(TweakID.DisableOuterRefraction, Section.LIQUID_GLASS, "Disable Outer Refraction", GP, "SolariumDisableOuterRefraction",
       description=QT_TRANSLATE_NOOP("Nugget", "Disables the outer refraction (the liquid bending of content at the glass edge) for a cleaner, less distorted look."),
       min_version="26.0"),
    _t(TweakID.DisableSolariumHDR, Section.LIQUID_GLASS, "Disable Solarium HDR", GP, "SolariumAllowHDR", value=False,
       description=QT_TRANSLATE_NOOP("Nugget", "Disables HDR tone-mapping in the Solarium renderer. Can fix washed-out or over-bright Liquid Glass areas. Enabled when the switch is OFF."),
       min_version="26.0"),

    # --- SpringBoard ---
    _t(TweakID.LockScreenFootnote, Section.SPRINGBOARD, "Lock Screen Footnote Text",
       FileLocation.footnote, "LockScreenFootnote", value="", kind=Kind.TEXT,
       description=QT_TRANSLATE_NOOP("Nugget", "Sets custom text shown at the bottom of the Lock Screen below the time. Long text is cut off — keep it short. Leave empty to remove.")),
    _t(TweakID.WatchOSCompatibility, Section.SPRINGBOARD, "Allow pairing with any watchOS version",
       FileLocation.nanoregistry, "", factory=_watchos_compatibility, ipad_only=True,
       description=QT_TRANSLATE_NOOP("Nugget", "Removes the minimum watchOS pairing check in NanoRegistry so you can pair an Apple Watch running any watchOS version with your iPhone.")),
    _t(TweakID.AirDropDisableTimeLimit, Section.SPRINGBOARD, "Disable AirDrop Time Limit for Everyone Option",
       FileLocation.airdrop, "OverrideTimeLimitEveryoneMode",
       description=QT_TRANSLATE_NOOP("Nugget", "Unlocks the hidden 'Everyone' AirDrop receiving option that would normally be limited to a 10-minute time window.")),
    _t(TweakID.SBDontLockAfterCrash, Section.SPRINGBOARD, "Disable Lock After Respring",
       FileLocation.springboard, "SBDontLockAfterCrash",
       description=QT_TRANSLATE_NOOP("Nugget", "Prevents the screen from locking right after a respring — the phone won't ask for a passcode immediately after the UI reloads.")),
    _t(TweakID.SBDontDimOrLockOnAC, Section.SPRINGBOARD, "Disable Screen Dimming While Charging",
       FileLocation.springboard, "SBDontDimOrLockOnAC",
       description=QT_TRANSLATE_NOOP("Nugget", "Stops the display from auto-dimming while the device is connected to a charger.")),
    _t(TweakID.SBHideLowPowerAlerts, Section.SPRINGBOARD, "Disable Low Battery Alerts",
       FileLocation.springboard, "SBHideLowPowerAlerts",
       description=QT_TRANSLATE_NOOP("Nugget", "Suppresses the 'Low Battery — 20% / 10%' system alerts.")),
    _t(TweakID.SBHideACPower, Section.SPRINGBOARD, "Hide AC Power on Lock Screen",
       FileLocation.springboard, "SBHideACPower",
       description=QT_TRANSLATE_NOOP("Nugget", "Hides the charging status from the Lock Screen while the device is plugged into AC power.")),
    _t(TweakID.SBNeverBreadcrumb, Section.SPRINGBOARD, "Disable Breadcrumbs",
       FileLocation.springboard, "SBNeverBreadcrumb",
       description=QT_TRANSLATE_NOOP("Nugget", "Disables the 'Return to <App>' breadcrumb button that appears in the status bar after opening a link from another app.")),
    _t(TweakID.SBShowSupervisionTextOnLockScreen, Section.SPRINGBOARD, "Show Supervision Text on Lock Screen",
       FileLocation.springboard, "SBShowSupervisionTextOnLockScreen",
       description=QT_TRANSLATE_NOOP("Nugget", "Shows the device-supervision text on the Lock Screen, like the '<Device> is supervised by <org>' label seen on MDM-managed devices.")),
    _t(TweakID.AirplaySupport, Section.SPRINGBOARD, "Enable AirPlay support for Stage Manager",
       FileLocation.springboard, "SBExtendedDisplayOverrideSupportForAirPlayAndDontFileRadars",
       description=QT_TRANSLATE_NOOP("Nugget", "Adds extended-display AirPlay support for Stage Manager so apps and external displays can use the feature more broadly.")),
    _t(TweakID.SBMinimumLockscreenIdleTime, Section.SPRINGBOARD, "Auto‑Lock (Lock Screen)",
       FileLocation.springboard, "SBMinimumLockscreenIdleTime", value=5, kind=Kind.NUMBER,
       min_value=0, max_value=600,
       description=QT_TRANSLATE_NOOP("Nugget", "Sets how many minutes of inactivity before the Lock Screen turns the display off. 0 = never auto-lock.")),
    _t(TweakID.SBAlwaysShowSystemApertureInSnapshots, Section.SPRINGBOARD, "Show Dynamic Island in Screenshots",
       FileLocation.springboard, "SBAlwaysShowSystemApertureInSnapshots", min_version="17.4", iphone_only=True,
       description=QT_TRANSLATE_NOOP("Nugget", "Forces the Dynamic Island to appear in screenshots instead of being hidden or shrunk while the screenshot is taken.")),
    _t(TweakID.HideDICompletely, Section.SPRINGBOARD, "Hide Dynamic Island Completely",
       FileLocation.springboard, "SBSuppressDynamicIslandCompletely", min_version="17.4", iphone_only=True,
       description=QT_TRANSLATE_NOOP("Nugget", "Suppresses the Dynamic Island cutout completely so it is never drawn. Can make the screen look odd on devices with a pill cutout.")),
    _t(TweakID.SBShowAuthenticationEngineeringUI, Section.SPRINGBOARD, "Show Red/Green Authentication Line on Lock Screen",
       FileLocation.springboard, "SBShowAuthenticationEngineeringUI",
       description=QT_TRANSLATE_NOOP("Nugget", "Shows a red/green authentication progress indicator on the Lock Screen while Face ID or passcode checks are running (engineering debug UI).")),
    _t(TweakID.UseFloatingTabBar, Section.SPRINGBOARD, "Disable Floating Tab Bar",
       FileLocation.uikit, "UseFloatingTabBar", value=False, ipad_only=True,
       description=QT_TRANSLATE_NOOP("Nugget", "Uses the old fixed tab bar style instead of the floating tab bar on iPad. Enabled when the switch is OFF.")),

    # --- Internal Options ---
    _t(TweakID.SBBuildNumber, Section.INTERNAL, "Show Build Version in Status Bar", GP, "UIStatusBarShowBuildVersion",
       description=QT_TRANSLATE_NOOP("Nugget", "Displays the iOS build number (e.g. 21A5284a) in the status bar next to the iOS version.")),
    _t(TweakID.RTL, Section.INTERNAL, "Force Right-to-Left Layout", GP, "NSForceRightToLeftWritingDirection",
       description=QT_TRANSLATE_NOOP("Nugget", "Forces a right-to-left layout for the entire system, mirroring the UI as if your primary language were RTL.")),
    _t(TweakID.LTR, Section.INTERNAL, "Force Left-to-Right Layout", GP, "NSForceLeftToRightWritingDirection",
       description=QT_TRANSLATE_NOOP("Nugget", "Forces a left-to-right layout across the whole system regardless of the RTL language setting.")),
    _t(TweakID.SBIconVisibility, Section.INTERNAL, "Show Hidden Icons on Home Screen", GP, "SBIconVisibility",
       description=QT_TRANSLATE_NOOP("Nugget", "Reveals hidden or disabled Home Screen icons, including internal placeholder icons that are normally not drawn.")),
    _t(TweakID.iMessageDiagnosticsEnabled, Section.INTERNAL, "iMessage Debugging", GP, "iMessageDiagnosticsEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Enables the iMessage engineering debug menu / diagnostics inside the Messages app.")),
    _t(TweakID.IDSDiagnosticsEnabled, Section.INTERNAL, "Continuity Debugging", GP, "IDSDiagnosticsEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Enables the Continuity engineering debug diagnostics in Settings (Apple ID and related sections).")),
    _t(TweakID.VCDiagnosticsEnabled, Section.INTERNAL, "FaceTime Debugging", GP, "VCDiagnosticsEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Enables FaceTime / VoIP engineering debug diagnostics.")),
    _t(TweakID.AccessoryDeveloperEnabled, Section.INTERNAL, "Show Accessory Developer Settings", GP, "AccessoryDeveloperEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Adds a hidden Accessory Developer settings page to the Settings app for testing accessories.")),
    _t(TweakID.DisableSecondsHand, Section.INTERNAL, "Disable Clock Icon Seconds Hand", GP, "SBDisableClockIconSecondsHand",
       description=QT_TRANSLATE_NOOP("Nugget", "Stops the animated second hand on the Clock app's Home Screen icon.")),
    _t(TweakID.DisableSearchingWebsites, Section.INTERNAL, "Disable Spotlight Searching in Websites", GP, "SBSearchDisabledDomains",
       description=QT_TRANSLATE_NOOP("Nugget", "Removes website / web search results from Spotlight search suggestions.")),
    _t(TweakID.ShowButtonHints, Section.INTERNAL, "Show Hardware Button Hints in Screenshots", GP, "SBHardwareButtonHintDropletsAlwaysVisibleInSnapshots",
       description=QT_TRANSLATE_NOOP("Nugget", "Shows the side button / action button hint labels in screenshots (engineering debug UI).")),
    _t(TweakID.AppStoreDebug, Section.INTERNAL, "App Store Debug Gesture", FileLocation.appStore, "debugGestureEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Enables the hidden debug gesture in the App Store app, used to dump store data and inspect the store backend.")),
    _t(TweakID.NotesDebugMode, Section.INTERNAL, "Notes Debug Mode", FileLocation.notes, "DebugModeEnabled",
       description=QT_TRANSLATE_NOOP("Nugget", "Turns on the Notes app debug menu for engineering debugging.")),
    _t(TweakID.BKDigitizerVisualizeTouches, Section.INTERNAL, "Show Touches With Debug Info", FileLocation.backboardd, "BKDigitizerVisualizeTouches",
       description=QT_TRANSLATE_NOOP("Nugget", "Visually marks every touch point on the screen with debugging information as you touch. Great for diagnosing touch issues.")),
    _t(TweakID.BKHideAppleLogoOnLaunch, Section.INTERNAL, "Hide Respring Icon", FileLocation.backboardd, "BKHideAppleLogoOnLaunch",
       description=QT_TRANSLATE_NOOP("Nugget", "Hides the Apple logo animation during respring, showing a black screen instead until the UI comes back.")),
    _t(TweakID.EnableWakeGestureHaptic, Section.INTERNAL, "Vibrate on Raise-to-Wake", FileLocation.coreMotion, "EnableWakeGestureHaptic",
       description=QT_TRANSLATE_NOOP("Nugget", "Plays a Taptic Engine vibration when the device wakes via the raise-to-wake gesture.")),
    _t(TweakID.PlaySoundOnPaste, Section.INTERNAL, "Play Sound on Paste", FileLocation.pasteboard, "PlaySoundOnPaste",
       description=QT_TRANSLATE_NOOP("Nugget", "Plays a sound every time content is pasted anywhere on the device.")),
    _t(TweakID.AnnounceAllPastes, Section.INTERNAL, "Show Notifications for System Pastes", FileLocation.pasteboard, "AnnounceAllPastes",
       description=QT_TRANSLATE_NOOP("Nugget", "Shows a system notification whenever an app reads the pasteboard, acting as a privacy indicator for system-level pastes.")),
)

SPECS_BY_SECTION = {section: [s for s in SPECS if s.section == section] for section in Section}
SPECS_BY_ID = {spec.id: spec for spec in SPECS}