"""Standalone PosterBoard database backup.

Two mechanisms, both kept GUI-independent so the backend apply path
(``device_manager._backup_posterboard_database``) needs no GUI imports:

* ``backup_posterboard_database`` — LEGACY: backs up the whole device and
  extracts the PosterBoard SQLite file. Only safe as a fallback now.
* ``targeted_posterboard_database_backup`` — modern channel: backs up ONLY the
  PosterBoard container (everything else the device uploads is drained
  mid-stream, never written to disk) and hands back a WAL-merged copy of the
  sqlite. This is what iOS 26 applies use instead of the full Phase 0 backup.

``src/gui/dialogs/pb_dialog.py`` imports the legacy function for its
"Fetch Database File" wizard.
"""

import os
import sqlite3
import tempfile

from PySide6.QtCore import QStandardPaths

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from src.devicemanagement.session import lockdown_session
from src.restore.protective import check_disk_space_for_backup, _validate_sqlite_db
from src.exceptions.nugget_exception import NuggetException
from src.devicemanagement.constants import is_supported_by_fork
from src.utils.async_retry import async_retry


async def backup_posterboard_database(udid: str, update_label=lambda x: None, update_progress=lambda x: None) -> str:
    """Back up the device and return the extracted PosterBoard sqlite db path."""
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.exceptions.device_errors import is_connection_error as _is_connection_error

    app_data_path = os.path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), 'Backups')
    if not os.path.exists(app_data_path):
        os.makedirs(app_data_path)
    backup_folder = os.path.join(app_data_path, udid)
    # check if a full backup is needed (makes it faster)
    needs_full = False
    if os.path.exists(backup_folder):
        files_to_verify = ["Info.plist", "Manifest.db", "Manifest.plist", "Status.plist"]
        for file in files_to_verify:
            if not os.path.exists(os.path.join(backup_folder, file)):
                needs_full = True
                break

    max_retries = 3

    async def _attempt():
        async with lockdown_session(udid) as service_provider:
            # hard-block fetching the database from an unsupported (old) iOS version
            if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                raise NuggetException(
                    "This version of iOS is not supported by this fork.\n\n"
                    "GoldenNugget only supports iOS 26.2 and newer. "
                    "Please use the original Nugget for iOS 26.1 and earlier.")
            async with Mobilebackup2Service(service_provider) as backup_client:
                try:
                    await backup_client.backup(full=needs_full, backup_directory=app_data_path, progress_callback=update_progress)
                except Exception as e:
                    if _is_device_locked_error(e):
                        raise NuggetException("Device locked during backup. Please unlock your device, keep it awake (tap screen periodically), and try again.")
                    raise

    async with lockdown_session(udid) as service_provider:
        await check_disk_space_for_backup(service_provider, path=app_data_path)

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        if attempt < total:
            update_label(f"Connection lost, retrying in {delay}s... (attempt {attempt}/{max_retries})")

    await async_retry(
        _attempt,
        max_retries,
        retry_if=_is_connection_error,
        exp_cap=15,
        on_retry=_on_retry,
    )

    # get the file, reading the sqlite db first to get the file id
    update_label("Getting the file...")
    db_path = os.path.join(backup_folder, "Manifest.db")
    if not _validate_sqlite_db(db_path):
        raise NuggetException("Backup manifest (Manifest.db) is not a valid SQLite database. The backup may have failed or been interrupted.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # resolve by file name: the store dir's structure version varies by iOS
    cursor.execute(
        "SELECT fileID FROM Files WHERE domain = ? AND relativePath LIKE ? ORDER BY relativePath DESC",
        ("AppDomain-com.apple.PosterBoard",
         "%PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"))
    fileID = cursor.fetchone()
    conn.close()
    if fileID is None or len(fileID) == 0:
        raise NuggetException("Could not find sqlite database in the backup!")
    fileID = fileID[0]
    db_file_path = os.path.join(backup_folder, fileID[:2], fileID)
    if not os.path.exists(db_file_path):
        raise NuggetException("The database file doesn't exist!")
    return db_file_path


async def targeted_posterboard_database_backup(udid: str, update_label=lambda x: None,
                                               update_progress=lambda x: None) -> str:
    """Back up ONLY the PosterBoard container and return the merged sqlite path.

    The PosterBoard delivery channel for iOS 26 applies: there is no Phase 0
    protective backup there (the restore is a plain sparse pass, nothing gets
    restored), so this pulls just the ``AppDomain-com.apple.PosterBoard``
    database off the device. The factory info lists only that container and the
    mid-stream filter drops every other file the device uploads, so the run
    stays small on disk and fast — no photos, contacts or settings are ever
    written here. Returns the extracted (WAL-merged) database path.
    """
    from src.exceptions.device_errors import is_connection_error as _is_connection_error
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.restore.protective import (
        POSTERBOARD_DB_DOMAIN, ProtectiveBackupService, _domain_match,
        _posterboard_db_match, extract_posterboard_db)

    app_data_path = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    pb_dir = os.path.join(app_data_path, "PosterBoard")
    if not os.path.exists(pb_dir):
        os.makedirs(pb_dir)
    dest_path = os.path.join(pb_dir, f"{udid}.sqlite3")

    max_retries = 3

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        if attempt < total:
            update_label(f"Connection lost, retrying in {delay}s... (attempt {attempt}/{max_retries})")

    async def _attempt():
        # hard-block fetching the database from an unsupported (old) iOS version
        with tempfile.TemporaryDirectory(prefix="nugget_pb_only_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                    raise NuggetException(
                        "This version of iOS is not supported by this fork.\n\n"
                        "GoldenNugget only supports iOS 26.2 and newer. "
                        "Please use the original Nugget for iOS 26.1 and earlier.")
                async with ProtectiveBackupService(service_provider, include_posterboard=True) as backup_client:
                    def _pb_only(backup_file):
                        # iOS 26: domain-qualified names (AppDomain-com.apple.PosterBoard/...);
                        # iOS 27: raw file-tree names (/.b/<n>/Containers/...). Match both.
                        device_name = backup_file.device_name or ""
                        return (_domain_match(device_name, POSTERBOARD_DB_DOMAIN)
                                or _posterboard_db_match(device_name))
                    try:
                        await backup_client.backup(
                            full=True, backup_directory=backup_dir,
                            progress_callback=update_progress, filter_callback=_pb_only)
                    except Exception as e:
                        if _is_device_locked_error(e):
                            raise NuggetException(
                                "Device locked during backup. Please unlock your device, "
                                "keep it awake (tap screen periodically), and try again.")
                        raise
            update_label("Getting the file...")
            db_path = extract_posterboard_db(backup_dir, udid, dest_path)
            if db_path is None:
                raise NuggetException(
                    "Could not find the PosterBoard database in the backup!")
            return db_path

    return await async_retry(
        _attempt, max_retries, retry_if=_is_connection_error,
        exp_cap=15, on_retry=_on_retry)