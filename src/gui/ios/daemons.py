from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QHBoxLayout, QLabel, QMessageBox

from src.gui.ios.components import IOSSectionHeader, IOSSwitch
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.tweak_loader import load_daemons
from src.tweaks.daemons_tweak import Daemon
from src.controllers.hotload import HotLoad, confirm_flagged


class IOSDaemonsContent(QWidget):
    """iOS-style daemons controls, usable inside any scroll area or page."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window

        # Ensure daemons tweaks are loaded
        load_daemons()

        self.daemons_tweak = tweaks[TweakID.Daemons]
        self.screen_time_tweak = tweaks.get(TweakID.ClearScreenTimeAgentPlist)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 32)
        layout.setSpacing(8)

        # Master enable switch
        layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Daemons to Disable")
        ))
        master_card = QWidget()
        master_row = QHBoxLayout(master_card)
        master_row.setContentsMargins(16, 10, 16, 10)
        master_row.setSpacing(12)
        master_label = QLabel(QCoreApplication.translate("Nugget", "Enable Daemon Modifications"))
        master_label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        master_row.addWidget(master_label, 1)
        self.master_switch = IOSSwitch(self.daemons_tweak.enabled)
        self.master_switch.toggled.connect(self._on_master_toggled)
        master_row.addWidget(self.master_switch)
        layout.addWidget(master_card)

        self.daemon_cards = []
        self.daemon_switches = []
        self._confirming = False
        self._hotload_acked = False
        for title, daemon in [
            (QCoreApplication.translate("Nugget", "Disable thermalmonitord"), Daemon.thermalmonitord),
            (QCoreApplication.translate("Nugget", "Disable OTA"), Daemon.OTA),
            (QCoreApplication.translate("Nugget", "Disable UsageTrackingAgent"), Daemon.UsageTrackingAgent),
            (QCoreApplication.translate("Nugget", "Disable Game Center"), Daemon.GameCenter),
            (QCoreApplication.translate("Nugget", "Disable ATWAKEUP"), Daemon.ATWAKEUP),
            (QCoreApplication.translate("Nugget", "Disable Tips Services"), Daemon.Tips),
            (QCoreApplication.translate("Nugget", "VPN Icon"), Daemon.VPN),
            (QCoreApplication.translate("Nugget", "Disable Chinese WLAN Service"), Daemon.ChineseLAN),
            (QCoreApplication.translate("Nugget", "Disable HealthKit"), Daemon.HealthKit),
            (QCoreApplication.translate("Nugget", "Disable AirPrint"), Daemon.AirPrint),
            (QCoreApplication.translate("Nugget", "Disable Assistive Touch"), Daemon.AssistiveTouch),
            (QCoreApplication.translate("Nugget", "Disable iCloud"), Daemon.iCloud),
            (QCoreApplication.translate("Nugget", "Disable Internet Tethering (Hotspot)"), Daemon.InternetTethering),
            (QCoreApplication.translate("Nugget", "Disable Passbook"), Daemon.PassBook),
            (QCoreApplication.translate("Nugget", "Disable Spotlight"), Daemon.Spotlight),
            (QCoreApplication.translate("Nugget", "Disable NanoTimeKit (Apple Watch Face Sync)"), Daemon.NanoTimeKit),
            (QCoreApplication.translate("Nugget", "Follow Up"), Daemon.FollowUp),
            (QCoreApplication.translate("Nugget", "Location Services"), Daemon.Location),
        ]:
            card, switch = self._make_daemon_switch(layout, title, daemon)
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))

        # Screen Time
        layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Disable Screen Time Agent")
        ))
        if self.screen_time_tweak is not None:
            card = QWidget()
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(16, 10, 16, 10)
            row_layout.setSpacing(12)
            label = QLabel(QCoreApplication.translate("Nugget", "Clear ScreenTimeAgent.plist file"))
            label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
            row_layout.addWidget(label, 1)
            self.screen_time_switch = IOSSwitch(self.screen_time_tweak.enabled)
            self.screen_time_switch.toggled.connect(self.screen_time_tweak.set_enabled)
            row_layout.addWidget(self.screen_time_switch)
            layout.addWidget(card)

        self._update_daemons_enabled()
        layout.addStretch()

    def _make_daemon_switch(self, layout, title: str, daemon: Daemon):
        card = QWidget()
        row_layout = QHBoxLayout(card)
        row_layout.setContentsMargins(16, 10, 16, 10)
        row_layout.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        row_layout.addWidget(label, 1)

        value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
        switch = IOSSwitch(value)
        switch.toggled.connect(
            lambda checked, d=daemon: self._on_daemon_toggled(d, checked)
        )
        row_layout.addWidget(switch)

        layout.addWidget(card)
        return card, switch

    def _on_master_toggled(self, checked: bool):
        if checked and not self._confirm_daemon_enable():
            # User hit "Stop" in one of the warnings: keep the master off.
            self.master_switch.blockSignals(True)
            self.master_switch.setChecked(False)
            self.master_switch.blockSignals(False)
            return
        self.daemons_tweak.set_enabled(checked)
        self._update_daemons_enabled()

    def _on_daemon_toggled(self, daemon: Daemon, checked: bool):
        if checked and not self._confirm_daemon_enable():
            # Revert the individual toggle so nothing gets applied.
            self._set_switch(daemon, False)
            return
        self.daemons_tweak.set_multiple_values(daemon.value, value=checked)
        if checked:
            self.master_switch.setChecked(True)
            if daemon is Daemon.Location:
                self._warn_location_daemon()

    def _set_switch(self, daemon: Daemon, value: bool):
        for d, switch in self.daemon_switches:
            if d is daemon:
                switch.blockSignals(True)
                switch.setChecked(value)
                switch.blockSignals(False)
                return

    def _confirm_daemon_enable(self) -> bool:
        """Show the bootloop + backup warnings once; the acknowledgement is
        stored in GoldenNugget settings (not in presets), so it only pops up
        the first time daemons are enabled for this install."""
        if self._confirming:
            return True
        settings = getattr(self.window, "settings", None) if self.window is not None else None
        # HotLoad: if the Daemons tweak is flagged dangerous for this
        # device/iOS, warn first. Acked once per page instance.
        if not self._hotload_acked:
            dm = getattr(self.window, "device_manager", None)
            version = dm.get_current_device_version() if dm is not None else None
            model = dm.get_current_device_model() if dm is not None else None
            hotload = HotLoad(settings)
            rule = hotload.rule_for(
                "Daemons", device_version=version, device_model=model)
            if rule is not None and not confirm_flagged(rule, self):
                return False
            self._hotload_acked = True
        if settings is not None and settings.value("daemon_bootloop_warned", False, type=bool):
            return True
        self._confirming = True
        try:
            if not self._show_confirm_dialog(
                "Hold Up before pressing continue, this section can bootloop "
                "your phone. Don't cry about that you have not been notified then."
            ):
                return False
            if not self._show_confirm_dialog(
                "Creating full backup is hightly recommended"
            ):
                return False
            if settings is not None:
                settings.setValue("daemon_bootloop_warned", True)
                settings.sync()
            return True
        finally:
            self._confirming = False

    def _show_confirm_dialog(self, text: str) -> bool:
        import PySide6.QtWidgets as QW
        box = QW.QMessageBox(self)
        box.setIcon(QW.QMessageBox.Icon.Warning)
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Hold Up"))
        box.setText(text)
        continue_btn = box.addButton(
            QCoreApplication.translate("Nugget", "Continue Anyway"),
            QW.QMessageBox.ButtonRole.AcceptRole)
        stop_btn = box.addButton(
            QCoreApplication.translate("Nugget", "Stop"),
            QW.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(continue_btn)
        box.exec()
        return box.clickedButton() is continue_btn

    def _warn_location_daemon(self):
        """Location Services daemon keeps PosterBoard alive on iPhone 14."""
        from src.devicemanagement.data_singleton import DataSingleton
        current = DataSingleton().current_device
        model = current.model if current is not None else ""
        if not model.startswith("iPhone14,"):
            return
        QMessageBox.warning(
            self,
            QCoreApplication.translate("Nugget", "Wallpaper Risk on iPhone 14"),
            QCoreApplication.translate(
                "Nugget",
                "Disabling Location Services has been reported to break wallpapers "
                "(PosterBoard) on iPhone 14. If your wallpaper disappears after "
                "applying, re-enable this daemon and apply again."))

    def _update_daemons_enabled(self):
        enabled = self.daemons_tweak.enabled
        for card in self.daemon_cards:
            card.setEnabled(enabled)

    def refresh_from_tweaks(self):
        """Resync every switch with the current tweak state."""
        self.master_switch.blockSignals(True)
        self.master_switch.setChecked(self.daemons_tweak.enabled)
        self.master_switch.blockSignals(False)
        self._update_daemons_enabled()

        for daemon, switch in self.daemon_switches:
            value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
            switch.blockSignals(True)
            switch.setChecked(value)
            switch.blockSignals(False)

        screen_time_switch = getattr(self, 'screen_time_switch', None)
        if screen_time_switch is not None:
            screen_time_switch.blockSignals(True)
            screen_time_switch.setChecked(self.screen_time_tweak.enabled)
            screen_time_switch.blockSignals(False)


class IOSDaemonsPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        self.content = IOSDaemonsContent(window, self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

    def refresh_from_tweaks(self):
        self.content.refresh_from_tweaks()
