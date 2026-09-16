"""Data model for a single icon theme (one WebClip per themed app)."""


class IconTheme:
    """One app icon replacement.

    ``bundle_id`` is the REAL app bundle id (e.g. ``com.instagram.instagram``);
    the WebClip gets ``ApplicationBundleIdentifier`` pointing at it, so tapping
    the replaced icon launches the actual app. ``display_name`` is the label
    shown under the icon on the home screen — the empty string hides the
    label entirely (matches Cowabunga's ``nameToDisplay: ""`` behaviour).
    ``icon_path`` points at the PNG file chosen by the user; ``icon_data`` is
    the PNG bytes loaded either at add time or at apply time.
    """

    def __init__(self, bundle_id: str, display_name: str = "",
                 icon_path: str = "", icon_data: bytes = None):
        self.bundle_id = bundle_id
        self.display_name = display_name
        self.icon_path = icon_path
        self.icon_data = icon_data

    def set_icon_data(self, data: bytes):
        self.icon_data = data

    def get_icon_data(self) -> bytes:
        """Return the icon PNG bytes, loading them from disk if needed."""
        if self.icon_data is not None:
            return self.icon_data
        if self.icon_path:
            with open(self.icon_path, "rb") as f:
                self.icon_data = f.read()
            return self.icon_data
        return None

    def folder(self) -> str:
        """WebClip folder name, mirroring Cowabunga's ``Cowabunga_<bundleID>,<displayName>.webclip``."""
        return f"Cowabunga_{self.bundle_id},{self.display_name}.webclip"