# GoldenNugget Async Operations

> Full codebase documentation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

This document describes the background threads, async backup/restore operations, and error handling used in GoldenNugget.

## HotLoad Safety Rules (src/controllers/hotload.py)

Remote safety rules (cached from
`hotload_rules.json`) that warn on / block dangerous or broken tweaks, and can
hide whole broken features. Behaviours per rule `action`:
- (default) — **block**: a flagged tweak is never applied (`rule_for` matched
  in `device_manager._apply_tweak_pass`) and enabling it shows a warning
  (`confirm_flagged` in the iOS tweaks/daemons/preset pages).
- `"kill_app"` — **kill switch**: the app refuses to start (or shuts itself
  down) on matching setups (`main_app._hotload_kill_or_none`).
- `"hide_feature"` (`feature` field) — **hide a whole feature page**: the
  feature's tweaks are never applied, removed from the iOS UI
  (`_hidden_sections` in `src/gui/ios/tweaks.py`), its Sidebar button and iOS
  home card are hidden (`_apply_hidden_feature_gating` in
  `src/gui/main_window.py`), and presets refuse to load it
  (`_hidden_tweak_names` stripping in `preset_manager._apply`, plus the
  "Hidden Features Skipped" warning in `src/gui/ios/settings.py`).

Feature → tweak membership lives in `FEATURE_TWEAKS` (Liquid Glass, Springboard,
Internal, PosterBoard, Daemons, Status Bar, Templates). `hidden_features()` /
`hidden_tweak_names()` / `feature_for()` resolve what is hidden for a given
device/model/app. All gating honours the kill switch (`hotload_enabled` pref);
when off, nothing is hidden or blocked.

## Tweak Registry (src/tweaks/registry.py)

Single source of truth for every plist-based tweak: id, section, title,
plist location, key, default value, UI kind (switch/text/number).

Single source of truth for every plist-based tweak: id, section, title,
plist location, key, default value, UI kind (switch/text/number).
- `tweak_loader.load_plist_tweaks()` builds the runtime instances from the
  registry (daemons stay hand-defined there).
- The iOS tweaks page (`src/gui/ios/tweaks.py`) renders its sections straight
  from `SPECS_BY_SECTION` — adding a tweak means adding one registry entry.
- Titles are marked with `QT_TRANSLATE_NOOP("Nugget", ...)` at
  definition time (so pyside6-lupdate sees them) and evaluated with
  `QCoreApplication.translate("Nugget", ...)` at render time in
  `src/gui/ios/tweaks.py`; keep `src/tweaks/registry.py` in the
  pyside6-lupdate file list so new strings reach the translators.
- Device compatibility (min iOS version, iPad/iPhone-only) is part of the
  spec (`min_version` / `iphone_only` / `ipad_only`);
  `src/gui/ios/compat.py` only evaluates it.

## Lockdown Sessions (src/devicemanagement/session.py)

`lockdown_session(serial)` is the one way to open a lockdown connection:
an async context manager that always closes safely (a rebooted device makes
`close()` raise ConnectionTerminatedError, which must never mask the real
result). Do not call `create_using_usbmux` directly in new code.

## Thread Workers (src/gui/thread_workers/)

### PBDBThread
**File**: `src/gui/thread_workers/pb_worker.py`
- **Purpose**: Generic background thread for backup-driven operations (PosterBoard database, etc.)
- **Signals**: `progress` (float), `infoLbl` (str), `alert` (object). There is **no declared `finished`** — callers use the inherited `QThread.finished`.
- Used by the PosterBoard "Fetch Database File" wizard (`PosterBoardDBWizard`)

## Apply / Reset Flow (src/devicemanagement/device_manager.py)

