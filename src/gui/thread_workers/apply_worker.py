from PySide6.QtCore import Signal, QThread, QSettings
from PySide6.QtWidgets import QMessageBox
from typing import Optional
import queue
import traceback
import threading

from src.gui.pages.pages_list import Page


class ApplyAlertMessage:
    def __init__(self, txt: str, title: str = "Error!", icon=QMessageBox.Critical, detailed_txt: str = None, backup_path: str = None):
        self.txt = txt
        self.title = title
        self.icon = icon
        self.detailed_txt = detailed_txt
        self.backup_path = backup_path


class _SudoState:
    """Thread-safe sudo password storage."""
    def __init__(self):
        self._lock = threading.Lock()
        self._pwd: Optional[str] = None

    def get_pwd(self) -> Optional[str]:
        with self._lock:
            pwd = self._pwd
            self._pwd = None
            return pwd

    def set_pwd(self, pwd: Optional[str]):
        with self._lock:
            self._pwd = pwd


_sudo_state = _SudoState()


def get_sudo_pwd() -> Optional[str]:
    return _sudo_state.get_pwd()


def set_sudo_pwd(pwd: Optional[str]):
    _sudo_state.set_pwd(pwd)


class ApplyThread(QThread):
    progress = Signal(str)
    alert = Signal(object)  # ApplyAlertMessage or None for sudo prompt
    finished_with_result = Signal(bool, str)  # success, error_message
    request_text = Signal(str, str, object)  # title, label, result box (main-thread prompt)

    # Only the password prompt is guarded by a timeout. The apply/restore itself
    # is allowed to run to completion: a three-phase protective restore can
    # legitimately exceed 10 minutes waiting for the device to reboot, and
    # forcibly terminating the worker thread mid-restore (QThread.terminate)
    # would corrupt the device state.
    _PROMPT_TIMEOUT_SEC = 10 * 60

    def __init__(self, manager, settings: QSettings, reset_pages: Optional[list[Page]] = None):
        super().__init__()
        self.manager = manager
        self.settings = settings
        self.reset_pages = reset_pages
        self.success = False
        self._error_msg: str = ""

    def update_label(self, txt: str):
        if txt == 'sudo_pwd':
            self.alert.emit(None)
        else:
            self.progress.emit(txt)

    def alert_window(self, msg: ApplyAlertMessage):
        self.alert.emit(msg)

    def prompt_password(self, title: str, label: str) -> Optional[str]:
        # Modal dialogs must be built on the main thread (macOS raises
        # NSInternalInconsistencyException otherwise), so relay the request
        # through a queued signal while this worker thread blocks on a queue.
        box = queue.Queue(maxsize=1)
        self.request_text.emit(title, label, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return None

    def run(self):
        try:
            self._do_work()
            self.success = True
            self._error_msg = ""
            self.finished_with_result.emit(True, "")
        except Exception as e:
            self.success = False
            self._error_msg = f"{type(e).__name__}: {e}"
            traceback_str = traceback.format_exc()
            self.alert.emit(ApplyAlertMessage(
                f"Operation failed: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str
            ))
            self.finished_with_result.emit(False, self._error_msg)

    def _do_work(self):
        if self.reset_pages is None:
            self.manager.apply_changes(self.update_label, self.alert_window, self.prompt_password)
        else:
            self.manager.reset_tweaks(self.reset_pages, self.settings, self.update_label, self.alert_window)


class RestoreCacheThread(QThread):
    """Restore the last protective backup cache (post-failure data recovery).

    Mirrors ``apply_changes``' Phase 1+3 so a protective backup that was kept
    on disk after a wedged/failed apply can be restored standalone — e.g. when
    the iPhone was not unlocked in time and Phase 3 was aborted. Runs in a
    background thread to keep the UI responsive (the restore waits for the
    device and for the user to unlock).
    """
    progress = Signal(str)
    alert = Signal(object)
    finished_with_result = Signal(bool, str)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def update_label(self, txt: str):
        self.progress.emit(txt)

    def run(self):
        try:
            self._do_work()
            self.finished_with_result.emit(True, "")
        except Exception as e:
            traceback_str = traceback.format_exc()
            self.alert.emit(ApplyAlertMessage(
                f"Failed to restore data from backup: {e}",
                title="Restore data",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
            ))
            self.finished_with_result.emit(False, f"{type(e).__name__}: {e}")

    def _do_work(self):
        import asyncio
        asyncio.run(self._restore())

    async def _restore(self):
        import tempfile
        from pathlib import Path
        from src.restore.protective import (
            make_protective_working_copy,
            clean_backup_for_restore,
            verify_backup_payloads,
        )
        from src.restore.restore import _restore_protective_backup
        from src.devicemanagement.session import lockdown_session

        udid = self.manager.get_current_device_udid()
        if not udid:
            raise RuntimeError("No device selected.")
        self.update_label("Locating protective backup cache...")
        base = self._find_cache_base(udid)
        if base is None:
            raise RuntimeError(
                "No protective backup cache found for this device. "
                "The cache lives in a temp folder and is lost on reboot.")
        self.update_label("Building working copy of the backup...")
        working_root = await asyncio.to_thread(
            make_protective_working_copy, str(base / "master"), udid)
        removed_rows, removed_files = await asyncio.to_thread(
            clean_backup_for_restore, working_root, udid,
            manifest_password=self._backup_password())
        self.update_label(
            f"Prepared backup (-{removed_rows} pruned rows). Connecting to device...")
        missing = await asyncio.to_thread(
            verify_backup_payloads, working_root, udid,
            self._backup_password())
        if missing:
            raise RuntimeError(
                f"{len(missing)} manifest rows lack payloads; the backup is "
                f"incomplete and cannot be restored. Remove the cache and apply "
                f"again to rebuild it.")

        lc = None
        async with lockdown_session(udid) as _ld:
            lc = _ld
            # the retry loop inside _restore_protective_backup reconnects as
            # needed after the wipe-induced lock and drops
            await _restore_protective_backup(
                lc, working_root, udid, reboot=False,
                progress_callback=self._progress_cb,
                backup_password=self._backup_password(),
                skip_apps=True)
        self.update_label("Data restored successfully.")

    def _progress_cb(self, value):
        if isinstance(value, str):
            self.update_label(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self.update_label(f"Restoring... {value:.1f}%")

    def _backup_password(self) -> str:
        try:
            return self.manager._get_backup_password()
        except Exception:
            return ""

    def _find_cache_base(self, udid: str):
        from PySide6.QtCore import QStandardPaths
        import tempfile
        from pathlib import Path
        bases = []
        try:
            bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        except Exception:
            pass
        try:
            bases.append(Path(QStandardPaths.writableLocation(
                QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")
        except Exception:
            pass
        for base in bases:
            if (base / "master" / udid / "Manifest.db").is_file():
                return base
            if (base / f"{udid}.json").is_file():
                return base
        return None


class RefreshDevicesThread(QThread):
    alert = Signal(object)

    def __init__(self, manager, settings):
        super().__init__()
        self.manager = manager
        self.settings = settings

    def alert_window(self, msg: ApplyAlertMessage):
        self.alert.emit(msg)

    def run(self):
        try:
            self.manager.get_devices(self.settings, self.alert_window)
        except Exception as e:
            self.alert.emit(ApplyAlertMessage(
                f"Failed to refresh devices: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback.format_exc()
            ))