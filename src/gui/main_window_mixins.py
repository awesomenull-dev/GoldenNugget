"""Mixins for :class:`MainWindow`, breaking the monolithic GUI shell into
focused pieces: device-bar handling, settings/presets/theme, navigation and
the apply/reset flow. Each mixin only reaches ``self`` attributes that
``MainWindow.__init__`` installs, so they stay plain objects mixed into
``class MainWindow(QtWidgets.QMainWindow, DeviceBarMixin, SettingsMixin,
NavigationMixin, ApplyMixin)``.
"""

from typing import Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QCoreApplication

from src.devicemanagement.constants import Version
from src.gui.dialogs import AboutProgramDialog
from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.thread_workers.apply_worker import (
    ApplyAlertMessage,
    ApplyThread,
    RefreshDevicesThread,
    get_sudo_pwd,
    set_sudo_pwd,
)
from src.gui.version import App_Build, App_Version
from src.gui.ios.theme_manager import ThemeManager
from src.gui.ios.tweaks import _hidden_feature_names
from src.gui.pages.pages_list import Page
from src.tweaks.tweak_classes import set_tweak_change_callback
from src.tweaks.tweaks import tweaks, TweakID


class DeviceBarMixin:
    """Device refresh, selection and per-device interface updates."""

    def updateInterfaceForNewDevice(self):
        # update the home page
        self.pages[Page.Home].updatePhoneInfo()


    def _apply_hidden_feature_gating(self):
        """Hide the Sidebar buttons and iOS home cards for HotLoad-hidden
        features on this device. Kept central so the gating survives every
        re-apply point (device refresh / selection).

        Only ever HIDES — it never re-shows a button that the device-version
        rules hid (e.g. Status Bar is disabled on iOS 27 because the Speakeasy
        override file is dropped by the wipe). The Status Bar stays hidden if
        either HotLoad OR iOS >= 27 says so.
        """
        hidden = _hidden_feature_names()
        if hidden:
            print(f"[HotLoad] Hiding feature pages: {', '.join(sorted(hidden))}")
        # Status Bar is also feature-broken on iOS 27 (Speakeasy override file
        # dropped by the safe-state-recovery wipe) even when HotLoad allows it.
        is_ios27 = False
        try:
            ver = self.device_manager.get_current_device_version()
            is_ios27 = ver != "" and Version(ver) >= Version("27.0")
        except Exception:
            is_ios27 = False
        statusbar_hidden = "Status Bar" in hidden or is_ios27
        # Sidebar (classic shell) buttons
        btn_map = {
            "Liquid Glass": self.ui.liquidGlassPageBtn,
            "Springboard": self.ui.springboardOptionsPageBtn,
            "Internal": self.ui.internalOptionsPageBtn,
            "PosterBoard": self.ui.posterboardPageBtn,
            "Daemons": self.ui.daemonsPageBtn,
        }
        for feat, btn in btn_map.items():
            btn.setVisible(feat not in hidden)
        self.ui.statusBarPageBtn.setVisible(not statusbar_hidden)
        # iOS home cards
        card_map = {
            "PosterBoard": self.ios_home.posterboard_card,
            "Daemons": self.ios_home.daemons_card,
        }
        for feat, card in card_map.items():
            card.setVisible(feat not in hidden)
        self.ios_home.set_statusbar_visible(not statusbar_hidden)


    @QtCore.Slot()
    def refresh_devices(self):
        if not self.refresh_in_progress:
            self.refresh_in_progress = True
            self.ui.refreshBtn.setDisabled(True)
            self.refresh_worker_thread = RefreshDevicesThread(manager=self.device_manager, settings=self.settings)
            self.refresh_worker_thread.alert.connect(self.alert_message)
            self.refresh_worker_thread.finished.connect(self.refresh_devices_finished)
            self.refresh_worker_thread.finished.connect(self.refresh_worker_thread.deleteLater)
            self.refresh_worker_thread.start()


    def warn_for_dev_beta(self):
        ver = self.device_manager.get_current_device_version()
        if ver == "":
            return
        if Version(ver) > Version("26.0") and not self.device_manager.get_current_device_build()[-1].isdigit():
            self.alert_message(ApplyAlertMessage(
                txt=self.tr("Warning: You are on iOS 26 beta.\n\nThis has been known to cause problems and potentially lead to bootloops.\n\nUse at your own risk!"),
                title="Warning", icon=QtWidgets.QMessageBox.Warning
            ), log_to_console=False)


    def refresh_devices_finished(self):
        self.refresh_in_progress = False
        self.toggle_thread_btns(disabled=False)
        # clear the picker
        self.ui.devicePicker.clear()

        if len(self.device_manager.devices) == 0:
            self.ui.devicePicker.setEnabled(False)
            self.ui.devicePicker.addItem(self.noneText)
            self.show_home()

            # hide all pages
            self.ui.sidebarDiv1.hide()

            self.ui.gestaltPageBtn.hide()
            self.ui.statusBarPageBtn.hide()
            self.ui.springboardOptionsPageBtn.hide()
            self.ui.internalOptionsPageBtn.hide()
            self.ui.liquidGlassPageBtn.hide()
            self.ui.daemonsPageBtn.hide()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.hide()

            self.ui.sidebarDiv2.hide()
            self.ui.applyPageBtn.hide()
            self.ui.jjtechBtn.hide()
            self.ui.duyBtn.show()

            # mirror in the iOS UI: no device → no status bar card
            if hasattr(self, "ios_home"):
                self.ios_home.set_statusbar_visible(False)
        else:
            self.ui.devicePicker.setEnabled(True)
            # populate the ComboBox with device names
            for device in self.device_manager.devices:
                tag = " (@ USB)" if device.connected_via_usb else " (@ WiFi)"
                self.ui.devicePicker.addItem(f"{device.name}{tag}")

            # show all pages
            self.ui.sidebarDiv1.show()
            self.ui.statusBarPageBtn.show()
            self.ui.springboardOptionsPageBtn.show()
            self.ui.internalOptionsPageBtn.show()
            self.ui.liquidGlassPageBtn.show()
            self.ui.daemonsPageBtn.show()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.show()

            self.ui.sidebarDiv2.show()
            self.ui.applyPageBtn.show()

            # HotLoad-hidden features are carved out of the Sidebar and iOS home
            self._apply_hidden_feature_gating()
        
        # update the selected device
        self.ui.devicePicker.setCurrentIndex(0)
        # HotLoad-hidden features are carved out of the Sidebar and iOS home
        self._apply_hidden_feature_gating()
        # keep the iOS home in sync
        self.ios_home.refresh_device_combo()
        self.ios_home.update_device_info()
        self.ios_home.update_status()


    def change_selected_device(self, index):
        if len(self.device_manager.devices) > 0:
            self.device_manager.set_current_device(index=index)
            # hide sidebar buttons that are for newer versions
            MinTweakVersions = {
                "no_patch": [self.ui.gestaltPageBtn],
                "26.0": [self.ui.liquidGlassPageBtn],
            }

            device_ver = Version(self.device_manager.data_singleton.current_device.version)
            # toggle option visibility for the minimum versions
            for version, views in MinTweakVersions.items():
                if version == "no_patch":
                    # these items only apply to unpatched devices, which do not exist on this fork
                    for view in views:
                        view.hide()
                else:
                    # show views if the version is higher
                    parsed_ver = Version(version)
                    for view in views:
                        view.setVisible(device_ver >= parsed_ver)
            # The Status Bar override file is dropped by the iOS 27
            # safe-state-recovery wipe, so the whole feature is hidden on iOS 27+.
            if device_ver >= Version("27.0"):
                self.ui.statusBarPageBtn.hide()
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(False)
            else:
                self.ui.statusBarPageBtn.show()
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(True)
            # mirror the Status Bar gating in the iOS UI
            if hasattr(self, "ios_home"):
                self.ios_home.set_statusbar_visible(device_ver < Version("27.0"))

            # force video looping on iPads (loop gated off the classic widgets)
            is_iphone = self.device_manager.get_current_device_model().startswith("iPhone")
            if not is_iphone:
                # force looping
                tweaks[TweakID.PosterBoard].loop_video = True

            # sparse-restore book credits do not apply to this fork
            self.ui.jjtechBtn.hide()
            # swap out the current posterboard file
            tweaks[TweakID.PosterBoard].config_manager.update_for_saved_database(self.device_manager.get_current_device_udid())

            # show the PB if initial load is true
            if self.initial_load:
                self.initial_load = False
                if len(tweaks[TweakID.PosterBoard].tendies) > 0:
                    self.show_ios_page(2)
                elif len(tweaks[TweakID.Templates].templates) > 0:
                    # templates have no dedicated page in the unified shell
                    self.show_ios_page(2)
                self._sync_sidebar_selection()
        else:
            self.device_manager.set_current_device(index=None)

        # update the interface
        self.updateInterfaceForNewDevice()
        self.ios_home.update_device_info()
        self.ios_home.update_status()
        if index > -1:
            self.warn_for_dev_beta()