### `_apply_changes()`
Main entry point for applying tweaks. Order:
1. `_raise_if_unsupported()` — hard-block iOS < 26.2
2. `_prepare_protective_backup()` — Phase 0: builds the protective backup that Phase 3 will restore. Default (cache OFF): a **live** `perform_protective_backup()` fresh every apply, **always carrying the PosterBoard container when wallpapers are pending** (`include_posterboard`) so the extracted DB is never stale. With the experimental cache ON: incremental refresh of the cached master; the "reuse as-is" fast path never applies when wallpapers are pending, so the extracted DB is still always fresh. Returns (PreparedBackup, posterboard_db_ok); (None, False) only when there is no UDID
3. Fallback: if the PB DB was needed but missing from the protective backup (device rejected container inclusion / encrypted), the legacy separate `_backup_posterboard_database(force=True)` runs (skipped if `GOLDENNUGGET_SKIP_PB_BACKUP=1`)
4. `_apply_tweak_pass()` — generate all tweak files, handle backup encryption, then `start_restore(prepared_backup_root=...)`

### Protective Backup Cache (src/restore/protective.py)
`ProtectiveBackupCache` keeps a per-device master copy of the protective
backup in `<temp>/goldennugget_protective_cache/master/<udid>`:
- **EXPERIMENTAL, OFF BY DEFAULT** — the cache only engages when the user
  enables "Use Fast Backup Cache (Experimental)" in Settings
  (`pref.use_backup_cache`). Cache off → the classic live
  `perform_protective_backup()` / `_backup_posterboard_database()` path runs,
  which is the stable default. Kill switch still hard-disables it:
  `GOLDENNUGGET_NO_BACKUP_CACHE=1`.
- The master's Manifest.db stays FULL (rows for mid-stream-drained payloads
  remain), so `perform_protective_backup(incremental_ok=True)` runs a true
  incremental refresh — repeat applies upload only what changed on the device.
- Restores never touch the master: `make_protective_working_copy()` builds a
  throwaway hardlink copy (metadata files are real copies — pruning rewrites
  Manifest.db and a hardlink would corrupt the master).
- Invalidated by UDID/iOS-version change; a PC reboot wipes it naturally.
- PosterBoard DB: kept mid-stream into the master when wallpapers are applied
  (`include_posterboard`; container included via a stock-format factory-info
  entry — verified working on iOS 27 db5) and extracted after the refresh
  (`extract_posterboard_db`); pruned from the restore copy so Phase 3 never
  clobbers the tweaked DB from Phase 2. The DB is resolved by FILE NAME —
  the store dir's structure version (61, 62, ...) varies between iOS
  releases. The on-device DB runs in WAL mode: `-wal` is extracted and folded
  into one consolidated database via the SQLite online-backup API (the `-shm`
  is NEVER copied — a stale shm desyncs against the wal and is a classic
  source of "database disk image is malformed"); on failure it degrades to
  the plain main file. If anything in this chain fails, the apply degrades
  to the legacy separate `_backup_posterboard_database` instead of aborting.
- Stale-journal protection: every `PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3`
  injection (sparse OR Phase 3) ships 0-byte `-wal`/`-shm` companions
  (`posterboard_tweak.py`), so the device never replays old WAL frames over
  the freshly restored database — a top cause of "PosterBoard breaks after
  loading wallpapers".
- New-wallpaper inserts in `pb_config_manager.update_sqlite` allocate
  `posterId` ABOVE `MAX(posterId)` (not `sqlite_sequence.seq + 1`, which can
  collide after row deletions and corrupt the on-device database).
- Prune self-heal: kept rows must have payloads when flags=1 (a missing one
  aborts Phase 3 with MBErrorDomain/205); directory rows (flags=2) are kept
  unconditionally — dropping them causes renameatx ENOENT during restore.
  `verify_backup_payloads()` logs leftovers before Phase 3.
