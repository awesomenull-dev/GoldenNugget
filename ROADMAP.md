# Roadmap

Short-term plan for GoldenNugget. Verify against `docs/ARCHITECTURE.md` before large changes.

Release order: 9.3.3 (transitional) → 9.4 (refactor core) → 9.4.1 → 9.4.2 (maintainability finishing line).

## 9.3.3 — transitional

Quick-win fixes only, no architecture change. Bridges 9.3.2 → 9.4.

- Remove the dead first `ApplyThread.update_label` (`src/gui/thread_workers/apply_worker.py`, shadowed duplicate at line 71)
- Drop the leftover `DEBUG: _add_posterboard_container called` log line (`src/restore/protective.py`)
- `PBTemplateException` → inherit `NuggetException` (it currently bypasses `detailed_text` and crash-handler classification)
- Unify the SSL handshake timeout: the `_sc.DEFAULT_SSL_HANDSHAKE_TIMEOUT = 60` set in both `protective.py` and `device_manager.py` should have a single owner
- Bump version to 9.3.3, changelog entry (format matches existing `CHANGELOG.md` entries)

> Status: all items done on branch `9.3.3` (`f01a5d0`), awaiting release.
> Note: the quick-wins in `apply_worker.py` / `protective.py` / `posterboard_exceptions.py` / `device_manager.py` also need to land in 9.4 when 9.3.3 merges back.

## 9.4 — refactor core (safety / regression)

The highest-risk refactoring, batched into the first refactor release. Also carries the CA changes already on `9.4-refactor` (drop bounds-origin workaround, honor `contentsScale` for emitter particles) and the version bump to 9.4.

1. **Shared retry helper** — the exponential-backoff loops in `protective.py` (`ProtectiveBackupService.connect`, 5 retries), `original_plist.py` (`psysbackup`), `pb_dialog.py` (`backup_posterboard_database`) and the InstallationProxy query in `restore.py` are copies with subtly different exception sets/retry counts. Extract one `async_retry` with configurable predicates/backoff. Backfilled into existing retry configs (5 / 3 / 3 / 3 attempts) without changing behaviour.
2. **Single source for domain↔path mapping** — `DeviceManager.get_domain_for_path` and `absolute_path_to_backup_location` maintain the same table independently; a reset writes to the wrong domain if they drift. Extract to one module, keep both call sites on it.
3. **Error classification** — `is_connection_error` / `is_device_locked_error` / `_is_transient_restore_error` are string-heuristics on pymobiledevice3 messages; move `_is_transient_restore_error` from `restore.py` into `device_errors.py` next to the others and harden matching.

Exit criteria: apply + reset flows fully re-tested on device, retry counts unchanged, no behaviour drift.

## 9.4.1 — maintainability, part 1

4. **Split `protective.py` (1541 LOC)** — extract logging, `inject_file_into_backup` (~320 LOC) into `src/restore/inject.py`, and `ProtectiveBackupCache` into `src/restore/protective_cache.py`. No logic changes, only movement.
5. **`main_window.py` (1002 LOC)** — extract navigation/routing and settings persistence into mixins.

Exit criteria: `protective.py` / `main_window.py` drop below ~700 LOC each; imports updated; nothing user-visible changes.

## 9.4.2 — maintainability, part 2 + UX

6. **`FEATURE_TWEAKS` derived from the registry** — the hand-maintained dict in `hotload.py` drifts when tweaks are added to `SPECS`; derive it from the main tweak spec (`Section`) instead so hidden-feature gating can't silently miss new tweaks.
7. **Unify logging** — `protective.py` owns an independent `print()`+file logger (`_LOG_FILE` hardcoded) that ignores `GOLDENNUGGET_LOG_FILE`; fold it into the stdlib logger path.
8. **Thread off GUI-blocking calls** — `get_devices()` and `reset_device_pairing()` call `asyncio.run()` on the caller's thread; move to the worker-thread pattern already used by `ApplyThread`/`PBDBThread`.

Exit criteria: no `asyncio.run()` left that can run on the GUI thread; single logging path for restore ops; `FEATURE_TWEAKS` no longer hand-maintained.

## Backlog (unconfirmed)

Ideas and larger feature work, not yet scheduled:

- (feature ideas TBD — e.g. new tweak categories, wallpaper/CA improvements, restore UX)
- Post-9.4.2 quality passes: review fork-feature differences (`dev-9.0`), CA renderer swap

## Merge order

```
main ← 9.3.3         (transitional fixes)
main ← 9.4-refactor   (refactor core; bring back 9.3.3 quick-wins)
main ← 9.4.1 / 9.4.2  (to be cut from 9.4-refactor or fresh branches)
```