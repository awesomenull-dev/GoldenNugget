from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

from src.gui.theme.theme_manager import ColorThemeManager
from src.gui.theme.colors import DARK, LIGHT, ACCENT_PRESETS
from src.gui.theme.styles import STYLES
from src.gui.theme.accent_picker import AccentPicker


def t(style_key: str) -> str:
    """Render a named stylesheet template with the current theme colors."""
    tm = ColorThemeManager.instance()
    template = STYLES[style_key]
    return template.format_map(tm.colors.__dict__)


def themed_stylesheet(style_key: str, **extra) -> str:
    """Render a stylesheet template with the current colors plus runtime
    extras (e.g. a generated caret image path passed as ``caret=...``)."""
    tm = ColorThemeManager.instance()
    payload = dict(tm.colors.__dict__)
    payload.update(extra)
    return STYLES[style_key].format_map(payload)


def theme_icon(resource_path: str, color_hex: str) -> QIcon:
    """Recolor a monochrome (white) SVG icon to *color_hex* using its alpha."""
    img = QImage(resource_path)
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(img.rect(), QColor(color_hex))
    painter.end()
    return QIcon(QPixmap.fromImage(img))


__all__ = [
    "ColorThemeManager", "DARK", "LIGHT", "ACCENT_PRESETS", "STYLES",
    "AccentPicker", "t", "themed_stylesheet", "theme_icon",
]