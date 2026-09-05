import asyncio
import os
import plistlib
import shutil
import ssl
import tempfile
import time

from PySide6.QtCore import QCoreApplication

from . import backup, perform_restore, reboot_device
from .mbdb import _FileMode
from .skip_setup27 import skip_all_setup27
from .protective import (
    PreparedBackup,
    clean_backup_for_restore,
    inject_file_into_backup,
    log_error,
    log_warn,
    log_info,
    make_protective_working_copy,
    new_protective_backup_dir,
    perform_protective_backup,
    prune_protective_backups,
    verify_backup_payloads,
    WORKING_COPY_PREFIX,
)
from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from pymobiledevice3.services.installation_proxy import InstallationProxyService
from pymobiledevice3.services.lockdown_service import LockdownService
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
from pymobiledevice3.exceptions import ConnectionTerminatedError, PyMobileDevice3Exception, DeviceNotFoundError, PasswordRequiredError, NotPairedError, ConnectionFailedError, InvalidServiceError

from src.exceptions.nugget_exception import NuggetException

class FileToRestore:
    def __init__(self,
                 contents: str, restore_path: str, contents_path: str = None, domain: str = "",
                 owner: int = 501, group: int = 501, mode: _FileMode = None
                ):
        self.contents = contents
        self.contents_path = contents_path
        self.restore_path = restore_path
        self.domain = domain
        self.owner = owner
        self.group = group
        self.mode = mode

def concat_exploit_file(file: FileToRestore, files_list: list[FileToRestore], last_domain: str) -> str:
    base_path = ""
    # set it to work in the separate volumes (prevents a bootloop)
    if file.restore_path.startswith("/var/mobile/"):
        # required on iOS 17.0+ since /var/mobile is on a separate partition
        base_path = "/var/mobile/backup"
    elif file.restore_path.startswith("/private/var/mobile/"):
        base_path = "/private/var/mobile/backup"
    elif file.restore_path.startswith("/private/var/"):
        base_path = "/private/var/backup"
    # don't append the directory if it has already been added (restore will fail)
    path, name = os.path.split(file.restore_path)
    domain_path = f"SysContainerDomain-../../../../../../../..{base_path}{path}/"
    new_last_domain = last_domain
    if last_domain != domain_path:
        files_list.append(backup.Directory(
            "",
            f"{domain_path}",
            owner=file.owner,
            group=file.group
        ))
        new_last_domain = domain_path
    files_list.append(backup.ConcreteFile(
        "",
        f"{domain_path}{name}",
        owner=file.owner,
        group=file.group,
        contents=file.contents
    ))
    return new_last_domain

def concat_regular_file(file: FileToRestore, files_list: list[FileToRestore], last_domain: str, last_path: str):
    path, name = os.path.split(file.restore_path)
    paths = path.split("/")
    new_last_domain = last_domain
    # append the domain first
    if last_domain != file.domain:
        files_list.append(backup.Directory(
            "",
            file.domain,
            owner=file.owner,
            group=file.group
        ))
        last_path = ""
        new_last_domain = file.domain
    # append each part of the path if it is not already there
    full_path = ""
    mode = file.mode
    if mode == None:
        mode = backup.DEFAULT
    for path_item in paths:
        if full_path != "":
            full_path += "/"
        full_path += path_item
        if not last_path.startswith(full_path):
            files_list.append(backup.Directory(
                full_path,
                file.domain,
                owner=file.owner,
                group=file.group,
                mode=mode
            ))
            last_path = full_path
    # finally, append the file
    files_list.append(backup.ConcreteFile(
        f"{full_path}/{name}",
        file.domain,
        owner=file.owner,
        group=file.group,
        contents=file.contents,
        src_path=file.contents_path,
        mode=mode
    ))
    return new_last_domain, full_path

# merge all files that have duplicates and returns the list without duplicates
def merge_duplicates(original_files: list[FileToRestore]) -> list[FileToRestore]:
    no_dupe_files: list[FileToRestore] = []
    existing_locations: dict[str: int] = {}
    for file in original_files:
        if file.domain == None:
            file_loc = "-"
        else:
            file_loc = file.domain + '-'
        restore_path = file.restore_path
        if file.restore_path.startswith('/'):
            restore_path = restore_path.removeprefix('/')
        file_loc += restore_path
        if file_loc in existing_locations:
            if not restore_path.endswith('.plist'):
                print(f'cannot merge duplicate file, ignoring {file_loc}')
                continue
            # merge the data (plist files only)
            print(f'merging duplicate files for {file_loc}')
            initial_data = plistlib.loads(no_dupe_files[existing_locations[file_loc]].contents)
            added_data = plistlib.loads(file.contents)
            initial_data.update(added_data)
            no_dupe_files[existing_locations[file_loc]].contents = plistlib.dumps(initial_data)
            del initial_data, added_data
        else:
            # add it to the no dupes list
            no_dupe_files.append(file)
            existing_locations[file_loc] = len(no_dupe_files) - 1
    return no_dupe_files

