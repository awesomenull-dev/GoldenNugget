#!/usr/bin/env python3
"""Offline test for the protective backup cache (no device needed).

Exercises: cache validity, hardlink working copies, prune interplay,
PosterBoard DB extraction. Run: python tools/test_protective_cache.py
"""
import os
import plistlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.protective import (
    ProtectiveBackupCache,
    clean_backup_for_restore,
    make_protective_working_copy,
)

UDID = "00008101-TESTUDID"
PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def make_manifest(device_dir: Path, rows):
    """rows: list of (domain, relative_path, payload_bytes or None, flags)."""
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    import hashlib
    for domain, rel, payload, *rest in rows:
        flags = rest[0] if rest else 1
        file_id = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        if payload is not None:
            pdir = device_dir / file_id[:2]
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / file_id).write_bytes(payload)
        conn.execute("INSERT OR REPLACE INTO Files VALUES (?, ?, ?, ?, NULL)", (file_id, domain, rel, flags))
    conn.commit()
    conn.close()


def main():
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="gn_cache_test_"))
    base = tmp / "cache"

    # --- build a fake master via the real cache paths ---
    cache = ProtectiveBackupCache(UDID, product_version="27.0")
    # redirect both bases into our temp dir (locate() scans them)
    cache._temp_base = tmp / "cache"
    cache._persist_base = tmp / "persist"
    cache.base = cache._temp_base
    cache.master_root = cache._temp_base / "master"
    cache.device_dir = cache.master_root / UDID
    cache.info_path = cache._temp_base / f"{UDID}.json"
    cache.device_dir.mkdir(parents=True, exist_ok=True)

    pb_payload = b"PBDB" * 100
    photo_payload = b"JPGDATA" * 500
    make_manifest(cache.device_dir, [
        ("HomeDomain", "Library/SpringBoard/IconState.plist", b"<plist>"),
        ("HomeDomain", "Library/SpringBoard", None, 2),          # directory row — no payload by design
        ("HomeDomain", "Library/Accounts", None, 2),             # directory row (regression: renameatx ENOENT)
        ("HomeDomain", "Library/Accounts/Accounts3.sqlite", b"acc"),
        ("CameraRollDomain", "DCIM/100APPLE/IMG.JPG", photo_payload),
        ("AppDomain-com.apple.PosterBoard",
         "Library/Application Support/PRBPosterExtensionDataStore/61/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3",
         pb_payload),
        ("HomeDomain", "Library/SMS/sms.db", None),  # drained mid-stream: row without payload
    ])
    for name, content in (("Status.plist", b"s"), ("Manifest.plist", b"m"), ("Info.plist", b"i")):
        (cache.device_dir / name).write_bytes(content)

    check("no master before first refresh marker", not cache.has_valid_master())
    import json
    base.mkdir(parents=True, exist_ok=True)
    with open(cache.info_path, "w") as f:
        json.dump({"udid": UDID, "product_version": "27.0"}, f)
    check("master valid after marker", cache.has_valid_master())

    other = ProtectiveBackupCache(UDID, product_version="26.2")
    other._temp_base = cache._temp_base
    other._persist_base = cache._persist_base
    other.base, other.master_root = cache.base, cache.master_root
    other.device_dir = cache.device_dir
    other.info_path = cache.info_path
    check("version change invalidates master", not other.has_valid_master())

    # --- working copy is hardlinked and isolated ---
    wc = make_protective_working_copy(str(cache.master_root), UDID)
    wc_device = Path(wc) / UDID
    src_icon = cache.device_dir / [p for p in cache.device_dir.rglob("*") if p.is_file() and p.name != "Status.plist"][0]
    check("working copy exists", wc_device.is_dir())

    # --- prune drops drained rows + non-protective payloads in the COPY only ---
    removed_rows, removed_files = clean_backup_for_restore(wc, UDID)
    check("prune removed rows", removed_rows >= 1)
    conn = sqlite3.connect(str(wc_device / "Manifest.db"))
    rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("sms.db pruned from working copy", "Library/SMS/sms.db" not in rels)
    check("icon state kept", "Library/SpringBoard/IconState.plist" in rels)
    # directory rows MUST survive: without them the restore agent fails with
    # renameatx ENOENT when staging files into those directories
    check("directory row Library/SpringBoard kept", "Library/SpringBoard" in rels)
    check("directory row Library/Accounts kept", "Library/Accounts" in rels)
    check("Accounts3.sqlite kept", "Library/Accounts/Accounts3.sqlite" in rels)
    # the raw PB DB must NOT be restored in Phase 3 (it would clobber the
    # tweaked DB from Phase 2) — it is renewed separately on every apply
    check("posterboard db pruned from working copy",
          "Library/Application Support/PRBPosterExtensionDataStore/61/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"
          not in rels)

    # --- MessagesDomain is preserved across the wipe (issue #25) ---
    make_manifest(cache.device_dir, [
        ("MessagesDomain", "5B/00", None, 2),  # directory row
        ("MessagesDomain", "5B/00/Avatar", None, 2),
        ("MessagesDomain", "5B/00/2/0-09-48-02.sqlitedb", b"msgs"),
        ("KeychainDomain", "keychain-backup.plist", b"keychain" * 10),
    ])
    wc2 = make_protective_working_copy(str(cache.master_root), UDID)
    wc2_device = Path(wc2) / UDID
    # default (unencrypted) prune: keychain NOT kept, MessagesDomain kept
    removed_rows, _ = clean_backup_for_restore(wc2, UDID, include_photos=True)
    conn = sqlite3.connect(str(wc2_device / "Manifest.db"))
    rels2 = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("MessagesDomain db kept", any("0-09-48-02.sqlitedb" in r for r in rels2))
    check("keychain pruned when unencrypted", "keychain-backup.plist" not in rels2)
    # encrypted prune: keychain kept too
    wc3 = make_protective_working_copy(str(cache.master_root), UDID)
    wc3_device = Path(wc3) / UDID
    removed_rows, _ = clean_backup_for_restore(wc3, UDID, include_photos=True, include_keychain=True)
    conn = sqlite3.connect(str(wc3_device / "Manifest.db"))
    rels3 = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("keychain kept when encrypted", "keychain-backup.plist" in rels3)
    check("messages kept when encrypted", any("0-09-48-02.sqlitedb" in r for r in rels3))

    # --- master untouched by pruning of the copy; PB row survives there ---
    conn = sqlite3.connect(str(cache.device_dir / "Manifest.db"))
    master_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("master manifest still has sms.db row", "Library/SMS/sms.db" in master_rels)

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()