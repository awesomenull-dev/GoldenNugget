"""
Protective backup module for iOS 27+.

On iOS 27, the sparse restore triggers a "safe state recovery" that purges
device data not present in the backup (photos, Apple ID credentials, user
settings). To keep user data alive, the three-phase flow in restore.py does:

  Phase 1 (this module): selective device backup. App containers are skipped
      device-side (empty Applications dict in the factory info), and every
      non-protective file the device uploads is discarded mid-stream instead
      of being written to disk. Peak disk usage drops from a full backup
      (10-100+ GB) to just the protective payload. If the selective upload
      fails for any reason, we automatically fall back to a full backup.
  Phase 3 (this module): the same backup directory — with Manifest.db pruned
      to the protective rows and orphan payload files removed — is restored
      back to the device after the security recovery.

Protective scope: HomeDomain/{Accounts, ConfigurationProfiles, Preferences,
Library/SpringBoard} (Apple ID + user settings + home screen layout),
Library/ControlCenter (Control Center module layout), Library/Shortcuts
(iOS Shortcuts automations and commands), Library/WebClips (Safari
"Add to Home Screen" web clips, incl. each <.webclip>/Storage PWA payload),
Library/WebApp + Library/WebKit/WebsiteData (installed-PWA data on iOS
releases that keep it outside the web clip), MessagesDomain
(iMessage/SMS/MMS), and, optionally, CameraRollDomain + MediaDomain (photos).
KeychainDomain (Apple Watch pairing, iMessage identity, Wi-Fi passwords) is
included only when backup encryption is enabled — keychain payloads are
encrypted at rest and iOS rejects them in an unencrypted backup.
"""

import asyncio
import os
import plistlib
import shutil
import sqlite3
import tempfile
import time
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymobiledevice3.exceptions as _pm3_exc
import pymobiledevice3.service_connection as _sc
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from PySide6.QtCore import QCoreApplication, QStandardPaths

from src.exceptions.nugget_exception import NuggetException
from src.restore.inject import (  # noqa: F401  (re-exported public API)
    _is_encrypted_backup,
    _validate_sqlite_db,
    inject_file_into_backup,
)
from src.restore.protective_cache import (  # noqa: F401  (re-exported public API)
    CACHE_PERSIST_MIN_GB,
    CACHE_REFRESH_SECS,
    ProtectiveBackupCache,
)


@dataclass
class PreparedBackup:
    """A protective backup prepared ahead of the three-phase restore."""
    root: str
    manifest_password: str = ""  # required to prune/inject encrypted manifests


# Minimum free disk space required before any device backup is started.
# Backups can easily reach several GB (photos, app data), so filling the disk
# mid-backup is a real hazard. Overridable via GOLDENNUGGET_MIN_FREE_GB.
#
# Note the destinations differ: ``psysbackup`` and the PosterBoard backup still
# write to the system temp directory, while live protective backups go to the
# persistent app-data folder (see ``protective_persistent_base``). Callers that
# pass a path must pass the one they actually write to — on a multi-volume Mac
# the check has to measure the right disk.
MIN_FREE_DISK_GB = 5.0


def _min_free_disk_bytes() -> int:
    try:
        return int(float(os.environ.get("GOLDENNUGGET_MIN_FREE_GB", str(MIN_FREE_DISK_GB))) * (1024 ** 3))
    except ValueError:
        return int(MIN_FREE_DISK_GB * (1024 ** 3))


def check_disk_space(path: str = None, min_free_bytes: int = None) -> None:
    """Raise ``NuggetException`` if free disk space is below the backup threshold.

    Device backups are written to disk (temp directory by default); a full
    backup can be tens of GB. Fail early with a clear error instead of filling
    the disk mid-backup, which would corrupt the backup and the apply flow.
    """
    import tempfile
    if path is None:
        path = tempfile.gettempdir()
    os.makedirs(path, exist_ok=True)  # disk_usage requires an existing path
    if min_free_bytes is None:
        min_free_bytes = _min_free_disk_bytes()
    usage = shutil.disk_usage(path)
    if usage.free < min_free_bytes:
        free_gb = usage.free / (1024 ** 3)
        required_gb = min_free_bytes / (1024 ** 3)
        raise NuggetException(
            QCoreApplication.translate(
                "Nugget",
                "Not enough free disk space: only {0} GB available, at least {1} GB is required for the backup. "
                "Free up space on your computer (backups are written to {2}) and try again.",
            ).format(f"{free_gb:.1f}", f"{required_gb:.1f}", path)
        )


async def _get_device_used_storage(lockdown_client) -> Optional[int]:
    """Return the device's used data storage in bytes, or ``None`` if unreadable.

    Queries the diagnostics relay's ``All`` report. ``TotalDataCapacity`` is the
    total size of the data partition and ``TotalDataSpace`` is its free space, so
    the difference is how much data a full device backup would carry. A full
    backup mirrors roughly the used capacity, so this is the disk space a backup
    needs to be written to the computer without exhausting it.
    """
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown_client) as diag:
            report = await diag.info("All")
        if not isinstance(report, dict):
            return None
        capacity = report.get("TotalDataCapacity")
        free = report.get("TotalDataSpace")
        if capacity is None or free is None:
            nested = report.get("DiskUsage")
            if isinstance(nested, dict):
                capacity = nested.get("TotalDataCapacity", capacity)
                free = nested.get("TotalDataSpace", free)
        if capacity is None or free is None:
            return None
        used = int(capacity) - int(free)
        return used if used > 0 else None
    except Exception:
        return None


