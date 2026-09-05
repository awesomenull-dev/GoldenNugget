# GoldenNugget Architecture

A guided tour of every part of the codebase: what each package does, how the
main flows work end-to-end, and which conventions hold the whole thing
together. For agent-facing operational notes see [AGENTS.md](../AGENTS.md);
for the iOS 27 status-bar research see [iOS27_StatusBar_Research.md](iOS27_StatusBar_Research.md);
for line-level verified facts gathered during a codebase audit see [FINDINGS.md](FINDINGS.md).

```
main_app.py ──► src/gui/main_window.py ──► pages/ (classic UI)  +  ios/ (iOS-style UI)
                        │
                        ▼
            src/devicemanagement/device_manager.py   (apply / reset orchestration)
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
  src/tweaks/     src/restore/      src/controllers/
  (what to write) (how to write it) (helpers: plists, xml, presets, …)
```

---

## Entry point — `src/cli` / `nugget_cli.py` / `main_app.py`

The unified CLI dispatcher lives in `src/cli/main.py` (routing + usage text,
exposed via `src.cli`). The top-level `nugget_cli.py` is a thin shim that
delegates to `src.cli.main`, keeping the PyInstaller entry script unchanged.
It dispatches subcommands then falls through to the GUI:

```
Nugget                          launch the GUI
Nugget apply-wallpaper [TENDIE] [--udid UDID] [--list]
Nugget restore-cache [...opts]  restore last protective cache (Phase-3 recovery)
Nugget restore [same as above]  alias for restore-cache
Nugget skip-setup [--udid]      mark all iOS setup panes completed
Nugget -m <module>| <script>.py  backward-compatible dispatcher
```

`main_app.py` is the underlying GUI/CLI dispatcher:
1. Adds `src/qt` to `sys.path` (joined with `__file__`) so the generated
   resource modules import; silences warnings and Wayland text-input spam.
2. CLI forms: `python main_app.py -m <module>` runs a tool module (falls back
   to `<module>.__main__` for packages); a trailing `<file>.py` (that does not
   end in `.tendies`/`.batter`) is run via `runpy.run_path`.
3. GUI startup: `--test-mode` fabricates **two** mock devices (iPhone 15 Pro /
   iPhone 16) with no USB; `--debug` upgrades logging to DEBUG + captures
   pymobiledevice3; `GOLDENNUGGET_LOG_FILE` overrides the stdlib log path.
4. Restores the `last_loaded_preset` (or "AutoSave") before the window is
   built; handles `.tendies`/`.batter` args by adding them to the tweaks.

Build: `compile.py` calls `PyInstaller.__main__.run(...)` directly (it does
**not** consume `Nugget.spec` — that file only applies if you run
`pyinstaller Nugget.spec` manually). `version.txt` supplies Windows version
metadata only; macOS adds `--osx-bundle-identifier`/codesign. i18n is not
compiled by `compile.py` — `.qm`/`resources_rc.py` are produced by the
pyside6-lrelease/lupdate/rcc pipeline (README / CI).

## Global state — one real singleton, two process singletons

| Object | File | Purpose |
|---|---|---|
| `tweaks` | `src/tweaks/tweaks.py` | **The only true module-level singleton**: `dict[TweakID → Tweak instance]`; the single source of runtime tweak state both UIs read and write |
| `DeviceManager` | `src/devicemanagement/device_manager.py` | device discovery, apply/reset orchestration (one instance, created in `main_app.py`) |
| `DataSingleton` | `src/devicemanagement/data_singleton.py` | **not a real singleton** — a plain 6-line class holding `current_device` + `device_available`. Each `DeviceManager` owns its own instance (`device_manager.py:115`); there is no global accessor. Treat its per-manager value as the source (e.g. read `window.device_manager.data_singleton`). Note: `ios/daemons.py:151-152` constructs a **fresh** instance, so `current_device` is always `None` there — the iPhone-14 location warning guard is effectively dead. |

---

## src/devicemanagement/ — talking to the device

