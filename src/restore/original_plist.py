"""Original plist capture, templating, and materialization.

On a freshly restored (or clean) device, Nugget can back up the original
system plists it later overwrites. Device-specific values (model, serial,
device name, ...) are replaced with ``<Placeholder>`` keys so the templates
are shareable across any device of the same model + iOS build. When resetting
(or applying) tweaks, the placeholders are substituted back with the *current*
device's values, restoring the user's original settings instead of writing an
empty plist (which is what caused boot loops).

Capture uses the same selective mobilebackup2 mechanism as the protective
backup: files the device uploads are filtered mid-stream so only the plists we
care about (plus the backup metadata) are written to disk. The on-device
Manifest.db is then used to map ``(domain, relativePath)`` back to the
payload files.
"""

import asyncio
import plistlib
import sqlite3

from pathlib import Path
from tempfile import TemporaryDirectory

from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
from typing import Optional

from src.devicemanagement.session import lockdown_session
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from src.exceptions.nugget_exception import NuggetException
from src.restore.protective import _validate_sqlite_db, check_disk_space_for_backup

# Keys from lockdown ``all_values`` whose string values are device-specific
# and should be replaced with placeholders when templating.
_TEMPLATE_KEYS = (
    "ProductType",
    "HardwareModel",
    "HardwarePlatform",
    "ProductVersion",
    "BuildVersion",
    "DeviceName",
    "SerialNumber",
    "UniqueDeviceID",
    "RegionInfo",
    "BasebandRegionSKU",
    "DeviceClass",
    "ProductName",
    "CPUArchitecture",
    "WiFiAddress",
    "BluetoothAddress",
    "MLBSerialNumber",
    "DieID",
    "FirmwareVersion",
    "PartitionType",
)

# Absolute path prefix -> backup (domain prefix, remainder handling).
# Mirrors the mapping in DeviceManager.get_domain_for_path, but always uses
# the fully-patched domain names (independent of the sparserestore status).
_BACKUP_DOMAIN_MAPPINGS = (
    ("/var/Managed Preferences/", "ManagedPreferencesDomain", False),
    ("/var/root/", "RootDomain", False),
    ("/var/preferences/", "SystemPreferencesDomain", False),
    ("/var/MobileDevice/", "MobileDeviceDomain", False),
    ("/var/mobile/", "HomeDomain", False),
    ("/var/db/", "DatabaseDomain", False),
    ("/var/containers/Shared/SystemGroup/", "SysSharedContainerDomain-", True),
    ("/var/containers/Data/SystemGroup/", "SysContainerDomain-", True),
)


def absolute_path_to_backup_location(path: str) -> tuple[Optional[str], Optional[str]]:
    """Map an absolute device path to ``(domain, relativePath)`` as used in Manifest.db."""
    for prefix, domain, is_container in _BACKUP_DOMAIN_MAPPINGS:
        if path.startswith(prefix):
            rest = path[len(prefix):]
            if is_container:
                group, sep, rel = rest.partition("/")
                if not sep:
                    return domain + group, ""
                return domain + group, rel
            return domain, rest
    return None, None


_MANAGED_PREFERENCES_MOBILE = "/var/Managed Preferences/mobile/"


def mobile_user_fallback_path(path: str) -> Optional[str]:
    """Return the HomeDomain copy of a managed-preference file.

    A reset writes an empty dict to ``/var/Managed Preferences/mobile/*.plist``,
    permanently nulling it. The corresponding ``/var/mobile/Library/Preferences/
    *.plist`` (HomeDomain) is a separate file that resets do not touch, so it
    still holds the user's real settings — a usable fallback when the primary
    copy was already nulled before the capture ran.
    """
    if path.startswith(_MANAGED_PREFERENCES_MOBILE):
        return "/var/mobile/Library/Preferences/" + path[len(_MANAGED_PREFERENCES_MOBILE):]
    return None


def is_empty_plist(data: bytes) -> bool:
    """True when ``data`` parses as an empty plist dict.

    The nulled plists written by resets are exactly ``{}`` — capturing one as
    an "original" would make every later reset restore the nulled state.
    """
    try:
        return plistlib.loads(data) == {}
    except Exception:
        return False


def _walk(obj, transform):
    if isinstance(obj, dict):
        return {k: _walk(v, transform) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, transform) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_walk(v, transform) for v in obj)
    return transform(obj)