async def check_disk_space_for_backup(lockdown_client=None, path: str = None,
                                      min_free_bytes: int = None) -> int:
    """Check free disk space before a device backup, sized to the device's data.

    The required free space is derived from the amount of data actually stored
    on the device (a full backup mirrors used capacity), never below the
    ``MIN_FREE_DISK_GB`` floor. If the device cannot be queried, the floor is
    used. Returns the required free space in bytes that was enforced.
    """
    if min_free_bytes is None:
        min_free_bytes = _min_free_disk_bytes()
        if lockdown_client is not None:
            used = await _get_device_used_storage(lockdown_client)
            if used is not None:
                min_free_bytes = max(min_free_bytes, used)
    check_disk_space(path=path, min_free_bytes=min_free_bytes)
    return min_free_bytes

# Bump SSL handshake timeout — the default 10 seconds is too short for
# mobilebackup2 service startup on busy or post-reboot devices (iOS 27+).
# Importing this module applies it process-wide.
_sc.DEFAULT_SSL_HANDSHAKE_TIMEOUT = 60

import logging

_logger = logging.getLogger("GoldenNugget.protective")


def log_info(msg: str) -> None:
    """Log an info message through the session logger."""
    _logger.info(msg)


def log_warn(msg: str) -> None:
    """Log a warning through the session logger."""
    _logger.warning(msg)


def log_error(msg: str) -> None:
    """Log an error through the session logger."""
    _logger.error(msg)

# --- DeviceLink protocol constants (from pymobiledevice3.services.device_link) ---

# Backup metadata files that must always be preserved (never filtered out)
_BACKUP_METADATA_FILES = frozenset({
    "Manifest.db",
    "Manifest.plist",
    "Status.plist",
    "Info.plist",
    "backup_manifest.db",
})

# Domains whose files should be kept in the protective backup.
PROTECTIVE_DOMAINS = frozenset({
    "CameraRollDomain",  # Actual photos and videos (DCIM/)
    "MediaDomain",       # Photo metadata (PhotoData/), PhotoStream, other media
    "MessagesDomain",    # iMessage / SMS / MMS (preserved across safe-state recovery)
})

# KeychainDomain is only included when the user has backup encryption
# enabled — keychain payloads are encrypted at rest and iOS rejects
# unencrypted keychain entries in a backup.  This preserves Apple Watch
# pairing, iMessage identity keys, Wi-Fi passwords, etc.
KEYCHAIN_DOMAIN = "KeychainDomain"

# Path prefixes within HomeDomain that contain Apple ID account data and
# user settings.
APPLE_ID_PATH_PREFIXES = (
    "Library/Accounts",              # Account database (Accounts3.sqlite)
    "Library/ConfigurationProfiles",  # Configuration profiles
    "Library/Preferences",           # User settings (dark mode, wallpaper, etc.)
)

# NOTE: ConfigurationProfiles (MDM/VPN/WebClip) backup was added in commit
# 25006f5 (Aug 12) and later removed again in the 8.3 hotfix (875d4e1) — the
# widened Phase 3 restore scope rolled back applied tweaks on repeat apply and
# corrupted the PosterBoard database. It was then re-added on top of the
# iOS 27 five-phase restore, which no longer shares scope with the tweak
# pass, so profiles now ride the protective backup without those regressions.
# Restoring profiles is still best-effort: iOS may re-install MDM profiles
# independently of the backup.

# Path prefixes within HomeDomain that hold SpringBoard's home screen layout
# and icon state. Restoring these keeps the home screen (icon layout, folders,
# dock) intact after the iOS 27 "safe state recovery" wipe.
SPRINGBOARD_PATH_PREFIXES = (
    "Library/SpringBoard",
)

# Path prefixes within HomeDomain holding the Control Center module layout
# (Library/ControlCenter/ModuleConfiguration.plist). Not part of the
# "user settings" prefix above, so it must be listed explicitly — otherwise
# the iOS 27 wipe resets Control Center to its default modules.
CONTROL_CENTER_PATH_PREFIXES = (
    "Library/ControlCenter",
)

# Path prefixes within HomeDomain holding iOS Shortcuts (the Shortcuts app:
# Library/Shortcuts/Shortcuts.sqlite, ShortcutIcons/, VoiceShortcuts/...).
# Automations and custom shortcuts are pure user data and would be lost to
# the iOS 27 "safe state recovery" wipe without an explicit entry.
SHORTCUTS_PATH_PREFIXES = (
    "Library/Shortcuts",
)

# Path prefixes within HomeDomain holding Safari "Add to Home Screen" web
# clips (Library/WebClips/<UUID>.webclip/Info.plist + icon.png). Pure user
# data that the iOS 27 "safe state recovery" wipe would discard; the icon
# layout (IconState.plist) references them by bundle id. The whole tree is
# kept, so a web app's own WKWebsiteDataStore under <.webclip>/Storage/
# (___IndexedDB, Default/<profile>/local storage, cookies, HSTS) rides along —
# that is where iOS 26/27 keeps installed-PWA data.
WEB_CLIPS_PATH_PREFIXES = (
    "Library/WebClips",
)