class SettingsMixin:
    """Settings/preset loading, theme switching and app-version label."""

    def loadSettings(self):
        try:
            # load the settings
            auto_reboot = self.settings.value("auto_reboot", True, type=bool)
            ignore_frame_limit = self.settings.value("ignore_pb_frame_limit", False, type=bool)
            disable_tendies_limit = self.settings.value("disable_tendies_limit", False, type=bool)
            auto_refresh_posterboard = self.settings.value("auto_refresh_posterboard", True, type=bool)
            use_backup_cache = self.settings.value("use_backup_cache", False, type=bool)

            skip_setup = self.settings.value("skip_setup", True, type=bool)
            supervised = self.settings.value("supervised", False, type=bool)
            organization_name = self.settings.value("organization_name", "", type=str)
            use_encrypted_backup = self.settings.value("use_encrypted_backup", False, type=bool)

            self.device_manager.pref_manager.auto_reboot = auto_reboot
            video_handler.set_ignore_frame_limit(ignore_frame_limit)
            self.device_manager.pref_manager.disable_tendies_limit = disable_tendies_limit
            self.device_manager.pref_manager.auto_refresh_posterboard = auto_refresh_posterboard
            self.device_manager.pref_manager.use_backup_cache = use_backup_cache
            self.device_manager.pref_manager.use_encrypted_backup = use_encrypted_backup
            self.device_manager.pref_manager.skip_setup = skip_setup
            self.device_manager.pref_manager.supervised = supervised
            self.device_manager.pref_manager.organization_name = organization_name
        except Exception:
            pass


    def _load_last_preset(self):
        """Load the latest autosaved preset on startup.

        Prefers the AutoSave preset (written on every tweak change) so the UI
        restores the most recent configuration. Falls back to the last
        manually-loaded preset when no autosave exists.
        """
        if "AutoSave" in self.preset_manager.list_presets():
            self.preset_manager.load_preset("AutoSave")
            # Rewrite AutoSave right away so stale entries (e.g. daemons that
            # are no longer exposed in the UI) are purged from disk on the
            # next launch instead of lingering in the file forever.
            self._save_autosave_preset()
            return
        last_preset = self.settings.value("last_loaded_preset", "", type=str)
        if last_preset:
            self.preset_manager.load_preset(last_preset)


    def _register_tweak_autosave(self):
        """Register callback to auto-save preset when tweaks change."""
        set_tweak_change_callback(self._on_tweak_changed)


    def _on_tweak_changed(self):
        """Called when any tweak value changes - schedule autosave."""
        if self._preset_autosave_pending:
            return
        self._preset_autosave_pending = True
        # Debounce: save after 500ms of no changes
        QtCore.QTimer.singleShot(500, self._save_autosave_preset)


    def _save_autosave_preset(self):
        """Save current tweak state to AutoSave preset."""
        self._preset_autosave_pending = False
        try:
            self.preset_manager.save_preset(
                "AutoSave", "Automatic save of last tweak configuration", tags=["auto"],
                device_model=self.device_manager.get_current_device_model() or "",
                ios_version=self.device_manager.get_current_device_version() or "")
        except Exception:
            pass  # Silent fail - autosave is best-effort


    def apply_theme(self, theme: int):
        """Apply the UI mode WITHOUT navigating away.

        CLASSIC: sidebar + classic home; iOS-style pages open as actions.
        IOS: full-screen iOS UI with the shared header providing back
        navigation. Only the chrome changes — the current page stays put.
        """
        self.theme_manager.save_theme(theme)
        is_ios = theme == ThemeManager.IOS
        self.ui.sidebar.setVisible(not is_ios)
        self.ui.deviceBar.setVisible(not is_ios)
        if is_ios:
            # iOS mode: full-screen, no padding
            self.shell_layout.setContentsMargins(0, 0, 0, 0)
            self.shell_layout.setSpacing(0)
            self.body_row.setSpacing(0)
            # entering the new UI: land on its home unless already inside it
            if self.content_stack.currentIndex() != 1:
                self.content_stack.setCurrentIndex(1)
                self.ios_pages.setCurrentIndex(0)
            self._update_shared_nav(self.ios_pages.currentIndex())
        else:
            # Classic mode: add padding around the shell
            self.shell_layout.setContentsMargins(16, 16, 16, 16)
            self.shell_layout.setSpacing(12)
            self.body_row.setSpacing(16)
            # classic UI never shows the shared header
            self.ios_nav.setVisible(False)
            if self.ios_pages.currentIndex() == 0:
                # the iOS home has no meaning inside the classic shell
                self.show_home()
        self._sync_sidebar_selection()


    def updateAppVersionLabel(self):
        new_text: str = self.ui.appVersionLbl.text()
        new_text = new_text.replace("%VERSION", App_Version)
        if App_Build > 0:
            new_text = new_text.replace("%BETATAG", f"(beta {App_Build})")
        else:
            new_text = new_text.replace("%BETATAG", "")
        self.ui.appVersionLbl.setText(new_text)


    def _sync_settings(self):
        """Sync settings to disk immediately after critical changes."""
        try:
            self.settings.sync()
        except Exception:
            pass  # Best effort