def materialize_plist(plist, device_values: dict[str, str]):
    """Substitute ``<Key>`` placeholders back with the current device's values."""
    def transform(value):
        if (isinstance(value, str) and value.startswith("<") and value.endswith(">")
                and len(value) > 2):
            key = value[1:-1]
            replacement = device_values.get(key)
            if replacement:
                return replacement
        return value

    return _walk(plist, transform)


async def psysbackup(
    udid: str,
    paths: list[str],
    update_label=lambda x: None,
    update_progress=lambda x: None,
    backup_password: str = "",
) -> dict[str, bytes]:
    """Capture and template the given absolute plist paths from the device.

    Returns a dict of ``absolute_path -> templated bytes`` for the files that
    exist on the device and parse as plists.

    The capture runs a full mobilebackup2 backup (a filtered backup makes the
    device abort with ``Manifest references files not in backup``), then reads
    the wanted payloads straight from the on-device Manifest.db. The backup is
    kept in a temporary directory that is removed when done.

    If backup_password is provided and the device has encryption enabled,
    it will be used to decrypt the backup manifest.
    """
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.exceptions.device_errors import is_connection_error as _is_connection_error

    update_label("Backing up device to capture original plists...")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            async with lockdown_session(udid) as ld:
                if attempt == 1:
                    await check_disk_space_for_backup(ld)
                # Check if backup encryption is enabled on device
                is_encrypted = False
                try:
                    async with Mobilebackup2Service(ld) as backup_client:
                        is_encrypted = await backup_client.get_will_encrypt()
                except Exception:
                    pass

                if is_encrypted:
                    if backup_password:
                        update_label("Backup encryption enabled — using provided password to decrypt manifest...")
                        print("[psysbackup] Backup encryption enabled, using provided password to decrypt manifest")
                    else:
                        # Can't read encrypted manifest without password - skip snapshot
                        update_label("Backup encryption enabled — skipping pre-apply snapshot (auto-revert unavailable).")
                        print("[psysbackup] Backup encryption enabled on device, skipping pre-apply snapshot (cannot read encrypted manifest without password)")
                        return {}

                with TemporaryDirectory() as tmp_dir:
                    async with Mobilebackup2Service(ld) as backup_client:
                        try:
                            await backup_client.backup(
                                full=True,
                                backup_directory=tmp_dir,
                                progress_callback=update_progress,
                                password=backup_password,
                            )
                        except NotEnoughDiskSpaceError:
                            raise NuggetException(
                                "Not enough free disk space on the computer for "
                                "the pre-reset capture. Free up space (previous "
                                "protective backups in the temp dir count against "
                                "it) and try again.")
                        except Exception as e:
                            if _is_device_locked_error(e):
                                update_label("Device locked during backup. Please unlock your device and keep it awake (tap screen periodically), then click Retry.")
                                raise NuggetException("Device locked during backup. Please unlock your device, keep it awake, and try again.")
                            if _is_connection_error(e) and attempt < max_retries:
                                delay = min(2 ** attempt, 15)
                                update_label(f"Connection lost, retrying in {delay}s... (attempt {attempt}/{max_retries})")
                                await asyncio.sleep(delay)
                                continue
                            raise
                    return _read_originals(Path(tmp_dir) / udid, paths)
        except NuggetException:
            raise
        except Exception as e:
            if _is_connection_error(e) and attempt < max_retries:
                continue
            raise
        # lockdown_session closes the connection safely on every path


def _read_originals(device_dir: Path, paths: list[str]) -> dict[str, bytes]:
    manifest = device_dir / "Manifest.db"
    if not manifest.exists():
        raise NuggetException("Could not find the backup manifest (Manifest.db).")
    if not _validate_sqlite_db(manifest):
        raise NuggetException("Backup manifest (Manifest.db) is not a valid SQLite database. The backup may have failed or been interrupted.")
    conn = sqlite3.connect(str(manifest))
    try:
        rows = conn.execute("SELECT fileID, domain, relativePath FROM Files").fetchall()
    finally:
        conn.close()
    lookup = {(domain, rel): file_id for file_id, domain, rel in rows}

    result = {}
    for path in paths:
        domain, rel = absolute_path_to_backup_location(path)
        if domain is None:
            continue
        file_id = lookup.get((domain, rel))
        if not file_id:
            continue
        payload = device_dir / file_id[:2] / file_id
        if not payload.exists():
            continue
        data = payload.read_bytes()
        try:
            plistlib.loads(data)
        except Exception:
            print(f"Skipping non-plist original: {path}")
            continue
        result[path] = data
    return result
