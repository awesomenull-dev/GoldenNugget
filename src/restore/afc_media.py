"""
AFC-backed parallel media backup/restore channel.

On iOS 27 the three-phase restore wipes the device (security recovery), so
photos/videos must survive on this computer between Phase 2 and Phase 3. They
are normally carried inside the protective mobilebackup2 backup, which is
slow (the whole Media tree uploads through DeviceLink). When
``use_afc_media`` is on, the *bulk* photo trees (``DCIM``,
``PhotoStreamsData`` — the actual photo/video files) are instead pulled over
plain ``com.apple.afc`` in *parallel* with the mobilebackup2 backup of
everything else, and pushed back over the same channel during Phase 3.

The scope is deliberately narrow: only the top-level Media trees in
``AFC_MEDIA_TREES`` go over AFC. ``PhotoData`` — the photo library database
(CPLAssets) plus its protected metadata (``PhotoData/UBF`` is NOT listable
over the media AFC service; it fails with AFC error 10 / PERM_DENIED on
iOS 27) — stays inside the mobilebackup2 backup, which reads it natively.
The mobilebackup2 upload filter and the manifest prune both exclude the same
``AFC_MEDIA_TREES`` so the split stays coherent end-to-end (no wasted
uploads, no manifest rows pointing at payloads that were never written).

Design rules:
- Progress is reported as strings only (never numbers): the mobilebackup2
  numbers drive the progress bar, and a concurrent numeric feed would corrupt
  it.
- Pull-side failures are fatal by default: the media dir is the ONLY copy of
  the user's photos after Phase 2 wipes the device, so a silent drop is data
  loss. Callers that need best-effort pass ``on_error="warn"``.
- Symlinks are skipped (never copied as files): following them could escape
  the Media tree and would duplicate content.
"""

import os
import posixpath

from pymobiledevice3.services.afc import MAXIMUM_READ_SIZE, AfcService

from src.exceptions.nugget_exception import NuggetException
from src.utils.log_util import log_info, log_warn, log_error

AFC_MEDIA_DIRNAME = "afc_media"

# Top-level Media trees moved to the AFC channel. Everything else under
# /var/mobile/Media (notably PhotoData/) stays in the mobilebackup2 backup:
# some of its subdirectories (PhotoData/UBF on iOS 27) are unlistable over the
# media AFC service, and restoring the photo library DB via mobilebackup2
# keeps the library consistent with the DCIM originals we push back over AFC.
AFC_MEDIA_TREES = frozenset({"DCIM", "PhotoStreamsData"})


def afc_media_enabled(pref_enabled: bool = True) -> bool:
    """Whether the AFC media channel is active for a given apply.

    The environment ``GOLDENNUGGET_NO_AFC_MEDIA=1`` kill switch always wins —
    it force-disables the channel the way ``GOLDENNUGGET_NO_BACKUP_CACHE``
    force-disables the backup cache.
    """
    return pref_enabled and os.environ.get("GOLDENNUGGET_NO_AFC_MEDIA") != "1"


def afc_media_dir_for(backup_root: str) -> str:
    """Media directory paired with a protective backup run.

    ``backup_root`` is ``<run dir>/device_backup``; the media tree lives next
    to it inside the same run dir (``<run dir>/afc_media``) so that run-level
    cleanup (prune_protective_backups, failure rmtree) reclaims both together.
    """
    return os.path.join(os.path.dirname(os.path.abspath(backup_root)),
                        AFC_MEDIA_DIRNAME)


def _is_afc_link(stat: dict) -> bool:
    return bool(stat) and stat.get("st_ifmt") == "S_IFLNK"


def _progress_str(action: str, done_files: int, total_files: int,
                  done_bytes: int, total_bytes: int) -> str:
    if total_bytes > 0:
        pct = 100.0 * done_bytes / total_bytes
        mb = done_bytes / (1024 * 1024)
        return (f"{action}... {pct:.0f}% ({done_files}/{total_files} files, "
                f"{mb:.1f} MB)")
    return f"{action}... {done_files}/{total_files} files"