class NavigationMixin:
    """Page structure, shared IOS nav bar and sidebar selection."""

    def _update_shared_nav(self, index: int):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            self.ios_nav.setVisible(False)
            return
        # the iOS home page is full-screen — no header at all
        self.ios_nav.setVisible(index != 0)
        if index == 0:
            self.ios_nav.clear_right_action()
            return
        title = self._ios_page_titles.get(index, "")
        self.ios_nav.set_title(title)
        self.ios_nav.set_back_visible(True)
        right = self._nav_right_actions.get(index)
        if right:
            self.ios_nav.set_right_action(right[0], right[1])
        else:
            self.ios_nav.clear_right_action()


    def _sync_sidebar_selection(self):
        """Move the checked highlight of the sidebar to the active view."""
        btns = (self.ui.homePageBtn, self.ui.posterboardPageBtn,
                self.ui.springboardOptionsPageBtn, self.ui.internalOptionsPageBtn,
                self.ui.liquidGlassPageBtn, self.ui.daemonsPageBtn,
                self.ui.applyPageBtn, self.ui.settingsPageBtn,
                self.ui.statusBarPageBtn)
        page_to_btn = {
            0: 0,   # home
            2: 1,   # posterboard
            7: 2,   # springboard
            8: 3,   # internal
            9: 4,   # liquid glass
            3: 5,   # daemons
            6: 6,   # apply
            4: 7,   # settings
            5: 8,   # status bar
        }
        idx = None
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            if self.content_stack.currentIndex() == 0:
                idx = 0
            elif self.content_stack.currentIndex() == 1:
                idx = page_to_btn.get(self.ios_pages.currentIndex())
            elif self.content_stack.currentIndex() == 2:
                idx = 5
        else:
            idx = page_to_btn.get(self.ios_pages.currentIndex())
        target = btns[idx] if idx is not None else None
        for b in btns:
            b.setChecked(b is target)


    def show_home(self):
        """Open the home page of the ACTIVE UI mode."""
        if self.theme_manager.current_theme == ThemeManager.IOS:
            self.content_stack.setCurrentIndex(1)
            self.ios_pages.setCurrentIndex(0)
            self._update_shared_nav(0)
        else:
            self.content_stack.setCurrentIndex(0)
        self._refresh_preset_widgets()
        self._sync_sidebar_selection()


    def _refresh_preset_widgets(self):
        """Keep the active-preset banners on both home pages in sync."""
        try:
            self.pages[Page.Home].refresh_preset_widget()
        except Exception:
            pass
        try:
            self.ios_home.refresh_preset_widget()
        except Exception:
            pass


    def show_ios_page(self, index: int):
        self.content_stack.setCurrentIndex(1)
        self.ios_pages.setCurrentIndex(index)


    def open_presets_section(self):
        """Open the settings page and scroll straight to the presets section."""
        self.content_stack.setCurrentIndex(1)
        self.ios_pages.setCurrentIndex(4)
        self._update_shared_nav(4)
        self._sync_sidebar_selection()
        self.ios_settings.scroll_to_presets()


    def eventFilter(self, obj, event):
        """Handle ESC and the mouse back button as navigation-back."""
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        try:
            etype = event.type()
        except (AttributeError, TypeError):
            return False
        if etype == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            return self._go_back()
        if etype == QtCore.QEvent.Type.MouseButtonPress and event.button() in (
                QtCore.Qt.MouseButton.BackButton, QtCore.Qt.MouseButton.ExtraButton1):
            return self._go_back()
        return False


    def _go_back(self) -> bool:
        """Navigate back.

        IOS mode: subpage -> iOS home (stay there).
        CLASSIC mode: any action page backs out to the classic home.
        """
        if self.content_stack.currentIndex() == 1:
            if self.theme_manager.current_theme == ThemeManager.IOS:
                if self.ios_pages.currentIndex() != 0:
                    self.ios_pages.setCurrentIndex(0)
                    return True
                return False
            # classic shell: action pages back out straight to classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        if self.content_stack.currentIndex() == 2:
            # classic daemons page -> classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        return False


    def on_homePageBtn_clicked(self):
        self.show_home()


    def on_statusBarPageBtn_clicked(self):
        self.show_ios_page(5)
        self._sync_sidebar_selection()


    def on_springboardOptionsPageBtn_clicked(self):
        self.show_ios_page(7)
        self._sync_sidebar_selection()


    def on_internalOptionsPageBtn_clicked(self):
        self.show_ios_page(8)
        self._sync_sidebar_selection()


    def on_liquidGlassPageBtn_clicked(self):
        self.show_ios_page(9)
        self._sync_sidebar_selection()


    def on_daemonsPageBtn_clicked(self):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            self.pages[Page.Daemons].load()
            self.pages[Page.Daemons].refresh()
            self.content_stack.setCurrentIndex(2)
        else:
            self.ios_daemons.refresh_from_tweaks()
            self.show_ios_page(3)
        self._sync_sidebar_selection()


    def on_posterboardPageBtn_clicked(self):
        self.show_ios_page(2)
        self._sync_sidebar_selection()


    def on_applyPageBtn_clicked(self):
        self.show_ios_page(6)
        self._sync_sidebar_selection()


    def on_settingsPageBtn_clicked(self):
        self.show_ios_page(4)
        self._sync_sidebar_selection()


    def show_about_dialog(self):
        dialog = AboutProgramDialog(self)
        dialog.exec()



