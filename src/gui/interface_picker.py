from PySide6.QtCore import Qt, QCoreApplication, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

import os

from src.gui.theme import ColorThemeManager

_ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "qt", "icon")


def _render_svg(path: str, width: int, height: int) -> QPixmap:
    """Render an SVG file into a monochrome-friendly QPixmap (no QtSvg widget needed)."""
    renderer = QSvgRenderer(path)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return QPixmap.fromImage(image)


class InterfacePickerDialog(QDialog):
    """First-launch dialog: pick Classic or iOS-style interface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Choose Interface"))
        self.setFixedWidth(420)
        self.choice = None  # "classic" | "ios"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(QCoreApplication.translate("Nugget", "Welcome to GoldenNugget"))
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._subtitle = QLabel(QCoreApplication.translate(
            "Nugget", "Choose your interface style"))
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._subtitle)

        layout.addSpacing(8)

        # Classic option
        self._classic_frame = QFrame()
        cf_lay = QVBoxLayout(self._classic_frame)
        cf_lay.setContentsMargins(16, 12, 16, 12)
        classic_art = QLabel()
        classic_art.setPixmap(_render_svg(
            os.path.join(_ICON_DIR, "ui_classic.svg"), 340, 160))
        classic_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        classic_art.setStyleSheet("border: none; background: transparent;")
        cf_lay.addWidget(classic_art)
        cf_title = QLabel(QCoreApplication.translate("Nugget", "Classic"))
        cf_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        self._cf_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Sidebar navigation with familiar layout"))
        self._cf_desc.setWordWrap(True)
        cf_lay.addWidget(cf_title)
        cf_lay.addWidget(self._cf_desc)
        self._classic_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._classic_frame.mousePressEvent = lambda e: self._pick("classic")
        layout.addWidget(self._classic_frame)

        # iOS-style option
        self._ios_frame = QFrame()
        io_lay = QVBoxLayout(self._ios_frame)
        io_lay.setContentsMargins(16, 12, 16, 12)
        ios_art = QLabel()
        ios_art.setPixmap(_render_svg(
            os.path.join(_ICON_DIR, "ui_ios.svg"), 340, 160))
        ios_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ios_art.setStyleSheet("border: none; background: transparent;")
        io_lay.addWidget(ios_art)
        io_title = QLabel(QCoreApplication.translate("Nugget", "iOS-style"))
        io_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        self._io_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Full-screen mobile-inspired interface"))
        self._io_desc.setWordWrap(True)
        io_lay.addWidget(io_title)
        io_lay.addWidget(self._io_desc)
        self._ios_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ios_frame.mousePressEvent = lambda e: self._pick("ios")
        layout.addWidget(self._ios_frame)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; background: transparent; }}
        """)
        self._subtitle.setStyleSheet(f"color: {c.text_secondary}; font-size: 14px;")
        self._classic_frame.setStyleSheet(f"""
            QFrame {{ background-color: {c.surface_hover}; border-radius: 12px; }}
            QFrame:hover {{ background-color: {c.border}; }}
        """)
        self._cf_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; border: none;")
        self._ios_frame.setStyleSheet(f"""
            QFrame {{ background-color: {c.surface_hover}; border-radius: 12px; }}
            QFrame:hover {{ background-color: {c.border}; }}
        """)
        self._io_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; border: none;")

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()
