# note: this document describes the capabilities and limitations of the native `com.apple.MercuryPoster` lock-screen wallpaper engine on iOS 27, based on on-device inspection of the `PRBPosterExtensionDataStore`.

## 1. What MercuryPoster Is

`com.apple.MercuryPoster` is the native lock-screen wallpaper provider on iOS 26.2+/27, peer of `com.apple.WallpaperKit.CollectionsPoster` (the Marble / iOS 16-era format). MercuryPoster powers the all-new lock-screen rendering pipeline on iOS 26+.

---

## 2. On-Device Structure

```
PRBPosterExtensionDataStore/61/Extensions/com.apple.MercuryPoster/
  ProviderInfo.plist
  configurations/<UUID>/
    com.apple.posterkit.role.identifier  ← PRPosterRoleLockScreen
    com.apple.posterkit.provider.descriptor.identifier
    providerInfo.plist
    versions/3/                          ← version 3 (CollectionsPoster uses 0)
      com.apple.posterkit.provider.instance.renderingConfiguration.plist
      com.apple.posterkit.provider.instance.complicationLayout.plist
      com.apple.posterkit.provider.instance.titleStyleConfiguration.plist
      com.apple.posterkit.provider.instance.quickActions.plist
      RuntimeSnapshotMetadata-{hash}-lock.plist
      RuntimeSnapshotMetadata-{hash}-home.plist
      RuntimeSnapshotColorStatisticsMetadata-{hash}-lock.plist
      RuntimeSnapshotColorStatisticsMetadata-{hash}-home.plist
      RuntimeSnapshot-{hash}-lock.atx    ← 3.2 MB, snapshot in .atx format
      RuntimeSnapshot-{hash}-home.atx    ← 3.2 MB, snapshot in .atx format
      supplements/0/
      contents/
```

On iOS 27 (24A435) only **one** configuration ships: `FFC91C29-91A7-42E0-A46C-00AFE0C3A8F4`.

---

## 3. RuntimeSnapshot (.atx) Format

The key element of MercuryPoster is the binary `.atx` files (Apple Texture format).

Each snapshot contains:
- The lock-screen wallpaper rendered into a dense graphics format (compressed texture data)
- A set of mip-map levels (`PUIPosterSnapshotBundleInfoKeySnapshotLevels`)
- Dimensions: 393×852 points, scale=3.0 (1179×2556 pixels)
- Identifier: `PUIPosterSnapshotBundleInfoKeySnapshotDefinitionIdentifier: RuntimeSnapshot`

Snapshot metadata plist:
```
PUIPosterSnapshotBundleInfoKeyAssetSize: {393, 852}
PUIPosterSnapshotBundleInfoKeyScale: 3.0
PUIPosterSnapshotBundleInfoKeyDeviceInterfaceOrientation: 1
PUIPosterSnapshotBundleInfoKeyHasColorStatistics: 1
PUIPosterSnapshotBundleInfoKeyPosterProvider: com.apple.MercuryPoster
PUIPosterSnapshotBundleInfoKeySnapshotImageFormat: atx
PUIPosterSnapshotBundleInfoKeySnapshotVersion: 15
```

---

## 4. Capabilities

| Capability | Supported | Notes |
|---|---|---|
| Depth button | Yes | native renderer, `depthEffectDisabled: false` |
| Parallax / gyro | Yes | `motionEffectsDisabled: false` |
| Quick actions (camera) | Yes | `quickActions.plist` on lock screen |
| Complication layout | Yes | clock, complications |
| Lock → home transition animation | Yes | separate lock + home `.atx` snapshots |
| LKState animations (chest opening, breathing, etc.) | No | no CAML → no LKState |
| Text / interactive layers | No | pure bitmap snapshot |
| Custom `wallpaper.ca` | No | MercuryPoster does not parse this format |
| Hot-swappable content (`.tendies`) | Partially | snapshot only replacable if `.atx` can be generated |

---

## 5. The Two iOS 27 Lock-Screen Formats Compared

| | **CollectionsPoster** (Marble) | **MercuryPoster** |
|---|---|---|
| Extension ID | `com.apple.WallpaperKit.CollectionsPoster` | `com.apple.MercuryPoster` |
| Config version | 0 (Versions/0) | 3 (Versions/3) |
| Main content | `wallpaper.ca/main.caml` (CAML ParameterizedCA) | `RuntimeSnapshot-{hash}-{state}.atx` (bitmap) |
| Wallpaper.plist | Yes | No |
| Depth button | Native iOS 27 wallpapers only | Yes (native renderer) |
| LKState animations | Renderer does not play them (native Marble ships empty `<states/>`) | No CAML → no animations |
| Parallax / gyro groups | CAML gyro groups | built into the snapshot |
| Render type | CollectsParams → CA → texture → post | snapshot rendered ahead by the engine |
| Customization | High (edit CAML layers) | Low (`.atx` is opaque) |
| Example | Marble Four, stock "lemon" wallpaper | single FFC91C29 configuration |

---

## 6. The "Mercury SimpleMinecraftChest" Experiment

`build_mercury_chest.py` built a tendie that:
1. Took the CAML from `iPhone 17.tendies` (Marble)
2. Placed it under `descriptors/Mercury SimpleMinecraftChest`
3. GoldenNugget routes any folder named with `mercury` → `com.apple.MercuryPoster`

**Problem**: MercuryPoster **does not read** `wallpaper.ca`. It looks for `.atx` snapshots. As a result:
- CAML wallpaper dropped into Mercury → renders as empty / placeholder
- The depth button never appears for the same reason
- Parallax does not work

This confirms MercuryPoster and CollectionsPoster are **two separate rendering pipelines** on iOS 27.

---

## 7. Takeaways for Development

1. **Depth button** appears only on native MercuryPoster wallpapers (`.atx` snapshots). Custom CollectionsPoster configurations (Marble format) cannot get the button — this is a render-engine limitation, not a plist one.

2. **LKState animations** (chest opening, breathing, etc.):
   - CollectionsPoster: ignored — native Marble ships empty `<states/>`
   - MercuryPoster: impossible — no CAML, animations cannot be authored through snapshots

3. **Custom lock-screen wallpapers on iOS 27**:
   - Only working path: CollectionsPoster + ParameterizedCA `wallpaper.ca`
   - Parallax (gyro groups) works
   - Static layers work
   - State animations (Locked/Unlock/Sleep) do not work

4. **Generating `.atx` snapshots**:
   - Binary, opaque format (proprietary Apple texture)
   - No known generation method
   - Custom `.atx` from CAML/images is not yet possible

5. **Best achievable result** for custom wallpapers:
   - Format: Marble / parameterized `wallpaper.ca`
   - Split content: Background (fill) + Floating (objects) + parallax groups
   - Depth cannot be enabled, but parallax can

---

## 8. References

- PosterBoard path: `/Library/Application Support/PRBPosterExtensionDataStore/61/Extensions/com.apple.MercuryPoster`
- Experiment script: `/tmp/.private/awesomenull/opencode/build_mercury_chest.py`
- Tendie output: `/home/awesomenull/Загрузки/SimpleMinecraftChest-Mercury.tendies`
- On-device Mercury config: `ipsw_work/pb_store/reconstructed/.../FFC91C29-91A7-42E0-A46C-00AFE0C3A8F4`
- Rendering config: `renderingConfiguration.plist` → `motionEffectsDisabled: false, depthEffectDisabled: false` (matches Marble)