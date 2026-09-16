"""Icon theming via HomeDomain WebClip folders.

Port of Cowabunga (Lite)'s "icon theming" feature to GoldenNugget. The real
app icons are never touched: for every themed app a WebClip folder is created
at ``HomeDomain/Library/WebClips/Cowabunga_<bundleID>,<displayName>.webclip/``
containing an ``Info.plist`` whose ``ApplicationBundleIdentifier`` points at
the REAL app bundle id — so tapping the replaced icon launches the actual app
directly (no "open in Safari" banner) — and an ``icon.png``. The folders are
delivered as regular HomeDomain ``FileToRestore`` entries, so they ride the
same restore path as the well-tested HomeDomain tweak files on every
supported version.
"""

import os
import plistlib
from shutil import copyfile

from PySide6.QtCore import QCoreApplication, QStandardPaths

from ..tweak_classes import Tweak
from .icon_theme import IconTheme

from src.utils.file_to_restore import FileToRestore


def persistent_themes_dir() -> str:
    """Stable folder holding the icon PNGs so applies/presets never depend on
    the original picker location (which could move or disappear)."""
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    folder = os.path.join(base, "GoldenNugget", "IconThemes")
    os.makedirs(folder, exist_ok=True)
    return folder


def make_webclip_plist(bundle_id: str, display_name: str) -> bytes:
    """WebClip Info.plist exactly like Cowabunga's ``makeInfoPlist``."""
    info = {
        "ApplicationBundleIdentifier": bundle_id,
        "ApplicationBundleVersion": 1,
        "ClassicMode": False,
        "ConfigurationIsManaged": False,
        "ContentMode": "UIWebClipContentModeRecommended",
        "FullScreen": True,
        "IconIsPrecomposed": False,
        "IconIsScreenShotBased": False,
        "IgnoreManifestScope": False,
        "IsAppClip": False,
        "Orientations": 0,
        "ScenelessBackgroundLaunch": False,
        "Title": display_name,
        "WebClipStatusBarStyle": "UIWebClipStatusBarStyleDefault",
        "RemovalDisallowed": False,
    }
    return plistlib.dumps(info, fmt=plistlib.PlistFormat.FMT_XML)


class IconThemesTweak(Tweak):
    def __init__(self):
        super().__init__(key=None)
        self.themes: list[IconTheme] = []

    def uses_domains(self):
        # WebClip folders all live under HomeDomain.
        return not self.is_empty()

    def is_empty(self) -> bool:
        return len(self.themes) == 0

    def add_theme(self, theme: IconTheme):
        # Replace an existing theme for the same bundle instead of adding a
        # second (and potentially conflicting) WebClip folder.
        for existing in self.themes:
            if existing.bundle_id == theme.bundle_id:
                self.themes.remove(existing)
                break
        self.themes.append(theme)

    def remove_theme(self, bundle_id: str):
        self.themes = [t for t in self.themes if t.bundle_id != bundle_id]

    def store_icon(self, theme: IconTheme):
        """Copy a theme's icon into the persistent store and point it there.

        Returns True when the icon is durably available for future applies.
        Idempotent for icons that already live in the store.
        """
        if theme.icon_data is not None:
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in theme.bundle_id)
            dest = os.path.join(persistent_themes_dir(), f"{safe}.png")
            try:
                with open(dest, "wb") as f:
                    f.write(theme.icon_data)
                theme.icon_path = dest
                theme.icon_data = None
                return True
            except OSError:
                return False
        if theme.icon_path and os.path.isfile(theme.icon_path):
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in theme.bundle_id)
            dest = os.path.join(persistent_themes_dir(), f"{safe}.png")
            try:
                if os.path.realpath(theme.icon_path) != os.path.realpath(dest):
                    copyfile(theme.icon_path, dest)
                theme.icon_path = dest
                return True
            except OSError:
                return False
        return False

    def sanitize_display_name(self, name: str) -> str:
        # Commas break the WebClip folder name pattern (it's a single comma-
        # separated string), and path separators would break restore paths.
        return "".join(" " if c in ",/" else c for c in name)

    def apply_tweak(self, files_to_restore: list[FileToRestore],
                    output_dir: str = None,
                    update_label=lambda x: None):
        if self.is_empty():
            return
        update_label(QCoreApplication.tr("Generating icon themes..."))
        skipped = []
        for theme in self.themes:
            display_name = self.sanitize_display_name(theme.display_name)
            folder = f"Library/WebClips/Cowabunga_{theme.bundle_id},{display_name}.webclip"

            # Info.plist
            files_to_restore.append(FileToRestore(
                contents=make_webclip_plist(theme.bundle_id, display_name),
                restore_path=f"{folder}/Info.plist",
                domain="HomeDomain"
            ))

            # icon.png — bytes by preference, then the stored path, then final
            # fallback to the persistent store copy.
            data = theme.get_icon_data()
            if data is None and theme.icon_path and os.path.isfile(theme.icon_path):
                with open(theme.icon_path, "rb") as f:
                    data = f.read()
            if data is None:
                skipped.append(theme.bundle_id)
                continue
            files_to_restore.append(FileToRestore(
                contents=data,
                restore_path=f"{folder}/icon.png",
                domain="HomeDomain"
            ))
        if skipped:
            update_label(QCoreApplication.tr(
                "Skipped icon themes without icon file: {0}").format(", ".join(skipped)))
        update_label(QCoreApplication.tr("Adding icon themes..."))