from PySide6.QtCore import Qt, QCoreApplication, Slot, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame
)

from src.gui.ios.components import IOSCard, IOSPrimaryButton
from src.gui.preset_widget import PresetWidget


class IOSHomePage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Logo + Title row
        header = QHBoxLayout()
        header.setSpacing(16)

        # Load logo from resources
        logo = QLabel(self)
        logo.setFixedSize(80, 80)
        logo.setScaledContents(True)
        pixmap = QPixmap(":/credits/big_nugget.png")
        if not pixmap.isNull():
            logo.setPixmap(pixmap)
        else:
            logo.setStyleSheet("background-color: #1C1C1E; border-radius: 14px;")
        header.addWidget(logo)

        title_layout = QVBoxLayout()
        title = QLabel(QCoreApplication.translate("Nugget", "GoldenNugget"), self)
        title.setStyleSheet("font-size: 32px; font-weight: 700; color: #FFFFFF;")
        title_layout.addWidget(title)

        # Dynamic subtitle from device
        self.subtitle = QLabel(QCoreApplication.translate("Nugget", "iPhone (iOS —)"), self)
        self.subtitle.setStyleSheet("font-size: 15px; color: #8E8E93;")
        title_layout.addWidget(self.subtitle)
        header.addLayout(title_layout, 1)

        # Device picker - actual dropdown with devices
        self.device_combo = QComboBox(self)
        self.device_combo.setFixedHeight(36)
        self.device_combo.setStyleSheet("""
            QComboBox {
                background-color: #1C1C1E;
                border-radius: 18px;
                color: #FFF;
                padding: 0 16px;
                font-size: 15px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #1C1C1E;
                color: #FFF;
                selection-background-color: #007AFF;
            }
        """)
        self.populate_device_picker()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        header.addWidget(self.device_combo)

        # Refresh button
        refresh_btn = QPushButton("⟳", self)
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1E;
                border-radius: 18px;
                color: #FFF;
                font-size: 18px;
                border: none;
            }
            QPushButton:hover { background-color: #2C2C2E; }
        """)
        refresh_btn.clicked.connect(self.refresh_devices)
        header.addWidget(refresh_btn)

        # Settings button
        settings_btn = QPushButton("⚙", self)
        settings_btn.setFixedSize(36, 36)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1E;
                border-radius: 18px;
                color: #FFF;
                font-size: 18px;
                border: none;
            }
            QPushButton:hover { background-color: #2C2C2E; }
        """)
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)

        layout.addLayout(header)

        # Status support label
        self.status_lbl = QLabel("", self)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextFormat(Qt.RichText)
        layout.addWidget(self.status_lbl)

        # Three cards row: PosterBoard, Tweaks, Daemons
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

        # Apply Tweaks button
        apply_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Apply Tweaks"))
        apply_btn.clicked.connect(self.open_apply_classic)
        layout.addWidget(apply_btn)

        # Reset Tweaks button
        reset_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Reset Tweaks"))
        reset_btn.clicked.connect(self.reset_tweaks)
        layout.addWidget(reset_btn)

        # Presets widget: makes the active preset explicit and offers a quick
        # path to the preset manager.
        self.preset_widget = PresetWidget(
            window=self.window, on_manage=self.open_presets_section, ios_style=True)
        layout.addWidget(self.preset_widget)

        # Process status indicator (apply/reset progress + completion)
        self.process_status_lbl = QLabel("", self)
        self.process_status_lbl.setWordWrap(True)
        self.process_status_lbl.setAlignment(Qt.AlignCenter)
        self.process_status_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #30D158;")
        self.process_status_lbl.hide()
        layout.addWidget(self.process_status_lbl)
        # Single auto-hide timer: restarted on every progress update so the
        # label never hides mid-apply (stacked singleShot timers caused
        # hide/show flicker on each progress tick).
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_process_status)

        layout.addStretch()

        # Initial update
        self.update_status()
        self.update_device_info()
        self.refresh_preset_widget()

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
        # Trigger refresh via main window
        self.window.refresh_devices()

    @Slot()
    def open_settings(self):
        # Open iOS settings page within the iOS stack
        self.window.ios_pages.setCurrentIndex(4)  # IOSSettingsPage

    def open_presets_section(self):
        """Open settings and jump straight to the presets section."""
        self.window.open_presets_section()

    def switch_to_ios_page(self, index: int):
        self.window.ios_pages.setCurrentIndex(index)

    def open_apply_classic(self):
        # Actually apply tweaks instead of just opening apply page
        self.window.apply_changes()

    def reset_tweaks(self):
        """Reset tweaks using the classic reset dialog (select pages to reset)."""
        from src.gui.dialogs.reset_dialog import ResetDialog
        dialog = ResetDialog(device_manager=self.window.device_manager, apply_reset=self.window.apply_changes)
        dialog.exec()

    def show_process_status(self, text: str, success: bool = None):
        """Show a status message for apply/reset operations.

        ``success``: True -> green, False -> red, None -> neutral progress.
        The message auto-hides after a few seconds.
        """
        if success is True:
            color = "#30D158"
        elif success is False:
            color = "#FF453A"
        else:
            color = "#007AFF"
        self.process_status_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {color};")
        self.process_status_lbl.setText(text)
        self.process_status_lbl.show()
        self._hide_timer.start(6000)

    def hide_process_status(self):
        self.process_status_lbl.hide()

    def update_status(self):
        try:
            if self.window.device_manager.get_current_device_udid():
                if self.window.device_manager.get_current_device_partially_supported():
                    status_text = QCoreApplication.translate("Nugget", "Partially Supported")
                    color = "#FFD60A"
                else:
                    status_text = QCoreApplication.translate("QCoreApplication", "Supported!")
                    color = "#30D158"
            else:
                status_text = QCoreApplication.translate("Nugget", "Not connected")
                color = "#FFFFFF"
        except AttributeError:
            status_text = QCoreApplication.translate("Nugget", "Not connected")
            color = "#FFFFFF"
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
        """Update the active-preset banner (call after loading/saving a preset)."""
        self.preset_widget.refresh()

    def set_statusbar_visible(self, visible: bool):
        self.statusbar_card.setVisible(visible)

    def _make_card(self, title: str, subtitle: str, page_index: int) -> IOSCard:
        """Build one of the feature shortcut cards (title + subtitle header)."""
        card = IOSCard()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background-color: #1C1C1E; border-top-left-radius: 12px; "
            "border-top-right-radius: 12px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_title = QLabel(
            QCoreApplication.translate("Nugget", title), header)
        header_title.setStyleSheet("font-size: 17px; font-weight: 600; color: #FFFFFF;")
        header_layout.addWidget(header_title, 1, Qt.AlignCenter)
        card_layout.addWidget(header)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)
        sub = QLabel(QCoreApplication.translate("Nugget", subtitle), content)
        sub.setStyleSheet("font-size: 14px; color: #8E8E93;")
        sub.setWordWrap(True)
        content_layout.addWidget(sub)
        card_layout.addWidget(content)

        card.mousePressEvent = lambda e: self.switch_to_ios_page(page_index)
        card.setCursor(Qt.PointingHandCursor)
        return card