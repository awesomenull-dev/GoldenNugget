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
Library/ControlCenter (Control Center module layout), and, optionally,
CameraRollDomain + MediaDomain (photos). KeychainDomain is
intentionally excluded: enabling backup encryption is slow and keychain data
is not needed for tweak functionality.
"""

import asyncio
import hashlib
import json
import os
import plistlib
import shutil
import sqlite3
import tempfile
import time
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymobiledevice3.exceptions as _pm3_exc
import pymobiledevice3.service_connection as _sc
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from PySide6.QtCore import QCoreApplication, QStandardPaths

from src.exceptions.nugget_exception import NuggetException


@dataclass
class PreparedBackup:
    """A protective backup prepared ahead of the three-phase restore."""
    root: str
    manifest_password: str = ""  # required to prune/inject encrypted manifests


# Minimum free disk space required before any device backup is started.
# Backups (protective, psysbackup, PosterBoard) are written to the system
# temp directory and can easily reach several GB (photos, app data). Overridable
# via the GOLDENNUGGET_MIN_FREE_GB environment variable.
MIN_FREE_DISK_GB = 5.0


# Cache placement: masters smaller than this stay in the system temp dir;
# anything bigger moves to the persistent GoldenNugget app-data folder (a
# tmpfs-backed /tmp has both a RAM cost and a hard size ceiling).
CACHE_PERSIST_MIN_GB = float(os.environ.get("GOLDENNUGGET_CACHE_PERSIST_MIN_GB", "1"))
# A cache younger than this is reused without touching the device at all
# (only when no PosterBoard work is pending); past it, an incremental
# refresh session keeps the master in sync.
CACHE_REFRESH_SECS = int(os.environ.get("GOLDENNUGGET_CACHE_REFRESH_SECS", "1800"))


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

# Log file path
_LOG_FILE = "/tmp/goldennugget_log.txt"

def _log_write(msg: str) -> None:
    """Write message to log file (always writes, regardless of debug mode)."""
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass  # Never fail on logging

def log_info(msg: str) -> None:
    """Log info message (always writes to log file)."""
    print(f"[INFO] {msg}")
    _log_write(f"[INFO] {msg}")

def log_warn(msg: str) -> None:
    """Log warning message (always writes to log file)."""
    print(f"[WARN] {msg}")
    _log_write(f"[WARN] {msg}")

def log_error(msg: str) -> None:
    """Log error message (always writes to log file)."""
    print(f"[ERROR] {msg}")
    _log_write(f"[ERROR] {msg}")

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
})

# Path prefixes within HomeDomain that contain Apple ID account data and
# user settings.
APPLE_ID_PATH_PREFIXES = (
    "Library/Accounts",              # Account database (Accounts3.sqlite)
    "Library/ConfigurationProfiles",  # Configuration profiles
    "Library/Preferences",           # User settings (dark mode, wallpaper, etc.)
)

# NOTE: ConfigurationProfiles backup/restore was added in commit 25006f5
# (Aug 12) to preserve MDM/VPN/WebClip profiles across the restore cycle,
# but this widened the Phase 3 restore scope enough to also roll back
# applied tweaks on repeat apply and corrupt the PosterBoard database.
# Profiles are not reliably preserved by this approach anyway (confirmed
# still reset in practice), so scope is reverted to the narrow pre-fix
# state. If profile preservation is revisited, it needs a separate,
# isolated restore path that does not share scope with tweak/PosterBoard
# state — see regression found in 8.3 (reverted before public release).

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


def _is_protective_file(domain: str, relative_path: str, include_photos: bool = True) -> bool:
    """Check if a file belongs in the protective backup."""
    filename = relative_path.rsplit("/", 1)[-1]
    if filename in _SKIP_FILES:
        return False
    if domain == "HomeDomain":
        if relative_path.startswith(_SKIP_PATH_PREFIXES):
            return False
        return (relative_path.startswith(APPLE_ID_PATH_PREFIXES)
                or relative_path.startswith(SPRINGBOARD_PATH_PREFIXES)
                or relative_path.startswith(CONTROL_CENTER_PATH_PREFIXES))
    if include_photos and domain in PROTECTIVE_DOMAINS:
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
                              include_posterboard: bool = False) -> bool:
    """Mid-stream backup filter: match an upload's device-side name against the keep-set.

    Upload names carry the domain and path (e.g. ``HomeDomain/Library/...``),
    mirroring pymobiledevice3's own BackupSelectionRule matching. Rejected
    payloads are drained by the DeviceLink; their Manifest.db rows survive so
    subsequent incremental backups do not re-upload them.
    """
    for domain in (("CameraRollDomain", "MediaDomain") if include_photos else ()) + \
            ("SystemPreferencesDomain",):
        if _domain_match(device_name, domain):
            return True
    for prefix in APPLE_ID_PATH_PREFIXES + SPRINGBOARD_PATH_PREFIXES + CONTROL_CENTER_PATH_PREFIXES:
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
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                return await super().connect()
            except (_pm3_exc.ConnectionTerminatedError, ConnectionError,
                    OSError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt >= max_retries:
                    break
                delay = min(2 ** attempt, 15)
                print(
                    f"[ProtectiveBackup] mobilebackup2 connect failed "
                    f"(attempt {attempt}/{max_retries}), retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

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
        log_info('DEBUG: _add_posterboard_container called')
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
    incremental_ok: bool = False,
) -> bool:
    if not incremental_ok:
        Path(backup_root).mkdir(parents=True, exist_ok=True)

    def _filter_callback(backup_file):
        return is_protective_device_file(
            backup_file.device_name or "",
            include_photos=include_photos,
            include_posterboard=include_posterboard)

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


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


class ProtectiveBackupCache:
    """Persistent per-device cache of the protective backup master copy.

    The master keeps the FULL Manifest.db (rows for drained payloads stay put)
    so mobilebackup2 can run true incremental refreshes against it: after the
    first apply, each next apply only uploads what actually changed on the
    device. Restores never touch the master — ``make_working_copy`` builds a
    throwaway hardlink copy that gets pruned and tweak-injected instead.

    Lives in the system temp dir, so a reboot naturally invalidates it.
    """

    def __init__(self, udid: str, product_version: str, encrypted: bool = False):
        self.udid = udid
        self.product_version = product_version
        self.encrypted = encrypted
        self._temp_base = Path(tempfile.gettempdir()) / "goldennugget_protective_cache"
        self._persist_base = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache"
        self.base = self._temp_base
        self.master_root = self.base / "master"
        self.device_dir = self.master_root / self.udid
        self.info_path = self.base / f"{self.udid}.json"

    def _read_info(self) -> dict:
        try:
            with open(self.info_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def locate(self) -> Optional[dict]:
        """Find an existing master across both bases; point homes at it.

        Returns dict(base, info, age_secs) or None when no usable master.
        """
        import time as _t
        now = int(_t.time())
        for base in (self._temp_base, self._persist_base):
            info_path = base / f"{self.udid}.json"
            try:
                with open(info_path, "r", encoding="utf-8") as f:
                    info = json.load(f)
            except Exception:
                continue
            if info.get("udid") != self.udid or info.get("product_version") != self.product_version:
                continue
            if bool(info.get("encrypted", False)) != self.encrypted:
                continue
            master = base / "master" / self.udid
            required = ("Manifest.db", "Manifest.plist", "Status.plist")
            if not all((master / n).is_file() for n in required):
                continue
            if not _validate_sqlite_db(master / "Manifest.db"):
                continue
            self.base = base
            self.master_root = base / "master"
            self.device_dir = master
            self.info_path = info_path
            created = int(info.get("created_ts", now))
            return {"base": base, "info": info, "age_secs": max(0, now - created)}
        return None

    def _set_home(self, base: Path):
        self.base = base
        self.master_root = base / "master"
        self.device_dir = self.master_root / self.udid
        self.info_path = base / f"{self.udid}.json"

    def relocate_by_size(self):
        """Move the master to the persistent base once it crosses the size cap."""
        limit = CACHE_PERSIST_MIN_GB * (1024 ** 3)
        size = _dir_size_bytes(self.master_root)
        desired = self._persist_base if size >= limit else self._temp_base
        if desired == self.base:
            return
        desired.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.master_root), str(desired / "master"))
        if self.info_path.exists():
            shutil.move(str(self.info_path), str(desired / self.info_path.name))
        # drop any leftover tree at the old home
        try:
            self.base.rmdir()
        except OSError:
            pass
        self._set_home(desired)

    def has_valid_master(self) -> bool:
        return self.locate() is not None

    async def refresh(self, lockdown_client: LockdownClient, progress_callback=None,
                      include_photos: bool = True, include_posterboard: bool = False) -> str:
        """Bring the master up to the device's current state (full or incremental).

        With ``include_posterboard`` the PosterBoard container rides along, so
        after this call ``extract_posterboard_db`` yields the live on-device
        database — refreshed BEFORE extraction, never a stale copy.
        """
        valid = self.has_valid_master()
        mode = "incremental" if valid else "full"
        log_info(f"Protective backup cache: {mode} refresh for {self.udid}")
        is_encrypted = await perform_protective_backup(
            lockdown_client, str(self.master_root), progress_callback,
            include_photos=include_photos, include_posterboard=include_posterboard,
            incremental_ok=valid)

        # placement by size: big masters move to the persistent app-data
        # folder (a tmpfs /tmp costs RAM and caps their size)
        self.relocate_by_size()

        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.info_path, "w", encoding="utf-8") as f:
            json.dump({"udid": self.udid,
                       "product_version": self.product_version,
                       "encrypted": is_encrypted,
                       "created_ts": int(time.time()),
                       "created": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        return str(self.master_root)

    def make_working_copy(self) -> str:
        """Build a throwaway hardlink copy of the master for prune + injection."""
        return make_protective_working_copy(str(self.master_root), self.udid)

    def purge(self):
        shutil.rmtree(self.master_root, ignore_errors=True)
        self.info_path.unlink(missing_ok=True)


def make_protective_working_copy(backup_root: str, udid: str) -> str:
    """Build a throwaway hardlink copy of a protective backup for prune + injection.

    Hardlinks keep it near-instant and size-free; pruning unlinks orphans
    without touching the source's own files (the cache master stays intact).
    """
    working_root = Path(tempfile.mkdtemp(prefix="nugget_protective_")) / "device_backup"
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


def _is_encrypted_backup(device_dir: Path) -> bool:
    """Check if a backup directory has an encrypted Manifest.db."""
    try:
        return Mobilebackup2Service._is_encrypted_backup(device_dir)
    except Exception:
        return False


def _validate_sqlite_db(db_path: Path) -> bool:
    """Check if a file is a valid SQLite database."""
    if not db_path.exists() or db_path.stat().st_size < 100:
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        conn.close()
        return True
    except sqlite3.DatabaseError:
        return False


def _keep_protective_entry(domain: str, relative_path: str, include_photos: bool = True) -> bool:
    """Keep-set predicate shared by the plain and encrypted prune paths."""
    if domain and relative_path and (_is_protective_file(domain, relative_path, include_photos)
                                     or domain == "SystemPreferencesDomain"):
        return True
    # the domain root directory row — without it the restore agent may skip
    # the whole domain
    return domain == "SystemPreferencesDomain" and relative_path == ""


def clean_backup_for_restore(backup_dir: "str | Path", udid: str,
                             include_photos: bool = True,
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
            return _keep_protective_entry(bf.domain, bf.relative_path, include_photos)
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
            if _keep_protective_entry(domain, rel_path, include_photos):
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


def _build_mbfile_blob(relative_path: str, contents: bytes, mode: int = 33188,
                       owner: int = 501, group: int = 501) -> bytes:
    """Build a ``MBFile`` archive blob for an injected backup file.

    Matches the NSKeyedArchiver structure BackupAgent2 writes to the
    ``file`` column of Manifest.db: an ``MBFile`` object carrying the file's
    metadata plus a ``Digest`` (SHA1 of the payload) and the data-protection
    extended attribute. Mode/ownership mirror a regular mobile-owned
    HomeDomain file; the extended attribute marks the file as exempt from
    data protection by SpringBoard (same as IconState.plist and friends).
    """
    now = int(time.time())
    extended_attributes = plistlib.dumps(
        {"com.apple.dataprotection.policy.exception-applied-by": b"com.apple.springboard"},
        fmt=plistlib.FMT_BINARY,
    )
    objects = [
        "$null",
        {
            "Birth": now,
            "LastModified": now,
            "LastStatusChange": now,
            "Flags": 0,
            "GroupID": group,
            "UserID": owner,
            "Mode": mode,
            "ProtectionClass": 4,
            "Size": len(contents),
            "RelativePath": plistlib.UID(2),
            "Digest": plistlib.UID(3),
            "ExtendedAttributes": plistlib.UID(4),
            "$class": plistlib.UID(5),
        },
        relative_path,
        hashlib.sha1(contents).digest(),
        extended_attributes,
        {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
    ]
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def _patch_donor_blob(donor_blob: bytes, relative_path: str, contents: bytes,
                      mode: Optional[int] = None, owner: Optional[int] = None,
                      group: Optional[int] = None) -> bytes:
    """Re-target a real MBFile blob from the same backup for a new payload.

    Cloning a row the device itself produced guarantees byte-exact metadata
    (extended attributes, protection class) instead of risking a hand-built
    archive the restore agent might reject. Only the path, digest, size and
    (optionally) mode/ownership change.
    """
    blob = plistlib.loads(donor_blob)
    objects = blob["$objects"]
    info = objects[1]
    objects[info["RelativePath"]] = relative_path
    objects[info["Digest"]] = hashlib.sha1(contents).digest()
    info["Size"] = len(contents)
    if mode is not None:
        info["Mode"] = mode
    if owner is not None:
        info["UserID"] = owner
    if group is not None:
        info["GroupID"] = group
    return plistlib.dumps(blob, fmt=plistlib.FMT_BINARY)


def _pick_donor_blob(conn, domain: str, relative_path: str) -> "Optional[bytes]":
    """Pick a donor MBFile blob the restore agent will accept.

    The iOS 27 restore agent silently skips rows whose blob it considers
    invalid, and it deduplicates by inode. A safe donor is a regular (0644)
    file with a SpringBoard data-protection exception and a real inode:
    ``IconState.plist`` is the canonical such file in the protective scope.
    Falls back to any regular row carrying a digest, then to the old
    arbitrary-row behavior.
    """
    preferred = ("Library/SpringBoard/IconState.plist",)
    for candidate in preferred:
        row = conn.execute(
            "SELECT file FROM Files WHERE domain = ? AND relativePath = ? "
            "AND flags = 1 AND file IS NOT NULL",
            (domain, candidate),
        ).fetchone()
        if row is not None:
            return row[0]

    for candidate_flags, candidate_blob in conn.execute(
        "SELECT flags, file FROM Files WHERE domain = ? AND file IS NOT NULL "
        "AND relativePath != ? AND flags = 1",
        (domain, relative_path),
    ):
        try:
            info = plistlib.loads(candidate_blob)["$objects"][1]
            if (info.get("Mode", 0) & 0o777) == 0o644 and isinstance(
                info.get("InodeNumber"), int
            ):
                return candidate_blob
        except Exception:
            continue

    for candidate_flags, candidate_blob in conn.execute(
        "SELECT flags, file FROM Files WHERE domain = ? AND file IS NOT NULL "
        "AND relativePath != ? AND flags = 1",
        (domain, relative_path),
    ):
        try:
            info = plistlib.loads(candidate_blob)["$objects"][1]
            if "Digest" in info and "ExtendedAttributes" in info:
                return candidate_blob
        except Exception:
            continue
    return None


def _build_mbdir_blob(relative_path: str, mode: int = 16877) -> bytes:
    """Build an ``MBFile``-style archive blob for a directory row.

    Mirrors what BackupAgent2 writes for flag=2 rows (dump of the device's
    own SystemPreferencesDomain dir rows): no digest, size 0, S_IFDIR mode,
    root-owned. The device's real rows carry a real inode, so a unique one
    must be stamped by the caller.
    """
    now = int(time.time())
    objects = [
        "$null",
        {
            "Birth": now,
            "LastModified": now,
            "LastStatusChange": now,
            "Flags": 0,
            "GroupID": 0,
            "UserID": 0,
            "Mode": mode,
            "ProtectionClass": 4,
            "Size": 0,
            "RelativePath": plistlib.UID(2),
            "InodeNumber": 0,
            "$class": plistlib.UID(3),
        },
        relative_path,
        {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
    ]
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def _ensure_directory_rows(conn, domain: str, relative_dir: str) -> None:
    """Insert flags=2 directory rows for every missing path component.

    The iOS 27 restore agent skips a file whose parent directories have no
    manifest rows, so before injecting a tweak file its directory chain must
    exist in Manifest.db. Rows are cloned from a real directory blob of the
    backup (byte-exact metadata) with a unique inode; falls back to a
    hand-built blob when the backup has no directory rows at all.
    """
    donor = conn.execute(
        "SELECT file FROM Files WHERE flags = 2 AND file IS NOT NULL LIMIT 1"
    ).fetchone()
    donor_blob = donor[0] if donor else None
    inode = _max_inode_in_manifest(conn)
    rel = ""
    for component in [""] + (relative_dir.split("/") if relative_dir else []):
        if component:
            rel = f"{rel}/{component}" if rel else component
        exists = conn.execute(
            "SELECT 1 FROM Files WHERE domain = ? AND relativePath = ? AND flags = 2",
            (domain, rel),
        ).fetchone()
        if exists:
            continue
        inode += 1
        if donor_blob is not None:
            blob = plistlib.loads(donor_blob)
            objects = blob["$objects"]
            info = objects[1]
            objects[info["RelativePath"]] = rel
        else:
            blob = plistlib.loads(_build_mbdir_blob(rel))
            objects = blob["$objects"]
        objects[1]["InodeNumber"] = inode
        blob = plistlib.dumps(blob, fmt=plistlib.FMT_BINARY)
        dir_id = hashlib.sha1(f"{domain}-{rel}".encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO Files (fileID, domain, relativePath, flags, file) "
            "VALUES (?, ?, ?, ?, ?)",
            (dir_id, domain, rel, 2, sqlite3.Binary(blob)),
        )


def _max_inode_in_manifest(conn) -> int:
    """Largest inode claimed by any regular or directory row (0 when none has one)."""
    max_inode = 0
    for (candidate_blob,) in conn.execute(
        "SELECT file FROM Files WHERE flags IN (1, 2) AND file IS NOT NULL"
    ):
        try:
            ino = plistlib.loads(candidate_blob)["$objects"][1].get("InodeNumber")
            if isinstance(ino, int):
                max_inode = max(max_inode, ino)
        except Exception:
            continue
    return max_inode


def inject_file_into_backup(backup_dir: "str | Path", udid: str, domain: str,
                            relative_path: str, contents: bytes,
                            mode: Optional[int] = None,
                            owner: Optional[int] = None,
                            group: Optional[int] = None,
                            manifest_password: str = "") -> bool:
    """Add a file to a pruned backup's Manifest.db and payload store.

    The iOS 27 "safe state recovery" wipe clears HomeDomain files that were
    staged by the sparse restore but are absent from the protective backup.
    Files the tweak writes can therefore be re-added here with their *new*
    content so Phase 3's mobilebackup2 restore lays them down natively (AFC
    cannot reach HomeDomain, so that is the only reliable path on iOS 27).

    The iOS 27 restore agent requires a well-formed regular-file blob with a
    real, *unique* inode (it deduplicates by inode — a clone sharing the
    donor's inode gets restored with the donor's content, and a fresh blob
    without an inode is skipped outright). The mode is normalized to a
    regular 0644-style file so the agent accepts the row.

    The file ID follows the standard ``SHA1("<domain>-<relativePath>")``
    convention and the payload is placed in the ``<aa>/<fileID>`` layout the
    restore agent expects. Returns True when the file was added.

    Encrypted backups are NOT supported here: their payloads are written to
    disk encrypted (each with a per-file key wrapped by the manifest keybag),
    and a locally-injected plaintext payload has no matching wrapped key — the
    Phase 3 restore agent fails to decrypt it (MBErrorDomain/205). Injection
    is skipped for encrypted backups rather than corrupting the restore.
    """
    device_dir = Path(backup_dir) / udid
    if not device_dir.is_dir():
        # Tolerate backup_dir already pointing at the device directory.
        if (Path(backup_dir) / "Manifest.db").exists():
            device_dir = Path(backup_dir)
        else:
            return False

    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.exists():
        return False

    encrypted = _is_encrypted_backup(device_dir)
    if encrypted:
        # See the docstring: plaintext injection into an encrypted backup makes
        # the Phase 3 restore fail with MBErrorDomain/205.
        log_warn(f"Skipping injection into encrypted backup for {domain}/{relative_path}")
        return False

    if not _validate_sqlite_db(manifest_db):
        log_error(f"Manifest.db at {manifest_db} is not a valid SQLite database. Cannot inject file.")
        return False

    file_id = hashlib.sha1(f"{domain}-{relative_path}".encode("utf-8")).hexdigest()

    conn = sqlite3.connect(str(manifest_db))
    try:
        # The restore agent skips a file whose parent directory rows are
        # missing, so ensure the whole directory chain first.
        dir_path, _ = os.path.split(relative_path)
        _ensure_directory_rows(conn, domain, dir_path)

        # The restore agent validates the blob and deduplicates by inode:
        # pick a donor the agent accepts, then stamp a unique inode so the
        # restored file cannot be confused with the donor's own file.
        flags, blob = 1, None
        donor = _pick_donor_blob(conn, domain, relative_path)
        unique_inode = _max_inode_in_manifest(conn) + 1
        safe_mode = (mode or 33188) & 0o100777
        if safe_mode & 0o777 == 0:
            safe_mode |= 0o644
        if donor is None:
            blob = _build_mbfile_blob(
                relative_path, contents,
                mode=safe_mode, owner=owner or 501, group=group or 501)
        else:
            blob = _patch_donor_blob(
                donor, relative_path, contents,
                mode=safe_mode, owner=owner or 501, group=group or 501)
        patched = plistlib.loads(blob)
        patched["$objects"][1]["InodeNumber"] = unique_inode
        blob = plistlib.dumps(patched, fmt=plistlib.FMT_BINARY)
        payload = device_dir / file_id[:2] / file_id
        payload.parent.mkdir(parents=True, exist_ok=True)
        # The working copy hardlinks payloads back to the cache master; writing
        # through such a link would overwrite the master's pristine payload with
        # tweaked content and corrupt every later apply. Break the link first so
        # the master keeps its original bytes.
        if payload.exists() or payload.is_symlink():
            payload.unlink(missing_ok=True)
        payload.write_bytes(contents)
        conn.execute(
            "INSERT OR REPLACE INTO Files (fileID, domain, relativePath, flags, file) "
            "VALUES (?, ?, ?, ?, ?)",
            (file_id, domain, relative_path, flags, sqlite3.Binary(blob)),
        )
        conn.commit()
        ok = True
    finally:
        conn.close()

    return ok