def has_sparserestore_capability(lockdown_client: LockdownClient = None) -> bool:
    if lockdown_client is None:
        return True
    try:
        ver = lockdown_client.product_version.split(".")
        major = int(ver[0])
        minor = int(ver[1]) if len(ver) > 1 else 0
    except (ValueError, IndexError):
        return True
    if major != 18:
        return major < 18
    # there is no iOS 18.0.2 and 18.0.1 works with sparserestore, so no need to check the patch number
    return minor == 0


# --- iOS 27+ three-phase restore -------------------------------------------
#
# Progress is mapped into per-phase ranges so the GUI bar never jumps
# backwards: Phase 1 (protective backup) 0-40, Phase 2 (sparse restore +
# reboot) 40-60, Phase 3 (reconnect + protective restore) 60-100.
_PHASE_BACKUP_END = 40
_PHASE_TWEAK_END = 60

# How long to wait for the device to come back after the iOS 27 security
# recovery before giving up. Apple logo → reboot → progress bar (like
# Erase All Contents) → full boot can take several minutes.
_RECONNECT_TIMEOUT = 20 * 60

# HomeDomain tweak files. They are injected into the protective backup after
# pruning (with the freshly-applied tweak content) so Phase 3's mobilebackup2
# restore writes them back after the wipe cleared the sparse restore's copy.
# AFC cannot reach HomeDomain on iOS 27 — ``com.apple.afc`` only exposes the
# media directory — so backup injection is the one reliable path.
_HOME_DOMAIN_TWEAK_PATHS = (
    "Library/SpringBoard/statusBarOverrides",  # Status Bar tweak
    # FeatureFlags user-level override candidates (iOS 27). The system-level
    # /var/preferences/FeatureFlags/Global.plist is on the restore agent's
    # sysprefs allowlist-blocklist: backups may only rewrite files the device
    # already knows (verified with a radios.plist marker probe). These user
    # paths ride the same proven HomeDomain injection.
    "Library/Preferences/com.apple.FeatureFlags.plist",  # CFPreferences suite
    "Library/FeatureFlags/Global.plist",
    "Library/FeatureFlags/Domain/SpringBoard.plist",
)

# SystemPreferencesDomain tweak files, re-injected for the same reason as the
# HomeDomain ones: the iOS 27 wipe clears whatever the sparse restore staged
# unless the protective backup carries it. /var/preferences is outside the
# protective scope, so tweak files landing there must be injected by hand.
_SYSTEM_PREFERENCES_TWEAK_PATHS = (
    "FeatureFlags/Global.plist",  # Status Bar (Speakeasy) feature flag override
)


def _scaled_callback(progress_callback, lo: float, hi: float):
    """Map pymobiledevice3's raw 0-100 progress into the [lo, hi] range.

    Status strings pass through untouched (the GUI shows them as labels);
    other non-numeric values are dropped so the bar never sees garbage.
    """
    span = hi - lo

    def _cb(value):
        if isinstance(value, str):
            progress_callback(value)
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        pct = max(0.0, min(100.0, float(value)))
        progress_callback(lo + span * pct / 100.0)

    return _cb


