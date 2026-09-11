"""Reusable preset banner widget.

Shows which preset is currently active (making presets explicit) and a
shortcut to open the preset manager. Used on both the classic and the
iOS-style home pages so the active state is always visible.
"""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from src.gui.theme import ColorThemeManager


class PresetBanner(QFrame):
    """A card that displays the active preset and a manage shortcut."""

    def __init__(self, ios_style: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("presetBanner")
        self.setFrameShape(QFrame.StyledPanel)
        self._ios_style = ios_style

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.caption_lbl = QLabel(QCoreApplication.translate(
            "Nugget", "Active preset"))
        text_col.addWidget(self.caption_lbl)

        self.active_lbl = QLabel(QCoreApplication.translate("Nugget", "AutoSave"))
        text_col.addWidget(self.active_lbl)

        layout.addLayout(text_col, 1)

        self.manage_btn = QPushButton(QCoreApplication.translate("Nugget", "Manage"), self)
        self.manage_btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.manage_btn)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        if self._ios_style:
            self.setStyleSheet(f"""
                PresetBanner {{
                    background-color: {c.bg_secondary};
                    border-radius: 12px;
                    border: none;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                PresetBanner {{
                    background-color: {c.surface_hover};
                    border-radius: 10px;
                    border: none;
                }}
            """)
        self.caption_lbl.setStyleSheet(f"font-size: 12px; color: {c.text_secondary};")
        self.active_lbl.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {c.text_primary};")
        self.manage_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c.accent};
                font-size: 15px;
                font-weight: 600;
                border: none;
                padding: 8px 12px;
            }}
            QPushButton:hover {{ color: {c.accent_hover}; }}
        """)

    def set_active_preset(self, name: str):
        self.active_lbl.setText(name or QCoreApplication.translate("Nugget", "AutoSave"))


class PresetWidget(QWidget):
    """Home-screen container: header + active-preset banner + manage action.

    ``on_manage`` is called when the user taps the manage button; set it to
    navigate to the preset manager section of the app.
    """

    def __init__(self, window=None, on_manage=None, ios_style: bool = True,
                 parent=None):
        super().__init__(parent)
        self.window = window
        self._on_manage = on_manage
        self._ios_style = ios_style

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._header = QLabel()
        layout.addWidget(self._header)

        self.banner = PresetBanner(ios_style=ios_style)
        self.banner.manage_btn.clicked.connect(self._on_manage_pressed)
        layout.addWidget(self.banner)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        if self._ios_style:
            self._header.setText(QCoreApplication.translate("Nugget", "PRESETS"))
            self._header.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {c.text_secondary};"
                "letter-spacing: 0.5px; padding-left: 4px;")
        else:
            self._header.setText(QCoreApplication.translate("Nugget", "Presets"))
            self._header.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {c.text_primary};")
        self.banner._retheme()

    def _on_manage_pressed(self):
        if self._on_manage is not None:
            self._on_manage()

    def refresh(self):
        """Recompute and display the currently active preset."""
        name = self._current_preset_name()
        self.banner.set_active_preset(name)

    def _current_preset_name(self) -> str:
        if self.window is None:
            return ""
        try:
            last = self.window.settings.value("last_loaded_preset", "", type=str)
        except Exception:
            last = ""
        if last:
            return last
        return ""
