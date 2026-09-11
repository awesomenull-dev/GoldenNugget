"""Persistent per-device cache of the protective backup master copy.

The master keeps the FULL Manifest.db (rows for drained payloads stay put)
so mobilebackup2 can run true incremental refreshes against it: after the
first apply, each next apply only uploads what actually changed on the
device. Restores never touch the master — ``make_working_copy`` builds a
throwaway hardlink copy that gets pruned and tweak-injected instead.

The master always lives in the persistent app-data store (never the system
temp dir): it is the sole copy of user data between Phase 2 (device wipe)
and Phase 3 (restore), so it must survive reboots and crashes.
"""

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths
from pymobiledevice3.lockdown import LockdownClient

from src.restore.inject import _validate_sqlite_db

_logger = logging.getLogger("GoldenNugget.cache")

# The master always lives in the persistent app-data store — a temp-based
# master is the sole copy of user data between Phase 2 (wipe) and Phase 3
# (restore), and a reboot would destroy it.
CACHE_PERSIST_MIN_GB = float(os.environ.get("GOLDENNUGGET_CACHE_PERSIST_MIN_GB", "1"))
# A cache younger than this is reused without touching the device at all
# (only when no PosterBoard work is pending); past it, an incremental
# refresh session keeps the master in sync.
CACHE_REFRESH_SECS = int(os.environ.get("GOLDENNUGGET_CACHE_REFRESH_SECS", "1800"))


class ProtectiveBackupCache:
    """Persistent per-device cache of the protective backup master copy.

    The master keeps the FULL Manifest.db (rows for drained payloads stay put)
    so mobilebackup2 can run true incremental refreshes against it: after the
    first apply, each next apply only uploads what actually changed on the
    device. Restores never touch the master — ``make_working_copy`` builds a
    throwaway hardlink copy that gets pruned and tweak-injected instead.
    """

    def __init__(self, udid: str, product_version: str, encrypted: bool = False):
        self.udid = udid
        self.product_version = product_version
        self.encrypted = encrypted
        self._temp_base = Path(tempfile.gettempdir()) / "goldennugget_protective_cache"
        self._persist_base = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache"
        # Always use the persistent store: the master is the sole copy of the
        # user's data between Phase 2 (device wipe) and Phase 3 (restore).  A
        # reboot would destroy a temp-based master, turning a recoverable
        # failure into permanent data loss.  The old temp-based location is
        # still searched by ``locate()`` for migration of existing caches.
        self.base = self._persist_base
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
        now = int(time.time())
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
        """Legacy no-op (kept for the placement test tool).

        The master always lives in the persistent app-data store — moving it
        to the system temp on size grounds made the sole copy of user data
        volatile: a reboot between Phase 2 (wipe) and Phase 3 (restore) lost
        it forever.  There is nothing to relocate anymore.
        """

    def has_valid_master(self) -> bool:
        return self.locate() is not None

    async def refresh(self, lockdown_client: LockdownClient, progress_callback=None,
                      include_photos: bool = True, include_posterboard: bool = False,
                      include_keychain: bool = False) -> str:
        """Bring the master up to the device's current state (full or incremental).

        With ``include_posterboard`` the PosterBoard container rides along, so
        after this call ``extract_posterboard_db`` yields the live on-device
        database — refreshed BEFORE extraction, never a stale copy.
        """
        from src.restore.protective import perform_protective_backup

        valid = self.has_valid_master()
        mode = "incremental" if valid else "full"
        _logger.info(f"Protective backup cache: {mode} refresh for {self.udid}")
        is_encrypted = await perform_protective_backup(
            lockdown_client, str(self.master_root), progress_callback,
            include_photos=include_photos, include_posterboard=include_posterboard,
            include_keychain=include_keychain,
            incremental_ok=valid)

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
        from src.restore.protective import make_protective_working_copy
        return make_protective_working_copy(str(self.master_root), self.udid)

    def purge(self):
        shutil.rmtree(self.master_root, ignore_errors=True)
        self.info_path.unlink(missing_ok=True)