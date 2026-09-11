from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QDialog, QLabel, QHBoxLayout
)

from src.gui.ios.components import (
    IOSSectionHeader, IOSCard, IOSSettingsRow,
    IOSSwitch, TextInputDialog, NumberInputDialog
)
from src.gui.ios.compat import is_tweak_compatible
from src.gui.theme import ColorThemeManager
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.registry import SPECS_BY_SECTION, SECTION_FEATURES, Kind, Section
from src.tweaks.tweak_loader import load_plist_tweaks
from src.tweaks.hidden import current_hidden_feature_names, current_hidden_tweak_names

# Feature (page) name -> registry Section it maps to in the iOS tweaks UI.
# A HotLoad-hidden feature loses its whole section here (and the Sidebar/Home
# entries), so its tweaks are never even shown.
_SECTION_FEATURES = SECTION_FEATURES


def _hidden_feature_names() -> set:
    """Names of HotLoad-hidden features for the current setup, as a set."""
    return current_hidden_feature_names()


def _hidden_tweak_names() -> set:
    """Names of the tweaks that belong to HotLoad-hidden features for the
    current setup. Used by the preset loader to strip them during load."""
    return current_hidden_tweak_names()


def _hidden_sections() -> set:
    """Registry Sections whose feature is hidden, so we skip rendering them."""
    hidden = _hidden_feature_names()
    return {s for s, feat in _SECTION_FEATURES.items() if feat in hidden}


class IOSSectionContent(QWidget):
    """iOS-style tweak controls for one or more registry sections.

    Can be reused inside any scroll area or page.
    """

    def __init__(self, window, sections=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.sections = sections
        self._switch_labels = []

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

            c = ColorThemeManager.instance().colors
            label = QLabel(title)
            label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
            self._switch_labels.append(label)
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
        hidden_sections = _hidden_sections()
        for section in sections_to_render:
            if section in hidden_sections:
                continue
            layout.addWidget(IOSSectionHeader(
                QCoreApplication.translate("Nugget", section.value)))
            for spec in SPECS_BY_SECTION[section]:
                renderers[spec.kind](spec)

        layout.addStretch()

    def set_force_solarium_fallback_visible(self, visible: bool):
        if self.force_solarium_fallback_card is not None:
            self.force_solarium_fallback_card.setVisible(visible)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        for lbl in self._switch_labels:
            lbl.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")

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
        self._scroll = scroll
        self.content = IOSSectionContent(window, list(Section), self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.content._retheme()

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
        self._scroll = scroll
        self.content = IOSSectionContent(window, [section], self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.content._retheme()

    def set_force_solarium_fallback_visible(self, visible: bool):
        self.content.set_force_solarium_fallback_visible(visible)