# Older/alternative HomeDomain homes for installed web-app data. iOS has kept
# per-web-app state under Library/WebApp (WebAppCache, WebAppLocalStorage) on
# some releases, and the modern shared WKWebsiteDataStore (ServiceWorkers,
# IndexedDB, LocalStorage per profile) under Library/WebKit/WebsiteData when
# a web app runs against the Safari store. Covering both makes PWA data
# survive the wipe regardless of which layout the release uses — the browser's
# own store lives in AppDomain-com.apple.mobilesafari and is out of scope.
WEB_APP_PATH_PREFIXES = (
    "Library/WebApp",
)
WEBKIT_WEBSITE_DATA_PATH_PREFIXES = (
    "Library/WebKit/WebsiteData",
)

# Files/dirs inside the protective HomeDomain scope that tweaks write
# themselves — restoring the stale copies would undo the applied tweaks.
_SKIP_PATH_PREFIXES = (
    "Library/SpringBoard/statusBarOverrides",  # Not captured stale; re-injected with fresh tweak content
)

# Files iOS manages internally and rejects if included in a sparse backup
# with incorrect metadata (e.g. wrong protection class). With copy=True the
# existing on-device data is preserved anyway, so skipping them is safe.
_SKIP_FILES = frozenset({
    "keychain-backup.plist",    # iOS validates protection class, rejects flags=4
    ".GlobalPreferences.plist",  # Written separately as tweaks; skip to avoid overwrite
})

# PosterBoard sqlite database carried by the protective backup so wallpaper
# applies need no second device backup. Scope note: the database lives in the
# cache MASTER only — clean_backup_for_restore prunes it from the restore copy
# so Phase 3 never clobbers the tweaked database Phase 2 lays down. Because
# the master is incrementally refreshed BEFORE extraction, the extracted DB
# always mirrors the live on-device state.
# The store directory carries a structure version (61, 62, ...) that varies
# between iOS releases, so matching is done by FILE NAME, not full path.
POSTERBOARD_DB_DOMAIN = "AppDomain-com.apple.PosterBoard"
POSTERBOARD_DB_NAME = "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"


def _is_protective_file(domain: str, relative_path: str, include_photos: bool = True, include_keychain: bool = False) -> bool:
    """Check if a file belongs in the protective backup."""
    filename = relative_path.rsplit("/", 1)[-1]
    # keychain-backup.plist carries the KeychainDomain payload. It is rejected
    # when restored unencrypted (iOS validates protection class, flags=4), but
    # with an encrypted backup — exactly the case where include_keychain is set —
    # the device decrypts it on restore, so it must be kept.
    if filename in _SKIP_FILES and not (include_keychain and filename == "keychain-backup.plist"):
        return False
    if domain == "HomeDomain":
        if relative_path.startswith(_SKIP_PATH_PREFIXES):
            return False
        return (relative_path.startswith(APPLE_ID_PATH_PREFIXES)
                or relative_path.startswith(SPRINGBOARD_PATH_PREFIXES)
                or relative_path.startswith(CONTROL_CENTER_PATH_PREFIXES)
                or relative_path.startswith(SHORTCUTS_PATH_PREFIXES)
                or relative_path.startswith(WEB_CLIPS_PATH_PREFIXES)
                or relative_path.startswith(WEB_APP_PATH_PREFIXES)
                or relative_path.startswith(WEBKIT_WEBSITE_DATA_PATH_PREFIXES))
    if include_photos and domain in PROTECTIVE_DOMAINS:
        return True
    if include_keychain and domain == KEYCHAIN_DOMAIN:
        return True
    return False


def _norm_device_name(device_name: str) -> str:
    return device_name.replace("\\", "/").lstrip("/")


def _domain_match(device_name: str, domain: str) -> bool:
    name = _norm_device_name(device_name)
    return name == domain or name.startswith(f"{domain}/")


def _path_match(device_name: str, path: str) -> bool:
    name = _norm_device_name(device_name)
    return name == path or name.startswith(f"{path}/") or f"/{path}/" in name


def is_protective_device_file(device_name: str, include_photos: bool = True,
                              include_posterboard: bool = False,
                              include_keychain: bool = False) -> bool:
    """Mid-stream backup filter: match an upload's device-side name against the keep-set.

    Upload names carry the domain and path (e.g. ``HomeDomain/Library/...``),
    mirroring pymobiledevice3's own BackupSelectionRule matching. Rejected
    payloads are drained by the DeviceLink; their Manifest.db rows survive so
    subsequent incremental backups do not re-upload them.
    """
    for domain in (("CameraRollDomain", "MediaDomain") if include_photos else ()) + \
            ("SystemPreferencesDomain", "MessagesDomain"):
        if _domain_match(device_name, domain):
            return True
    if include_keychain and _domain_match(device_name, KEYCHAIN_DOMAIN):
        return True
    for prefix in (APPLE_ID_PATH_PREFIXES + SPRINGBOARD_PATH_PREFIXES
               + CONTROL_CENTER_PATH_PREFIXES + SHORTCUTS_PATH_PREFIXES
               + WEB_CLIPS_PATH_PREFIXES + WEB_APP_PATH_PREFIXES
               + WEBKIT_WEBSITE_DATA_PATH_PREFIXES):
        if _path_match(device_name, f"HomeDomain/{prefix}") or _path_match(device_name, prefix):
            return True
    if include_posterboard:
        name = _norm_device_name(device_name)
        if "PRBPosterExtensionDataStore" in name and POSTERBOARD_DB_NAME in name:
            return True
    return False


