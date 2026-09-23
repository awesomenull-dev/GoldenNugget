from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from pymobiledevice3.ca import create_keybag_file
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

def skip_setup_panes() -> list:
    """Resolve the exact ``SkipSetup`` pane list: every pane is skipped,
    Apple ID sign-in included. Keeps ``SKIP_ALL_PANES`` as the canonical list.
    """
    return list(SKIP_ALL_PANES)


async def skip_all_setup27(ld: LockdownClient, udid: str | None = None,
                           supervised: bool = False,
                           organization_name: str = ""):
    async with MobileConfigService(lockdown=ld) as mcs:
        cloud_config = await mcs.get_cloud_configuration() or {}
        cloud_config['SkipSetup'] = skip_setup_panes()
        cloud_config["AllowPairing"] = True
        cloud_config["ConfigurationWasApplied"] = True
        cloud_config["CloudConfigurationUIComplete"] = True
        cloud_config["IsSupervised"] = False
        cloud_config["ConfigurationSource"] = 0
        cloud_config["PostSetupProfileWasInstalled"] = True
        if supervised:
            cloud_config["IsSupervised"] = True
            # create/add the keybag
            if organization_name:
                with TemporaryDirectory() as temp_dir:
                    keybag_file = Path(temp_dir) / 'keybag'
                    create_keybag_file(keybag_file, organization_name)
                    cer = x509.load_pem_x509_certificate(keybag_file.read_bytes())
                    public_key = cer.public_bytes(Encoding.DER)
                    # make sure the mdm is removable
                    cloud_config["OrganizationName"] = organization_name
                    cloud_config['OrganizationMagic'] = str(uuid4())
                    cloud_config['IsMDMUnremovable'] = False
                    cloud_config['SupervisorHostCertificates'] = [public_key]
            else:
                # remove keybag info
                if 'OrganizationMagic' in cloud_config:
                    cloud_config.pop('OrganizationMagic')
                if 'SupervisorHostCertificates' in cloud_config:
                    cloud_config.pop('SupervisorHostCertificates')
        await mcs.set_cloud_configuration(cloud_config)
