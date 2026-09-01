from os import path, makedirs, remove, listdir
import shutil
import sqlite3
import json
import time
from PySide6.QtCore import QStandardPaths
from typing import Optional

from src.exceptions.nugget_exception import NuggetException
from src.controllers.files_handler import get_bundle_files
from src.devicemanagement.preference_manager import PreferenceManager
from src.restore.protective import log_warn
from .pb_config_item import PBConfigItem


def _list_tables(db_path: str) -> list[str]:
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        return tables
    except sqlite3.DatabaseError:
        return []


def _validate_posterboard_db(db_path: str, strict: bool = True) -> bool:
    """Check if a file is a valid PosterBoard SQLite database.

    strict=True requires the classic table set (pre-db5 schema).
    strict=False accepts any healthy database that carries poster-ish
    tables — the schema may change between iOS releases (db5+).
    """
    if not path.exists(db_path) or path.getsize(db_path) < 100:
        return False
    try:
        conn = sqlite3.connect(db_path)
        # First check it's a valid SQLite database
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        cursor = conn.cursor()
        if strict:
            tables_to_check = ["poster", "posterAttributes", "posterRoleMembership", "sqlite_sequence"]
            for tab in tables_to_check:
                cursor.execute(f"PRAGMA table_info({tab})")
                if cursor.fetchone() is None:
                    log_warn(f"PosterBoard DB validation: missing table '{tab}' "
                             f"(tables present: {_list_tables(db_path)})")
                    conn.close()
                    return False
        else:
            tables = [t.lower() for t in _list_tables(db_path)]
            if not any("poster" in t for t in tables):
                log_warn(f"PosterBoard DB validation: no poster-ish tables (present: {tables})")
                conn.close()
                return False
        # Check database integrity
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        if result is None or result[0] != "ok":
            conn.close()
            return False
        conn.close()
        return True
    except sqlite3.DatabaseError:
        return False
    except Exception:
        return False


def _is_encrypted_database(db_path: str) -> bool:
    """Check if a database file appears to be encrypted (SQLCipher) or unreadable."""
    if not path.exists(db_path) or path.getsize(db_path) < 100:
        return False
    try:
        # Try to open as regular SQLite first
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        conn.close()
        return False
    except sqlite3.DatabaseError as e:
        # Check if it's an encryption-related error
        err_msg = str(e).lower()
        if "encrypted" in err_msg or "not a database" in err_msg or "file is not a database" in err_msg:
            return True
        return False
    except Exception:
        return False

DB_FILE_NAME = "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"