### `session.py`
`lockdown_session(serial)` — the **only** sanctioned way to open a lockdown
connection. Async context manager that always closes safely (a rebooted
device makes `close()` raise `ConnectionTerminatedError`, which must never
mask the real result). `create_using_usbmux` appears directly only where
connection ownership transfers to a caller (`_wait_for_device`,
`perform_restore`, `skip_setup`, `tools/` scripts).

### `constants.py`
- `Device` — plain data object (udid, version, model, locale…).
- `is_supported_by_fork(version)` — hard gate: iOS > 26.1 only.
- `Version` — re-export of `packaging.version.Version`.

### `preference_manager.py`
QSettings-backed user preferences (`auto_reboot`, `use_encrypted_backup`,
skip-setup options…) plus the PosterBoard saved-database helpers.

### `device_manager.py` — the orchestrator
Key methods:

- `_get_devices()` — usbmux scan; per-device lockdown probe; encryption check
  (blocks non-experimental encrypted use); builds `Device` objects.
- `apply_changes()` → `_apply_changes()` — the main flow, see below.
- `_prepare_protective_backup()` — Phase 0: cached protective backup; when
  wallpapers are applied, also includes the PosterBoard container and
  extracts its database right after the refresh. Returns a `PreparedBackup`.
- `_apply_tweak_pass()` — asks every loaded tweak to generate its files,
  merges them into one restore list, handles backup-encryption prompts,
  then calls `start_restore()`.
- `start_restore()` → `restore_files()` (src/restore).
- `reset_tweaks()` — captures original plists via `psysbackup()`, then builds
  "restore the originals" files per selected page.

#### Apply flow (end-to-end)
```
apply_changes()
 ├─ _raise_if_unsupported()                    iOS < 26.2 hard-blocked
 ├─ _prepare_protective_backup()               Phase 0 (cache, see below)
 │    ├─ encrypted? prompt password / bypass cache
 │    └─ wallpapers applied? include PB container + extract DB after refresh
 ├─ _backup_posterboard_database(force=True)   only if the cache could not
 │                                             provide a usable DB
 └─ _apply_tweak_pass(prepared_backup_root)
      ├─ every tweak.apply_tweak(...)          files generated into one list
      ├─ skip-setup + .GlobalPreferences copy  HomeDomain survival copies
      ├─ backup-encryption password handling   (iOS 27+)
      └─ start_restore(files, prepared_backup_root)
           └─ restore_files → _restore_ios27   three phases, below
```

---

## src/tweaks/ — what gets written

### Registry-first design (`registry.py`)
Every *registry-managed* plist tweak is defined **once** as a `TweakSpec`:
`id`, `section` (Liquid Glass / SpringBoard / Internal Options), `title`
(marked with `QT_TRANSLATE_NOOP` — see below), `location`, `key`, `value`,
`kind` (`switch` / `text` / `number`, plus `min_value`/`max_value` for
numbers), compatibility (`min_version`, `max_version`, `iphone_only`,
`ipad_only`) and an optional `factory` for non-basic tweaks. The only
factory-backed spec is WatchOS Compatibility → an `AdvancedPlistTweak` over
`FileLocation.nanoregistry` (also `ipad_only=True`).

Not every plist tweak is a spec: `Daemons` (an `AdvancedPlistTweak` over
`disabled.plist`) and `ClearScreenTimeAgentPlist` (a `NullifyFileTweak`) are
hand-built in `load_daemons()`, and the three non-plist extra tweaks
(`PosterBoard`, `Templates`, `StatusBar`) live outside the registry.

**Translation:** titles are wrapped in `QT_TRANSLATE_NOOP("Nugget", title)` at
*definition* time (registry.py) so they reach pyside6-lupdate; the real
`QCoreApplication.translate("Nugget", spec.title)` happens at *render* time in
`src/gui/ios/tweaks.py`.

Consumers:
- `tweak_loader.load_plist_tweaks()` builds instances into `tweaks`
  (idempotent — already-loaded IDs keep their live instance so UI state
  survives re-entry; `load_daemons()` builds the hand-defined daemon tweaks
  separately).
