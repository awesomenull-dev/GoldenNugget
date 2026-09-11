"""Legacy standalone PosterBoard database backup.

Backs up the whole device and extracts the PosterBoard SQLite database file,
used when the posterboard container could not be carried inside the protective
backup (device rejected the container / encrypted backup). Lives here so the
backend apply path (``device_manager._backup_posterboard_database``) does not
depend on the GUI package; ``src/gui/dialogs/pb_dialog.py`` imports it too.
"""

import os
import sqlite3

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