async def _pull_one(afc, src: str, dst: str, stat) -> int:
    """Stream one regular file from the device to ``dst``, returning bytes."""
    size = int(stat.get("st_size", 0))
    if size <= MAXIMUM_READ_SIZE:
        data = await afc.get_file_contents(src)
        with open(dst, "wb") as f:
            f.write(data)
        return len(data)
    handle = await afc.fopen(src)
    try:
        written = 0
        with open(dst, "wb") as f:
            while written < size:
                to_read = min(MAXIMUM_READ_SIZE, size - written)
                chunk = await afc.fread(handle, to_read)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
        return written
    finally:
        await afc.fclose(handle)


async def _list_afc_tree(afc, dirpath: str, entries: list,
                         on_error: str) -> None:
    """Recursively collect the regular files under ``dirpath`` into ``entries``.

    Mirrors the on-device layout: each item is (src, rel, stat) where ``rel``
    is the path relative to the AFC root (``DCIM/100APPLE/IMG_0001.JPG``).
    Directory entries that cannot be listed are skipped with a warning (their
    contents are out of scope for AFC — e.g. protected PhotoData subdirs),
    never fatal.
    """
    try:
        children = await afc.listdir(dirpath)
    except Exception as e:
        msg = f"AFC media: cannot list {dirpath or '/'}: {e}"
        if on_error == "warn":
            log_warn(msg + " — skipping this directory")
            return
        raise NuggetException(msg) from e
    for name in sorted(children):
        if name in (".", ".."):
            continue
        src = posixpath.join(dirpath, name)
        rel = src.lstrip("/")
        try:
            st = await afc.stat(src)
            if _is_afc_link(st):
                log_info(f"AFC media: skipping symlink {src}")
                continue
            if st.get("st_ifmt") == "S_IFDIR":
                await _list_afc_tree(afc, src, entries, on_error)
            else:
                entries.append((src, rel, st))
        except Exception as e:
            msg = f"AFC media: could not stat {src}: {e}"
            if on_error != "warn":
                raise NuggetException(msg) from e
            log_warn(msg + " — skipping this entry")


async def backup_media_via_afc(lockdown_client, media_root: str,
                               progress_callback=None,
                               on_error: str = "raise",
                               diff: bool = False) -> dict:
    """Pull the bulk photo trees over AFC into ``media_root``.

    Walks only the top-level Media trees named by ``AFC_MEDIA_TREES`` (DCIM,
    PhotoStreamsData) under the AFC root and mirrors every regular file into
    ``media_root`` preserving the on-device layout. Returns a tally dict
    ``{"files": int, "bytes": int, "skipped": int}``.

    With ``diff=True`` a local file that already exists at the same size is
    left untouched, so only new/changed objects are pulled — that is the
    cache refresh path, where ``media_root`` is the persistent per-device
    media store from a previous run (the first pull is still a full one).
    Extra local files (deleted on the device) are never removed: the media
    dir is the ONLY copy of the user's photos after a wipe, so deleting
    anything here would be data loss.
    """
    root = os.path.abspath(media_root)
    os.makedirs(root, exist_ok=True)
    tally = {"files": 0, "bytes": 0, "skipped": 0}

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    if os.path.isdir(root) and os.listdir(root):
        log_info(f"AFC media pull: {root} already populated — "
                 f"{'diff refresh (pull only new/changed)' if diff else 'full refresh'}")
    async with AfcService(lockdown_client) as afc:
        entries: list = []
        root_children = await afc.listdir("/")
        for name in sorted(root_children):
            if name in (".", ".."):
                continue
            if name not in AFC_MEDIA_TREES:
                log_info(f"AFC media: leaving {name} to the mobilebackup2 "
                         "backup (out of AFC scope)")
                continue
            await _list_afc_tree(afc, f"/{name}", entries, on_error)

        total_files = len(entries)
        total_bytes = sum(int(st.get("st_size", 0)) for _src, _rel, st in entries)

        done_files = 0
        done_bytes = 0
        failed: list[str] = []
        skipped = 0
        for src, rel, st in entries:
            dst = os.path.join(root, *rel.split("/"))
            if diff:
                try:
                    if (os.path.getsize(dst) == int(st.get("st_size", 0))):
                        # Same size on both ends — already local, skip the pull.
                        skipped += 1
                        done_files += 1
                        continue
                except OSError:
                    pass  # file missing locally -> pull it
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                n = await _pull_one(afc, src, dst, st)
            except Exception as e:
                msg = f"AFC media: failed to pull {src}: {e}"
                if on_error == "warn":
                    log_warn(msg)
                    failed.append(src)
                else:
                    raise NuggetException(msg) from e
            done_files += 1
            done_bytes += n
            if done_files % 25 == 0 or done_files == total_files:
                _log(_progress_str("Backing up photos/videos over AFC",
                                   done_files, total_files, done_bytes, total_bytes))

        log_info(f"AFC media pull complete: {total_files} files, "
                 f"{total_bytes / (1024 * 1024):.1f} MB"
                 + (f" ({skipped} already present, skipped)" if skipped else ""))
        tally["files"] = total_files
        tally["bytes"] = total_bytes
        tally["skipped"] = skipped
        if failed:
            log_warn(f"AFC media pull: {len(failed)} files skipped on error "
                     f"(e.g. {failed[:3]})")
            tally["failed"] = failed
    return tally