- The iOS tweaks page renders sections straight from `SPECS_BY_SECTION`
  (`SPECS_BY_ID` powers compatibility lookups).
- `gui/ios/compat.py` evaluates `min_version` / `max_version` / device
  restrictions from the spec (public API unchanged).

Adding a tweak = adding one registry entry.

### Tweak classes (`tweak_classes.py`)
`Tweak` base (key/owner/group, `enabled=False`, change-notification via a
module-level callback that drives the autosave) with concrete generators:
- `BasicPlistTweak` — one key into one managed plist, **merges** into existing
  plists (does not wipe sibling keys).
- `AdvancedPlistTweak` — a dict of keys into one plist; `apply_tweak`
  **replaces** the whole plist dict (unlike BasicPlistTweak's merge);
  `set_multiple_values(keys, value)` stamps one value across many keys (used
  by the Daemons UI).
- `NullifyFileTweak` — writes a zero-byte file (plist nuking).
- Special generators live outside `tweak_classes.py`: `StatusBarTweak`
  (`status_bar/`), `PosterboardTweak` + `TemplatesTweak`
  (`posterboard/`). (There is **no** `PasscodeThemeTweak` — that class does
  not exist; only parked Qt-Designer chrome remains.)

`Daemons` is an `AdvancedPlistTweak` over the `Daemon` enum's bundle IDs
(`src/tweaks/daemons_tweak.py`); the class itself is enum-agnostic — the UI
translates `Daemon.X → [bundle IDs]`. Disabling the Location daemon on an
iPhone 14-family device (`iPhone14,*`) triggers a wallpaper-risk warning in
both UIs (the classic Daemons page embeds the same `IOSDaemonsContent`).

### PosterBoard subsystem (`tweaks/posterboard/`)
Wallpapers are always applied **as configurations written into the
PosterBoard sqlite database** (the old descriptor-file method was removed —
broken on iOS 26+).

- `posterboard_tweak.py` — `use_configs = True` (the descriptor apply method
  is gone, broken on iOS 26+), `structure_version = 61`. `verify_tendie` caps
  total descriptors at 10 and warns when a tendie ships its own `.sqlite3`
  (`unsafe_container`). `recursive_add` walks tendies/templates, randomizes
  UUIDs, classifies parenthesized descriptor types into Photos / Mercury /
  Collections extension providers, registers them (`add_config`), and stages
  the modified DB (`update_sqlite`) appended as an AppDomain file; `ordered`
  descriptors get reverse-sorted sequential ids. iOS 26.4+ uses a Configs
  model (`update_for_family` forces the Marble/Lavender family) plus
  `update_plist_id` rewriting. Optional live-photo (`create_live_photo_files`,
  bundling HEIC thumbnails + `.aar` via `wrap_in_aar`) and video-loop CAML
  (`create_video_loop_files`) generation via `video_handler`.
- `pb_config_manager.py` — the DB pipeline: pulls the live DB (from the
  protective-backup cache), validates (`_validate_posterboard_db` with
  `strict=True` for the classic schema, `strict=False` for any healthy
  poster-ish DB because the schema varies on iOS db5+; always runs
  `PRAGMA integrity_check`), stages config entries
  (`update_sqlite` re-writes `poster`/`posterAttributes`/`posterRoleMembership`
  rows, computing `roleSortKey`), and produces the modified database. It also
  surfaces the SQLCipher "disable backup encryption" error.
- `template_file.py` + `template_options/` — the `.batter`-style template
  format: JSON-defined option widgets (picker/remove/replace/set) that edit
  caml/xml/plist payloads at apply time.
- `status_bar/status_setter.py` + `status_bar_tweak.py` — binary
  `StatusBarOverrideData` struct (cffi, `-malign-double`) translated into the
  Speakeasy FeatureFlags payload (`SpringBoard.SpeakeasyNewStatusBar` in
  `FeatureFlags/Global.plist`); `apply_tweak` returns early (no-op) on iOS
  ≥27.0 (no write permission). **The Speakeasy dict schema is explicitly
  unconfirmed in code** (keys are "guesses" mirroring the classic
  `statusBarOverrides`). Reset writes an empty dict
  (`{"SpringBoard": {"SpeakeasyNewStatusBar": {}}}`) to avoid disabling the
  whole status bar. Caveat: the UI offers status-bar controls on iOS 27+ but
  the apply silently no-ops.

---

## src/restore/ — how it gets written

### `restore.py` — five-phase restore (`_restore_ios27`)
All supported devices (26.2+) take this path:

```
Phase 0 (in device_manager): cached protective backup + PosterBoard DB
Phase 1 (0-40%):  working copy of the cached master (hardlinks), or a fresh
                  perform_protective_backup() when there is no cache
                  → clean_backup_for_restore() prune
                  → inject PosterBoard files (pb_inject_files, AppDomain)
Phase 2 (40-60%): perform_restore() sparse restore → reboot
                  → iOS 27 "safe state recovery" wipes data volume
Phase 3 (60-90%): _wait_for_device() (20 min budget, _RECONNECT_TIMEOUT)
                  → _restore_protective_backup() puts user data back
                  (max_retries=18, fixed 3s sleep, only for transient errors)
Phase 4 (90-95%): skip_all_setup27()  — only if skip-setup requested
Phase 5 (95-100%): reboot_device()    — only if auto_reboot (default on iOS 27)
```

`prepared_backup_root` is a `PreparedBackup(root, manifest_password)`; when
absent (encrypted-without-password / kill switch), Phase 1 falls back to an
in-place `perform_protective_backup()`.

Progress ranges are the real `_PHASE_BACKUP_END=40`, `_PHASE_TWEAK_END=60`,
and the hardcoded `90`/`95`/`100` bounds in `_restore_ios27` — the old
"Phase 3 = 60-100%" summary is simplified: the last 10% belongs to skip-setup
and reboot.

Phase 3 details: `perform_protective_backup` itself has **no** retry loop —
the only retry is `ProtectiveBackupService.connect()` with **5** attempts
(backoff 2, 4, 8, 15 s). Phase 3 restore retries transient errors only
(`_is_transient_restore_error`: ConnectionTerminatedError/OSError, ssl,
"InvalidService", "SpringBoard ... ready for a restore", "start ... service").

Phase 2 has its own guard: if the sparse restore drops at 0% it waits 25 s and
retries once on a fresh connection (`max_sparse_attempts = 2`).

A 1-hour stale-working-copy GC removes old `nugget_protective_*` temp dirs at
the start of `_restore_ios27`.

Sparse staging itself lives in `backup.py` + `mbdb.py` (MBDB/Manifest
construction) and `__init__.py::perform_restore` (with `GOLDENNUGGET_KEEP_SPARSE`
debug copy support). `_Mobilebackup2NoEscrow` is used when a fresh post-wipe
re-pair carries no EscrowBag.

### `protective.py` — the cache and everything around it
- `ProtectiveBackupCache` — per-device master copy in
  `<temp>/goldennugget_protective_cache/master/<udid>`. The master keeps a
  FULL Manifest.db (rows for drained payloads stay) so mobilebackup2 can run
  true incremental refreshes; invalidated by UDID/iOS-version change or by
  the encryption state flipping; a reboot wipes it naturally.
- `perform_protective_backup(..., incremental_ok)` — selective backup:
  pymobiledevice3's native `filter_callback` drains non-protective uploads
  mid-stream while their manifest rows survive (that is what makes the next
  incremental cheap). Keep-set: CameraRoll/Media (photos),
  SystemPreferencesDomain, HomeDomain Accounts / ConfigurationProfiles /
  Preferences / SpringBoard / ControlCenter / Shortcuts / WebClips, optionally the
  PosterBoard DB.
  (Note: the module's own doc-comment at `protective.py:212-220` claims
  ConfigurationProfiles was reverted, but the code still keeps it.)
- `make_protective_working_copy()` — hardlink clone (metadata real-copied);
  pruning never corrupts the master.
- `clean_backup_for_restore()` — prunes to the keep-set; self-heals by
  dropping regular-file rows whose payload is missing (MBErrorDomain/205)
  while keeping directory rows (renameatx ENOENT). Encrypted manifests are
  decrypted/pruned/re-encrypted locally via pymobiledevice3 when a password
  is supplied (prune only touches the working copy, never the master).
- `inject_file_into_backup()` — adds fresh tweak content so injected tweaks
  survive the wipe through Phase 3's native restore. **Only PosterBoard files
  (`pb_inject_files`, `AppDomain-com.apple.PosterBoard`) are injected today** —
  the old `_HOME_DOMAIN_TWEAK_PATHS`/`_SYSTEM_PREFERENCES_TWEAK_PATHS`
  constants are dead code. For **encrypted** backups injection is **always
  skipped** (plaintext payloads would fail the restore agent's decrypt).
- `extract_posterboard_db()` — resolves the PB database by FILE NAME
  (structure version varies), pulls `-wal`/`-shm` siblings and checkpoints
  them into one consolidated database.
- `verify_backup_payloads()` — last-line diagnostic before Phase 3.
- `prune_protective_backups()` → `dedupe_protective_payloads()`: keeps
  `PROTECTIVE_KEEP_RUNS=2` newest runs (never deleting anything younger than
  `PROTECTIVE_MIN_AGE_HOURS=24`) and hardlinks each older run's payloads the
  newest also carries (same fileID + content SHA-1 from the run's own
  Manifest.db blobs) onto the newest run — stale-but-kept runs stop eating
  disk immediately while still resolving for rollback.
- `check_disk_space_for_backup()` — sizes the requirement from the device's
  real used storage; `GOLDENNUGGET_MIN_FREE_GB` overrides the floor and
  `GOLDENNUGGET_CACHE_PERSIST_MIN_GB`/`GOLDENNUGGET_CACHE_REFRESH_SECS`
  tune the cache placement/refresh.

### `original_plist.py`
`psysbackup()` — full capture of the plists listed by `FileLocation` so
Reset can restore originals instead of empty files. When backup encryption is
enabled it returns `{}` (skips) **only if no `backup_password` is provided**;
with a password it decrypts the manifest and proceeds.

---

## src/gui/ — two UIs, one state

The `Page` enum (`pages_list.py`) and the designer `pages` QStackedWidget
share 15 indices, but the designer stack is **parked** (`main_window.py:150-152`)
and is not the live navigator. Real navigation uses:
- `self.pages` — dict of the 9 live classic page wrappers (`pages/main/*`,
  `pages/tools/*`), keyed by `Page`.
- `self.content_stack` — 3 entries: classic home / iOS root / classic daemons.
- `self.ios_pages` — 10 hand-built iOS pages (`ios/`): home, tweaks,
  posterboard, daemons, settings, statusbar, apply, springboard, internal,
  liquidglass (the last three are `IOSSectionPage` built from the registry
  `Section` enum).

- **Classic** — Qt Designer (`mainwindow.ui` → `mainwindow_ui.py`) wrappers in
  `pages/main/*` and `pages/tools/*`. The classic Daemons page literally embeds
  the shared `IOSDaemonsContent`.
- **iOS-style** — hand-built widgets in `ios/`, rendered from the registry
  where applicable; a single shared `IOSNavBar` is reconfigured per page.
- Both bind to the same `tweaks` instances — toggling in either UI changes the
  same state. `theme_manager.py` (`CLASSIC`/`IOS`) only *persists* the choice;
  `MainWindow.apply_theme()` actually flips the chrome.
- Dialogs: PosterBoard fetch wizard (`pb_dialog.py`, 3-step `PosterBoardDBWizard`
  + `PBDBThread`), reset picker (`reset_dialog.py`), about/update/help
  (`dialogs.py`).
- Thread workers (`thread_workers/`): 
  - `PBDBThread` (`pb_worker.py`) — signals `progress`/`infoLbl`/`alert`; there
    is **no declared** `finished` (callers use inherited `QThread.finished`).
  - `ApplyThread` — applies/resets; `alert.emit(None)` triggers the sudo prompt;
    `prompt_password` builds password dialogs on the main thread via
    `request_text`, with a 10-minute timeout.
  - `RestoreCacheThread` — standalone Phase-1+3 recovery (working copy → prune →
    verify → `_restore_protective_backup`, `reboot=False, skip_apps=True`).
  - `RefreshDevicesThread` — device refresh.

## src/controllers/ — support services

| Module | Role |
|---|---|
| `settings.py` | QSettings: writes to org `GoldenNugget`, falls back to legacy `Nugget`; SIGBUS-avoiding `value()` |
| `preset_manager.py` | export/import/apply of tweak presets (`PRESET_VERSION=2`; serializes all tweaks except PosterBoard; statusbar uses cffi base64). `export_preset(..., include=)` performs a **partial export** — filters the preset's tweaks to a given subset of `TweakID`s and marks the metadata as `partial` with the `included` list |
| `translator.py` | language switching (`os.execl` restart), RTL fixes, `.ts/.qm` pipeline via pyside6-lupdate/lrelease |
| `plist_handler.py` / `xml_handler.py` | plist key writes; namespace-aware XML/caml value setters matching on `nuggetId`/`id` (hardened `eval` for `nuggetOffset` equations) |
| `video_handler.py` | ffmpeg/opencv video→CAML conversion for video wallpapers (400-frame limit) |
| `files_handler.py` / `path_handler.py` | bundled-resource access, Windows path fixes |
| `web_request_handler.py` | update checks against the GitHub releases API |
| `nugget_logger.py` / `aar.py` | logging setup; `.aar` assembly (`wrap_in_aar`) |

## Conventions

- **Errors**: `NuggetException(message, detailed_text)` for user-facing
  failures. Connection/locked classification lives **once** in
  `src/exceptions/device_errors.py` (`is_device_locked_error`,
  `is_connection_error`) and is imported (aliased) by other modules, feeding
  the retry loops (`min(2**attempt, 15)s` connection backoff; Phase 3 restore
  uses 18 × fixed 3 s for transient errors only).
- **Logging**: `log_info/log_warn/log_error` in `protective.py` → console +
  `/tmp/goldennugget_log.txt`. `GOLDENNUGGET_LOG_FILE` overrides the stdlib
  `setup_logging` path (`main_app.py`/`nugget_logger.py`); note that
  `protective.py`'s own `_LOG_FILE` is a hardcoded constant and does **not**
  read the env var.
- **i18n**: registry titles use `QT_TRANSLATE_NOOP("Nugget", …)` at definition
  time and are evaluated with `QCoreApplication.translate("Nugget", …)` at
  render time; other UI strings translate inline. Catalogs are crowdsourced in
  the gNugget-i18n submodule and synced by CI (note: the `i18n/` submodule may
  be unchecked out locally).
- **Kill switches / env**: `GOLDENNUGGET_NO_BACKUP_CACHE`,
  `GOLDENNUGGET_SKIP_PB_BACKUP`, `GOLDENNUGGET_MIN_FREE_GB`,
  `GOLDENNUGGET_CACHE_PERSIST_MIN_GB`, `GOLDENNUGGET_CACHE_REFRESH_SECS`,
  `GOLDENNUGGET_PB_SPARSE`, `GOLDENNUGGET_KEEP_SPARSE`, `GOLDENNUGGET_LOG_FILE`.
- **Testing**: offline regression for the backup cache in
  `tools/test_protective_cache.py` and cache placement in
  `tools/test_cache_placement.py` (no device needed); smoke run =
  `QT_QPA_PLATFORM=offscreen python main_app.py --test-mode`. `tools/` also
  holds device operation utilities (backups, syslog capture, sparse inspection).
