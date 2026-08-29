#!/usr/bin/env python3
"""Restore the last protective backup cache to the device.

After a failed/wedged apply (e.g. the iPhone was not unlocked in time and
Phase 3 was aborted), the protective backup that protects the user's data is
kept on disk. Normally it is only restored automatically as part of a full
apply. This script lets you restore it standalone, so you can recover the
user's data after the iOS 27 "safe state recovery" wipe without re-running a
whole apply.

It does the same thing GoldenNugget does internally for a restore:
  1. locate the cache master for the device (temp or persistent bases),
  2. build a throwaway hardlink working copy,
  3. prune Manifest.db down to the protective payloads (so rows that were
     drained mid-stream and have no payload cannot fail with MBErrorDomain/205),
  4. wait for the device to be reachable and unlocked,
  5. restore via mobilebackup2, retrying and waiting for the unlock while
     the user unlocks the phone.

Usage:
    python3 restore_cache.py                 # restore for the first connected device
    python3 restore_cache.py --udid UDID     # restore for a specific device
    python3 restore_cache.py --password XXXX # backup password (encrypted caches)
    python3 restore_cache.py --cache-root /path  # override cache base (debug)
    python3 restore_cache.py --timeout 20    # minutes to wait for unlock
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6 import QtCore  # noqa: E402  (QStandardPaths used by the cache)
from pymobiledevice3.lockdown import create_using_usbmux  # noqa: E402
from pymobiledevice3 import usbmux  # noqa: E402
from pymobiledevice3.exceptions import (  # noqa: E402
    PasswordRequiredError, DeviceNotFoundError, NotPairedError,
    ConnectionFailedError, ConnectionTerminatedError, PyMobileDevice3Exception,
)

from src.restore.protective import (  # noqa: E402
    ProtectiveBackupCache,
    make_protective_working_copy,
    clean_backup_for_restore,
    verify_backup_payloads,
    log_info, log_warn, log_error,
)
from src.restore.restore import (  # noqa: E402
    _restore_protective_backup,
)
from src.restore.skip_setup27 import skip_all_setup27  # noqa: E402
from src.restore import reboot_device  # noqa: E402


async def _list_connected_devices_async() -> list:
    """Return the UDIDs of every device visible to usbmuxd (awaitable)."""
    try:
        devs = [d for d in await usbmux.list_devices()]
    except Exception:
        devs = []
    out = []
    for d in devs:
        udid = getattr(d, "udid", None) or getattr(d, "serial", None)
        if udid:
            out.append(udid)
    return sorted(set(out))


def _list_connected_devices() -> list:
    """Synchronous wrapper of ``_list_connected_devices_async``.

    Only for callers OUTSIDE a running event loop (skip_setup.py,
    apply_wallpaper.py). Code inside an async function must use
    ``await _list_connected_devices_async()`` instead.
    """
    return asyncio.run(_list_connected_devices_async())


async def _find_cache_udid(preferred: str, cache_root: str | None):
    """Pick a candidate udid to attempt restoring from."""
    bases = []
    if cache_root:
        bases.append(Path(cache_root))
    else:
        bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        bases.append(
            Path(QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")

    # candidates for udid
    cached_udids = []
    for base in bases:
        info_dir = base
        if info_dir.is_dir():
            for p in sorted(info_dir.glob("*.json")):
                # filename is <udid>.json
                cached_udids.append(p.stem)
        master_dir = base / "master"
        if master_dir.is_dir():
            for udid_dir in master_dir.iterdir():
                if udid_dir.is_dir():
                    cached_udids.append(udid_dir.name)
    cached_udids = list(dict.fromkeys(cached_udids))

    connected = await _list_connected_devices_async()

    if preferred:
        return preferred
    # prefer a cached udid that is also connected
    for u in cached_udids:
        if u in connected:
            return u
    # any connected device
    if connected:
        return connected[0]
    # only a cached udid exists (device not enumerated yet)
    if cached_udids:
        return cached_udids[0]
    return None


def _pick_base(cache_root: str | None, udid: str):
    bases = []
    if cache_root:
        bases.append(Path(cache_root))
    else:
        bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        bases.append(
            Path(QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")
    for base in bases:
        json_path = base / f"{udid}.json"
        if json_path.is_file():
            return base
    # master may exist without json
    for base in bases:
        if (base / "master" / udid / "Manifest.db").is_file():
            return base
    return None


async def _restore_with_wait(lc, backup_root: str, udid: str, backup_password: str,
                             unlock_timeout_min: int, progress_callback):
    """Restore, retrying on transient errors and WAITING for the unlock.

    This is the standalone version of Phase 3 that does not give up on the
    first PasswordRequiredError — it keeps waiting up to ``unlock_timeout_min``
    for the user to unlock the device, since an iOS 27 wipe restore needs the
    phone unlocked to run.
    """
    import ssl
    import time

    from src.restore.restore import _is_transient_restore_error  # noqa: E401

    start = time.monotonic()
    deadline = start + unlock_timeout_min * 60
    attempt = 0
    transmit = (DeviceNotFoundError, NotPairedError, ConnectionFailedError,
                ConnectionTerminatedError, PyMobileDevice3Exception,
                ssl.SSLError, OSError)
    while True:
        attempt += 1
        try:
            await _restore_protective_backup(
                lc, backup_root, udid, reboot=False,
                progress_callback=progress_callback,
                backup_password=backup_password,
                skip_apps=True)
            return
        except PasswordRequiredError:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise
            progress_callback(
                f"iPhone is LOCKED - unlock it to continue "
                f"(waiting up to {remaining // 60}:{remaining % 60:02d} remaining)...")
            # reconnect after unlocking (the lockdown service may drop)
            try:
                lc.close()
            except Exception:
                pass
            await asyncio.sleep(5)
            try:
                lc = await create_using_usbmux(serial=udid, autopair=False)
            except Exception:
                lc = await create_using_usbmux(serial=udid, autopair=True)
            continue
        except transmit as e:
            if not _is_transient_restore_error(e):
                progress_callback(f"Restore error ({type(e).__name__}): {e}")
                raise
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise
            progress_callback(
                f"Device not ready, retrying... ({attempt}) "
                f"({remaining // 60}:{remaining % 60:02d} remaining)")
            await asyncio.sleep(3)


async def run(args) -> int:
    udid = args.udid
    udid = await _find_cache_udid(udid, args.cache_root)
    if not udid:
        print("ERROR: no device and no cached backup found.")
        print("Connect the iPhone over USB or pass --udid.")
        return 1
    print(f"Using UDID: {udid}")

    base = _pick_base(args.cache_root, udid)
    if base is None:
        print(f"ERROR: no protective cache found for {udid}.")
        print("Looked in temp + app-data cache bases.")
        return 1
    print(f"Cache base: {base}")

    # build a restorable (pruned) working copy from the master
    try:
        working_root = await asyncio.to_thread(
            make_protective_working_copy, str(base / "master"), udid)
    except Exception as e:
        print(f"ERROR: could not copy cache master: {e}")
        return 1
    print(f"Working copy: {working_root}")

    # prune manifest to protective payloads so no mid-stream-drained row can
    # fail the restore with MBErrorDomain/205
    removed_rows, removed_files = await asyncio.to_thread(
        clean_backup_for_restore, working_root, udid,
        manifest_password=args.password or "")
    print(f"Pruned: -{removed_rows} manifest rows, -{removed_files} payload files")

    missing = await asyncio.to_thread(
        verify_backup_payloads, working_root, udid, args.password or "")
    if missing:
        log_error(f"{len(missing)} manifest rows lack payloads "
                  f"(e.g. {missing[:5]}) - Phase 3 will likely fail with MBErrorDomain/205")

    def progress_cb(value):
        if isinstance(value, str):
            print(f"  {value}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            print(f"  {value:.1f}%")

    print("Waiting for device (unlock it when prompted)...")
    try:
        print("Connecting to the device...")
        lc = None
        try:
            lc = await create_using_usbmux(serial=udid, autopair=False)
        except Exception:
            lc = await create_using_usbmux(serial=udid, autopair=True)
        print("Connected. Restoring protective backup...")
        await _restore_with_wait(lc, working_root, udid,
                                 args.password or "", args.timeout,
                                 progress_cb)
        print("\nSUCCESS: protective backup restored.")
        # Phase 5 (mirrors _restore_ios27): skip setup panes, then reboot so
        # the restored data + skip-setup actually take effect on iOS 27+.
        try:
            if not args.no_skip_setup:
                print("Applying skip setup panes...")
                await skip_all_setup27(lc, udid)
                print("Skip setup applied.")
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: skip setup failed (data is still restored): {type(e).__name__}: {e}")
        if not args.no_reboot:
            print("Rebooting device...")
            try:
                await reboot_device(reboot=True, lockdown_client=lc)
                print("Reboot command sent.")
            except Exception as e:  # noqa: BLE001
                print(f"WARNING: reboot failed, please reboot manually: {type(e).__name__}: {e}")
        print("Your device should now be back at the lock screen with your data.")
        return 0
    except DeviceNotFoundError as e:
        print(f"\nERROR: device not reachable: {e}")
        print("Make sure it is connected via USB and the screen is unlocked.")
        return 2
    except PasswordRequiredError as e:
        print(f"\nERROR: timed out waiting for unlock: {e}")
        print("The backup is preserved on disk - unlock the phone and run this "
              "script again to finish restoring.")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR: restore failed: {type(e).__name__}: {e}")
        return 4


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", help="device UDID (default: auto-detect)")
    parser.add_argument("--password", help="backup password (for encrypted caches)")
    parser.add_argument("--cache-root", help="override cache base directory")
    parser.add_argument("--timeout", type=int, default=20,
                        help="minutes to wait for the unlock (default: 20)")
    parser.add_argument("--no-skip-setup", action="store_true",
                        help="do not apply skip-setup panes after restoring (Phase 5)")
    parser.add_argument("--no-reboot", action="store_true",
                        help="do not reboot the device after restoring (Phase 5)")
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