async def _push_one(afc, src: str, remote_rel: str) -> int:
    """Push one local file onto the device, returning bytes written."""
    size = os.path.getsize(src)
    if size <= MAXIMUM_READ_SIZE:
        with open(src, "rb") as f:
            await afc.set_file_contents(remote_rel, f.read())
        return size
    handle = await afc.fopen(remote_rel, "w")
    try:
        with open(src, "rb") as f:
            while True:
                chunk = f.read(MAXIMUM_READ_SIZE)
                if not chunk:
                    break
                await afc.fwrite(handle, chunk)
        return size
    finally:
        await afc.fclose(handle)


async def restore_media_via_afc(lockdown_client, media_root: str,
                                progress_callback=None,
                                on_error: str = "raise") -> dict:
    """Push a previously pulled Media tree back to the device over AFC.

    Mirrors ``media_root`` (which holds the AFC root layout: DCIM/, PhotoData/,
    ...) back onto the device after the iOS 27 security-recovery wipe. Returns
    a tally dict ``{"files": int, "bytes": int}``.
    """
    root = os.path.abspath(media_root)
    if not os.path.isdir(root):
        log_info(f"AFC media restore: nothing to restore (no {root})")
        return {"files": 0, "bytes": 0}

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    entries = []
    total_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, root).replace(os.sep, "/")
            entries.append((src, rel))
            total_bytes += os.path.getsize(src)

    async with AfcService(lockdown_client) as afc:
        done_files = 0
        done_bytes = 0
        failed: list[str] = []
        for src, rel in entries:
            remote = f"/{rel}"
            rdir = posixpath.dirname(remote)
            try:
                if rdir and rdir != "/":
                    await afc.makedirs(rdir)
                n = await _push_one(afc, src, remote)
            except Exception as e:
                msg = f"AFC media: failed to restore {remote}: {e}"
                if on_error == "warn":
                    log_warn(msg)
                    failed.append(remote)
                else:
                    raise NuggetException(msg) from e
            done_files += 1
            done_bytes += n
            if done_files % 25 == 0 or done_files == len(entries):
                _log(_progress_str("Restoring photos/videos over AFC",
                                   done_files, len(entries), done_bytes, total_bytes))

        log_info(f"AFC media restore complete: {done_files} files, "
                 f"{done_bytes / (1024 * 1024):.1f} MB")
        if failed:
            log_warn(f"AFC media restore: {len(failed)} files failed "
                     f"(e.g. {failed[:3]})")
            tally = {"files": done_files, "bytes": done_bytes, "failed": failed}
            return tally
    return {"files": done_files, "bytes": done_bytes}