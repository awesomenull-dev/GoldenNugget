from enum import Enum, auto

class TweakID(Enum):
    # tweaks page
    PosterBoard = auto()
    Templates = auto()
    StatusBar = auto()

    # springboard
    LockScreenFootnote = auto()
    WatchOSCompatibility = auto()
    AirDropDisableTimeLimit = auto()
    SBDontLockAfterCrash = auto()
    SBDontDimOrLockOnAC = auto()
    SBHideLowPowerAlerts = auto()
    SBHideACPower = auto()
    SBNeverBreadcrumb = auto()
    SBShowSupervisionTextOnLockScreen = auto()
    AirplaySupport = auto()
    SBMinimumLockscreenIdleTime = auto()
    SBAlwaysShowSystemApertureInSnapshots = auto()
    HideDICompletely = auto()
    SBShowAuthenticationEngineeringUI = auto()
    UseFloatingTabBar = auto()
    SBDisableIconParallax = auto()

    # internal
    SBBuildNumber = auto()
    RTL = auto()
    LTR = auto()
    SBIconVisibility = auto()
    MetalForceHudEnabled = auto()
    iMessageDiagnosticsEnabled = auto()
    IDSDiagnosticsEnabled = auto()
    VCDiagnosticsEnabled = auto()
    AccessoryDeveloperEnabled = auto()

    DisableSecondsHand = auto()
    DisableSearchingWebsites = auto()
    ShowButtonHints = auto()

    AppStoreDebug = auto()
    NotesDebugMode = auto()
    BKDigitizerVisualizeTouches = auto()
    BKHideAppleLogoOnLaunch = auto()
    EnableWakeGestureHaptic = auto()
    PlaySoundOnPaste = auto()
    AnnounceAllPastes = auto()

    # liquid glass
    ForceSolariumFallback = auto()
    DisableSolarium = auto()
    IgnoreSolariumLinkedOnCheck = auto()
    NoLiquidClock = auto()
    NoLiquidDock = auto()
    DisableSpecularMotion = auto()
    DisableOuterRefraction = auto()
    DisableSolariumHDR = auto()
    # iOS 27 additions
    DisallowGlassButtons = auto()
    DisallowGlassLockScreen = auto()
    ForceEnhancedSpeculars = auto()
    ForceSolariumIntelligence = auto()
    UISolariumFallback = auto()
    IgnoreSolariumHardwareCheck = auto()
    IgnoreSolariumOptOut = auto()
    DisableSpecularEverywhere = auto()
    # SpringBoard home-screen glass family (same preference table as the keys
    # above; read by SpringBoard from com.apple.springboard, all Bool)
    DisableWidgetSpecular = auto()
    DisableDockSpecular = auto()
    DisableFolderSpecular = auto()
    ExcludeClearGlassShadows = auto()
    ExcludeDockShadow = auto()
    ExcludeSearchShadow = auto()
    UseFlatIconsEverywhere = auto()

    # daemons
    Daemons = auto()
    ClearScreenTimeAgentPlist = auto()