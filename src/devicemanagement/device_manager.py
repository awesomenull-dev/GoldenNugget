import asyncio
import os.path
import plistlib
import sys
import traceback

from tempfile import TemporaryDirectory
from typing import Optional
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from uuid import uuid4

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QSettings, QCoreApplication

from packaging.version import Version

from pymobiledevice3 import usbmux
from pymobiledevice3.ca import create_keybag_file
from pymobiledevice3.services.mobile_config import MobileConfigService
from pymobiledevice3.exceptions import MuxException, PasswordRequiredError, ConnectionTerminatedError, AccessDeniedError, InvalidServiceError
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
import pymobiledevice3.service_connection as _sc


from src.devicemanagement.session import lockdown_session
from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
from src.controllers.hotload import HotLoad
from src.restore.skip_setup27 import SKIP_ALL_PANES

# Bump SSL handshake timeout from 10s to 60s for all lockdown services.
_sc.DEFAULT_SSL_HANDSHAKE_TIMEOUT = 60

# Temporarily allow writing up to this many PosterBoard tendies in a single
# restore. Applying more than one tendie at once can race PosterBoard's sqlite
# regeneration, so the count is capped.
MAX_TENDIES_PER_RESTORE = 3

from src.devicemanagement.constants import Device, Version, is_supported_by_fork
from src.devicemanagement.data_singleton import DataSingleton
from .preference_manager import PreferenceManager

from src.gui.thread_workers.apply_worker import ApplyAlertMessage
from src.gui.pages.pages_list import Page
from src.controllers.path_handler import fix_windows_path

from src.exceptions.nugget_exception import NuggetException

from src.tweaks.tweaks import tweaks, TweakID, BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak, StatusBarTweak
from src.tweaks.posterboard.posterboard_tweak import PosterboardTweak
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.tweaks.basic_plist_locations import FileLocation

from src.restore.restore import restore_files, FileToRestore
from src.restore.original_plist import psysbackup, materialize_plist, is_empty_plist, mobile_user_fallback_path
from src.restore.protective import log_info, log_warn

def get_files_list_str(files_list: list[FileToRestore] = None) -> str:
    files_str: str = ""
    if files_list != None:
        files_str = "FILES LIST:"
        print("\nFile List:\n")
        for file in files_list:
            file_info = f"\n    Domain: {file.domain}\n    Path: {file.restore_path}"
            files_str += file_info
            print(file_info)
    return files_str

def show_apply_error(e: Exception, update_label=lambda x: None, files_list: list[FileToRestore] = None):
    print(traceback.format_exc())
    update_label("Failed to restore")
    if "Find My" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("Find My must be disabled in order to use this tool."),
                       detailed_txt=QCoreApplication.tr("Disable Find My from Settings (Settings -> [Your Name] -> Find My) and then try again."))
    elif "Encrypted Backup MDM" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("Nugget cannot be used on this device. Click Show Details for more info."),
                       detailed_txt=QCoreApplication.tr("Your device is managed and MDM backup encryption is on. This must be turned off in order for Nugget to work. Please do not use Nugget on your school/work device!"))
    elif "SessionInactive" in str(e) or "ConnectionAbortedError" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("The session was terminated. Refresh the device list and try again."))
    elif "PasswordRequiredError" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("Device is password protected! You must trust the computer on your device."),
                       detailed_txt=QCoreApplication.tr("Unlock your device. On the popup, click \"Trust\", enter your password, then try again."))
    elif isinstance(e, ConnectionTerminatedError):
        files_str: str = get_files_list_str(files_list)
        return ApplyAlertMessage(QCoreApplication.tr("Device failed in sending files. The file list is possibly corrupted or has duplicates. Click Show Details for more info."),
                                 detailed_txt=files_str + "TRACEBACK:\n\n" + str(traceback.format_exc()))
    elif isinstance(e, AccessDeniedError):
        return ApplyAlertMessage(QCoreApplication.tr("Access denied while sending files."), detailed_txt="Try running the program with sudo.")
    elif isinstance(e, InvalidServiceError):
        return ApplyAlertMessage(QCoreApplication.tr("You must enable developer mode on your device. You can do it in the Settings app."),
                                 detailed_txt=QCoreApplication.tr("Applying tweaks requires developer mode.\n\nYou can enable this at the bottom of Settings > Privacy & Security > Developer Mode on your iPhone or iPad."))
    elif isinstance(e, NuggetException):
        return ApplyAlertMessage(str(e), detailed_txt=e.detailed_text)
    else:
        files_str: str = get_files_list_str(files_list)
        error_msg = type(e).__name__ + ": " + repr(e)
        # Check if this is a protective backup failure with a backup path
        backup_path = None
        error_str = str(e)
        if "protective backup kept at:" in error_str:
            import re
            match = re.search(r'protective backup kept at:\s*(\S+)', error_str)
            if match:
                backup_path = match.group(1)
        return ApplyAlertMessage(
            error_msg, 
            detailed_txt=files_str + "TRACEBACK:\n\n" + str(traceback.format_exc()),
            backup_path=backup_path
        )