async def _wait_for_device(udid: str, progress_callback,
                           timeout: float = _RECONNECT_TIMEOUT,
                           prompt_choice=None) -> LockdownClient:
    """Wait for the device to return after the iOS 27 security recovery.

    Polls usbmux with capped exponential backoff. Fully async — the caller's
    event loop (and the GUI) stays responsive for the whole wait.

    The pairing record SURVIVES the wipe (verified: SideStore keeps working),
    so the connect runs WITHOUT autopair — forcing a re-pair crashes with
    MissingValueError while the device is still finishing recovery and has
    no DevicePublicKey to give. If the host turns out to be unpaired after
    a short grace period, one autopair fallback is attempted.

    Instead of failing the whole restore when the wait times out (the classic
    "device was not unlocked in time after the security recovery" case), the
    caller can pass ``prompt_choice(title, text) -> "abort" | "resume"``: the
    timeout then shows an Abort/Resume prompt, and "resume" simply restarts a
    fresh waiting cycle instead of killing the restore.
    """
    from pymobiledevice3.exceptions import (
        DeviceNotFoundError, PasswordRequiredError, NotPairedError,
        ConnectionFailedError, ConnectionTerminatedError, LockdownError,
        MissingValueError,
    )
    while True:
        start = time.monotonic()
        deadline = start + timeout
        delay = 1.0
        last_error = None
        autopair_tried = False
        saw_password_required = False
        while True:
            elapsed = int(time.monotonic() - start)
            progress_callback(
                f"Waiting for device after security recovery "
                f"({elapsed // 60}:{elapsed % 60:02d} elapsed)..."
            )
            try:
                return await create_using_usbmux(serial=udid, autopair=False)
            except NotPairedError as e:
                # pairing genuinely lost — try a full re-pair once, after giving
                # the device time to finish recovery
                last_error = e
                if not autopair_tried and time.monotonic() - start >= 30:
                    autopair_tried = True
                    try:
                        return await create_using_usbmux(serial=udid, autopair=True)
                    except (MissingValueError, LockdownError) as e2:
                        last_error = e2
            except (DeviceNotFoundError, PasswordRequiredError,
                    ConnectionFailedError, ConnectionTerminatedError,
                    ConnectionError, OSError, asyncio.TimeoutError,
                    LockdownError) as e:
                # LockdownError covers MissingValueError and every other
                # lockdown-level complaint the recovering device may emit
                last_error = e
                if isinstance(e, PasswordRequiredError):
                    saw_password_required = True
            if time.monotonic() + delay > deadline:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)
        # inner wait cycle exhausted — offer Abort/Resume instead of aborting
        err = DeviceNotFoundError(
            f"Device {udid} not reachable after reboot "
            f"({int(timeout // 60)} min timeout). Unlock the device and make "
            f"sure it is connected via USB. Last error: {last_error}"
        )
        if prompt_choice is None:
            raise err
        title = QCoreApplication.tr("Device took too long to unlock")
        if saw_password_required:
            text = QCoreApplication.tr(
                "The device has not been unlocked for too long after the "
                "security recovery \u2014 it keeps asking for your passcode.\n\n"
                "Unlock it, enter the passcode and tap \"Trust\" if prompted, "
                "then choose:\n\n"
                "  \u2022 Resume \u2014 keep waiting (restarts the \"Waiting for "
                "device to reconnect after security recovery\" cycle).\n"
                "  \u2022 Abort \u2014 stop now. Tweaks may not be applied and "
                "data protection stays incomplete.")
        else:
            text = QCoreApplication.tr(
                "The device has not been unlocked for too long after the "
                "security recovery.\n\n"
                "Unlock it, enter the passcode and make sure it stays "
                "connected via USB, then choose:\n\n"
                "  \u2022 Resume \u2014 keep waiting (restarts the \"Waiting for "
                "device to reconnect after security recovery\" cycle).\n"
                "  \u2022 Abort \u2014 stop now. Tweaks may not be applied and "
                "data protection stays incomplete.")
        log_info("Reconnect wait timed out; asking the user whether to resume or abort")
        try:
            decision = prompt_choice(title, text)
        except Exception as e:
            log_warn(f"Reconnect prompt failed ({e}) — aborting")
            raise err
        if decision != "resume":
            raise err
        log_info("User chose to resume — restarting the reconnect wait cycle")


def _is_transient_restore_error(error) -> bool:
    """True for Phase 3 errors that mean 'device still booting, try again'."""
    name = type(error).__name__
    msg = str(error)
    # ssl.SSLError subclasses OSError, so this covers SSL drops too.
    if isinstance(error, (ConnectionTerminatedError, OSError)):
        return True
    if "InvalidService" in name:
        return True
    if "NotEnoughDiskSpace" in str(error):
        return True  # device-side purge request — retry after cleanup
    # MBErrorDomain/1: SpringBoard not ready for a restore yet.
    if "SpringBoard" in msg and "ready for a restore" in msg:
        return True
    return "start" in msg.lower() and "service" in msg.lower()


