from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtGui import QColor, QPalette

from src.gui.theme.colors import ThemeColors, DARK, LIGHT, ACCENT_PRESETS


class ColorThemeManager(QObject):
    """Manages the app's color theme (dark/light + accent).

    Singleton accessed via ``ColorThemeManager.instance()``.
    Emits ``theme_changed`` whenever the palette or accent changes so
    connected widgets can re-render their stylesheets.
    """

    theme_changed = Signal()

    _inst = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("GoldenNugget", "GoldenNugget")
        self._has_explicit_mode = self._settings.contains("color_mode")
        self._mode = self._settings.value("color_mode", "dark")
        self._accent_name = self._settings.value("accent_color", "blue")
        self._colors = self._build_colors()

    @classmethod
    def instance(cls) -> "ColorThemeManager":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    # ---- current palette ------------------------------------------------

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dark(self) -> bool:
        return self._mode == "dark"

    def c(self, slot: str) -> str:
        """Shortcut: return the hex value for *slot* from the active palette."""
        return getattr(self._colors, slot)

    # ---- switching -------------------------------------------------------

    def set_mode(self, mode: str):
        if mode not in ("dark", "light"):
            return
        if mode == self._mode:
            return
        self._mode = mode
        self._has_explicit_mode = True
        self._settings.setValue("color_mode", mode)
        self._colors = self._build_colors()
        self.theme_changed.emit()

    def set_accent(self, name: str):
        if name not in ACCENT_PRESETS:
            return
        if name == self._accent_name:
            return
        self._accent_name = name
        self._settings.setValue("accent_color", name)
        self._colors = self._build_colors()
        self.theme_changed.emit()

    def set_system_theme(self, dark: bool):
        """Sync with the OS dark/light mode (called by platform detection)."""
        self.set_mode("dark" if dark else "light")

    def apply_system_theme(self, dark: bool):
        """Follow the OS dark/light mode, but never override a mode the user
        chose manually via the Settings switch (that choice persists first)."""
        if not self._has_explicit_mode:
            self.set_mode("dark" if dark else "light")

    # ---- QPalette for Fusion style ---------------------------------------

    def build_palette(self) -> QPalette:
        pal = QPalette()
        c = self._colors
        pal.setColor(QPalette.ColorRole.Window, QColor(c.bg_primary))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(c.text_primary))
        pal.setColor(QPalette.ColorRole.Base, QColor(c.bg_input))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c.bg_tertiary))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.bg_elevated))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c.text_primary))
        pal.setColor(QPalette.ColorRole.Text, QColor(c.text_primary))
        pal.setColor(QPalette.ColorRole.Button, QColor(c.bg_secondary))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(c.text_primary))
        pal.setColor(QPalette.ColorRole.BrightText, QColor(c.error))
        pal.setColor(QPalette.ColorRole.Link, QColor(c.accent))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(c.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(c.text_inverse))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c.text_disabled))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c.text_disabled))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c.text_disabled))
        return pal

    # ---- helpers ---------------------------------------------------------

    def _build_colors(self) -> ThemeColors:
        base = DARK if self._mode == "dark" else LIGHT
        accent, hover, pressed = ACCENT_PRESETS[self._accent_name]
        return base.with_accent(accent, hover, pressed)

    def accent_hex(self) -> str:
        """Return the ``(r, g, b)`` tuple for the current accent."""
        accent, _, _ = ACCENT_PRESETS[self._accent_name]
        return accent

    def accent_rgb(self) -> tuple:
        accent, _, _ = ACCENT_PRESETS[self._accent_name]
        q = QColor(accent)
        return (q.red(), q.green(), q.blue())