- Encrypted backups: supported when the user provides the backup password
  (prompted in `_prepare_protective_backup`; reused later for the Phase 3
  restore). The manifest is decrypted only locally on the pruned working
  copy (`clean_backup_for_restore` / `inject_file_into_backup` take a
  `manifest_password`). Without a password — or when the encryption state
  flips vs. what the master was built with — the cache is bypassed.
  Caveat: injected tweak payloads stay plaintext inside an otherwise
  device-encrypted backup, so injection is **always skipped** for encrypted
  backups (a decrypt mismatch would fail the restore). Also, encrypted +
  `needs_posterboard` forces the legacy separate PB backup
  (`(PreparedBackup, False)`).
  Kill switch: `GOLDENNUGGET_NO_BACKUP_CACHE=1`.

### `_apply_tweak_pass()`
- Generates every tweak's files in a single pass and restores them together
- iOS 27+: prompts for backup password if encryption is enabled (`use_encrypted_backup` pref)
- Writes a `.GlobalPreferences.plist` copy to the HomeDomain path
  (`FileLocation.globalPreferencesHomeDomain`) so user
  region/language/appearance survive the iOS 27 wipe. Note: this copy is **not
  merged** with the device's current file — it is written verbatim from the
  bundled base plist.
- Calls `start_restore(prepared_backup_root=...)` internally

### `start_restore()`
- Entry point for all restores (apply and reset)
- Opens a lockdown connection and delegates to `restore_files()`
- Passes `backup_password` for encrypted backups and `prepared_backup_root` down to the three-phase restore

### `_reset_tweaks()`
- Reset flow: `_raise_if_unsupported()` → `_capture_original_plists()` (via `psysbackup()`) → build reset files → `start_restore()`

## Restore Module (src/restore/)

### `restore_files()`
- Main restore orchestration
- Builds a `backup.Backup` object from the `FileToRestore` list
- Always delegates to `_restore_ios27()` (three-phase) — all supported devices (26.2+) go through this path

### `_restore_ios27()` — Five-Phase Restore
> The code executes **five** phases; the older docs summarised it as three, but
> Phase 3 ends at 90% and the last 10% belongs to skip-setup and reboot.

**Phase 1 (0-40%)**: Protective Backup
- With `prepared_backup_root` (cached master OR the fresh Phase-0 live backup): builds a hardlink working copy — no device backup runs here. Without it: `perform_protective_backup()` runs live. With `skip_protective_backup`: the phase is skipped entirely (user opted out on low disk space)
- Otherwise: `perform_protective_backup()` — selective backup of photos, Apple ID, settings
- `clean_backup_for_restore()` — prunes manifest to protective files only
- Injects PosterBoard files (`pb_inject_files`, AppDomain) — the only injected tweak payload today

**Phase 2 (40-60%)**: Sparse Restore + Reboot
- `perform_restore()` — applies tweaks via sparse restore; if it drops at 0% it waits 25 s and retries once on a fresh connection
- Triggers the iOS 27 "safe state recovery" wipe on reboot

**Phase 3 (60-90%)**: Protective Restore
- `_wait_for_device()` — reconnects after reboot (default 20 min timeout)
- `_restore_protective_backup()` — restores the Phase 1 backup, with password if encrypted; retries **18 times at fixed 3 s**, only for `_is_transient_restore_error` results

**Phase 4 (90-95%)**: `skip_all_setup27()` — only when skip-setup is requested

**Phase 5 (95-100%)**: `reboot_device()` — only when auto-reboot is on

### `perform_protective_backup()` (src/restore/protective.py)
- Creates a selective device backup via mobilebackup2
- Filters: keeps HomeDomain (Accounts, ConfigurationProfiles, Preferences, SpringBoard, ControlCenter, Shortcuts, WebClips), CameraRoll/Media (photos), SystemPreferencesDomain
- Skips: AppDomain-* containers (empty `Applications` in factory info), KeychainDomain
- Encryption: uses existing encryption if enabled, otherwise unencrypted
- Connection handling: the only retry is `ProtectiveBackupService.connect()`
  with **5 attempts** (backoff 2s, 4s, 8s, 15s); `perform_protective_backup`
  itself has no retry loop