class PBConfigManager:
    def __init__(self):
        self.staging = False
        self.saved_items: list[PBConfigItem] = []
        self.staged_items: list[PBConfigItem] = []
        self.database = None
        self.staged_database = None
        self.config_files: list[str] = []
        self.config_files_folder: Optional[str] = None

    def start_staging(self):
        self.staged_items.clear()
        if self.staged_database != None and path.exists(self.staged_database):
            try:
                remove(self.staged_database)
            except Exception:
                pass
        self.staged_database = None
        self.staging = True
    def cleanup(self):
        self.staged_items.clear()
        self.staging = False
    def add_config(self, uuid: str, ext: str):
        new_conf = PBConfigItem(uuid, ext, set_selected=True)
        self.staged_items.append(new_conf)

    def cache_config_files(self):
        # cache the files for config conversion
        if len(self.config_files) == 0:
            self.config_files_folder = get_bundle_files("files/posterboard/configconversion")
            for item in listdir(self.config_files_folder):
                self.config_files.append(path.basename(item))
    def file_needs_updated(self, filename: str) -> bool:
        if not filename.endswith(".plist"):
            return False
        self.cache_config_files()
        if filename in self.config_files:
            return True
        return False
    
    def save_staged_ids(self, udid: str):
        if self.staging:
            PreferenceManager.save_pbconfig_ids(self.staged_items, udid)
            self.saved_items = self.staged_items
            self.cleanup()
    
    def update_for_saved_database(self, udid: str) -> bool:
        db_data = PreferenceManager.get_pbconfig_path(udid)
        if db_data is None:
            self.database = None
            self.staged_database = None
            return False

        # Validate the saved database before using it
        if not _validate_posterboard_db(db_data):
            log_warn(f"Saved PosterBoard database for {udid} is corrupted or invalid, removing it")
            # Remove the corrupted database and ids
            PreferenceManager.remove_pbconfig_data(udid)
            PreferenceManager.remove_pbconfig_ids(udid)
            self.database = None
            self.staged_database = None
            return False

        self.database = db_data
        # get the list of saved ids
        self.saved_items = PreferenceManager.get_pbconfig_ids(udid)
        return True

    def update_database_file(self, new_db: str, udid: str) -> bool:
        # make sure it has the tables: "poster", "posterAttributes", "posterRoleMembership", and "sqlite_sequence"
        # copy to a writeable path
        app_data_path = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not path.exists(app_data_path):
            makedirs(app_data_path)
        dbpath = path.join(app_data_path, DB_FILE_NAME)

        # Validate source database before copying
        if _is_encrypted_database(new_db):
            raise NuggetException(
                "The PosterBoard database from the backup appears to be encrypted. "
                "Please disable backup encryption on your device (Settings > General > "
                "Transfer or Reset iPhone > Erase All Content and Settings is NOT needed; "
                "just uncheck 'Encrypt local backup' in Finder/iTunes and create a new backup) "
                "and try again."
            )

        if not (_validate_posterboard_db(new_db) or _validate_posterboard_db(new_db, strict=False)):
            tables = _list_tables(new_db)
            log_warn(f"PosterBoard DB rejected; sqlite_master contains: {tables}")
            raise NuggetException(
                "The PosterBoard database from the backup is corrupted or invalid. "
                "This can happen if the backup was interrupted. "
                "Please create a fresh backup of your device and try again."
            )

        shutil.copyfile(new_db, dbpath)

        # Validate the copied database
        if not _validate_posterboard_db(dbpath):
            raise NuggetException(
                "Failed to create a valid copy of the PosterBoard database. "
                "The backup file may be corrupted. Please create a fresh backup and try again."
            )

        # make sure it has the tables
        db_connection = sqlite3.connect(dbpath)
        db_cursor = db_connection.cursor()
        tables_to_check = ["poster", "posterAttributes", "posterRoleMembership", "sqlite_sequence"]
        for tab in tables_to_check:
            db_cursor.execute(f"PRAGMA table_info({tab})")
            if db_cursor.fetchone() is None:
                db_connection.close()
                return False
        # check the saved ids
        final_saved_items: list[PBConfigItem] = []
        for item in self.saved_items:
            # TODO: Remove if not in current configuration
            try:
                db_cursor.execute("SELECT * FROM poster WHERE UUID = ?", (item.uuid,))
                sort_keys = db_cursor.fetchall()
                if sort_keys is None or len(sort_keys) == 0:
                    final_saved_items.append(item)
            except Exception:
                print("Error executing database sequence, ignoring.")
        self.saved_items = final_saved_items
        # it is correct format, update database
        db_connection.close()
        self.database = dbpath
        if udid is not None:
            # save the database
            PreferenceManager.save_pbconfig_file(dbpath, udid)
            PreferenceManager.save_pbconfig_ids(self.saved_items, udid)
        return True

    def update_sqlite(self) -> str:
        # Append a new wallpaper row for every staged tendie. posterId starts
        # ABOVE the current MAX(posterId) so deleted rows can never leave a
        # colliding id behind (the old "sqlite_sequence seq + 1" scheme could
        # clash and corrupt the on-device database).
        # in "poster" table, add new entry:
        #   posterId = max(existing posterId) + position
        #   UUID = uuid of wallpaper
        #   providerId = extension string
        # in "posterAttributes" table, add new entry:
        #   posterUUID = uuid of wallpaper
        #   roleId = "PRPosterRoleLockScreen"
        #   attributeIdentifier = "PRPosterRoleAttributeTypeUsageMetadata"
        #   attributePayload = {"creationDate":1771975981.427938,"extensionAvailable":true,"attributeType":"PRPosterRoleAttributeTypeUsageMetadata"}
        # in "posterRoleMembership" table, add new entry:
        #   posterUUID = uuid of wallpaper
        #   roleId = "PRPosterRoleLockScreen"
        #   roleSortKey = # of highest sort key + 1
        if self.database is None:
            raise NuggetException("PosterBoard database file not selected!")

        # Validate the database before use
        if not _validate_posterboard_db(self.database):
            raise NuggetException(
                "The PosterBoard database is corrupted or invalid. "
                "This can happen if the backup was interrupted or the database was modified externally. "
                "Please fetch a fresh database from your device and try again."
            )

        # copy and open database file
        self.staged_database = path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), f'STAGED-{DB_FILE_NAME}')
        shutil.copyfile(self.database, self.staged_database)

        # Validate the staged copy
        if not _validate_posterboard_db(self.staged_database):
            raise NuggetException(
                "Failed to create a valid copy of the PosterBoard database for staging. "
                "The source database may be corrupted. Please fetch a fresh database and try again."
            )

        conn = sqlite3.connect(self.staged_database, timeout=10)
        try:
            cursor = conn.cursor()
            # insert ABOVE the current max posterId: the old "sqlite_sequence
            # seq + 1" scheme collides (primary-key clash -> failed apply or a
            # corrupted on-device database) whenever rows were deleted and the
            # stored sequence has drifted from the real max.
            cursor.execute("SELECT MAX(posterId) FROM poster")
            row = cursor.fetchone()
            max_poster_id = int(row[0]) if row and row[0] is not None else 0
            seq = max_poster_id
            # get the poster role sort key (falls back to seq)
            cursor.execute("SELECT roleSortKey FROM posterRoleMembership WHERE roleId = ?", ("PRPosterRoleLockScreen",))
            sort_keys = cursor.fetchall()
            try:
                curr_role_sort_key = max((key[0] for key in sort_keys), default=seq)
            except Exception:
                curr_role_sort_key = seq
            # remove the currently selected wallpaper
            cursor.execute("DELETE FROM posterAttributes WHERE roleId = ? AND attributeIdentifier = ? AND attributePayload = ?",
                           ("PRPosterRoleLockScreen", "SELECTED", 1))
            # combine the saved items
            self.staged_items = self.saved_items + self.staged_items
            for wallpaper in self.staged_items:
                seq += 1
                wallpaper.posterId = seq
                cursor.execute("INSERT INTO poster (posterId, UUID, providerId) VALUES (?, ?, ?)",
                               (wallpaper.posterId, wallpaper.uuid, wallpaper.extension))
                # TODO: Figure out when you need to add PRPosterRoleAmbient
                wallpaper_payload = json.dumps(
                    {
                        "creationDate": time.time(),
                        "extensionAvailable": True,
                        "attributeType": "PRPosterRoleAttributeTypeUsageMetadata",
                        "lastActivatedDate": time.time() + 0.0001,
                        "lastSelectedDate": time.time() + 0.00001,
                    },
                    separators=(",", ":"),
                )
                if wallpaper.set_selected:
                    cursor.execute("INSERT INTO posterAttributes (posterUUID, roleId, attributeIdentifier, attributePayload) VALUES (?, ?, ?, ?)",
                                (wallpaper.uuid, "PRPosterRoleLockScreen", "SELECTED", 1))
                cursor.execute("INSERT INTO posterAttributes (posterUUID, roleId, attributeIdentifier, attributePayload) VALUES (?, ?, ?, ?)",
                               (wallpaper.uuid, "PRPosterRoleLockScreen", "PRPosterRoleAttributeTypeUsageMetadata",
                                wallpaper_payload))
                curr_role_sort_key += 1
                cursor.execute("INSERT INTO posterRoleMembership (posterUUID, roleId, roleSortKey) VALUES (?, ?, ?)",
                               (wallpaper.uuid, "PRPosterRoleLockScreen", curr_role_sort_key))
            # keep sqlite_sequence in sync; recreate the row if it is missing
            cursor.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                           (seq, "poster"))
            if cursor.rowcount == 0:
                cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                               ("poster", seq))
            conn.commit()
        finally:
            conn.close()
        return self.staged_database