class _Mobilebackup2NoEscrow(Mobilebackup2Service):
    """mobilebackup2 started WITHOUT the escrow bag.

    After the iOS 27 safe-state wipe, _wait_for_device() re-pairs the
    device. The fresh pair record carries no EscrowBag (one is only
    issued when pairing a passcode-protected device), so the stock
    Mobilebackup2Service — which hardcodes include_escrow_bag=True —
    dies with KeyError: 'EscrowBag'.
    """

    def __init__(self, lockdown: LockdownClient) -> None:
        LockdownService.__init__(self, lockdown, self.SERVICE_NAME,
                                 include_escrow_bag=False)


def _start_mobilebackup2(lc: LockdownClient) -> Mobilebackup2Service:
    """Pick the mobilebackup2 variant matching the pair record's escrow state."""
    pair_record = getattr(lc, "pair_record", None)
    if pair_record is not None and "EscrowBag" not in pair_record:
        log_warn("Pair record has no EscrowBag (fresh re-pair after the "
                 "wipe) — starting mobilebackup2 without it")
        return _Mobilebackup2NoEscrow(lc)
    return Mobilebackup2Service(lc)


async def _restore_protective_backup(lc: LockdownClient, backup_root: str,
                                      udid: str, reboot: bool,
                                      progress_callback, backup_password: str = "",
                                      skip_apps: bool = True) -> None:
    """Phase 3: restore the pruned protective backup.

    Retries while SpringBoard / mobilebackup2 are still coming up after the
    security recovery (they can take minutes on iOS 27).

    The progress_callback is already pre-scaled by the caller.
    """
    max_retries = 18
    for attempt in range(1, max_retries + 1):
        try:
            async with _start_mobilebackup2(lc) as mb:
                await mb.restore(
                    backup_root,
                    system=True, copy=True, remove=False,
                    reboot=reboot, source=udid,
                    skip_apps=skip_apps,
                    progress_callback=progress_callback,
                    password=backup_password,
                )
            return
        except (PyMobileDevice3Exception, ConnectionTerminatedError,
                ssl.SSLError, OSError, DeviceNotFoundError, PasswordRequiredError, 
                NotPairedError, ConnectionFailedError) as e:
            if attempt >= max_retries or not _is_transient_restore_error(e):
                # The device already told us which file it stubbed on — cross-check
                # the pruned manifest on disk so the log shows exactly which rows
                # are missing their payload (MBErrorDomain/205 post-mortem).
                if not _is_transient_restore_error(e):
                    try:
                        missing = verify_backup_payloads(backup_root, udid, backup_password)
                        if missing:
                            log_error(f"MBErrorDomain/205 context: {len(missing)} manifest rows "
                                      f"lack payloads (e.g. {missing[:5]})")
                    except Exception:
                        pass
                if isinstance(e, InvalidServiceError):
                    raise NuggetException(
                        "The iPhone would not start the restore service "
                        "(mobilebackup2) even after several minutes of retries.",
                        detailed_text=(
                            "This is not about Developer Mode - that is only "
                            "needed for the tweak restore (BookRestore), not "
                            "for restoring your data.\n\nThe phone was likely "
                            "still booting, locked, or had the screen off. "
                            "Unlock the iPhone, keep the screen on, wait for "
                            "it to reach the home screen, then apply again. "
                            "Your data was not lost - the protective backup is "
                            "kept on this computer and will be restored on the "
                            "next run."
                        ),
                    )
                raise
            progress_callback(
                f"Device not ready, retrying ({attempt}/{max_retries})..."
            )
            await asyncio.sleep(3)