class ProtectiveBackupService(Mobilebackup2Service):
    """Mobilebackup2Service tuned for fast protective backups.

    - ``init_mobile_backup_factory_info`` returns an empty ``Applications``
      dict, so the device skips all app containers (AppDomain-*) entirely —
      they are never uploaded at all. With ``include_posterboard`` it lists
      only the PosterBoard container so its sqlite database rides the same
      backup.
    - Mid-stream payload filtering is done via pymobiledevice3's native
      ``filter_callback`` on ``backup()``.
    - ``connect`` retries transient failures with exponential backoff —
      iOS 27+ devices can take a while to spin up mobilebackup2.
    """

    def __init__(self, lockdown, include_posterboard: bool = False):
        super().__init__(lockdown)
        self.include_posterboard = include_posterboard

    async def connect(self, max_retries: int = 5):
        from src.utils.async_retry import async_retry

        retryable = (_pm3_exc.ConnectionTerminatedError, ConnectionError,
                     OSError, asyncio.TimeoutError)
        base_connect = super().connect
        return await async_retry(
            base_connect,
            max_retries,
            retry_if=lambda e: isinstance(e, retryable),
            exp_cap=15,
            on_retry=lambda attempt, total, e, delay: print(
                f"[ProtectiveBackup] mobilebackup2 connect failed "
                f"(attempt {attempt}/{total}), retrying in {delay}s: {e}"
            ),
        )

    async def init_mobile_backup_factory_info(self, afc):
        root_node = self.lockdown.all_values
        info = {
            "iTunes Version": "10.0.1",
            "iTunes Files": {},
            "Unique Identifier": self.lockdown.udid.upper(),
            "Target Type": "Device",
            "Target Identifier": root_node["UniqueDeviceID"],
            "Serial Number": root_node["SerialNumber"],
            "Product Version": root_node["ProductVersion"],
            "Product Type": root_node["ProductType"],
            "Installed Applications": [],
            "GUID": _uuid.uuid4().bytes,
            "Display Name": root_node.get("DeviceName", ""),
            "Device Name": root_node.get("DeviceName", ""),
            "Build Version": root_node["BuildVersion"],
            "Applications": {},  # skip all app containers — big speedup
        }
        if self.include_posterboard:
            await self._add_posterboard_container(info)
        return info

    async def _add_posterboard_container(self, info: dict):
        """List only the PosterBoard container so its sqlite DB rides this backup.

        The entry mirrors what the stock factory info carries for an app
        (ApplicationSINF / iTunesMetadata / PlaceholderIcon / Container) —
        that format provably yields the PosterBoard DB in full backups.
        """
        try:
            from pymobiledevice3.services.installation_proxy import InstallationProxyService
            from pymobiledevice3.services.springboard import SpringBoardServicesService
            bundle_id = POSTERBOARD_DB_DOMAIN.removeprefix("AppDomain-")
            async with InstallationProxyService(lockdown=self.lockdown) as ip:
                apps = await ip.get_apps(application_type="Any", calculate_sizes=False)
            app_info = apps.get(bundle_id)
            if app_info is None:
                log_warn("PosterBoard app not found via installation proxy; skipping container inclusion")
                return
            entry = {
                "Container": app_info["Container"],
                "CFBundleIdentifier": bundle_id,
                "CFBundleVersion": app_info.get("CFBundleVersion", "1.0"),
                "ApplicationSINF": app_info.get("ApplicationSINF", b""),
                "iTunesMetadata": app_info.get("iTunesMetadata", {}),
            }
            try:
                async with SpringBoardServicesService(self.lockdown) as sbs:
                    entry["PlaceholderIcon"] = await sbs.get_icon_pngdata(bundle_id)
            except Exception:
                entry["PlaceholderIcon"] = b""
            info["Installed Applications"] = [bundle_id]
            info["Applications"] = {bundle_id: entry}
        except Exception as e:
            log_warn(f"PosterBoard container inclusion failed: {e}")


async def perform_protective_backup(
    lockdown_client: LockdownClient,
    backup_root: str,
    progress_callback=None,
    include_photos: bool = True,
    include_posterboard: bool = False,
    include_keychain: bool = False,
    incremental_ok: bool = False,
) -> bool:
    if not incremental_ok:
        Path(backup_root).mkdir(parents=True, exist_ok=True)

    def _filter_callback(backup_file):
        return is_protective_device_file(
            backup_file.device_name or "",
            include_photos=include_photos,
            include_posterboard=include_posterboard,
            include_keychain=include_keychain)

    is_encrypted = False
    async with ProtectiveBackupService(lockdown_client, include_posterboard=include_posterboard) as mb:
        try:
            is_encrypted = await mb.get_will_encrypt()
        except Exception:
            pass
        if is_encrypted:
            log_info("Backup encryption already enabled on device.")
            progress_callback("Using existing backup encryption...")
        else:
            progress_callback("Creating protective backup (unencrypted)...")
        try:
            await mb.backup(full=not incremental_ok, backup_directory=backup_root,
                            progress_callback=progress_callback,
                            filter_callback=_filter_callback)
        except NotEnoughDiskSpaceError:
            log_warn("Device sent disk space purge request — ignoring, backup data is preserved")

    return is_encrypted


