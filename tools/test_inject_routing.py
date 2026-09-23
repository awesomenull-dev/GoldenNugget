#!/usr/bin/env python3
"""Offline test for the inject-all routing gate (no device needed).

The whole "ALL tweak files ride Phase 3's protective restore" design hinges
on restore_files reading the prepared backup's encryption flag correctly:
an unencrypted backup can hold plaintext-injected rows (inject_all), an
encrypted one cannot (MBErrorDomain/205 → fall back to the sparse pass).
This test locks in the _is_encrypted_backup detection logic against
synthetic backup dirs. Run: python tools/test_inject_routing.py
"""
import os
import plistlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.inject import _is_encrypted_backup

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    # 1. Unencrypted backup (the default for this project) → inject_all.
    d = root / "unencrypted"
    (d / "UDID").mkdir(parents=True)
    (d / "UDID" / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    (d / "UDID" / "Manifest.db").write_bytes(b"\x00" * 1024)
    check("unencrypted backup (Manifest.plist at device dir) → False",
          _is_encrypted_backup(d / "UDID") is False)

    # 2. Encrypted backup → the sparse pass must stay (inject_all off).
    d = root / "encrypted"
    (d / "UDID").mkdir(parents=True)
    (d / "UDID" / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))
    check("encrypted backup → True",
          _is_encrypted_backup(d / "UDID") is True)

    # 3. No manifest present at all → must read False (never hard-block
    #    injection on a spurious probe failure; the missing-manifest live
    #    restore bubble is caught elsewhere).
    d = root / "no_manifest"
    (d / "UDID").mkdir(parents=True)
    (d / "UDID" / "Manifest.db").write_bytes(b"\x00" * 1024)
    check("no manifest → False",
          _is_encrypted_backup(d / "UDID") is False)

    # 4. Snapshot/Manifest.plist fallback path (used by cache/incremental).
    d = root / "snapshot_manifest"
    snap = d / "UDID" / "Snapshot"
    snap.mkdir(parents=True)
    (snap / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))
    check("Snapshot/Manifest.plist IsEncrypted=True → True",
          _is_encrypted_backup(d / "UDID") is True)

    # 5. empty Manifest.plist (st_size 0) → falls through to Snapshot.
    d = root / "empty_top_manifest"
    snap = d / "UDID" / "Snapshot"
    snap.mkdir(parents=True)
    (d / "UDID" / "Manifest.plist").write_bytes(b"")
    (snap / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    check("empty top Manifest.plist + Snapshot False → False",
          _is_encrypted_backup(d / "UDID") is False)

    # 6. cache master layout: root itself IS the device dir (master/<udid>).
    d = root / "cache_master"
    d.mkdir()
    (d / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    check("cache master layout (root == device dir) → False",
          _is_encrypted_backup(d) is False)

print(f"\nALL PASSED ({PASS} checks)")