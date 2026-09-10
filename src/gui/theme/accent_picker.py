from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton

from src.gui.theme.colors import ACCENT_PRESETS
from src.gui.theme.theme_manager import ColorThemeManager


class AccentPicker(QWidget):
    """Row of colored circles for choosing the accent color."""

    accent_changed = Signal(str)

    _SIZE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tm = ColorThemeManager.instance()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._buttons: dict[str, QPushButton] = {}

        for name in ACCENT_PRESETS:
            btn = QPushButton(self)
            btn.setFixedSize(self._SIZE, self._SIZE)
            btn.setCursor(Qt.PointingHandCursor)
            accent_hex = ACCENT_PRESETS[name][0]
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent_hex};
                    border-radius: {self._SIZE // 2}px;
                    border: 3px solid transparent;
                }}
                QPushButton:hover {{
                    border: 3px solid {accent_hex};
                    background-color: {accent_hex};
                }}
            """)
            btn.clicked.connect(lambda checked, n=name: self._on_click(n))
            btn.setToolTip(name.capitalize())
            self._buttons[name] = btn
            layout.addWidget(btn)
        layout.addStretch()

        self._highlight_selected()

    def _on_click(self, name: str):
        self._tm.set_accent(name)
        self._highlight_selected()
        self.accent_changed.emit(name)

    def _highlight_selected(self):
        current = self._tm._accent_name
        for name, btn in self._buttons.items():
            accent_hex = ACCENT_PRESETS[name][0]
            if name == current:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {accent_hex};
                        border-radius: {self._SIZE // 2}px;
                        border: 3px solid {self._tm.c('text_primary')};
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {accent_hex};
                        border-radius: {self._SIZE // 2}px;
                        border: 3px solid transparent;
                    }}
                    QPushButton:hover {{
                        border: 3px solid {accent_hex};
                    }}
                """)