async def _restore_ios27(back: backup.Backup, reboot: bool,
                          lockdown_client: LockdownClient, progress_callback,
                          backup_password: str = "",
                          prepared_backup_root: PreparedBackup = None,
                          pb_inject_files: list = None,
                          skip_setup: bool = True,
                          skip_protective_backup: bool = False,
                          include_keychain: bool = False,
                          prompt_choice=None):
    """iOS 27+ restore: backup → tweak → wipe → restore → skip setup → reboot.

    Phase 1 (0-40%):  Selective backup of photos, Apple ID, user
                      settings, and Messages. Non-protective data is drained
                      mid-stream, so no multi-GB full backup ever hits the
                      disk. KeychainDomain rides along only when the backup
                      is encrypted (see include_keychain). With
                      ``prepared_backup_root`` the backup already happened
                      earlier in the apply flow (fresh Phase-0 live
                      backup, or the persistent cache master + incremental
                      refresh), so this phase only builds the pruned working
                      copy. With ``skip_protective_backup`` the whole phase
                      (and Phase 3) is skipped — the user opted out on low
                      disk space.
    Phase 2 (40-60%): Apply tweaks via sparse restore → reboot, which
                      triggers the iOS 27 "safe state recovery" wipe.
    Phase 3 (60-90%):  Reconnect and restore the pruned Phase 1 backup so
                      user data survives the wipe. The restore itself does
                      not reboot; that happens after setup skip.
    Phase 4 (90-95%): Skip the iOS setup panes via cloud configuration.
    Phase 5 (95-100%): Reboot the device so the changes take effect.
    """
    udid = lockdown_client.udid
    started = time.monotonic()
    using_cache = prepared_backup_root is not None
    # With the cache the prune password was captured when the master was built.
    # Without it, this run's freshly-created backup uses the device's current
    # encryption, so the Phase 3 restore password doubles as the manifest
    # password. Leaving it "" would skip pruning and make Phase 3 try to
    # download the rows that were drained mid-stream → MBErrorDomain/205.
    manifest_password = prepared_backup_root.manifest_password if using_cache else backup_password
    protective_dir = None
    if using_cache:
        backup_root = await asyncio.to_thread(
            make_protective_working_copy, prepared_backup_root.root, udid)
        protective_dir = os.path.dirname(backup_root)
    else:
        # Live backup taken here rather than pre-prepared. It still has to go
        # to persistent storage: Phase 2 is about to wipe the device, after
        # which this directory is the sole copy of the user's data. A temp dir
        # would be swept by the cleanup below (or lost on reboot).
        backup_root = new_protective_backup_dir(udid)
        prune_protective_backups(udid)
        protective_dir = os.path.dirname(backup_root)
    backup_complete = False
    try:
        log_info(f"Starting iOS 27 restore for device {udid}")
        log_info(f"Protective backup directory: {protective_dir}")

        # Clean up stale working copies from crashed runs (>1h old).
        #
        # ONLY working copies — those are rebuilt from the backup on every run.
        # Live protective backups live outside the temp dir under their own
        # tree (see protective_persistent_base); after Phase 2 has wiped the
        # device they are the sole copy of the user's data, so sweeping them
        # here would turn a recoverable failure into permanent loss. The
        # prefix is the guard, and the check below makes it fail safe.
        import glob as _glob
        from .protective import protective_persistent_base
        _persistent_base = str(protective_persistent_base())
        for stale in sorted(_glob.glob(os.path.join(
                tempfile.gettempdir(), WORKING_COPY_PREFIX + "*"))):
            try:
                if stale == protective_dir:
                    continue
                if os.path.abspath(stale).startswith(_persistent_base):
                    log_error(f"Refusing to sweep {stale}: inside the persistent "
                              f"protective backup store")
                    continue
                age_h = (time.time() - os.path.getctime(stale)) / 3600
                if age_h > 1:
                    shutil.rmtree(stale, ignore_errors=True)
                    log_info(f"Cleaned stale working copy: {stale} ({age_h:.0f}h old)")
            except OSError:
                pass

        # === Phase 1: selective protective backup (0-40%) ===
        progress_callback(0)
        if using_cache:
            log_info("Phase 1: Using prepared protective backup "
                     "(cached master or the fresh Phase-0 live backup)")
        elif skip_protective_backup:
            log_warn("Phase 1: protective backup SKIPPED at the user's request "
                     "(no data protection for this apply)")
        else:
            log_info("Phase 1: Starting protective backup (photos, Apple ID, settings, home screen)")
            await perform_protective_backup(
                lockdown_client, backup_root,
                progress_callback=_scaled_callback(progress_callback, 0, _PHASE_BACKUP_END),
                include_photos=True,
                include_keychain=include_keychain,
            )
        backup_complete = not skip_protective_backup

        # Prune Manifest.db + orphan payloads in a worker thread
        removed_rows = removed_files = 0
        injected = failed = 0
        missing_payloads = []
        if backup_complete:
            removed_rows, removed_files = await asyncio.to_thread(
                clean_backup_for_restore, backup_root, udid,
                include_keychain=include_keychain,
                manifest_password=manifest_password
            )
        log_info(f"Phase 1: Pruned backup: -{removed_rows} manifest rows, -{removed_files} payload files "
                 f"({time.monotonic() - started:.1f}s into the run)")


        # PosterBoard files (staged DB + configuration plists) ride the
        # protective restore on beta 6+, since AppDomain sparse restores are
        # rejected there — see the pb_via_protective note in restore_files.
        if backup_complete:
            for f in (pb_inject_files or []):
                rel = f.restore_path.lstrip("/")
                data = f.contents
                if data is None and f.contents_path:
                    with open(f.contents_path, "rb") as fh:
                        data = fh.read()
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if inject_file_into_backup(
                        backup_root, udid, f.domain, rel, data,
                        mode=_FileMode.S_IFREG | 0o644,
                        owner=f.owner, group=f.group,
                        manifest_password=manifest_password):
                    injected += 1
                else:
                    failed += 1
            if pb_inject_files:
                level = log_error if failed else log_info
                level(f"PosterBoard files delivered via protective restore: "
                      f"{injected} ok, {failed} failed")

            # Last line of defence against MBErrorDomain/205: the device requests
            # every regular-file row's payload — a single missing one aborts the
            # whole Phase 3 restore.
            missing_payloads = await asyncio.to_thread(
                verify_backup_payloads, backup_root, udid, manifest_password)
            if missing_payloads:
                log_error(f"{len(missing_payloads)} manifest rows lack payloads "
                          f"(e.g. {missing_payloads[:5]}) — Phase 3 will likely fail with MBErrorDomain/205")

        progress_callback(_PHASE_BACKUP_END)

        # === Phase 2: apply tweaks → reboot (40-60%) ===
        log_info(f"Phase 2: Applying tweaks via sparse restore ({len(back.files)} files)")
        if len(back.files) == 0:
            log_error("Phase 2: file list is EMPTY — nothing to apply, the device "
                      "will reboot without triggering security recovery")
        sparse_progress = {"last": None, "calls": 0}

        def _tracking_callback(value):
            # remember how far the sparse restore actually got before any
            # connection drop — a drop at 0% means it was rejected, not applied
            sparse_progress["calls"] += 1
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sparse_progress["last"] = value
            progress_callback(_scaled_callback(
                progress_callback, _PHASE_BACKUP_END, _PHASE_TWEAK_END)(value))

        # The cache session finishes right before Phase 2 starts; on some
        # devices backupd needs a moment before accepting another mobilebackup2
        # client — a drop at 0% is that wedge, not a rejection. Cool down and
        # retry once on a fresh connection.
        max_sparse_attempts = 2
        for sparse_attempt in range(max_sparse_attempts):
            sparse_progress["last"] = None
            sparse_progress["calls"] = 0
            try:
                await perform_restore(
                    backup=back, reboot=True,
                    lockdown_client=lockdown_client if sparse_attempt == 0 else None,
                    progress_callback=_tracking_callback)
                log_info(f"Phase 2: sparse restore completed cleanly "
                         f"({sparse_progress['calls']} progress events)")
                break
            except (ConnectionTerminatedError, ssl.SSLEOFError,
                    ConnectionAbortedError, ConnectionResetError):
                if sparse_progress["last"] is None and sparse_attempt + 1 < max_sparse_attempts:
                    log_warn("Phase 2: connection dropped at 0% right after the cache "
                             "session — cooling down 25s and retrying once on a "
                             "fresh connection")
                    await asyncio.sleep(25)
                    continue
                if sparse_progress["last"] is None:
                    log_error("Phase 2: connection dropped with ZERO restore progress "
                              "on every attempt — the sparse restore was likely "
                              "REJECTED. Security state recovery will not trigger; "
                              "tweaks are NOT applied.")
                else:
                    log_info(f"Phase 2: Device rebooted during sparse restore "
                             f"(expected; last progress {sparse_progress['last']:.1f}%)")
                break
        progress_callback(_PHASE_TWEAK_END)

        # === Phase 3: reconnect + restore protective backup (60-90%) ===
        log_info("Phase 3: Waiting for device to reconnect after security recovery")
        lc = await _wait_for_device(udid, progress_callback, prompt_choice=prompt_choice)
        try:
            # brief settle time after reconnect — _restore_protective_backup
            # retries handle any remaining startup delay
            await asyncio.sleep(3)
            if skip_protective_backup or not backup_complete:
                log_warn("Phase 3: skipping protective restore (user opted out "
                         "of data protection)")
            else:
                await _restore_protective_backup(
                    lc, backup_root, udid, False,
                    _scaled_callback(progress_callback, _PHASE_TWEAK_END, 90),
                    backup_password=backup_password,
                    skip_apps=not bool(pb_inject_files))
                log_info("Phase 3: Protective backup restored successfully")

            # === Phase 4: skip setup panes (90-95%) ===
            if skip_setup:
                progress_callback("Skipping setup panes...")
                log_info("Phase 4: Skipping setup panes via MobileConfigService")
                await skip_all_setup27(lc, udid)
                log_info("Phase 4: Setup panes skipped successfully")
                progress_callback(95)

            # === Phase 5: reboot (95-100%) ===
            if reboot:
                progress_callback("Rebooting device...")
                log_info("Phase 5: Rebooting device")
                await reboot_device(reboot=True, lockdown_client=lc)
                log_info("Phase 5: Reboot command sent")
                progress_callback(100)
        finally:
            try:
                await lc.close()
            except Exception:
                pass
    except Exception as e:
        if backup_complete:
            kept = backup_root if not using_cache else prepared_backup_root.root
            log_error(f"Restore failed; protective backup kept at: {kept}")
            try:
                e.add_note(f"Protective backup kept at: {kept}")
            except AttributeError:
                pass
            if using_cache:
                # the master stays for debugging; drop only the pruned working copy
                shutil.rmtree(protective_dir, ignore_errors=True)
            raise
        log_error(f"Restore failed before backup completed: {e}")
        shutil.rmtree(protective_dir, ignore_errors=True)
        raise

    if using_cache:
        # working copy was fully restored; the master cache stays for next apply
        shutil.rmtree(protective_dir, ignore_errors=True)
    elif skip_protective_backup:
        # user opted out of data protection — nothing was kept
        shutil.rmtree(protective_dir, ignore_errors=True)
    else:
        log_info(f"Protective backup kept at: {backup_root}")
    log_info(f"iOS 27 restore completed successfully in {time.monotonic() - started:.1f}s")
    progress_callback(100)


