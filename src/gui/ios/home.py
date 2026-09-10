from PySide6.QtCore import Qt, QCoreApplication, Slot, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame
)

from src.gui.ios.components import IOSCard, IOSPrimaryButton
from src.gui.preset_widget import PresetWidget
from src.gui.theme import t, ColorThemeManager


class IOSHomePage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")
        self._c = ColorThemeManager.instance().colors

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Logo + Title row
        header = QHBoxLayout()
        header.setSpacing(16)

        # Load logo from resources
        self._logo = QLabel(self)
        self._logo.setFixedSize(80, 80)
        self._logo.setScaledContents(True)
        pixmap = QPixmap(":/credits/big_nugget.png")
        if not pixmap.isNull():
            self._logo.setPixmap(pixmap)
        else:
            self._logo.setStyleSheet(f"background-color: {self._c.bg_secondary}; border-radius: 14px;")
        header.addWidget(self._logo)

        title_layout = QVBoxLayout()
        self._title = QLabel(QCoreApplication.translate("Nugget", "GoldenNugget"), self)
        self._title.setStyleSheet(t("home_title"))
        title_layout.addWidget(self._title)

        self.subtitle = QLabel(QCoreApplication.translate("Nugget", "iPhone (iOS —)"), self)
        self.subtitle.setStyleSheet(t("home_subtitle"))
        title_layout.addWidget(self.subtitle)
        header.addLayout(title_layout, 1)

        self.device_combo = QComboBox(self)
        self.device_combo.setFixedHeight(36)
        self._style_device_combo()
        self.populate_device_picker()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        header.addWidget(self.device_combo)

        self._refresh_btn = QPushButton("⟳", self)
        self._refresh_btn.setFixedSize(36, 36)
        self._refresh_btn.setStyleSheet(t("home_icon_button"))
        self._refresh_btn.clicked.connect(self.refresh_devices)
        header.addWidget(self._refresh_btn)

        self._settings_btn = QPushButton("⚙", self)
        self._settings_btn.setFixedSize(36, 36)
        self._settings_btn.setStyleSheet(t("home_icon_button"))
        self._settings_btn.clicked.connect(self.open_settings)
        header.addWidget(self._settings_btn)

        layout.addLayout(header)

        self.status_lbl = QLabel("", self)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextFormat(Qt.RichText)
        layout.addWidget(self.status_lbl)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.posterboard_card = self._make_card(
            "PosterBoard", "Animated wallpapers & templates", 2)
        self.tweaks_card = self._make_card(
            "Tweaks", "Customize system settings", 1)
        self.daemons_card = self._make_card(
            "Daemons", "Disable system daemons", 3)
        self.statusbar_card = self._make_card(
            "Status Bar", "Customize the status bar", 5)
        cards_row.addWidget(self.posterboard_card, 1)
        cards_row.addWidget(self.tweaks_card, 1)
        cards_row.addWidget(self.daemons_card, 1)
        cards_row.addWidget(self.statusbar_card, 1)
        layout.addLayout(cards_row)

        apply_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Apply Tweaks"))
        apply_btn.clicked.connect(self.open_apply_classic)
        layout.addWidget(apply_btn)

        reset_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Reset Tweaks"))
        reset_btn.clicked.connect(self.reset_tweaks)
        layout.addWidget(reset_btn)

        self.preset_widget = PresetWidget(
            window=self.window, on_manage=self.open_presets_section, ios_style=True)
        layout.addWidget(self.preset_widget)

        self.process_status_lbl = QLabel("", self)
        self.process_status_lbl.setWordWrap(True)
        self.process_status_lbl.setAlignment(Qt.AlignCenter)
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.process_status_lbl.hide()
        layout.addWidget(self.process_status_lbl)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_process_status)

        layout.addStretch()

        self.update_status()
        self.update_device_info()
        self.refresh_preset_widget()

    def _style_device_combo(self):
        c = self._c
        self.device_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {c.bg_secondary};
                border-radius: 18px;
                color: {c.text_primary};
                padding: 0 16px;
                font-size: 15px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                selection-background-color: {c.accent};
            }}
        """)

    def _retheme(self):
        self._c = ColorThemeManager.instance().colors
        c = self._c
        if self._logo.pixmap() is None or self._logo.pixmap().isNull():
            self._logo.setStyleSheet(f"background-color: {c.bg_secondary}; border-radius: 14px;")
        self._title.setStyleSheet(t("home_title"))
        self.subtitle.setStyleSheet(t("home_subtitle"))
        self._style_device_combo()
        self._refresh_btn.setStyleSheet(t("home_icon_button"))
        self._settings_btn.setStyleSheet(t("home_icon_button"))
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.update_status()
        # Rebuild card headers for new colors
        for card, title, sub_text in [
            (self.posterboard_card, "PosterBoard", "Animated wallpapers & templates"),
            (self.tweaks_card, "Tweaks", "Customize system settings"),
            (self.daemons_card, "Daemons", "Disable system daemons"),
            (self.statusbar_card, "Status Bar", "Customize the status bar"),
        ]:
            header = card.findChild(QFrame)
            if header:
                header.setStyleSheet(
                    f"background-color: {c.bg_secondary}; border-top-left-radius: 12px; "
                    f"border-top-right-radius: 12px;")
            title_lbl = card.findChild(QLabel)
            if title_lbl:
                title_lbl.setStyleSheet(
                    f"font-size: 17px; font-weight: 600; color: {c.text_primary};")
            # Find subtitle label (second label in card)
            labels = card.findChildren(QLabel)
            if len(labels) > 1:
                labels[1].setStyleSheet(f"font-size: 14px; color: {c.text_secondary};")

    def populate_device_picker(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        try:
            devices = self.window.device_manager.devices
            if devices:
                for device in devices:
                    tag = " (@ USB)" if device.connected_via_usb else " (@ WiFi)"
                    self.device_combo.addItem(f"{device.name}{tag}")
            else:
                self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
        except Exception:
            self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
        self.device_combo.blockSignals(False)

    @Slot()
    def on_device_changed(self, index):
        if len(self.window.device_manager.devices) > 0 and index >= 0:
            self.window.change_selected_device(index)
            self.update_device_info()
            self.update_status()

    @Slot()
    def refresh_devices(self):
        self.window.refresh_devices()

    @Slot()
    def open_settings(self):
        self.window.ios_pages.setCurrentIndex(4)

    def open_presets_section(self):
        self.window.open_presets_section()

    def switch_to_ios_page(self, index: int):
        self.window.ios_pages.setCurrentIndex(index)

    def open_apply_classic(self):
        self.window.apply_changes()

    def reset_tweaks(self):
        from src.gui.dialogs.reset_dialog import ResetDialog
        dialog = ResetDialog(device_manager=self.window.device_manager, apply_reset=self.window.apply_changes)
        dialog.exec()

    def show_process_status(self, text: str, success: bool = None):
        c = self._c
        if success is True:
            color = c.success
        elif success is False:
            color = c.error
        else:
            color = c.accent
        self.process_status_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {color};")
        self.process_status_lbl.setText(text)
        self.process_status_lbl.show()
        self._hide_timer.start(6000)

    def hide_process_status(self):
        self.process_status_lbl.hide()

    def update_status(self):
        c = self._c
        try:
            if self.window.device_manager.get_current_device_udid():
                if self.window.device_manager.get_current_device_partially_supported():
                    status_text = QCoreApplication.translate("Nugget", "Partially Supported")
                    color = c.warning
                else:
                    status_text = QCoreApplication.translate("QCoreApplication", "Supported!")
                    color = c.success
            else:
                status_text = QCoreApplication.translate("Nugget", "Not connected")
                color = c.text_primary
        except AttributeError:
            status_text = QCoreApplication.translate("Nugget", "Not connected")
            color = c.text_primary
        self.status_lbl.setText(f"<span style='color:{color};'>{status_text}</span>")

    def update_device_info(self):
        try:
            ver = self.window.device_manager.get_current_device_version() or "—"
            build = self.window.device_manager.get_current_device_build() or "—"
            self.subtitle.setText(QCoreApplication.translate("Nugget", "iPhone (iOS {0} {1})").format(ver, build))
        except AttributeError:
            self.subtitle.setText(QCoreApplication.translate("Nugget", "iPhone (iOS —)"))

    def refresh_device_combo(self):
        self.populate_device_picker()

    def refresh_preset_widget(self):
        self.preset_widget.refresh()

    def set_statusbar_visible(self, visible: bool):
        self.statusbar_card.setVisible(visible)

    def _make_card(self, title: str, subtitle: str, page_index: int) -> IOSCard:
        c = self._c
        card = IOSCard()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {c.bg_secondary}; border-top-left-radius: 12px; "
            f"border-top-right-radius: 12px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_title = QLabel(
            QCoreApplication.translate("Nugget", title), header)
        header_title.setStyleSheet(
            f"font-size: 17px; font-weight: 600; color: {c.text_primary};")
        header_layout.addWidget(header_title, 1, Qt.AlignCenter)
        card_layout.addWidget(header)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)
        sub = QLabel(QCoreApplication.translate("Nugget", subtitle), content)
        sub.setStyleSheet(f"font-size: 14px; color: {c.text_secondary};")
        sub.setWordWrap(True)
        content_layout.addWidget(sub)
        card_layout.addWidget(content)

        card.mousePressEvent = lambda e: self.switch_to_ios_page(page_index)
        card.setCursor(Qt.PointingHandCursor)
        return card