### Live backup retention & dedupe (src/restore/protective.py)
- `prune_protective_backups()` keeps the newest `PROTECTIVE_KEEP_RUNS=2` runs and
  refuses to fully delete anything younger than `PROTECTIVE_MIN_AGE_HOURS=24`
  (right after a failed apply the newest backup is the only copy of user data).
- `dedupe_protective_payloads()` runs first on every prune: each older run's
  payloads that the newest run also carries — same fileID **and** same content
  SHA-1, read from each run's own Manifest.db `MBFile` blobs — are replaced by
  hardlinks to the newest run's files. Stale-but-kept runs stop eating disk
  immediately while staying fully readable for rollback; a file that genuinely
  changed between runs keeps its own payload and is never clobbered. Encrypted
  manifests without a password are skipped.

### `clean_backup_for_restore()` (src/restore/protective.py)
- Prunes Manifest.db to protective files only (temp-table keep-set, single DELETE)
- Removes orphaned payload files
- Skipped for encrypted backups (device handles it)

### `_restore_protective_backup()` (src/restore/restore.py)
- Restores the pruned backup after the security recovery
- Retries up to **18 times, fixed 3s between attempts** (`max_retries = 18`), and
  only for results matching `_is_transient_restore_error` (SpringBoard /
  mobilebackup2 startup delay)
- Accepts `backup_password` for encrypted backups

## Original Plist Capture (src/restore/original_plist.py)

### `psysbackup()`
- Full device backup to capture original plists before a reset
- Templates device-specific values (SerialNumber, DeviceName, etc.)
- Skipped (returns `{}`) if backup encryption is enabled **and no
  `backup_password` is provided**; with a password it decrypts the manifest
  and proceeds
- Retry logic: 3 attempts, backoff `min(2**attempt, 15)`s (2s, 4s) for connection errors
- Validates Manifest.db is valid SQLite before reading

## PosterBoard Backup (src/gui/dialogs/pb_dialog.py)

### `backup_posterboard_database()`
- Backs up the PosterBoard SQLite database for animated wallpapers
- Uses incremental backup if a previous backup exists
- Retry logic: 3 attempts, backoff `min(2**attempt, 15)`s (2s, 4s) for connection errors
- Validates Manifest.db before extracting the database

## Error Handling

### Device Lock Detection
- `is_device_locked_error()` — detects "ErrorCode" + "208", "Device locked",
  or "MBErrorDomain" in the message (defined **once** in
  `src/exceptions/device_errors.py`; imported/aliased locally as
  `_is_device_locked_error` in `device_manager.py`, `protective.py`,
  `original_plist.py`, `pb_dialog.py`)
- Used in: `psysbackup()`, `backup_posterboard_database()`, `perform_protective_backup()`, `_backup_posterboard_database()`, `_capture_original_plists()`
- User message: "Device locked - unlock and keep awake"

### Connection Error Detection
- `is_connection_error()` — detects ConnectionTerminatedError, ConnectionError,
  OSError, asyncio.TimeoutError by `isinstance`, plus lowercase substring
  heuristics ("connection", "incomplete", "terminated") — same single
  definition in `device_errors.py`
- Retry logic: 3 attempts with backoff `min(2**attempt, 15)`s — actual delays are 2s and 4s
- Used in all backup/restore operations

### Global Crash Handler (src/exceptions/crash_handler.py)
- `install_crash_handler()` sets `sys.excepthook` (plus a `sys.unraisablehook`
  fallback) and is called once at `main_app` import, before the window is built.
- `CrashHandlerApp` is a `QApplication` subclass whose `notify()` routes
  exceptions raised inside Qt event handlers/slots to the same handler —
  PySide6 would otherwise print and drop them.
