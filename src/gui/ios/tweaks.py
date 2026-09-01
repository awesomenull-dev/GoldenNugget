from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QDialog, QDialogButtonBox,
    QLineEdit, QSpinBox, QLabel, QHBoxLayout
)

from src.gui.ios.components import (
    IOSSectionHeader, IOSCard, IOSSettingsRow,
    IOSSwitch
)
from src.gui.ios.compat import is_tweak_compatible
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.registry import SPECS_BY_SECTION, Kind, Section
from src.tweaks.tweak_loader import load_plist_tweaks


class TextInputDialog(QDialog):
    """iOS-style text input dialog"""
    def __init__(self, title: str, current_value: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
            }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QLineEdit {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.input = QLineEdit()
        self.input.setText(current_value)
        self.input.setPlaceholderText(QCoreApplication.translate("TextInputDialog", "Enter value..."))
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        layout.addWidget(buttons)

    def get_value(self) -> str:
        return self.input.text()


class NumberInputDialog(QDialog):
    """iOS-style number input dialog"""
    def __init__(self, title: str, current_value: int = 0, min_val: int = 0, max_val: int = 999, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QSpinBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 0; }
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.spin = QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(current_value)
        self.spin.setButtonSymbols(QSpinBox.NoButtons)
        self.spin.setStyleSheet("""
            QSpinBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
        """)
        layout.addWidget(self.spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        layout.addWidget(buttons)

    def get_value(self) -> int:
        return self.spin.value()


class IOSSectionContent(QWidget):
    """iOS-style tweak controls for one or more registry sections.

    Can be reused inside any scroll area or page.
    """

    def __init__(self, window, sections=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.sections = sections

        # Load tweaks (idempotent) so the sections below actually populate
        load_plist_tweaks()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 32)
        layout.setSpacing(8)

        try:
            device_ver = self.window.device_manager.get_current_device_version()
        except Exception:
            device_ver = ""
        try:
            model = self.window.device_manager.get_current_device_model() or ""
        except Exception:
            model = ""
        is_iphone = model.startswith("iPhone")

        def is_compatible(tweak_id: TweakID) -> bool:
            return is_tweak_compatible(tweak_id, device_ver, is_iphone)

        self.force_solarium_fallback_card = None

        # Helper to create a switch row for boolean tweaks
        def make_switch(tweak_id: TweakID, title: str, description: str = ""):
            if tweak_id not in tweaks:
                return
            tweak = tweaks[tweak_id]
            card = IOSCard()
            if tweak_id == TweakID.ForceSolariumFallback:
                self.force_solarium_fallback_card = card
            if not is_compatible(tweak_id):
                card.hide()
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)

            label = QLabel(title)
            label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
            row_layout.addWidget(label, 1)

            switch = IOSSwitch(tweak.enabled)
            switch.toggled.connect(lambda checked: tweak.set_enabled(checked))
            row_layout.addWidget(switch)

            if description:
                label.setToolTip(description)
                switch.setToolTip(description)
                card.setToolTip(description)

            layout.addWidget(card)

        # Helper for text input tweaks
        def make_text_input(tweak_id: TweakID, title: str, description: str = ""):
            if tweak_id not in tweaks:
                return
            if not is_compatible(tweak_id):
                return
            tweak = tweaks[tweak_id]
            card = IOSCard()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            row = IOSSettingsRow(title)
            if description:
                row.setToolTip(description)
            current = ""
            if hasattr(tweak, 'value') and tweak.value:
                current = str(tweak.value)
                row.setText(f"{title}  ({current})")
            row.clicked.connect(lambda: self._show_text_input_dialog(tweak_id, title, current, row))
            card_layout.addWidget(row)
            layout.addWidget(card)

        # Helper for number input tweaks
        def make_number_input(tweak_id: TweakID, title: str, min_val: int = 0, max_val: int = 999,
                              description: str = ""):
            if tweak_id not in tweaks:
                return
            if not is_compatible(tweak_id):
                return
            tweak = tweaks[tweak_id]
            card = IOSCard()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            row = IOSSettingsRow(title)
            if description:
                row.setToolTip(f"{description}\n\n"
                               + QCoreApplication.translate("Nugget", "Range: {0} – {1}")
                               .format(min_val, max_val))
            current = 0
            if hasattr(tweak, 'value') and tweak.value:
                current = int(tweak.value) if tweak.value else 0
                row.setText(f"{title}  ({current})")
            row.clicked.connect(lambda: self._show_number_input_dialog(tweak_id, title, current, row, min_val, max_val))
            card_layout.addWidget(row)
            layout.addWidget(card)

        # Render sections straight from the registry. Titles (and descriptions)
        # are stored as QT_TRANSLATE_NOOP markers and translated here, at
        # render time.
        def tr_title(spec) -> str:
            return QCoreApplication.translate("Nugget", spec.title)

        def tr_description(spec) -> str:
            if not spec.description:
                return ""
            return QCoreApplication.translate("Nugget", spec.description)

        renderers = {
            Kind.SWITCH: lambda spec: make_switch(spec.id, tr_title(spec), tr_description(spec)),
            Kind.TEXT: lambda spec: make_text_input(spec.id, tr_title(spec), tr_description(spec)),
            Kind.NUMBER: lambda spec: make_number_input(
                spec.id, tr_title(spec), spec.min_value, spec.max_value, tr_description(spec)),
        }

        sections_to_render = self.sections if self.sections is not None else list(Section)
        for section in sections_to_render:
            layout.addWidget(IOSSectionHeader(
                QCoreApplication.translate("Nugget", section.value)))
            for spec in SPECS_BY_SECTION[section]:
                renderers[spec.kind](spec)

        layout.addStretch()

    def set_force_solarium_fallback_visible(self, visible: bool):
        if self.force_solarium_fallback_card is not None:
            self.force_solarium_fallback_card.setVisible(visible)

    def _show_text_input_dialog(self, tweak_id: TweakID, title: str, current: str, row: IOSSettingsRow):
        dialog = TextInputDialog(title, current, self)
        if dialog.exec() == QDialog.Accepted:
            value = dialog.get_value()
            tweaks[tweak_id].set_value(value, toggle_enabled=True)
            display = value if value else "(empty)"
            row.setText(f"{title}  ({display})")

    def _show_number_input_dialog(self, tweak_id: TweakID, title: str, current: int, row: IOSSettingsRow, min_val: int, max_val: int):
        dialog = NumberInputDialog(title, current, min_val, max_val, self)
        if dialog.exec() == QDialog.Accepted:
            value = dialog.get_value()
            tweaks[tweak_id].set_value(value, toggle_enabled=True)
            row.setText(f"{title}  ({value})")


class IOSTweaksPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        self.content = IOSSectionContent(window, list(Section), self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

    def set_force_solarium_fallback_visible(self, visible: bool):
        self.content.set_force_solarium_fallback_visible(visible)


class IOSSectionPage(QWidget):
    """Standalone iOS-style page for a single tweak section."""

    def __init__(self, window, section: Section, parent=None):
        super().__init__(parent)
        self.window = window
        self.section = section
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        self.content = IOSSectionContent(window, [section], self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

    def set_force_solarium_fallback_visible(self, visible: bool):
        self.content.set_force_solarium_fallback_visible(visible)