async def is_backup_encrypted(lockdown_client: LockdownClient) -> bool:
    """Check whether the device currently encrypts its backups."""
    try:
        async with Mobilebackup2Service(lockdown_client) as mb:
            return await mb.get_will_encrypt()
    except Exception as e:
        log_warn(f"Could not read backup encryption state: {e}")
        return False


# --- Live protective backups (the only copy after Phase 2 wipes the device) --
#
# Between Phase 2 (sparse restore, which triggers the iOS 27 wipe) and Phase 3
# (protective restore) the backup directory on this computer is the SOLE copy
# of the user's photos, Apple ID and settings. It therefore must not live in
# the system temp directory — a reboot or an OS temp sweep destroys it — and
# it must never be caught by the routine that disposes of throwaway working
# copies. Both used to be true: every backup and working copy shared the
# ``nugget_protective_`` prefix under ``tempfile.gettempdir()``, so a failed
# apply had its only surviving copy deleted one hour later, with no prompt.
PROTECTIVE_PERSIST_DIRNAME = "protective"

# Disposable working copies carry a prefix of their own so the periodic sweep
# in restore.py can never match a real backup.
WORKING_COPY_PREFIX = "nugget_working_"

# Retention for finished live backups: how many to keep per device, and how
# long a directory must exist before it becomes eligible for deletion.
PROTECTIVE_KEEP_RUNS = 2
PROTECTIVE_MIN_AGE_HOURS = 24.0