class ApplyMixin:
    """Apply/reset orchestration, alerts and dialog prompts."""

    def update_label(self, txt: str):
        # Mirror progress into the iOS surfaces (home indicator + Apply page)
        try:
            if txt:
                self.ios_home.show_process_status(txt)
                self.ios_apply.set_status(txt)
        except Exception:
            pass


    def remove_tweaks_clicked(self):
        dialog = ResetDialog(device_manager=self.device_manager, apply_reset=self.apply_changes)
        dialog.exec()


    @QtCore.Slot()
    def apply_tweaks_clicked(self):
        self.apply_changes()


    def apply_changes(self, reset_pages: list=None):
        if not self.apply_in_progress:
            self.apply_in_progress = True
            self.toggle_thread_btns(disabled=True)
            self.worker_thread = ApplyThread(manager=self.device_manager, settings=self.settings, reset_pages=reset_pages)
            self.worker_thread.progress.connect(self.update_label)
            self.worker_thread.alert.connect(self.alert_message)
            self.worker_thread.request_text.connect(self.on_password_request)
            self.worker_thread.choice_prompt.connect(self.on_choice_prompt)
            self.worker_thread.finished_with_result.connect(self.finish_apply_thread)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.start()


    def alert_message(self, alert: Optional[ApplyAlertMessage], log_to_console: bool = True):
        if alert is None:
            # do sudo dialog input
            get_sudo_pwd() # clear if it is already there
            pwd, ok = QtWidgets.QInputDialog.getText(None, "Enter Sudo Password", "Enter Your Computer's Password:", QtWidgets.QLineEdit.Password, "")
            if ok and pwd:
                set_sudo_pwd(pwd)
            return
        if log_to_console:
            print(alert.txt)
        # Apply/reset failures carry a traceback: route them through the same
        # parsed crash dialog (severity/likely cause + Copy Error + Report on
        # GitHub + Open Log), instead of a raw QMessageBox.
        if (alert.icon == QtWidgets.QMessageBox.Critical
                and alert.exc_type is not None and alert.detailed_txt):
            from src.exceptions.crash_handler import show_error_dialog, _classify
            info = _classify(alert.exc_type, alert.exc_value)
            self._embedded_alert_error(alert, info)
            return
        detailsBox = QtWidgets.QMessageBox()
        detailsBox.setIcon(alert.icon)
        detailsBox.setWindowTitle(alert.title)
        detailsBox.setText(alert.txt)
        if alert.detailed_txt != None:
            detailsBox.setDetailedText(alert.detailed_txt)
        restore_btn = None
        if alert.backup_path:
            restore_btn = detailsBox.addButton(
                self.tr("Restore data from backup"), QtWidgets.QMessageBox.AcceptRole)
        detailsBox.exec()
        if restore_btn is not None and detailsBox.clickedButton() is restore_btn:
            self._start_cache_restore()


    def _embedded_alert_error(self, alert: ApplyAlertMessage, info: dict):
        """Show an apply failure through the crash/error dialog."""
        # Need the restore callback to survive the dialog's exec() lifetime.
        def _restore():
            self._start_cache_restore()
        from src.exceptions.crash_handler import show_error_dialog
        show_error_dialog(
            summary=alert.txt,
            traceback_text=alert.detailed_txt,
            info=info,
            backup_path=alert.backup_path,
            on_restore=_restore if alert.backup_path else None,
        )


    def _start_cache_restore(self):
        from src.gui.thread_workers.apply_worker import RestoreCacheThread
        if getattr(self, '_cache_restore_in_progress', False):
            return
        self._cache_restore_in_progress = True
        worker = RestoreCacheThread(manager=self.device_manager)
        worker.progress.connect(self._update_restore_label)
        worker.alert.connect(self.alert_message)
        worker.finished_with_result.connect(self._finish_cache_restore)
        worker.finished.connect(worker.deleteLater)
        worker.start()


    def _update_restore_label(self, txt: str):
        try:
            self.ios_home.show_process_status(txt)
        except Exception:
            pass


    def _finish_cache_restore(self, success: bool, error_msg: str = ""):
        self._cache_restore_in_progress = False
        if not success or error_msg:
            self.alert_message(ApplyAlertMessage(
                txt=f"Restore data: {error_msg or 'failed'}",
                title="Restore data",
                icon=QtWidgets.QMessageBox.Critical,
            ), log_to_console=False)


    def on_password_request(self, title: str, label: str, box):
        try:
            password, ok = QtWidgets.QInputDialog.getText(
                self, title, label, QtWidgets.QLineEdit.Password)
            box.put(password if (ok and password) else None)
        except Exception:
            try:
                box.put(None)
            except Exception:
                pass


    def on_choice_prompt(self, title: str, text: str, box):
        """Main-thread Abort/Resume dialog (e.g. device locked too long after
        the security recovery). Built here — never on the worker thread — and
        the decision is boxed back to the waiting worker."""
        try:
            mbox = QtWidgets.QMessageBox(self)
            mbox.setWindowTitle(title)
            mbox.setIcon(QtWidgets.QMessageBox.Warning)
            mbox.setText(text)
            abort_btn = mbox.addButton(
                QCoreApplication.tr("Abort"), QtWidgets.QMessageBox.RejectRole)
            resume_btn = mbox.addButton(
                QCoreApplication.tr("Resume"), QtWidgets.QMessageBox.AcceptRole)
            mbox.setDefaultButton(resume_btn)
            mbox.exec()
            result = "abort" if mbox.clickedButton() is abort_btn else "resume"
        except Exception:
            result = "abort"
        try:
            box.put(result)
        except Exception:
            pass


    def finish_apply_thread(self, success: bool = False, error_msg: str = ""):
        self.apply_in_progress = False
        self.toggle_thread_btns(disabled=False)
        worker = getattr(self, 'worker_thread', None)
        is_reset = worker is not None and worker.reset_pages is not None
        # Show completion indicator on the iOS home page
        try:
            if success:
                self.ios_home.show_process_status(
                    QCoreApplication.tr("Reset complete!") if is_reset else QCoreApplication.tr("Apply complete!"),
                    success=True)
            else:
                self.ios_home.show_process_status(
                    QCoreApplication.tr("Operation failed"), success=False)
        except Exception:
            pass
        if success:
            if worker is not None and not is_reset:
                self.prompt_star_on_github()
        else:
            # Show error notification if not already shown via alert
            if error_msg and "timed out" not in error_msg.lower():
                self.alert_message(ApplyAlertMessage(
                    txt=f"Operation failed: {error_msg}",
                    title="Error",
                    icon=QtWidgets.QMessageBox.Critical
                ), log_to_console=False)


    def prompt_star_on_github(self):
        if self.settings.value("star_prompt_done", False, type=bool):
            return
        self.settings.setValue("star_prompt_done", True)
        self._sync_settings()
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(self.tr("Enjoying GoldenNugget?"))
        box.setText(self.tr("If you like GoldenNugget, please consider giving it a star on GitHub!"))
        star_btn = box.addButton(self.tr("Star on GitHub"), QtWidgets.QMessageBox.AcceptRole)
        box.addButton(self.tr("Not now"), QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == star_btn:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QtCore.QUrl("https://github.com/awesomenull-dev/GoldenNugget"))


    def prompt_first_launch_backup(self) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Back up your device"))
        box.setText(QCoreApplication.translate(
            "Nugget",
            "Have you made a backup of your iPhone? Tweaks and daemon changes "
            "are risky — a bad tweak can bootloop the device or force a full "
            "restore, which erases everything. Create a backup in iTunes or "
            "Finder before using GoldenNugget."))
        box.setDetailedText(QCoreApplication.translate(
            "Nugget",
            "Back up your iPhone before tweaking:\n"
            "• Windows: iTunes → your device → Back Up Now\n"
            "• Mac: Finder → your device → Back Up Now\n\n"
            "GoldenNugget's own protected backup also runs automatically when "
            "you apply tweaks, but a full iTunes/Finder backup is the only "
            "complete safety net."))
        got_it = box.addButton(
            QCoreApplication.translate("Nugget", "Got it, I'm backed up"),
            QtWidgets.QMessageBox.AcceptRole)
        box.addButton(
            QCoreApplication.translate("Nugget", "I'll do it later"),
            QtWidgets.QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is got_it


    def toggle_thread_btns(self, disabled: bool):
        if disabled or not self.apply_in_progress:
            self.ios_apply.set_busy(disabled)
        if disabled or not self.refresh_in_progress:
            self.ui.refreshBtn.setDisabled(disabled)