class DeviceManager:
    ## Class Functions
    def __init__(self):
        self.devices: list[Device] = []
        self.data_singleton = DataSingleton()
        self.current_device_index = 0

        # preferences
        self.pref_manager = PreferenceManager(None)
        
        # Backup password (for encrypted backups)
        self._backup_password: Optional[str] = None

        # Set when the user chose to continue without data protection (e.g.
        # out of disk space) — Phase 1 must not re-run the protective backup.
        self._protective_backup_skipped = False
        
        # Test mode
        self._test_mode = "--test-mode" in sys.argv
    
    def _get_backup_password(self) -> str:
        """Get backup password from settings or return empty string."""
        if self._backup_password:
            return self._backup_password
        # Try to get from settings
        if self.pref_manager.settings:
            pwd = self.pref_manager.settings.value("backup_password", "", type=str)
            if pwd:
                self._backup_password = pwd
                return pwd
        return ""
    
    def get_devices(self, settings: QSettings, show_alert=lambda x: None):
        # Guard against an unresponsive usbmuxd/lockdown hang blocking startup
        # forever. Enumeration of a handful of devices is normally near-instant,
        # so 60s is a generous ceiling.
        try:
            asyncio.run(asyncio.wait_for(self._get_devices(settings, show_alert), timeout=60))
        except asyncio.TimeoutError:
            show_alert(ApplyAlertMessage(
                txt=QCoreApplication.tr("Getting the device list timed out."),
                detailed_txt=QCoreApplication.tr(
                    "Device enumeration took too long. Check your USB connection and try again.")
            ))
    async def _get_devices(self, settings: QSettings, show_alert=lambda x: None):
        # Test mode: use mock device already set up in main_app.py
        if self._test_mode:
            self.pref_manager.settings = settings
            return
        
        self.devices.clear()
        # handle errors when failing to get connected devices
        try:
            connected_devices = await usbmux.list_devices()
        except Exception:
            sysmsg = QCoreApplication.tr("If you are on Linux, make sure you have usbmuxd and libimobiledevice installed.")
            if os.name == 'nt':
                sysmsg = QCoreApplication.tr("Make sure you have the \"Apple Devices\" app from the Microsoft Store or iTunes from Apple's website.")
            show_alert(ApplyAlertMessage(
                txt=QCoreApplication.tr("Failed to get device list. Click \"Show Details\" for the traceback.") + f"\n\n{sysmsg}", detailed_txt=str(traceback.format_exc())
            ))
            self.set_current_device(index=None)
            return
        # Connect via usbmuxd
        for device in connected_devices:
            try:
                async with lockdown_session(device.serial) as ld:
                    # Check backup encryption status if experimental option not enabled
                    if not self.pref_manager.use_encrypted_backup:
                        try:
                            from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
                            mb = Mobilebackup2Service(ld)
                            await mb.connect()
                            is_encrypted = await mb.get_will_encrypt()
                            await mb.close()
                            if is_encrypted:
                                show_alert(ApplyAlertMessage(
                                    txt=QCoreApplication.tr("Backup encryption is enabled on your iPhone."),
                                    detailed_txt=QCoreApplication.tr(
                                        "GoldenNugget needs to temporarily disable backup encryption to apply tweaks safely.\n\n"
                                        "Please choose one:\n"
                                        "1. Disable encryption on your iPhone: Settings → General → Transfer or Reset iPhone → Backup Password → Turn Off\n"
                                        "2. Or enable \"Use Encrypted Backups (Experimental)\" in GoldenNugget Settings → enter your backup password when prompted.\n\n"
                                        "Tip: Option 1 is simpler if you don't know your backup password."
                                    )
                                ))
                                self.set_current_device(index=None)
                                return
                        except Exception:
                            pass  # If we can't check, continue anyway
                    vals = ld.all_values
                    model = vals['ProductType']
                    hardware = vals['HardwareModel']
                    cpu = vals['HardwarePlatform']
                    try:
                        product_type = settings.value(device.serial + "_model", "", type=str)
                        hardware_type = settings.value(device.serial + "_hardware", "", type=str)
                        cpu_type = settings.value(device.serial + "_cpu", "", type=str)
                        if product_type == "":
                            # save the new product type
                            settings.setValue(device.serial + "_model", model)
                        else:
                            model = product_type
                        if hardware_type == "":
                            # save the new hardware model
                            settings.setValue(device.serial + "_hardware", hardware)
                        else:
                            hardware = hardware_type
                        if cpu_type == "":
                            # save the new cpu model
                            settings.setValue(device.serial + "_cpu", cpu)
                        else:
                            cpu = cpu_type
                    except Exception:
                        show_alert(ApplyAlertMessage(txt=QCoreApplication.tr("Click \"Show Details\" for the traceback."), detailed_txt=str(traceback.format_exc())))
                    locale = await ld.get_locale()
                    dev = Device(
                            udid=device.serial,
                            usb=device.is_usb,
                            name=vals['DeviceName'],
                            version=vals['ProductVersion'],
                            build=vals['BuildVersion'],
                            model=model,
                            hardware=hardware,
                            cpu=cpu,
                            locale=locale,
                        )
                    self.devices.append(dev)
            except PasswordRequiredError as e:
                show_alert(ApplyAlertMessage(txt=QCoreApplication.tr("Device is password protected! You must trust the computer on your device.\n\nUnlock your device. On the popup, click \"Trust\", enter your password, then try again.")))
            except MuxException as e:
                # there is probably a cable issue
                print(f"MUX ERROR with lockdown device with UUID {device.serial}")
                show_alert(ApplyAlertMessage(txt="MuxException: " + repr(e) + "\n\n" + QCoreApplication.tr("If you keep receiving this error, try using a different cable or port."),
                               detailed_txt=str(traceback.format_exc())))
            except Exception as e:
                print(f"ERROR with lockdown device with UUID {device.serial}")
                show_alert(ApplyAlertMessage(txt=f"{type(e).__name__}: {repr(e)}", detailed_txt=str(traceback.format_exc())))
        
        if len(self.devices) > 0:
            self.set_current_device(index=0)
        else:
            self.set_current_device(index=None)

    ## CURRENT DEVICE
    def set_current_device(self, index: int = None):
        if index == None or len(self.devices) == 0:
            self.data_singleton.current_device = None
            self.data_singleton.device_available = False
            self.current_device_index = 0
        else:
            self.data_singleton.current_device = self.devices[index]
            if not is_supported_by_fork(self.devices[index].version):
                # hard-block old versions (< 26.2): the device is listed so the
                # user sees it, but every action is refused.
                self.data_singleton.device_available = False
            else:
                self.data_singleton.device_available = True
            self.current_device_index = index
        
    def get_current_device_name(self) -> str:
        device = self.data_singleton.current_device
        return device.name if device != None else QCoreApplication.tr("No Device")

    def get_current_device_version(self) -> str:
        device = self.data_singleton.current_device
        return device.version if device != None else ""

    def get_current_device_build(self) -> str:
        device = self.data_singleton.current_device
        return device.build if device != None else ""

    def get_current_device_udid(self) -> Optional[str]:
        device = self.data_singleton.current_device
        return device.udid if device != None else None

    def get_current_device_model(self) -> str:
        device = self.data_singleton.current_device
        return device.model if device != None else ""

    def get_current_device_is_supported_by_fork(self) -> bool:
        device = self.data_singleton.current_device
        return is_supported_by_fork(device.version) if device != None else False

    def get_current_device_partially_supported(self) -> bool:
        """iOS 27 devices use the experimental three-phase protective restore."""
        device = self.data_singleton.current_device
        if device == None:
            return False
        try:
            return Version(device.version) >= Version("27.0")
        except Exception:
            return False
        
    def reset_device_pairing(self):
        asyncio.run(self._reset_device_pairing())
    async def _reset_device_pairing(self):
        # first, unpair it
        if self.data_singleton.current_device == None:
            return
        async with lockdown_session(self.data_singleton.current_device.udid) as ld:
            await ld.unpair()
            # next, pair it again
            await ld.pair()
        QMessageBox.information(None, QCoreApplication.tr("Pairing Reset"), QCoreApplication.tr("Your device's pairing was successfully reset. Refresh the device list before applying."))

    async def add_skip_setup(self, files_to_restore: list[FileToRestore], restoring_domains: bool):
        # TODO: Probably should move this to its own file
        if self.pref_manager.skip_setup and restoring_domains:
            # get the already existing cloud config info
            async with lockdown_session(self.data_singleton.current_device.udid) as ld:
                async with MobileConfigService(lockdown=ld) as mcs:
                    cloud_config_plist = await mcs.get_cloud_configuration()
            # add the 2 skip setup files
            cloud_config_plist["SkipSetup"] = list(SKIP_ALL_PANES)
            cloud_config_plist["AllowPairing"] = True
            cloud_config_plist["ConfigurationWasApplied"] = True
            cloud_config_plist["CloudConfigurationUIComplete"] = True
            cloud_config_plist["IsSupervised"] = False
            cloud_config_plist["ConfigurationSource"] = 0
            cloud_config_plist["PostSetupProfileWasInstalled"] = True
            if self.pref_manager.supervised == True:
                cloud_config_plist["IsSupervised"] = True
                # create/add the keybag
                if self.pref_manager.organization_name != None and self.pref_manager.organization_name != "":
                    with TemporaryDirectory() as temp_dir:
                        keybag_file = Path(temp_dir) / 'keybag'
                        create_keybag_file(keybag_file, self.pref_manager.organization_name)
                        cer = x509.load_pem_x509_certificate(keybag_file.read_bytes())
                        public_key = cer.public_bytes(Encoding.DER)
                        # make sure the mdm is removable
                        cloud_config_plist["OrganizationName"] = self.pref_manager.organization_name
                        cloud_config_plist['OrganizationMagic'] = str(uuid4())
                        cloud_config_plist['IsMDMUnremovable'] = False
                        cloud_config_plist['SupervisorHostCertificates'] = [public_key]
                else:
                    # remove keybag info
                    if 'OrganizationMagic' in cloud_config_plist:
                        cloud_config_plist.pop('OrganizationMagic')
                    if 'SupervisorHostCertificates' in cloud_config_plist:
                        cloud_config_plist.pop('SupervisorHostCertificates')
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(cloud_config_plist),
                restore_path="Library/ConfigurationProfiles/CloudConfigurationDetails.plist",
                domain="SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles"
            ))
            purplebuddy_plist: dict = {
                "SetupDone": True,
                "SetupFinishedAllSteps": True
            }
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(purplebuddy_plist),
                restore_path="mobile/com.apple.purplebuddy.plist",
                domain="ManagedPreferencesDomain"
            ))

    def get_domain_for_path(self, path: str, owner: int = 501) -> str:
        # returns Domain: str?, Path: str
        fully_patched = True
        # just make the Sys Containers to use the regular way (won't work for mga)
        sysSharedContainer = "SysSharedContainerDomain-"
        sysContainer = "SysContainerDomain-"
        mappings: dict = {
            "/var/Managed Preferences/": "ManagedPreferencesDomain",
            "/var/root/": "RootDomain",
            "/var/preferences/": "SystemPreferencesDomain",
            "/var/MobileDevice/": "MobileDeviceDomain",
            "/var/mobile/": "HomeDomain",
            "/var/db/": "DatabaseDomain",
            "/var/containers/Shared/SystemGroup/": sysSharedContainer,
            "/var/containers/Data/SystemGroup/": sysContainer
        }
        for mapping in mappings.keys():
            if path.startswith(mapping):
                new_path = path.replace(mapping, "")
                new_domain = mappings[mapping]
                # if patched, include the next part of the path in the domain
                if fully_patched and (new_domain == sysSharedContainer or new_domain == sysContainer):
                    parts = new_path.split("/")
                    new_domain += parts[0]
                    new_path = new_path.replace(parts[0] + "/", "")
                return new_path, new_domain
        return path, ""
    
    def concat_file(self, contents: str, path: str, files_to_restore: list[FileToRestore], owner: int = 501, group: int = 501):
        # TODO: try using inodes here instead
        file_path, domain = self.get_domain_for_path(path, owner=owner)
        files_to_restore.append(FileToRestore(
            contents=contents,
            restore_path=file_path,
            domain=domain,
            owner=owner, group=group
        ))
    
    ## APPLYING OR REMOVING TWEAKS AND RESTORING
    def _raise_if_unsupported(self):
        if not self.get_current_device_is_supported_by_fork():
            raise NuggetException(QCoreApplication.tr(
                "This version of iOS is not supported by this fork.\n\n"
                "GoldenNugget only supports iOS 26.2 and newer. "
                "Please use the original Nugget for iOS 26.1 and earlier."))

    async def start_restore(self, files_to_restore: list[FileToRestore], update_label=lambda x: None, backup_password: str = "", prepared_backup_root: str = None, skip_protective_backup: bool = False, include_keychain: bool = False, prompt_choice=None):
        # hard-block any restore on an unsupported (old) iOS version
        self._raise_if_unsupported()
        self.update_label = update_label
        self.do_not_unplug = ""
        if self.data_singleton.current_device.connected_via_usb:
            self.do_not_unplug = "\n" + QCoreApplication.tr("DO NOT UNPLUG")
        # Use manual try/finally instead of async with so that ld.close()
        # errors (e.g. ConnectionTerminatedError after device reboot) do not
        # propagate as a misleading "Connection Lost" error to the UI.
        # lockdown_session suppresses close() errors the same way.
        async with lockdown_session(self.data_singleton.current_device.udid) as ld:
            update_label(QCoreApplication.tr("Preparing to restore...") + self.do_not_unplug)
            await restore_files(
                files=files_to_restore, reboot=self.pref_manager.auto_reboot,
                lockdown_client=ld,
                progress_callback=self.progress_callback,
                backup_password=backup_password,
                prepared_backup_root=prepared_backup_root,
                skip_protective_backup=skip_protective_backup,
                include_keychain=include_keychain,
                prompt_choice=prompt_choice,
            )
            tweaks[TweakID.PosterBoard].config_manager.save_staged_ids(self.get_current_device_udid())
            msg = QCoreApplication.tr("Your device will now restart.\n\nRemember to turn Find My back on!")
            if not self.pref_manager.auto_reboot:
                msg = QCoreApplication.tr("Please restart your device to see changes.")
            return ApplyAlertMessage(txt=QCoreApplication.tr("All done! ") + msg, title=QCoreApplication.tr("Success!"), icon=QMessageBox.Information)

    def progress_callback(self, progress):
        if self.update_label == None:
            return
        if isinstance(progress, str):
            self.update_label(progress)
            return
        prog = ""
        if progress != None:
            prog = f" ({progress:6.1f}% )"
        self.update_label(QCoreApplication.tr("Restoring to device...{0}{1}").format(prog, self.do_not_unplug))
    def _backup_progress(self, update_label):
        """Progress callback for backup-driven captures (psysbackup).

        Unlike ``progress_callback`` it does not depend on ``self.update_label``
        (only set by ``start_restore``), so it is safe to call before any
        restore has started. Status strings pass through as labels; anything
        that is not a number is dropped so the bar never sees garbage.
        """
        def _cb(progress):
            if isinstance(progress, str):
                update_label(progress)
                return
            if isinstance(progress, bool) or not isinstance(progress, (int, float)):
                return
            update_label(QCoreApplication.tr("Backing up device... ({0:.1f}%)").format(progress))
        return _cb
    def apply_changes(self, update_label=lambda x: None, show_alert=lambda x: None, prompt_password=None, prompt_choice=None):
        asyncio.run(self._apply_changes(update_label, show_alert, prompt_password, prompt_choice))
    async def _apply_changes(self, update_label=lambda x: None, show_alert=lambda x: None, prompt_password=None, prompt_choice=None):
        files_to_restore: list[FileToRestore] = []
        final_alert = None
        pb = tweaks[TweakID.PosterBoard]
        original_tendies = list(pb.tendies)
        try:
            self._raise_if_unsupported()
            update_label(QCoreApplication.tr("Applying changes to files..."))
            self._protective_backup_skipped = False

            # iOS 26.2+ (iOS 27 era) uses the heavy three-phase protective restore
            pb.tendies = original_tendies[:MAX_TENDIES_PER_RESTORE]

            needs_posterboard = not (
                len(pb.tendies) == 0 and pb.videoFile is None
                and len(tweaks[TweakID.Templates].templates) == 0)
            log_info(f'needs_posterboard={needs_posterboard}, tendies={len(pb.tendies)}, videoFile={pb.videoFile is not None}')

            # Phase 0: protective backup.
            #  - iOS 27+ (partial support): the heavy backup is built and later
            #    restored (Phase 1/3) to survive the security-recovery wipe.
            #  - iOS 26.x: the apply is a plain sparse restore (no wipe), so the
            #    backup is only run as a PosterBoard delivery vehicle — it ships
            #    the WAL-merged sqlite to GoldenNugget, then is discarded; the
            #    restore stays the usual raw sparse pass.
            prepared_root = None
            pb_from_cache = False
            partially_supported = self.get_current_device_partially_supported()
            should_prepare = partially_supported or needs_posterboard
            if should_prepare:
                # On NotEnoughDiskSpaceError the user can choose to continue
                # without it — tweaks still apply, but there is no data
                # protection (photos/settings get wiped).
                try:
                    prepared_root, pb_from_cache = await self._prepare_protective_backup(
                        update_label, needs_posterboard=needs_posterboard,
                        prompt_password=prompt_password,
                        force_live=not partially_supported)
                except Exception as e:
                    if "disk space" in str(e).lower() or "NotEnoughDiskSpace" in type(e).__name__:
                        from PySide6.QtWidgets import QMessageBox
                        reply = QMessageBox.question(
                            None,
                            QCoreApplication.tr("Not Enough Disk Space"),
                            QCoreApplication.tr(
                                "The protective backup failed because the device or "
                                "computer does not have enough free disk space.\n\n"
                                "Continue anyway WITHOUT data protection?\n"
                                "(Photos, settings and app data may be lost.)"),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No)
                        if reply == QMessageBox.StandardButton.Yes:
                            log_warn("User chose to continue without protective backup")
                            prepared_root = None
                            pb_from_cache = False
                            self._protective_backup_skipped = True
                        else:
                            return
                    else:
                        raise
                if not partially_supported:
                    # iOS 26: the backup is only used to pull the PosterBoard
                    # sqlite; the restore itself is a plain sparse pass, so the
                    # prepared root must not reach Phase 1/3.
                    log_info("iOS 26.x apply: Phase 0 used only for PosterBoard sqlite "
                             "delivery — proceeding with raw sparse restore")
                    prepared_root = None
            else:
                log_info("Phase 0 skipped: nothing to prepare (no iOS 27 restore, no PosterBoard)")

            # fallback: PosterBoard DB missing from the cache backup (e.g. the
            # device rejected container inclusion) -> legacy separate backup
            if needs_posterboard and not pb_from_cache:
                if os.environ.get("GOLDENNUGGET_SKIP_PB_BACKUP"):
                    log_warn("GOLDENNUGGET_SKIP_PB_BACKUP=1 set; skipping PosterBoard DB fetch")
                else:
                    await self._backup_posterboard_database(update_label, force=True)

            final_alert, files_to_restore = await self._apply_tweak_pass(
                update_label,
                templates=tweaks[TweakID.Templates].templates,
                prepared_backup_root=prepared_root,
                prompt_password=prompt_password,
                prompt_choice=prompt_choice,
                skip_protective_backup=self._protective_backup_skipped,
            )
            update_label(QCoreApplication.tr("Success!"))
        except Exception as e:
            final_alert = show_apply_error(e, update_label, files_list=files_to_restore)
        finally:
            pb.tendies = original_tendies
            show_alert(final_alert)

    async def _prepare_protective_backup(self, update_label=lambda x: None,
                                         needs_posterboard: bool = False,
                                         prompt_password=None,
                                         force_live: bool = False) -> tuple:
        """Phase 0: build the protective backup that Phase 3 will restore.
    
        Two modes:
    
        * LIVE (default): runs a fresh ``perform_protective_backup`` right now,
          always including the PosterBoard container when wallpapers are being
          applied — so ``extract_posterboard_db`` yields the fresh sqlite and the
          config manager builds new wallpapers on top of the current on-device
          state. No caching involved.
    
        * CACHE (EXPERIMENTAL, off by default): reuses/refreshes the persistent
          per-device master ("Use Fast Backup Cache (Experimental)" in Settings).
          When wallpapers are applied the master ALWAYS refreshes first — the
          "reuse as-is" fast path only applies when nothing is pending — so the
          extracted DB is never a stale copy.
    
Returns (PreparedBackup, posterboard_db_ok). When the PosterBoard
        container cannot be read out of the backup the caller falls back to the
        legacy separate ``_backup_posterboard_database``. Returns (None, False)
        only when there is no UDID at all.

        ``force_live`` bypasses the experimental cache and always runs a fresh
        live backup. Used on iOS 26, where the restore is a plain sparse pass —
        the backup is never restored, it only exists to ship a WAL-merged
        PosterBoard sqlite to GoldenNugget.
        """
        udid = self.get_current_device_udid()
        if not udid:
            return None, False
        if force_live:
            log_info("Phase 0: forced live (iOS 26 PosterBoard delivery) — cache bypassed")
    
        from src.restore.protective import (
            PreparedBackup, extract_posterboard_db, is_backup_encrypted,
            new_protective_backup_dir, perform_protective_backup,
            prune_protective_backups)
    
        def _register_pb_db(backup_root: str) -> bool:
            """Extract the fresh PosterBoard sqlite and register it for editing.
    
            Returns False (so the legacy separate backup still runs) when the
            container is missing from the backup or the DB is unusable.
            """
            if not needs_posterboard or os.environ.get("GOLDENNUGGET_SKIP_PB_BACKUP"):
                return True
            import tempfile as _tempfile
            with _tempfile.TemporaryDirectory(prefix="nugget_pbdb_") as tmp_dir:
                db_path = extract_posterboard_db(
                    backup_root, udid, os.path.join(tmp_dir, "posterboard.sqlite3"))
                if db_path is None:
                    log_warn("PosterBoard DB missing from the protective backup — "
                             "falling back to a separate backup")
                    return False
                pb = tweaks[TweakID.PosterBoard]
                try:
                    if not pb.config_manager.update_database_file(db_path, udid):
                        raise NuggetException("The PosterBoard database is not of the correct format!")
                    pb.config_manager.update_for_saved_database(udid)
                    update_label(QCoreApplication.tr("PosterBoard database backed up successfully."))
                except NuggetException as e:
                    log_warn(f"PosterBoard DB unusable ({e}) — falling back to a separate backup")
                    return False
            return True
    
        async def _live_backup(lc, encrypted: bool) -> tuple:
            """Fresh protective backup (no cache) with the PosterBoard container
            riding along whenever wallpapers are about to be applied."""
            # Persistent, one directory per run. Once Phase 2 wipes the device
            # this backup is the ONLY copy of the user's photos, Apple ID and
            # settings, so it must survive a reboot and must never be swept as
            # a temp leftover. A fresh directory per run also means a failed
            # backup cannot damage the previous run's copy.
            backup_root = new_protective_backup_dir(udid)
            prune_protective_backups(udid)
            update_label(QCoreApplication.tr("Backing up device..."))
            await perform_protective_backup(
                lc, backup_root, progress_callback=self._backup_progress(update_label),
                include_photos=True, include_posterboard=needs_posterboard,
                include_keychain=encrypted)
            log_info(f"Phase 0: live protective backup ready (always fresh; "
                     f"PosterBoard container {'included' if needs_posterboard else 'not needed'}; "
                     f"keychain {'included' if encrypted else 'excluded (backup not encrypted)'})")
            prepared = PreparedBackup(root=backup_root, manifest_password="")
            if needs_posterboard and encrypted:
                log_warn("Encrypted backup cannot yield a readable PosterBoard DB — "
                         "falling back to a separate backup")
                return prepared, False
            return prepared, _register_pb_db(backup_root)
    
        cache_enabled = (not force_live
                         and self.pref_manager.use_backup_cache
                         and not os.environ.get("GOLDENNUGGET_NO_BACKUP_CACHE"))
    
        async with lockdown_session(udid) as lc:
            if not cache_enabled:
                log_info("Protective backup cache is an experimental feature and is "
                         "off — running a fresh live protective backup instead")
                return await _live_backup(lc, await is_backup_encrypted(lc))
    
            # --- EXPERIMENTAL cache path ---
            encrypted = await is_backup_encrypted(lc)
            manifest_password = ""
            if encrypted:
                if prompt_password is None:
                    log_info("No password prompt available — bypassing the protective backup cache")
                    return await _live_backup(lc, encrypted)
                update_label(QCoreApplication.tr("Backup encryption is enabled. Enter your backup password to use the fast cached backup:"))
                password = prompt_password(
                    QCoreApplication.tr("Backup Encryption Password"),
                    QCoreApplication.tr("Enter your iTunes/Finder backup password (used locally to prepare the cached backup):"))
                if not password:
                    log_info("No backup password provided — bypassing the protective backup cache")
                    return await _live_backup(lc, encrypted)
                manifest_password = password
                self._backup_password = password  # reuse it for the Phase 3 restore prompt
            from src.restore.protective import CACHE_REFRESH_SECS, ProtectiveBackupCache
            cache = ProtectiveBackupCache(udid, product_version=self.get_current_device_version(),
                                          encrypted=encrypted)
            found = cache.locate()
            # fast path: a fresh cache (no wallpapers pending) is reused as-is —
            # no device session at all; past the TTL it gets an incremental refresh
            if found and not needs_posterboard and found["age_secs"] < CACHE_REFRESH_SECS:
                log_info(f"Cache is {found['age_secs'] // 60} min old — reusing without a backup session")
                master_root = str(cache.master_root)
            else:
                update_label(QCoreApplication.tr("Backing up device (cached)..."))
                master_root = await cache.refresh(
                    lc, progress_callback=self._backup_progress(update_label),
                    include_photos=True, include_posterboard=needs_posterboard,
                    include_keychain=encrypted)
    
            prepared = PreparedBackup(root=master_root, manifest_password=manifest_password)
            if needs_posterboard and encrypted:
                log_warn("Encrypted cache cannot yield a readable PosterBoard DB — "
                         "falling back to a separate backup")
                return prepared, False
            return prepared, _register_pb_db(master_root)

    async def _backup_posterboard_database(self, update_label=lambda x: None, force: bool = False):
        """Fetch the device's PosterBoard sqlite database before applying wallpapers.

        The database (PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3) holds the
        user's current wallpapers. A fresh copy is pulled from the device every
        time a tendie is about to be applied (``force=True``) so the config
        manager always builds on top of the current on-device state. Previously
        fetched copies are only reused when the database is genuinely needed and
        a fresh one isn't required (``force=False``).

        Uses the same mechanism as the "Fetch Database File" wizard
        (``backup_posterboard_database`` in ``src/gui/dialogs/pb_dialog.py``),
        i.e. a full mobilebackup2 backup + Manifest.db lookup. Failure is
        non-fatal: the apply continues and config mode surfaces its own clear
        error later.
        """
        udid = self.get_current_device_udid()
        if not udid:
            return
        # already backed up for this device and no fresh copy required -> reuse it
        if not force and PreferenceManager.has_pbconfig_data(udid):
            return
        pb = tweaks[TweakID.PosterBoard]
        if (len(pb.tendies) == 0 and pb.videoFile is None
                and len(tweaks[TweakID.Templates].templates) == 0):
            # no wallpapers being added, nothing to back up
            return

        update_label(QCoreApplication.tr("Fetching PosterBoard database..."))
        from src.gui.dialogs.pb_dialog import backup_posterboard_database
        try:
            db_file_path = await backup_posterboard_database(udid, update_label)
            if not db_file_path or not os.path.exists(db_file_path):
                raise NuggetException("The PosterBoard database file doesn't exist!")
            update_label(QCoreApplication.tr("Saving PosterBoard database..."))
            if not pb.config_manager.update_database_file(db_file_path, udid):
                raise NuggetException("The PosterBoard database is not of the correct format!")
            pb.config_manager.update_for_saved_database(udid)
            update_label(QCoreApplication.tr("PosterBoard database backed up successfully."))
        except Exception as e:
            print(f"Failed to back up PosterBoard database: {e}")
            print(traceback.format_exc())
            if _is_device_locked_error(e):
                update_label(QCoreApplication.tr("Warning: could not back up PosterBoard database — device is locked. Please unlock your device and try again."))
            else:
                update_label(QCoreApplication.tr("Warning: could not back up the PosterBoard database automatically."))

    async def _get_lockdown_values(self) -> dict:
        udid = self.get_current_device_udid()
        if not udid:
            return {}
        async with lockdown_session(udid) as ld:
            return dict(ld.all_values)

    def _get_original_plist_paths(self) -> list[str]:
        return [loc.value for loc in FileLocation]

    async def _capture_original_plists(self, udid: str, update_label) -> dict:
        """Run the psysbackup capture and return usable originals.

        The mobile-user copy (HomeDomain) of a managed-preference file is
        preferred over the managed copy: tweaks and resets write only to
        ``/var/Managed Preferences/mobile/*.plist``, so the HomeDomain copy is
        the truest original even when tweaks were applied before the capture
        ran. The managed copy is used only when no HomeDomain copy exists.
        Entries that are still empty after both sources are dropped — a nulled
        plist must never be stored as an "original", otherwise reset keeps
        restoring the nulled state.
        """
        paths = self._get_original_plist_paths()
        fallbacks = [mobile_user_fallback_path(p) for p in paths]
        fallbacks = [f for f in fallbacks if f is not None and f not in paths]
        captured = await psysbackup(
            udid, paths + fallbacks, update_label, self._backup_progress(update_label), self._get_backup_password())
        originals = {}
        for path in paths:
            data = None
            fallback = mobile_user_fallback_path(path)
            if fallback:
                data = captured.get(fallback)
            if data is None or is_empty_plist(data):
                data = captured.get(path)
            if data is not None and not is_empty_plist(data):
                originals[path] = data
        return originals

    async def _apply_tweak_pass(self, update_label=lambda x: None, templates: list = None, prepared_backup_root=None, prompt_password=None, prompt_choice=None, skip_protective_backup: bool = False):
        """Generate all tweak files and restore them to the device in one pass.

        Returns (alert, files_to_restore) so the caller can surface the result
        and keep the file list for error reporting.
        """
        if templates is None:
            templates = tweaks[TweakID.Templates].templates
        # create the other plists
        flag_plist: dict = {}
        basic_plists: dict = {}
        basic_plists_ownership: dict = {}
        files_data: dict = {}
        uses_domains: bool = False
        # create the restore file list
        files_to_restore: list[FileToRestore] = [
        ]
        tmp_dirs = [] # temporary directory for unzipping pb and template files

        hotload = HotLoad(self.pref_manager.settings)
        hotload_version = self.get_current_device_version()
        hotload_model = self.get_current_device_model()
        hotload_skipped = []
        # stale/blocked tweaks are skipped; whole hidden features are never applied
        hotload_hidden_names = hotload.hidden_tweak_names(
            device_version=hotload_version, device_model=hotload_model)

        try:
            # set the plist keys
            for tweak_name in tweaks:
                tweak = tweaks[tweak_name]
                # HotLoad: never apply tweaks flagged as dangerous/broken for
                # this device / iOS version (kill switch off -> no rules match),
                # and never apply tweaks of a hidden feature.
                if (tweak_name in hotload_hidden_names
                        or hotload.rule_for(tweak_name,
                                            device_version=hotload_version,
                                            device_model=hotload_model) is not None):
                    hotload_skipped.append(tweak_name)
                    continue
                if isinstance(tweak, BasicPlistTweak) or isinstance(tweak, AdvancedPlistTweak):
                    basic_plists = tweak.apply_tweak(basic_plists)
                    basic_plists_ownership[tweak.file_location] = tweak.owner
                elif isinstance(tweak, NullifyFileTweak):
                    tweak.apply_tweak(files_data)
                    if tweak.enabled and tweak.file_location.value.startswith("/var/mobile/"):
                        uses_domains = True
                elif isinstance(tweak, PosterboardTweak) or isinstance(tweak, TemplatesTweak):
                    tmp_dirs.append(TemporaryDirectory())
                    tweak.apply_tweak(
                        files_to_restore=files_to_restore,
                        output_dir=fix_windows_path(tmp_dirs[len(tmp_dirs)-1].name),
                        templates=templates,
                        version=self.get_current_device_version(),
                        force_pb_refresh=self.pref_manager.auto_refresh_posterboard,
                        update_label=update_label
                    )
                    if tweak.uses_domains():
                        uses_domains = True
                elif isinstance(tweak, StatusBarTweak):
                    # iOS 27: the status bar is Speakeasy, a SpringBoard
                    # feature flag — writing fails due to no write permissions.
                    # The feature is disabled on iOS 27+.
                    flag_plist = tweak.apply_tweak(flag_plist, version=self.get_current_device_version())

            if hotload_skipped:
                names = sorted(t.name if hasattr(t, "name") else str(t) for t in hotload_skipped)
                update_label(QCoreApplication.tr(
                    "Skipped HotLoad-flagged tweaks: ") + ", ".join(names))

            # Generate backup
            update_label(QCoreApplication.tr("Generating backup..."))
            if len(flag_plist) > 0:
                self.concat_file(
                    contents=plistlib.dumps(flag_plist),
                    path=FileLocation.featureflags.value,
                    files_to_restore=files_to_restore
                )
            
            self.add_skip_setup(files_to_restore, uses_domains)
            for location, plist in basic_plists.items():
                if location in basic_plists_ownership:
                    ownership = basic_plists_ownership[location]
                else:
                    ownership = 501
                self.concat_file(
                    contents=plistlib.dumps(plist),
                    path=location.value,
                    files_to_restore=files_to_restore,
                    owner=ownership, group=ownership
                )
            # iOS 27+: Also write .GlobalPreferences.plist to HomeDomain so
            # tweaks that depend on it survive the Phase 3 protective backup restore.
            # ManagedPreferencesDomain is the primary location; HomeDomain is a
            # secondary copy for iOS 27 compatibility. (Phase 3 skips this file
            # to avoid overwriting the tweak copy.)
            home_plist = basic_plists.get(FileLocation.globalPreferences, {})
            self.concat_file(
                contents=plistlib.dumps(home_plist),
                path=FileLocation.globalPreferencesHomeDomain.value,
                files_to_restore=files_to_restore,
                owner=501, group=501
            )

            for location, data in files_data.items():
                self.concat_file(
                    contents=data,
                    path=location.value,
                    files_to_restore=files_to_restore,
                    owner=501, group=501
                )

            # Check if backup encryption is enabled and handle it
            backup_password = ""
            if Version(self.get_current_device_version()) >= Version("27.0"):
                # Check if backup encryption is enabled on device
                async with lockdown_session(self.get_current_device_udid()) as check_ld:
                    try:
                        async with Mobilebackup2Service(check_ld) as mb:
                            is_encrypted = await mb.get_will_encrypt()
                        if is_encrypted:
                            if self.pref_manager.use_encrypted_backup:
                                # reuse the password entered for the cached backup, if any
                                backup_password = self._get_backup_password()
                                if backup_password:
                                    log_info("Using existing backup encryption with provided password")
                                    update_label(QCoreApplication.tr("Password accepted. Proceeding with encrypted restore..."))
                                else:
                                    # User wants to keep encryption - ask for password to use it
                                    update_label(QCoreApplication.tr("Backup encryption is enabled. We'll use it for the restore."))
                                    update_label(QCoreApplication.tr("Please enter your iTunes/Finder backup password:"))
                                    if prompt_password is None:
                                        raise NuggetException(QCoreApplication.tr("Backup password is required for encrypted restore. Please provide the password or disable encryption in iTunes/Finder."))
                                    password = prompt_password(
                                        QCoreApplication.tr("Backup Encryption Password"),
                                        QCoreApplication.tr("Enter your iTunes/Finder backup password (required for encrypted restore):"))
                                    if password:
                                        backup_password = password
                                        log_info("Using existing backup encryption with provided password")
                                        update_label(QCoreApplication.tr("Password accepted. Proceeding with encrypted restore..."))
                                    else:
                                        raise NuggetException(QCoreApplication.tr("Backup password is required for encrypted restore. Please provide the password or disable encryption in iTunes/Finder."))
                            else:
                                # User doesn't want encryption - show friendly error
                                raise NuggetException(QCoreApplication.tr(
                                    "Backup encryption is enabled on your iPhone.\n\n"
                                    "GoldenNugget needs to temporarily disable it to apply tweaks safely.\n\n"
                                    "Please choose one:\n"
                                    "1. Disable encryption on your iPhone: Settings → General → Transfer or Reset iPhone → Backup Password → Turn Off\n"
                                    "2. Or enable \"Use Encrypted Backups (Experimental)\" in GoldenNugget Settings → enter your backup password when prompted.\n\n"
                                    "Tip: Option 1 is simpler if you don't know your backup password."
                                ))
                    except Exception as e:
                        if isinstance(e, NuggetException):
                            raise
                        log_warn(f"Failed to check backup encryption status: {e}")

            # restore to the device
            # include_keychain only when backup encryption is active — iOS rejects
            # keychain entries in an unencrypted backup, and the keychain is what
            # preserves Apple Watch pairing / iMessage identity across the wipe.
            final_alert = await self.start_restore(
                files_to_restore, update_label, backup_password=backup_password,
                prepared_backup_root=prepared_backup_root,
                skip_protective_backup=skip_protective_backup,
                include_keychain=bool(backup_password),
                prompt_choice=prompt_choice)
            return final_alert, files_to_restore
        finally:
            if len(tmp_dirs) > 0:
                for tmp_dir in tmp_dirs:
                    try:
                        tmp_dir.cleanup()
                    except Exception as e:
                        # ignore clean up errors
                        print(str(e))

    ## RESETTING TWEAKS
    def reset_tweaks(self, reset_pages: list[Page], settings: QSettings, update_label=lambda x: None, show_alert=lambda x: None, prompt_choice=None):
        asyncio.run(self._reset_tweaks(reset_pages, settings, update_label, show_alert, prompt_choice))
    async def _reset_tweaks(self, reset_pages: list[Page], settings: QSettings, update_label=lambda x: None, show_alert=lambda x: None, prompt_choice=None):
        try:
            self._raise_if_unsupported()
            # create the restore file list
            files_to_restore: list[FileToRestore] = []
            # Capture the device's original plists fresh via psysbackup so the
            # reset can restore the user's files instead of empty ones.
            udid = self.get_current_device_udid()
            if not udid:
                raise NuggetException(QCoreApplication.tr("No device connected."))
            all_values = await self._get_lockdown_values()
            update_label(QCoreApplication.tr("Capturing original plists..."))
            captured = await self._capture_original_plists(udid, update_label)
            original_plists = {}
            for path, data in captured.items():
                try:
                    original_plists[path] = plistlib.loads(data)
                except Exception:
                    continue
            files_to_null: list[str] = []
            uses_domains = False

            # use if-statements instead of match (switch) statements for compatibility with Python 3.9
            for page in reset_pages:
                if page == Page.StatusBar:
                    ## STATUS BAR
                    # iOS 26.2+ (iOS 27 era): the status bar is Speakeasy, a SpringBoard
                    # feature flag — disable it instead of writing the
                    # unread classic statusBarOverrides file. An empty flag
                    # dict (no "Enabled" key) keeps SpringBoard's default
                    # behavior — {"Enabled": False} could be read as
                    # disabling the whole Speakeasy status bar.
                    self.concat_file(
                        contents=plistlib.dumps({
                            "SpringBoard": {
                                "SpeakeasyNewStatusBar": {}
                            }
                        }),
                        path=FileLocation.featureflags.value,
                        files_to_restore=files_to_restore
                    )
                elif page == Page.Springboard:
                    ## SPRINGBOARD
                    files_to_null.append(FileLocation.springboard.value)
                    files_to_null.append(FileLocation.uikit.value)
                elif page == Page.Daemons:
                    ## DAEMONS
                    default_daemons = {
                        "com.apple.magicswitchd.companion": True,
                        "com.apple.security.otpaird": True,
                        "com.apple.dhcp6d": True,
                        "com.apple.bootpd": True,
                        "com.apple.ftp-proxy-embedded": False,
                        "com.apple.relevanced": True
                    }
                    self.concat_file(
                        contents=plistlib.dumps(default_daemons),
                        path=FileLocation.disabledDaemons.value,
                        files_to_restore=files_to_restore,
                        owner=0, group=0
                    )
                    uses_domains = True
                elif page == Page.InternalOptions:
                    ## INTERNAL OPTIONS
                    files_to_null.append(FileLocation.globalPreferences.value)
                    files_to_null.append(FileLocation.appStore.value)
                    files_to_null.append(FileLocation.backboardd.value)
                    files_to_null.append(FileLocation.coreMotion.value)
                    files_to_null.append(FileLocation.pasteboard.value)
                    files_to_null.append(FileLocation.notes.value)

            # add the files to null from the list
            for file_path in files_to_null:
                original = original_plists.get(file_path)
                if original is not None:
                    contents = plistlib.dumps(materialize_plist(original, all_values))
                else:
                    # Restore a valid empty plist instead of a zero-byte
                    # file: on iOS 26.2+ a truncated plist (e.g. an empty
                    # com.apple.springboard.plist) makes SpringBoard crash
                    # at boot, which sends the device into a boot loop. An
                    # empty dict parses fine and makes the system fall back
                    # to its default values.
                    contents = plistlib.dumps({})
                self.concat_file(
                    contents=contents,
                    path=file_path,
                    files_to_restore=files_to_restore
                )

            await self.add_skip_setup(files_to_restore, uses_domains)

            # restore to the device
            final_alert = await self.start_restore(files_to_restore, update_label,
                                                   prompt_choice=prompt_choice)
            update_label(QCoreApplication.tr("Success!"))
        except Exception as e:
            final_alert = show_apply_error(e, update_label, files_list=files_to_restore)
        finally:
            show_alert(final_alert)
