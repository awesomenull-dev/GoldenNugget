from enum import Enum


# Daemons that must never be disabled — disabling them bootloops the device.
# Kept empty by design; entries are removed from the codebase entirely rather
# than blocked at runtime.
DANGEROUS_DAEMONS: set["Daemon"] = set()  # filled below, after the class definition
DANGEROUS_KEYS = frozenset()

class Daemon(Enum):
    OTA = [
        "com.apple.mobile.softwareupdated",
        "com.apple.OTATaskingAgent",
        "com.apple.softwareupdateservicesd",
        "com.apple.mobile.NRDUpdated"
    ]
    UsageTrackingAgent = ["com.apple.UsageTrackingAgent"]
    GameCenter = ["com.apple.gamed"]
    ScreenTime = [
        "com.apple.ScreenTimeAgent",
        "com.apple.homed",
        "com.apple.familycircled",
        "com.apple.familynotification",
        "com.apple.asktod"
    ]
    CrashReports = [
        "com.apple.ReportCrash",
        "com.apple.ReportCrash.Jetsam",
        "com.apple.ReportMemoryException",
        "com.apple.OTACrashCopier",
        "com.apple.analyticsd",
        "com.apple.wifianalyticsd",
        "com.apple.aslmanager",
        "com.apple.coresymbolicationd",
        "com.apple.crash_mover",
        "com.apple.crashreportcopymobile",
        "com.apple.DumpBasebandCrash",
        "com.apple.DumpPanic",
        "com.apple.logd",
        "com.apple.logd.admin",
        "com.apple.logd.events",
        "com.apple.logd.watchdog",
        "com.apple.logd_helper",
        "com.apple.logd_reporter",
        "com.apple.logd_reporter.report_statistics",
        "com.apple.system.logger",
        "com.apple.hangreporter",
        "com.apple.hangtracerd",
        "com.apple.spindump",
        "com.apple.tailspind",
        "com.apple.rtcreportingd",
        "com.apple.syslogd",
        "com.apple.signpost.signpost_reporter",
        "com.apple.pluginkit.pkreporter",
        "com.apple.ProxiedCrashCopier",
        "com.apple.ProxiedCrashCopier.ProxyingDevice",
        "com.apple.ReportSystemMemory"
    ]
    Diagnostics = [
        "com.apple.diagnosticd",
        "com.apple.diagnosticextensionsd",
        "com.apple.diagnosticservicesd",
        "com.apple.diagnosticspushd",
        "com.apple.symptomsd-diag",
        "com.apple.sysdiagnose",
        "com.apple.sysdiagnose.darwinos",
        "com.apple.sysdiagnose_helper"
    ]
    ATWAKEUP = ["com.apple.atc.atwakeup"]
    Tips = ["com.apple.tipsd"]
    VPN = ["com.apple.racoon"]
    Location = ["com.apple.locationd"]
    ChineseLAN = [
        "com.apple.wapic",
        "com.apple.wifi.wapic"
    ]
    AssistiveTouch = ["com.apple.assistivetouchd"]
    iCloud = ["com.apple.itunescloudd"]
    InternetTethering = ["com.apple.MobileInternetSharing"]
    PassBook = ["com.apple.passd"]
    Spotlight = [
        "com.apple.searchd",
        "com.apple.corespotlightservice",
        "com.apple.spotlightknowledged",
        "com.apple.spotlightknowledged.updater",
        "com.apple.spotlight.IndexAgent"
    ]
    NanoTimeKit = ["com.apple.nanotimekitcompaniond"]
    FollowUp = ["com.apple.followupd"]
    # --- Safe additions (from MiniVoidyy/GoldenNugget-) grouped by function.
    # Only daemons whose disable is safe and not already removed/disabled by iOS.
    AppleAds = [
        "com.apple.promotedcontentd",
        "com.apple.adprivacyd",
        "com.apple.adservicesd"
    ]
    News = ["com.apple.newsd"]
    AskPermissions = ["com.apple.askpermissiond"]
    FamilySharing = [
        "com.apple.familycircled",
        "com.apple.familynotificationd"
    ]
    VideoSubscriptions = ["com.apple.videosubscriptionsd"]
    WebBookmarks = ["com.apple.webbookmarksd"]
    AppleWatchNano = [
        "com.apple.nanoregistryd",
        "com.apple.nanomediacontrold",
        "com.apple.nanopreferencesd"
    ]
    SiriServices = [
        "com.apple.siriactionsd",
        "com.apple.siriinferenced",
        "com.apple.assistant.intentdaemon"
    ]
    Feedback = ["com.apple.feedbackd"]
    Commerce = ["com.apple.commerce"]
    Automount = ["com.apple.automountd"]
    WifiLogging = ["com.apple.wifilogd"]
    Maps = ["com.apple.geod"]
    SafariSuggestions = ["com.apple.parsecd"]
    Shazam = ["com.apple.shazamd"]
    SettingsStats = ["com.apple.settings-statsd"]
    StatusKit = ["com.apple.statuskit"]
    Reminders = ["com.apple.reminderd"]
    AirPlay = ["com.apple.airplay"]
    GameKitService = ["com.apple.gamekitservice"]
    Sidecar = ["com.apple.sidecarcore"]
    SpeechRecognition = ["com.apple.speechrecognition"]
    Translate = ["com.apple.translated"]
    MockLocation = ["com.apple.mocksynclocationd"]
    DeviceCheck = ["com.apple.devicecheckd"]


# Danger list fills in now that the class is defined.
DANGEROUS_DAEMONS: set["Daemon"] = set()
DANGEROUS_KEYS = frozenset(k for d in DANGEROUS_DAEMONS for k in d.value)
