# Shortcut Companion (concept)

> **Update (verified):** Home Screen shortcut **icons** are no longer lost.
> The Phase 2 sparse-restore wipes them, but Phase 3 (protective restore)
> brings them back: the protective backup now carries
> `HomeDomain/Library/SpringBoard/IconState.plist` (icon layout) together
> with `HomeDomain/Library/Shortcuts/Shortcuts.sqlite` (the Shortcuts
> library). Real-world verified — restored successfully from a full device
> backup. This companion is now only an optional fallback for edge cases
> (protective restore skipped / patches lost), not the primary mechanism.

## Problem (historical)

The Phase 2 sparse restore wipes Home Screen icons. Phase 3, in its original
narrow scope (photos/Apple ID/settings without SpringBoard + Shortcuts), could
not bring them back.

## Concept

A two-part Shortcuts-app companion that the user runs around the apply flow:

1. **Backup** — run before applying tweaks.
2. **Restore** — re-run after applying.

> iOS does not let a shortcut enumerate or export the whole Shortcuts library
> automatically. Backup therefore works via the **share sheet**: the user
> selects one or more shortcuts and shares them *into* the companion, which
> packs them into one file.

## Suggested actions

### Backup — "Nugget Save"

Input: the `.shortcut` files shared into it.

1. Make Archive (zip)
2. Save File → ask where to save (e.g. `Files → GoldenNugget`)

Output: one `Nugget-Backup.zip`.

### Restore — "Nugget Restore"

1. Get Contents of Folder → the backup folder
2. Extract Archive
3. Quick Look each `.shortcut` → iOS offers "Add Shortcut"
   (optionally Choose from List first)
4. Re-add Home Screen icons manually in the Shortcuts app
   (⋯ → "Add to Home Screen") — only needed if the protective restore was
   skipped and icons were lost.

## Implementation notes for contributors

- A real, importable `.shortcut` file must be **exported from a Mac or iPhone**
  (signed/entitled plist). It cannot be reliably hand-crafted on Linux — the
  action identifiers and parameters are opaque.
- To get an iCloud link (for the future QR image in the apply popup):
  share the built shortcut → "iCloud Link" → copy the `icloud.com/...` URL.
- When the QR lands in the app, the iOS 27 apply flow should show:
  "Added shortcuts to your Home Screen? Backup them first. [QR]
  After applying, re-run it to restore."

## Verification checklist

- [ ] Share multiple shortcuts into "Nugget Save" → one `.zip` comes out
- [ ] "Nugget Restore" unzips and shows "Add Shortcut" per file
- [ ] Icon returns to Home Screen after re-adding
- [x] Full cycle verified: apply tweaks → protective restore → Home Screen
      intact (via `Library/SpringBoard/IconState.plist` + `Library/Shortcuts`)