# files is a list of FileToRestore objects
async def restore_files(files: list[FileToRestore], reboot: bool = False, lockdown_client: LockdownClient = None, progress_callback = lambda x: None, backup_password: str = "", prepared_backup_root: PreparedBackup = None, skip_setup: bool = True, skip_protective_backup: bool = False, include_keychain: bool = False, prompt_choice=None):
    # create the files to be backed up
    files_list = [
    ]
    apps_list = []
    active_bundle_ids = []
    apps = None
    sorted_files = sorted(merge_duplicates(files), key=lambda x: (x.domain or "", x.restore_path or ""), reverse=False)
    # add the file paths
    last_domain = ""
    last_path = ""
    exploit_only = True
    # extra check for system version to prevent sparserestore from restoring on iOS 18.1+
    passed_version_check = has_sparserestore_capability(lockdown_client)
    # iOS 27 dev beta 6 / public beta 4 reject sparse restores that contain
    # AppDomain-* domains: the device drops the connection at 0% and no
    # security recovery triggers. With a prepared protective backup we can
    # deliver PosterBoard files through Phase 3's native restore instead —
    # injected into the pruned working copy like every other tweak file.
    # GOLDENNUGGET_PB_SPARSE=1 forces the old sparse delivery.
    pb_via_protective = (prepared_backup_root is not None
                         and os.environ.get("GOLDENNUGGET_PB_SPARSE") != "1")
    pb_inject_files = []
    for file in sorted_files:
        if file.domain == "" or file.domain == "z":
            if passed_version_check:
                last_domain = concat_exploit_file(file, files_list, last_domain)
        else:
            if pb_via_protective and file.domain == "AppDomain-com.apple.PosterBoard":
                pb_inject_files.append(file)
                continue
            last_domain, last_path = concat_regular_file(file, files_list, last_domain, last_path)
            exploit_only = False
            # add the app bundle to the list
            if last_domain.startswith("AppDomain"):
                bundle_id = last_domain.removeprefix("AppDomain-")
                if bundle_id in active_bundle_ids:
                    continue
                # All AppDomain-* bundles MUST be registered in
                # Manifest.plist's Applications dictionary, otherwise
                # the device-side restore daemon will reject the domain
                # with MBErrorDomain/205 ("Unknown domain name").
                # This includes system apps like com.apple.PosterBoard.
                if apps is None:
                    # A failed lookup here would abort the whole sparse
                    # restore later — retry hard, then fail loudly.
                    last_err = None
                    for attempt in range(1, 4):
                        try:
                            async with InstallationProxyService(lockdown=lockdown_client) as ips:
                                apps = await ips.get_apps(application_type="Any", calculate_sizes=False)
                            break
                        except Exception as e:
                            last_err = e
                            log_warn(f"InstallationProxy query failed "
                                     f"(attempt {attempt}/3): {e}")
                            await asyncio.sleep(min(2 ** attempt, 8))
                    if apps is None:
                        raise NuggetException(
                            "Could not query installed apps from the device "
                            f"(needed to register {bundle_id} for the restore). "
                            f"Last error: {last_err}")
                try:
                    app_info = apps[bundle_id]
                except KeyError:
                    log_warn(f"AppDomain bundle '{bundle_id}' not found in installation proxy; "
                             "the device may reject this restore")
                    active_bundle_ids.append(bundle_id)
                else:
                    active_bundle_ids.append(bundle_id)
                    # NOTE: `Path` must be the APP BUNDLE path (/Applications/X.app),
                    # exactly like in real iTunes backups — pointing it at the data
                    # container makes the restore agent abort at 0%.
                    apps_list.append(backup.AppBundle(
                        identifier=bundle_id,
                        path=app_info.get("Path") or app_info["Container"],
                        version=str(app_info.get("CFBundleVersion", "1.0")),
                        container_content_class="Data/Application"
                    ))
                    log_info(f"Registered AppDomain bundle for restore: {bundle_id} "
                             f"({apps_list[-1].path})")

    # create the backup
    back = backup.Backup(files=files_list, apps=apps_list)

    from src.devicemanagement.constants import Version as _V
    device_ver = _V(lockdown_client.product_version)

    if os.environ.get("GOLDENNUGGET_NO_PROTECTIVE_BACKUP") == "1":
        # Kill switch: force the iOS 26-style apply — a single-pass sparse
        # restore with NO three-phase restore at all (no Phase 0/1/3 backup,
        # no security-recovery wipe). Handy for fast iteration (e.g. daemon
        # bootloop testing). skip_setup then rides on reconnect + cloud config
        # instead of the legacy crash_on_purpose trick.
        skip_protective_backup = True
        log_warn("GOLDENNUGGET_NO_PROTECTIVE_BACKUP=1 — forcing iOS 26-style "
                 "single-pass sparse restore (no protective backups, no "
                 "security-recovery wipe)")

    if device_ver >= _V("27.0"):
        if skip_protective_backup:
            # Raw sparse mode (GOLDENNUGGET_NO_PROTECTIVE_BACKUP=1): the iOS 27
            # three-phase restore would trigger Apple's security-recovery erasure
            # and restore an empty backup — exactly what bootloop-testing must
            # avoid. Run the plain sparse pass instead; the reboot to apply the
            # tweaks happens inside perform_restore (reboot=True).
            try:
                await perform_restore(backup=back, reboot=reboot,
                                      lockdown_client=lockdown_client,
                                      progress_callback=progress_callback)
            except (ConnectionTerminatedError, ssl.SSLEOFError,
                    ConnectionAbortedError, ConnectionResetError):
                log_info("Device disconnected during restore — expected on reboot")
            if reboot and skip_setup:
                lc = await _wait_for_device(lockdown_client.udid,
                                            progress_callback,
                                            prompt_choice=prompt_choice)
                log_info("Raw sparse: skipping setup panes via MobileConfigService")
                await skip_all_setup27(lc, lockdown_client.udid)
                progress_callback(95)
        else:
            # iOS 27 era: three-phase protective backup + restore
            await _restore_ios27(back, reboot, lockdown_client, progress_callback,
                                 backup_password=backup_password,
                                 prepared_backup_root=prepared_backup_root,
                                 pb_inject_files=pb_inject_files,
                                 skip_setup=skip_setup,
                                 skip_protective_backup=skip_protective_backup,
                                 include_keychain=include_keychain,
                                 prompt_choice=prompt_choice)
    else:
        # iOS 26.x: plain sparse restore — no security recovery wipe,
        # no protective backup needed.  When all files use the path-traversal
        # exploit (no AppDomain files), crash the restore to skip setup — the
        # device reboots without showing the setup assistant.
        if exploit_only and skip_setup:
            files_list.append(backup.ConcreteFile(
                "", "SysContainerDomain-../../../../../../../.." + "/crash_on_purpose",
                contents=b""))
            back = backup.Backup(files=files_list, apps=apps_list)
        try:
            await perform_restore(backup=back, reboot=reboot,
                                  lockdown_client=lockdown_client,
                                  progress_callback=progress_callback)
        except (ConnectionTerminatedError, ssl.SSLEOFError,
                ConnectionAbortedError, ConnectionResetError):
            log_info("Device disconnected during restore — expected on reboot")