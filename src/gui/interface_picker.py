from PySide6.QtCore import Qt, QCoreApplication, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

import os

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
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; background: transparent; }
        """)
        self.choice = None  # "classic" | "ios"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(QCoreApplication.translate("Nugget", "Welcome to GoldenNugget"))
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(QCoreApplication.translate(
            "Nugget", "Choose your interface style"))
        subtitle.setStyleSheet("color: #8E8E93; font-size: 14px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Classic option
        classic_frame = QFrame()
        classic_frame.setStyleSheet("""
            QFrame { background-color: #2C2C2E; border-radius: 12px; }
            QFrame:hover { background-color: #3A3A3C; }
        """)
        cf_lay = QVBoxLayout(classic_frame)
        cf_lay.setContentsMargins(16, 12, 16, 12)
        classic_art = QLabel()
        classic_art.setPixmap(_render_svg(
            os.path.join(_ICON_DIR, "ui_classic.svg"), 340, 160))
        classic_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        classic_art.setStyleSheet("border: none; background: transparent;")
        cf_lay.addWidget(classic_art)
        cf_title = QLabel(QCoreApplication.translate("Nugget", "Classic"))
        cf_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        cf_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Sidebar navigation with familiar layout"))
        cf_desc.setStyleSheet("color: #8E8E93; font-size: 13px; border: none;")
        cf_desc.setWordWrap(True)
        cf_lay.addWidget(cf_title)
        cf_lay.addWidget(cf_desc)
        classic_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        classic_frame.mousePressEvent = lambda e: self._pick("classic")
        layout.addWidget(classic_frame)

        # iOS-style option
        ios_frame = QFrame()
        ios_frame.setStyleSheet("""
            QFrame { background-color: #2C2C2E; border-radius: 12px; }
            QFrame:hover { background-color: #3A3A3C; }
        """)
        io_lay = QVBoxLayout(ios_frame)
        io_lay.setContentsMargins(16, 12, 16, 12)
        ios_art = QLabel()
        ios_art.setPixmap(_render_svg(
            os.path.join(_ICON_DIR, "ui_ios.svg"), 340, 160))
        ios_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ios_art.setStyleSheet("border: none; background: transparent;")
        io_lay.addWidget(ios_art)
        io_title = QLabel(QCoreApplication.translate("Nugget", "iOS-style"))
        io_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        io_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Full-screen mobile-inspired interface"))
        io_desc.setStyleSheet("color: #8E8E93; font-size: 13px; border: none;")
        io_desc.setWordWrap(True)
        io_lay.addWidget(io_title)
        io_lay.addWidget(io_desc)
        ios_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        ios_frame.mousePressEvent = lambda e: self._pick("ios")
        layout.addWidget(ios_frame)

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()