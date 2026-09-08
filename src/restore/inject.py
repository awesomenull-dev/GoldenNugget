"""Manifest.db tweak injection for the iOS 27 protective restore.

The iOS 27 "safe state recovery" wipe clears HomeDomain files that were
staged by the sparse restore but are absent from the protective backup.
Files the tweak writes can be re-added here with their *new* content so
Phase 3's mobilebackup2 restore lays them down natively (AFC cannot reach
HomeDomain, so that is the only reliable path on iOS 27).

This module is a leaf: it depends only on stdlib + pymobiledevice3 and knows
nothing about the backup/restore flow in ``protective.py``.
"""

import hashlib
import logging
import os
import plistlib
import sqlite3
import time
from pathlib import Path
from typing import Optional

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

_logger = logging.getLogger("GoldenNugget.inject")


def _is_encrypted_backup(device_dir: Path) -> bool:
    """Check if a backup directory has an encrypted Manifest.db."""
    try:
        return Mobilebackup2Service._is_encrypted_backup(device_dir)
    except Exception:
        return False


def _validate_sqlite_db(db_path) -> bool:
    """Check if a file is a valid SQLite database (accepts str or Path)."""
    if isinstance(db_path, str):
        db_path = Path(db_path)
    if not db_path.exists() or db_path.stat().st_size < 100:
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        conn.close()
        return True
    except sqlite3.DatabaseError:
        return False


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
        _logger.warning(f"Skipping injection into encrypted backup for {domain}/{relative_path}")
        return False

    if not _validate_sqlite_db(manifest_db):
        _logger.error(f"Manifest.db at {manifest_db} is not a valid SQLite database. Cannot inject file.")
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