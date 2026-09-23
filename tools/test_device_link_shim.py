#!/usr/bin/env python3
"""Offline test for the DeviceLink contents-of-directory shim (no device needed).

Verifies that enumerating a missing directory (e.g. the ``Snapshot`` payload
dir probed during incremental backups) answers with an empty listing instead of
crashing on ``path.iterdir()``. Run: python tools/test_device_link_shim.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore import protective  # noqa: E402  (installs the shim on import)

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


class FakeStatus:
    def __init__(self):
        self.calls = []

    async def status_response(self, status_code, status_str="", status_dict=None):
        self.calls.append((status_code, status_str, status_dict))


class FakeLink:
    def __init__(self, root: Path):
        self.root_path = root
        self.status = FakeStatus()

    async def status_response(self, status_code, status_str="", status_dict=None):
        await self.status.status_response(status_code, status_str, status_dict)


async def main():
    from pymobiledevice3.services.device_link import DeviceLink

    assert getattr(DeviceLink, "_gn_contents_installed", False), "shim not installed"

    tmp = Path(tempfile.mkdtemp(prefix="gn_dl_shim_"))

    handler = DeviceLink.contents_of_directory

    # nested dir with a file -> regular entries come back
    (tmp / "existing").mkdir()
    (tmp / "existing" / "file.txt").write_text("hello")

    link = FakeLink(tmp)
    await handler(link, ["DLContentsOfDirectory", "existing"])
    check("existing dir lists entries", link.status.calls[0][2].get("file.txt") is not None)

    # missing dir (the Snapshot probe) -> empty dict, no crash
    link2 = FakeLink(tmp)
    await handler(link2, ["DLContentsOfDirectory", "missing"])
    check("missing dir answers empty", link2.status.calls[0][2] == {})

    print(f"\n{15 + PASS} assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\nALL PASSED ({PASS} checks)")