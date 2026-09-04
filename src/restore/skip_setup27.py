from pymobiledevice3.lockdown import create_using_usbmux, LockdownClient
from pymobiledevice3.services.mobile_config import MobileConfigService

# Canonical list of setup panes to mark as skipped. This is the single source of
# truth for every skip-setup path:
#   - the standalone CLI (skip_setup.py)
#   - the iOS 27 Phase-4 sweep (skip_all_setup27 below)
#   - the iOS 26 cloud-config path (device_manager.add_skip_setup)
# It is the union of the curated iOS 27 list and the older iOS 26 list so no pane
# is lost on either OS (an identifier that is unknown to a given iOS is a no-op).
# Keep the list here and never fork a copy.
SKIP_ALL_PANES = [
    'Location',
    'Restore',
    'SIMSetup',
    'Android',
    'AppleID',
    'IntendedUser',
    'TOS',
    'Siri',
    'ScreenTime',
    'Diagnostics',
    'SoftwareUpdate',
    'Passcode',
    'Biometric',
    'Payment',
    'Zoom',
    'DisplayTone',
    'MessagingActivationUsingPhoneNumber',
    'HomeButtonSensitivity',
    'CloudStorage',
    'ScreenSaver',
    'TapToSetup',
    'Keyboard',
    'PreferredLanguage',
    'SpokenLanguage',
    'WatchMigration',
    'OnBoarding',
    'TVProviderSignIn',
    'TVHomeScreenSync',
    'Privacy',
    'TVRoom',
    'iMessageAndFaceTime',
    'AppStore',
    'Safety',
    'Multitasking',
    'ActionButton',
    'Intelligence',
    'CameraButton',
    'TermsOfAddress',
    'AccessibilityAppearance',
    'Welcome',
    'Appearance',
    'RestoreCompleted',
    'UpdateCompleted',
    'WiFi',
    'Display',
    'Tone',
    'TouchID',
    'TrueToneDisplay',
    'FileVault',
    'iCloudStorage',
    'iCloudDiagnostics',
    'Registration',
    'DeviceToDeviceMigration',
    'UnlockWithWatch',
    'Accessibility',
    'All',
    'Avatar',
    'DeviceProtection',
    'Key',
    'LockdownMode',
    'Wallpaper',
    'PrivacySubtitle',
    'SecuritySubtitle',
    'DataSubtitle',
    'AppleIDSubtitle',
    'AppearanceSubtitle',
    'OnboardingSubtitle',
    'AppleTVSubtitle',
    'WebContentFiltering',
    'AdditionalPrivacySettings',
    'EnableLockdownMode',
    'OSShowcase',
    'SafetyAndHandling',
    'Tips',
]

async def skip_all_setup27(ld: LockdownClient, udid: str | None = None):
    async with MobileConfigService(lockdown=ld) as mcs:
        cloud_config = await mcs.get_cloud_configuration() or {}
        cloud_config['SkipSetup'] = list(SKIP_ALL_PANES)
        await mcs.set_cloud_configuration(cloud_config)