def protective_persistent_base() -> Path:
    """Per-user folder holding live protective backups that survive reboots."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.AppDataLocation)) / "GoldenNugget" / PROTECTIVE_PERSIST_DIRNAME


def new_protective_backup_dir(udid: str) -> str:
    """Create a fresh, persistent directory for one live protective backup.

    Layout: ``<persistent base>/<udid>/<timestamp>-<pid>/device_backup``.

    A new directory per run means a failed or interrupted backup can never
    damage the previous run's copy — the one thing standing between a wiped
    device and permanent data loss. The returned path is the directory that
    *contains* the device folder, matching what ``clean_backup_for_restore``
    and ``make_protective_working_copy`` expect.
    """
    safe_udid = udid or "unknown"
    # The random suffix keeps two runs in the same second apart: sharing a
    # directory would let a failing backup overwrite the previous run's copy.
    run_dir = (protective_persistent_base() / safe_udid
               / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{_uuid.uuid4().hex[:8]}")
    backup_root = run_dir / "device_backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    return str(backup_root)


def list_protective_backups(udid: str) -> list:
    """Completed, usable live backup run directories for ``udid``, newest first.

    A run qualifies only when its Manifest.db landed AND reads as a backup
    that can actually be restored:

    - a run still being taken has no Manifest.db yet — excluded (and thus
      never a prune candidate);
    - a run interrupted mid-upload can leave a truncated/corrupt Manifest.db
      behind. Restoring from it silently skips pruning
      (``clean_backup_for_restore`` returns (0, 0) on an unreadable manifest)
      and ``verify_backup_payloads`` then returns no findings for a
      non-sqlite file, so Phase 3 would ship a backup full of payload-less
      rows and fail with MBErrorDomain/205. Such runs are excluded here, so
      the recovery path falls through to the next newest intact run instead.
    - encrypted manifests are not sqlite and cannot be validated as such;
      they are recognised via ``_is_encrypted_backup`` and kept (the prune
      and verify paths handle decryption downstream).
    """
    safe_udid = udid or "unknown"
    root = protective_persistent_base() / safe_udid
    if not root.is_dir():
        return []
    runs = []
    for entry in root.iterdir():
        device_dir = entry / "device_backup" / safe_udid
        manifest_db = device_dir / "Manifest.db"
        if not entry.is_dir() or not manifest_db.is_file():
            continue
        if (not _validate_sqlite_db(manifest_db)
                and not _is_encrypted_backup(device_dir)):
            log_warn(f"Skipping protective backup {entry.name}: Manifest.db is "
                     f"corrupt or incomplete (interrupted upload?)")
            continue
        runs.append(entry)
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs


def find_latest_protective_backup(udid: str) -> Optional[str]:
    """``backup_root`` of the newest live protective backup for ``udid``.

    Used by the post-failure "Restore data" recovery path. Returns None when
    the device has no stored backup.
    """
    runs = list_protective_backups(udid)
    return str(runs[0] / "device_backup") if runs else None


def prune_protective_backups(udid: str, keep: int = PROTECTIVE_KEEP_RUNS,
                             min_age_hours: float = PROTECTIVE_MIN_AGE_HOURS) -> int:
    """Drop older live backups for ``udid``, keeping the newest ``keep``.

    Refuses to delete anything younger than ``min_age_hours``: right after a
    failed apply the newest backup is the only copy of the user's data, and
    deleting it on a timer is precisely the failure this replaces. Returns the
    number of run directories removed.

    Before the age-based deletion the kept-but-old runs are deduplicated
    against the newest one (``dedupe_protective_payloads``): stale copies get
    freed immediately even when they are too young to delete outright, but
    they stay readable for rollback.
    """
    try:
        dedupe_protective_payloads(udid)
    except Exception as e:
        log_warn(f"Protective payload dedupe failed: {e}")
    runs = list_protective_backups(udid)
    removed = 0
    now = time.time()
    for old in runs[keep:]:
        age_h = (now - old.stat().st_mtime) / 3600
        if age_h < min_age_hours:
            log_info(f"Protective backup {old.name} is only {age_h:.1f}h old — keeping it")
            continue
        shutil.rmtree(old, ignore_errors=True)
        if not old.exists():
            removed += 1
            log_info(f"Pruned old protective backup: {old}")
    return removed


def make_protective_working_copy(backup_root: str, udid: str) -> str:
    """Build a throwaway hardlink copy of a protective backup for prune + injection.

    Hardlinks keep it near-instant and size-free; pruning unlinks orphans
    without touching the source's own files (the cache master stays intact).

    The copy is disposable, so it uses ``WORKING_COPY_PREFIX`` — the periodic
    sweep in restore.py cleans up leftovers from crashed runs under that
    prefix only.
    """
    working_root = Path(tempfile.mkdtemp(prefix=WORKING_COPY_PREFIX)) / "device_backup"
    src_root = Path(backup_root) / udid
    if not src_root.is_dir():
        # Tolerate a root pointing directly at the device directory.
        if (Path(backup_root) / "Manifest.db").is_file():
            src_root = Path(backup_root)
        else:
            raise NuggetException("Protective backup is missing its payload.")

    dst_root = working_root / udid
    dst_root.mkdir(parents=True, exist_ok=True)
    # metadata (incl. sqlite sidecars) must be real copies: pruning rewrites
    # Manifest.db, and a hardlink would corrupt the cache master through the
    # shared inode/-wal.
    always_copy = set(_BACKUP_METADATA_FILES) | {"Manifest.db-wal", "Manifest.db-shm"}
    for dirpath, _dirnames, filenames in os.walk(src_root):
        rel = Path(dirpath).relative_to(src_root)
        (dst_root / rel).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            src_file = Path(dirpath) / name
            dst_file = dst_root / rel / name
            if name in always_copy:
                shutil.copy2(src_file, dst_file)
            else:
                try:
                    os.link(src_file, dst_file)
                except OSError:
                    shutil.copy2(src_file, dst_file)
    return str(working_root)


def verify_backup_payloads(backup_dir: "str | Path", udid: str,
                           manifest_password: str = "") -> list:
    """Return relativePaths of regular-file manifest rows whose payload is missing.

    Such rows make the Phase 3 restore fail with MBErrorDomain/205 (the device
    requests the payload and the host cannot provide it). For encrypted backups
    the manifest is decrypted locally first (``manifest_password``) so the same
    check still runs instead of being silently skipped.
    """
    device_dir = Path(backup_dir) / udid
    if not device_dir.is_dir():
        if (Path(backup_dir) / "Manifest.db").is_file():
            device_dir = Path(backup_dir)
        else:
            return []
    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.exists():
        return []
    decrypted_tmp = None
    if not _validate_sqlite_db(manifest_db):
        if not _is_encrypted_backup(device_dir):
            return []
        if not manifest_password:
            log_warn("Manifest.db is encrypted and no password was given — "
                     "skipping local payload verification")
            return []
        try:
            decrypted_tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
            decrypted_tmp.close()
            Mobilebackup2Service._decrypt_backup_manifest_db(
                device_dir, manifest_password, Path(decrypted_tmp.name))
            manifest_db = Path(decrypted_tmp.name)
        except Exception as e:
            log_warn(f"Could not decrypt manifest for payload verification: {e}")
            return []
    missing = []
    try:
        conn = sqlite3.connect(str(manifest_db))
        try:
            for file_id, rel_path in conn.execute(
                    "SELECT fileID, relativePath FROM Files WHERE flags = 1"):
                if not (device_dir / file_id[:2] / file_id).is_file():
                    missing.append(rel_path)
        finally:
            conn.close()
    finally:
        if decrypted_tmp is not None:
            os.unlink(decrypted_tmp.name)
    return missing


def extract_posterboard_db(backup_root: str, udid: str, dest_path: str) -> Optional[str]:
    """Pull the PosterBoard sqlite database out of a (refreshed) protective backup.

    Call this AFTER ``ProtectiveBackupCache.refresh(include_posterboard=True)``
    so the extracted database mirrors the live on-device state. Returns the
    destination path, or None when the backup does not carry the database
    (e.g. container inclusion was rejected by the device).
    """
    device_dir = Path(backup_root) / udid
    if not device_dir.is_dir():
        if (Path(backup_root) / "Manifest.db").is_file():
            device_dir = Path(backup_root)
        else:
            return None
    manifest_db = device_dir / "Manifest.db"
    if not _validate_sqlite_db(manifest_db):
        return None
    conn = sqlite3.connect(str(manifest_db))
    try:
        pb_rows = conn.execute(
            "SELECT fileID, relativePath FROM Files WHERE domain = ? ORDER BY relativePath",
            (POSTERBOARD_DB_DOMAIN,),
        ).fetchall()
    finally:
        conn.close()

    if not pb_rows:
        log_warn("Master manifest has NO PosterBoard rows — the device did not back up the container")
        return None

    # resolve by FILE NAME: the store dir carries a structure version that
    # varies between iOS releases; prefer the highest-versioned match
    candidates = sorted((r for r in pb_rows if r[1].endswith(POSTERBOARD_DB_NAME)),
                        key=lambda r: r[1], reverse=True)
    if not candidates:
        log_warn(f"No {POSTERBOARD_DB_NAME} among the PosterBoard rows")
        return None
    file_id, rel_path = candidates[0]

    def _payload_for(suffix: str) -> Optional[Path]:
        target = rel_path + suffix
        for fid, rp in pb_rows:
            if rp == target:
                p = device_dir / fid[:2] / fid
                return p if p.is_file() else None
        return None

    main_payload = _payload_for("")
    if main_payload is None:
        return None

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    wal_payload = _payload_for("-wal")
    if wal_payload is None:
        # no WAL sibling — the main file already holds the whole state
        shutil.copyfile(main_payload, dest)
        return str(dest)

    # The on-device database runs in WAL mode: recent wallpaper data may live
    # in the -wal sibling rather than the main file. Copy main + wal into a
    # scratch directory (NEVER the -shm: a stale shm desyncs against the wal
    # and is a classic source of "database disk image is malformed"), then
    # use SQLite's online-backup API to fold the wal frames into one clean
    # database file. Plain-copying the bare main file would lose that data.
    work_dir = Path(tempfile.mkdtemp(prefix="nugget_pbwal_"))
    try:
        work_main = work_dir / "posterboard.sqlite3"
        shutil.copyfile(main_payload, work_main)
        shutil.copyfile(wal_payload, str(work_main) + "-wal")
        dest.unlink(missing_ok=True)
        try:
            src = sqlite3.connect(str(work_main))
            merged = sqlite3.connect(str(dest))
            try:
                src.backup(merged)  # snapshot of main + wal in one atomic file
                merged.execute("PRAGMA journal_mode=DELETE")
                merged.commit()
            finally:
                src.close()
                merged.close()
        except Exception:
            log_warn("WAL consolidation failed — falling back to the plain database file")
        if not _validate_sqlite_db(dest):
            log_warn("Consolidated PosterBoard DB failed validation — "
                     "falling back to the plain database file")
            dest.unlink(missing_ok=True)
            shutil.copyfile(main_payload, dest)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return str(dest)


def _iter_payload_files(device_dir: Path):
    """Yield every payload file in the backup, flat or in hash subdirectories."""
    for entry in sorted(device_dir.iterdir()):
        if entry.is_file():
            if entry.name not in _BACKUP_METADATA_FILES:
                yield entry
        elif entry.is_dir():
            yield from _iter_payload_files(entry)


def _payload_digests_by_fileid(device_dir: Path) -> dict:
    """Map fileID -> content digest (SHA-1) for a backup's regular-file rows.

    Read from the MBFile blobs the device itself wrote into ``Manifest.db`` —
    exact (digest == payload SHA-1, no payload I/O needed) and independent of
    the on-disk payload. Returns ``{}`` when the manifest cannot be read
    (e.g. an encrypted backup without a password).
    """
    manifest_db = device_dir / "Manifest.db"
    if not _validate_sqlite_db(manifest_db):
        return {}
    out = {}
    try:
        conn = sqlite3.connect(str(manifest_db))
        try:
            for file_id, blob in conn.execute(
                    "SELECT fileID, file FROM Files WHERE flags = 1 AND file IS NOT NULL"):
                try:
                    # MBFile archive layout: $objects[3] is the SHA-1 Digest.
                    obj = plistlib.loads(blob)
                    digest = obj["$objects"][3]
                except Exception:
                    continue
                if isinstance(digest, (bytes, bytearray)):
                    out[file_id] = bytes(digest)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return {}
    return out


def dedupe_protective_payloads(udid: str) -> tuple:
    """Free disk by hardlinking payloads older runs share with the newest.

    A fresh protective run mostly repeats the previous one — only the files
    that actually changed on-device differ — so kept older runs waste space
    holding byte-identical copies. For every payload an older run carries in
    common with the newest run (same fileID AND same content digest), the
    older payload is replaced by a hardlink to the newest one: the older
    backup still resolves every path (so rollback keeps working) while the
    duplicate stops costing disk space.

    Matching uses the SHA-1 digests each run's Manifest.db records, so a file
    that legitimately changed between runs (same fileID, new content) keeps
    its own payload and is never clobbered. Encrypted runs without a password
    are skipped (their manifests cannot be read).

    Returns (files_deduped, bytes_freed).
    """
    runs = list_protective_backups(udid)
    if len(runs) < 2:
        return 0, 0
    safe_udid = udid or "unknown"
    newest_dir = runs[0] / "device_backup" / safe_udid
    newest_digests = _payload_digests_by_fileid(newest_dir)
    if not newest_digests:
        return 0, 0
    files = bytes_freed = 0
    for run in runs[1:]:
        old_dir = run / "device_backup" / safe_udid
        old_digests = _payload_digests_by_fileid(old_dir)
        for file_id, digest in old_digests.items():
            if newest_digests.get(file_id) != digest:
                continue
            new_payload = newest_dir / file_id[:2] / file_id
            old_payload = old_dir / file_id[:2] / file_id
            if not new_payload.is_file() or not old_payload.is_file():
                continue
            try:
                if os.path.samefile(old_payload, new_payload):
                    continue
                os.unlink(old_payload)
                os.link(new_payload, old_payload)
                files += 1
                bytes_freed += new_payload.stat().st_size
            except OSError:
                continue
    if files:
        log_info(f"Deduplicated {files} payload files across protective backups "
                 f"(freed {bytes_freed / 1024 / 1024:.1f} MiB on disk)")
    return files, bytes_freed


def _keep_protective_entry(domain: str, relative_path: str, include_photos: bool = True,
                           include_keychain: bool = False) -> bool:
    """Keep-set predicate shared by the plain and encrypted prune paths."""
    if domain and relative_path and (_is_protective_file(domain, relative_path, include_photos, include_keychain)
                                     or domain == "SystemPreferencesDomain"):
        return True
    # the domain root directory row — without it the restore agent may skip
    # the whole domain
    if relative_path == "" and domain in ("SystemPreferencesDomain", "MessagesDomain"):
        return True
    if include_keychain and relative_path == "" and domain == KEYCHAIN_DOMAIN:
        return True
    return False


def clean_backup_for_restore(backup_dir: "str | Path", udid: str,
                             include_photos: bool = True,
                             include_keychain: bool = False,
                             manifest_password: str = "") -> tuple:
    """Prune a backup directory down to its protective payload.

    1. Deletes every non-protective row from Manifest.db in a single DELETE
       (keep-set staged in a temp table instead of per-row DELETEs).
    2. Deletes payload files not referenced by the keep-set, scanning hash
       subdirectories too (iOS may store payloads as "<aa>/<fileID>").
    3. Removes directories left empty by the pruning.

    Encrypted backups are supported when ``manifest_password`` is given:
    pymobiledevice3 decrypts the manifest, prunes it and re-encrypts it in
    place (the caller works on a working copy, so the cache master keeps its
    own encrypted manifest untouched).

    Returns (removed_manifest_rows, removed_payload_files).
    """
    device_dir = Path(backup_dir) / udid
    if not device_dir.is_dir():
        # Tolerate backup_dir already pointing at the device directory.
        if (Path(backup_dir) / "Manifest.db").exists():
            device_dir = Path(backup_dir)
        else:
            return 0, 0

    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.exists():
        return 0, 0

    if _is_encrypted_backup(device_dir):
        if not manifest_password:
            log_info("Backup is encrypted and no password was given — skipping local manifest pruning")
            return 0, 0
        def _keep(bf) -> bool:
            if bf.domain is None or bf.relative_path is None:
                return False
            return _keep_protective_entry(bf.domain, bf.relative_path, include_photos, include_keychain)
        allowed_ids = Mobilebackup2Service.prune_backup_manifest(
            device_dir, _keep, password=manifest_password)
        removed_files = 0
        for payload in _iter_payload_files(device_dir):
            if payload.name not in allowed_ids:
                payload.unlink(missing_ok=True)
                removed_files += 1
        for dirpath, _dirnames, _filenames in os.walk(device_dir, topdown=False):
            d = Path(dirpath)
            if d != device_dir and not any(d.iterdir()):
                d.rmdir()
        log_info(f"Encrypted manifest pruned with password (-{removed_files} orphan payloads)")
        return 0, removed_files

    if not _validate_sqlite_db(manifest_db):
        log_error(f"Manifest.db at {manifest_db} is not a valid SQLite database. Skipping cleanup.")
        return 0, 0

    keep_ids = set()
    removed_rows = 0
    missing_payloads = []
    conn = sqlite3.connect(str(manifest_db))
    try:
        cur = conn.cursor()
        cur.execute("SELECT fileID, domain, relativePath, flags FROM Files")
        for file_id, domain, rel_path, flags in cur:
            if _keep_protective_entry(domain, rel_path, include_photos, include_keychain):
                # only regular files carry a <aa>/<fileID> payload; directory
                # rows (flags=2) MUST survive without one — dropping them
                # makes the restore agent fail with renameatx ENOENT
                if flags == 1 and not (device_dir / file_id[:2] / file_id).is_file():
                    # a file row without a payload makes the restore fail with
                    # MBErrorDomain/205 — drop it and let the device's own
                    # data stand
                    missing_payloads.append(rel_path)
                else:
                    keep_ids.add(file_id)

        if missing_payloads:
            log_warn(f"Prune: dropping {len(missing_payloads)} file rows with missing payloads "
                     f"(e.g. {missing_payloads[:5]})")

        cur.execute("CREATE TEMP TABLE nugget_keep (fileID TEXT PRIMARY KEY)")
        cur.executemany("INSERT INTO nugget_keep (fileID) VALUES (?)",
                        ((fid,) for fid in keep_ids))
        cur.execute("DELETE FROM Files WHERE fileID NOT IN (SELECT fileID FROM nugget_keep)")
        removed_rows = max(cur.rowcount, 0)
        conn.commit()
    finally:
        conn.close()

    removed_files = 0
    for payload in _iter_payload_files(device_dir):
        if payload.name not in keep_ids:
            payload.unlink(missing_ok=True)
            removed_files += 1

    # Remove directories left empty (deepest first).
    for dirpath, _dirnames, _filenames in os.walk(device_dir, topdown=False):
        d = Path(dirpath)
        if d != device_dir and not any(d.iterdir()):
            d.rmdir()

    return removed_rows, removed_files