- On an uncaught exception it shows a `CrashDialog` with a **"Copy Error"**
  button (copies the full traceback to the clipboard) and a **"Continue"**
  button that dismisses the dialog and lets the session keep running (no
  data-loss exit). `KeyboardInterrupt` is still allowed to exit normally.
- Never raises: the crash handler safely falls back to stderr if no
  `QApplication` exists yet.

### Backup Encryption Handling
- Checks `get_will_encrypt()` before operations
- iOS 27+ apply: prompts for password via QInputDialog if encryption is enabled and `use_encrypted_backup` is set
- Phase 3 passes the password to `mb.restore(password=backup_password)`
- `psysbackup` capture is skipped if encrypted **without a password** (cannot read manifest)

## Async/Await Patterns

All device communication uses async/await with pymobiledevice3:
- `create_using_usbmux()` — Lockdown connection
- `Mobilebackup2Service` — Backup/restore operations
- `AfcService` — File system access
- `InstallationProxyService` — App info
- `MobileConfigService` — Profile management

## Progress Reporting

Progress callbacks pass through the call chain:
```
update_label (UI)
  → _backup_progress() / progress_callback
  → psysbackup() / perform_protective_backup() / backup_posterboard_database()
  → mb.backup() / mb.restore() progress callbacks
```

## Key Retry Configurations

| Operation | Max Retries | Backoff | Errors Handled |
|-----------|-------------|---------|----------------|
| Protective Backup connect | 5 | 2s, 4s, 8s, 15s | Connection |
| psysbackup (pre-reset capture) | 3 | 2s, 4s | Connection, Device Locked |
| PosterBoard Backup | 3 | 2s, 4s | Connection, Device Locked |
| Phase 2 Sparse Restore | 2 | 25s once (if drop at 0%) | Transient |
| Phase 3 Restore | 18 | 3s fixed | Transient (service not ready) |
| InstallationProxy (AppDomain) | 3 | 2s, 4s, 8s | Any Exception |

## Data Flow Summary

```
User clicks "Apply Tweaks"
    |
_apply_changes()
    |_ _raise_if_unsupported()
    |_ _prepare_protective_backup()          [Phase 0: live backup (default) or cached master refresh]
    |     |_ cache OFF (default) -> fresh live perform_protective_backup()
    |     |_ cache ON (experimental) -> incremental master refresh; "reuse as-is" fast path only when NOT needs_posterboard
    |     |_ wallpapers applied? -> include PosterBoard container in the backup + extract fresh DB after
    |_ PB DB missing from the protective backup / encrypted? -> legacy _backup_posterboard_database(force=True)
    |_ _apply_tweak_pass(prepared_backup_root)
         |_ generate tweak files
         |_ backup encryption handling (iOS 27+ password prompt)
         |_ start_restore(prepared_backup_root)
              |_ restore_files()
                   |_ _restore_ios27()
                        Phase 1 (0-40%):  hardlink working copy of prepared backup (cache master OR fresh Phase-0 live)
                                         + clean_backup_for_restore() + inject PosterBoard (AppDomain)
                                         (skipped entirely if the user opted out on low disk space)
                        Phase 2 (40-60%): perform_restore() (sparse) -> reboot (25s+retry if drop at 0%)
                        Phase 3 (60-90%): _wait_for_device() -> _restore_protective_backup(password) [18x3s]
                                         (skipped when data protection was opted out)
                        Phase 4 (90-95%): skip_all_setup27()      (only if skip-setup)
                        Phase 5 (95-100%): reboot_device()        (only if auto_reboot)
```

## Logging

- Console output: `print()` for immediate feedback
- Log file: `/tmp/goldennugget_log.txt` (via `src/restore/protective.py` log functions;
  note `protective.py`'s `_LOG_FILE` is a hardcoded constant and ignores the env var)
- Verbose logging: pass `--debug` to `main_app.py`; the stdlib logger path can be
  overridden with the `GOLDENNUGGET_LOG_FILE` env var