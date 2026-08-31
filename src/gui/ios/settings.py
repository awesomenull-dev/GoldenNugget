from PySide6.QtCore import Qt, QCoreApplication, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QInputDialog,
    QFileDialog, QDialog
)
from typing import Optional

from src.gui.ios.components import (
    IOSSectionHeader, IOSSwitch, IOSPrimaryButton
)
from src.gui.ios.theme_manager import ThemeManager
from src.gui.pages.main.settings import available_languages
from src.controllers.video_handler import set_ignore_frame_limit
from src.controllers.preset_manager import PresetManager
from src.controllers.hotload import HotLoad, confirm_flagged
from src.tweaks.tweaks import tweaks, TweakID


class IOSSettingsPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")
        self.lang_indexes = []
        self.preset_manager = PresetManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)


        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        self.scroll_area = scroll
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(16, 16, 16, 32)
        self.content_layout.setSpacing(8)

        # Appearance
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Appearance")))

        theme_on = self.window.theme_manager.current_theme == ThemeManager.IOS
        self.theme_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "iOS-style Interface"),
            theme_on,
            lambda ios_on: self.window.apply_theme(
                ThemeManager.IOS if ios_on else ThemeManager.CLASSIC),
        )

        # HotLoad safety rules
        self.content_layout.addWidget(
            IOSSectionHeader(QCoreApplication.translate("Nugget", "Safety (HotLoad)")))
        self._hotload = HotLoad(self.window.settings)
        self.hotload_switch = self._make_switch(
            QCoreApplication.translate("Nugget",
                "Apply automatic safety rules (warns on dangerous features)"),
            self._hotload.is_enabled(),
            self._make_hotload_handler(),
        )

        # Language
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "App Language")))
        self._make_language_row()

        # Device
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Device")))
        pref = self.window.device_manager.pref_manager

        self._make_switch(
            QCoreApplication.translate("Nugget", "Auto Reboot After Applying"),
            pref.auto_reboot,
            self._make_setting_handler("auto_reboot"),
        )

        reset_pairing_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Reset Device Pairing"))
        reset_pairing_btn.clicked.connect(self.window.device_manager.reset_device_pairing)
        self.content_layout.addWidget(reset_pairing_btn)

        # PosterBoard
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "PosterBoard")))

        self._make_switch(
            QCoreApplication.translate("Nugget", "Ignore Posterboard Frame Limit"),
            self.window.settings.value("ignore_pb_frame_limit", False, type=bool),
            lambda checked: (
                set_ignore_frame_limit(checked),
                self.window.settings.setValue("ignore_pb_frame_limit", checked),
                self.window._sync_settings(),
            ),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Disable Tendies Limit"),
            pref.disable_tendies_limit,
            self._make_setting_handler("disable_tendies_limit"),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Force PosterBoard Refresh"),
            pref.auto_refresh_posterboard,
            self._make_setting_handler("auto_refresh_posterboard"),
        )

        self._make_pb_setup_section()

        # Backup
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Backup")))

        encrypted_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "Use Encrypted Backups (Experimental)"),
            pref.use_encrypted_backup,
            lambda checked: self._on_encrypted_backup_toggled(checked, encrypted_switch),
        )

        # Setup
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Setup")))

        self._make_switch(
            QCoreApplication.translate("Nugget", "Skip Setup * (non-exploit files only)"),
            pref.skip_setup,
            self._make_setting_handler("skip_setup"),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Enable Supervision * (requires Skip Setup)"),
            pref.supervised,
            self._make_setting_handler("supervised"),
        )

        self._make_text_row(
            QCoreApplication.translate("Nugget", "Enter Organization Name"),
            pref.organization_name,
            self._on_org_name_edited,
        )

        # Presets
        self._make_presets_section()

        # About
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "About")))

        about_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "About GoldenNugget"))
        about_btn.clicked.connect(self.show_about)
        self.content_layout.addWidget(about_btn)

        self.refresh_presets()
        self.content_layout.addStretch()

    # ---------- helpers ----------

    def _make_switch(self, title: str, checked: bool, on_toggled) -> IOSSwitch:
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        label.setWordWrap(True)
        row.addWidget(label, 1)

        switch = IOSSwitch(checked)
        switch.toggled.connect(on_toggled)
        row.addWidget(switch)
        self.content_layout.addWidget(card)
        return switch

    def _make_setting_handler(self, pref_attr: str):
        pref = self.window.device_manager.pref_manager
        def handler(checked: bool):
            setattr(pref, pref_attr, checked)
            self.window.settings.setValue(pref_attr, checked)
            self.window._sync_settings()
        return handler

    def _make_hotload_handler(self):
        def handler(checked: bool):
            self._hotload.set_enabled(checked)
        return handler

    def _on_encrypted_backup_toggled(self, checked: bool, switch):
        pref = self.window.device_manager.pref_manager
        if checked:
            reply = QMessageBox.question(
                self.window,
                "Enable Encrypted Backups?",
                "WARNING: Using encrypted backups with GoldenNugget is experimental "
                "and may cause DATA LOSS or leave your device stuck on the Setup "
                "screen after applying tweaks.\n\n"
                "Make sure you know your backup password before continuing.\n\n"
                "Enable encrypted backups anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                switch.blockSignals(True)
                switch.setChecked(False)
                switch.blockSignals(False)
                return
        pref.use_encrypted_backup = checked
        self.window.settings.setValue("use_encrypted_backup", checked)
        self.window._sync_settings()

    def _make_text_row(self, title: str, current: str, on_submit):
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        row.addWidget(label, 1)

        self.org_value_lbl = QLabel(current if current else QCoreApplication.translate("MainWindow", "None"))
        self.org_value_lbl.setStyleSheet("color: #8E8E93; font-size: 14px;")
        row.addWidget(self.org_value_lbl)

        edit_btn = QLabel("✎")
        edit_btn.setStyleSheet("color: #007AFF; font-size: 17px;")
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.mousePressEvent = lambda e: self._on_text_row_edit(title, on_submit)
        row.addWidget(edit_btn)

        self.content_layout.addWidget(card)

    def _on_text_row_edit(self, title: str, on_submit):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(QCoreApplication.translate("Nugget", "Enter value:"))
        dialog.setTextValue(self.window.device_manager.pref_manager.organization_name)
        dialog.setStyleSheet("""
            QDialog, QInputDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QLineEdit {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 10px 14px;
            }
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 10px 20px;
                border: none;
            }
        """)
        if dialog.exec() == QDialog.Accepted:
            text = dialog.textValue()
            on_submit(text)
            self.org_value_lbl.setText(text if text else QCoreApplication.translate("MainWindow", "None"))

    def _on_org_name_edited(self, text: str):
        pref = self.window.device_manager.pref_manager
        pref.organization_name = text
        self.window.settings.setValue("organization_name", text)
        self.window._sync_settings()

    def _make_language_row(self):
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(QCoreApplication.translate("Nugget", "App Language"))
        label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        row.addWidget(label, 1)

        self.lang_drp = QComboBox()
        self.lang_drp.setStyleSheet("""
            QComboBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 14px;
                padding: 8px 12px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #8E8E93; margin-right: 10px; }
            QComboBox QAbstractItemView {
                background-color: #2C2C2E;
                border: 1px solid #3A3A3C;
                border-radius: 10px;
                color: #FFFFFF;
                selection-background-color: #007AFF;
            }
        """)
        for language in available_languages.keys():
            self.lang_indexes.append(available_languages[language])
            self.lang_drp.addItem(language)
        try:
            idx = self.lang_indexes.index(self.window.translator.get_saved_locale_code())
        except Exception:
            idx = 0
        self.lang_drp.setCurrentIndex(idx)
        self.lang_drp.activated.connect(self._on_lang_selected)
        row.addWidget(self.lang_drp)

        self.content_layout.addWidget(card)

    def _on_lang_selected(self, index: int):
        new_lang = self.lang_indexes[index]
        if new_lang != self.window.translator.get_saved_locale_code():
            self.window.translator.set_new_language(new_lang, restart=True)

    def _make_pb_setup_section(self):
        self.content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "PosterBoard Database")
        ))

        # wallpapers are always applied as configurations (iOS 26+ data store
        # layout); the descriptors apply method is broken and was removed

        self._make_label_row(QCoreApplication.translate("Nugget", "Database"), "sqlite: None")

        self._make_button_row(
            QCoreApplication.translate("Nugget", "Get Database from Device"),
            self._on_pb_get_db,
        )
        self._make_button_row(
            QCoreApplication.translate("Nugget", "Select Database File"),
            self._on_pb_select_db,
        )

        # saved ids list
        ids_card = QWidget()
        ids_layout = QVBoxLayout(ids_card)
        ids_layout.setContentsMargins(16, 12, 16, 12)
        ids_layout.setSpacing(8)
        ids_title = QLabel(QCoreApplication.translate("Nugget", "Saved Configuration IDs"))
        ids_title.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        ids_layout.addWidget(ids_title)

        self.saved_ids_list = QListWidget()
        self.saved_ids_list.setStyleSheet("""
            QListWidget {
                background-color: #1C1C1E;
                border: none;
                border-radius: 8px;
                color: #e8e8e8;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item { padding: 6px; }
            QListWidget::item:selected { background-color: #535353; color: #ffffff; }
        """)
        self.saved_ids_list.setMinimumHeight(90)
        ids_layout.addWidget(self.saved_ids_list)

        ids_btns = QHBoxLayout()
        clear_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Clear"))
        clear_btn.clicked.connect(self._on_clear_saved_ids)
        remove_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Remove Selected"))
        remove_btn.clicked.connect(self._on_remove_selected_id)
        ids_btns.addWidget(clear_btn)
        ids_btns.addWidget(remove_btn)
        ids_layout.addLayout(ids_btns)
        self.content_layout.addWidget(ids_card)

        self._refresh_saved_ids()

    def _make_label_row(self, title: str, value: str):
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        row.addWidget(label, 1)

        self.pb_db_lbl = QLabel(value)
        self.pb_db_lbl.setStyleSheet("color: #8E8E93; font-size: 14px;")
        row.addWidget(self.pb_db_lbl)
        self.content_layout.addWidget(card)

    def _make_button_row(self, title: str, on_click):
        btn = IOSPrimaryButton(title)
        btn.setFixedHeight(44)
        btn.clicked.connect(on_click)
        self.content_layout.addWidget(btn)

    def _make_mini_button(self, title: str):
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton(title)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #3b3b3b;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 13px;
                padding: 8px 12px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)
        return btn

    def _on_pb_get_db(self):
        from src.gui.dialogs import PosterBoardDBWizard
        current = self.window.device_manager.data_singleton.current_device
        if current is None:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Get Database"),
                QCoreApplication.translate("QCoreApplication", "Please connect a device."))
            return
        wizard = PosterBoardDBWizard(current.udid, self.pb_db_lbl, self._refresh_saved_ids)
        wizard.exec()

    def _on_pb_select_db(self):
        from PySide6.QtWidgets import QFileDialog as FD
        selected_file, _ = FD.getOpenFileName(
            self, QCoreApplication.translate("Nugget", "Select PBFPosterExtensionDataStoreSQLiteDatabase File"),
            "", "*.sqlite3", options=FD.ReadOnly)
        if selected_file in (None, ""):
            tweaks[TweakID.PosterBoard].config_manager.database = None
            self.pb_db_lbl.setText("sqlite: None")
        else:
            if not tweaks[TweakID.PosterBoard].config_manager.update_database_file(
                    selected_file, self.window.device_manager.get_current_device_udid()):
                QMessageBox.critical(
                    self, QCoreApplication.translate("QtCore.QCoreApplication", "Error!"),
                    QCoreApplication.translate("Nugget", "The database is not of the correct format!"))
                return
            self.pb_db_lbl.setText("sqlite: Selected")

    def _refresh_saved_ids(self):
        self.saved_ids_list.clear()
        saved_ids = tweaks[TweakID.PosterBoard].config_manager.saved_items
        if len(saved_ids) == 0:
            self.saved_ids_list.setEnabled(False)
            self.saved_ids_list.addItem(QCoreApplication.translate("MainWindow", "None"))
        else:
            self.saved_ids_list.setEnabled(True)
            self.saved_ids_list.addItems([item.to_str() for item in saved_ids])

    def _on_clear_saved_ids(self):
        confirm = QMessageBox.question(
            self, QCoreApplication.translate("Nugget", "Clear Saved IDs"),
            QCoreApplication.translate("Nugget", "Clear all saved configuration IDs?"))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        tweaks[TweakID.PosterBoard].config_manager.saved_items.clear()
        self._refresh_saved_ids()

    def _on_remove_selected_id(self):
        curr_row = self.saved_ids_list.currentRow()
        if curr_row >= 0 and len(tweaks[TweakID.PosterBoard].config_manager.saved_items) > 0:
            tweaks[TweakID.PosterBoard].config_manager.saved_items.pop(curr_row)
            self._refresh_saved_ids()

    # ---------- presets ----------

    def _make_presets_section(self):
        self.content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Presets")
        ))

        card = QWidget()
        presets_layout = QVBoxLayout(card)
        presets_layout.setContentsMargins(16, 12, 16, 12)
        presets_layout.setSpacing(8)

        name_row = QHBoxLayout()
        self.preset_name_txt = QLineEdit()
        self.preset_name_txt.setPlaceholderText(QCoreApplication.translate("Nugget", "Preset name"))
        self.preset_desc_txt = QLineEdit()
        self.preset_desc_txt.setPlaceholderText(QCoreApplication.translate("Nugget", "Description (optional)"))
        for edit in (self.preset_name_txt, self.preset_desc_txt):
            edit.setStyleSheet("""
                QLineEdit {
                    background-color: #1C1C1E;
                    border: none;
                    border-radius: 10px;
                    color: #FFFFFF;
                    font-size: 14px;
                    padding: 10px 14px;
                }
            """)
        name_row.addWidget(self.preset_name_txt, 2)
        name_row.addWidget(self.preset_desc_txt, 3)
        presets_layout.addLayout(name_row)

        save_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Save Preset"))
        save_btn.clicked.connect(self._on_preset_save)
        presets_layout.addWidget(save_btn)

        self.preset_list = QListWidget()
        self.preset_list.setStyleSheet("""
            QListWidget {
                background-color: #1C1C1E;
                border: none;
                border-radius: 8px;
                color: #e8e8e8;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background-color: #535353; color: #ffffff; }
        """)
        self.preset_list.setMinimumHeight(120)
        presets_layout.addWidget(self.preset_list)

        btns_row = QHBoxLayout()
        for title, handler in [
            (QCoreApplication.translate("Nugget", "Load"), self._on_preset_load),
            (QCoreApplication.translate("Nugget", "Delete"), self._on_preset_delete),
            (QCoreApplication.translate("Nugget", "Refresh"), self.refresh_presets),
            (QCoreApplication.translate("Nugget", "Export"), self._on_preset_export),
            (QCoreApplication.translate("Nugget", "Partial Export"), self._on_preset_partial_export),
            (QCoreApplication.translate("Nugget", "Import"), self._on_preset_import),
        ]:
            btn = self._make_mini_button(title)
            btn.clicked.connect(handler)
            btns_row.addWidget(btn)
        presets_layout.addLayout(btns_row)

        self.content_layout.addWidget(card)

    def scroll_to_presets(self):
        """Scroll the settings page to the presets section at the bottom."""
        if self.scroll_area is not None:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh_presets(self):
        self.preset_list.clear()
        for meta in self.preset_manager.list_presets_with_metadata():
            name = meta["name"]
            desc = meta.get("description", "")
            model = meta.get("device_model", "Unknown")
            ios = meta.get("ios_version", "Unknown")
            tags = meta.get("tags", [])
            tag_str = "  #" + " #".join(tags) if tags else ""
            if desc:
                item_text = f"{name}\n  {desc}  ({model} • iOS {ios}){tag_str}"
            else:
                item_text = f"{name}  ({model} • iOS {ios}){tag_str}"
            item = QListWidgetItem(item_text)
            self.preset_list.addItem(item)
            item.setData(Qt.UserRole, name)

    def _on_preset_save(self):
        name = self.preset_name_txt.text().strip()
        desc = self.preset_desc_txt.text().strip()
        if not name:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Save Preset"),
                QCoreApplication.translate("Nugget", "Enter a name for this preset."))
            return
        if self.preset_manager.save_preset(
                name, desc, tags=[],
                device_model=self.window.device_manager.get_current_device_model() or "",
                ios_version=self.window.device_manager.get_current_device_version() or ""):
            self.preset_name_txt.clear()
            self.preset_desc_txt.clear()
            self.refresh_presets()
        else:
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Save Preset"),
                QCoreApplication.translate("Nugget", "Failed to save the preset."))

    def _on_preset_load(self):
        if self.preset_list.currentRow() < 0:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Load Preset"),
                QCoreApplication.translate("Nugget", "Select a preset to load first."))
            return
        item_text = self.preset_list.currentItem().text()
        name = self.preset_list.currentItem().data(Qt.UserRole) or item_text.split("\n")[0].strip()
        meta = self.preset_manager.get_preset_metadata(name)
        desc = meta.get("description", "") if meta else ""
        model = meta.get("device_model", "Unknown") if meta else "Unknown"
        ios = meta.get("ios_version", "Unknown") if meta else "Unknown"
        confirm = QMessageBox.question(
            self, QCoreApplication.translate("Nugget", "Load Preset"),
            QCoreApplication.translate(
                "Nugget",
                "Load preset \"{0}\"?\n\nDescription: {1}\nDevice: {2} • iOS {3}\n\nThis will replace your current configuration."
            ).format(name, desc, model, ios))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        compat_msg = self._daemon_compat_warning(name, meta)
        if compat_msg:
            reply = QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Daemon Compatibility"),
                compat_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.preset_manager.preset_has_daemon_changes(name):
            dm = self.window.device_manager
            hotload = HotLoad(getattr(self.window, "settings", None))
            rule = hotload.rule_for(
                "Daemons",
                device_version=dm.get_current_device_version(),
                device_model=dm.get_current_device_model())
            if rule is not None and not confirm_flagged(rule, self):
                return
        if not self.preset_manager.load_preset(name):
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Load Preset"),
                QCoreApplication.translate("Nugget", "Failed to load the preset."))
            return
        self.window.settings.setValue("last_loaded_preset", name)
        self.window._sync_settings()
        QMessageBox.information(
            self, QCoreApplication.translate("Nugget", "Load Preset"),
            QCoreApplication.translate(
                "Nugget",
                "Preset \"{0}\" loaded.\n\nGoldenNugget will now restart to apply the changes.").format(name))
        self._restart_app()

    @staticmethod
    def _major_version(ver: str):
        """Return the iOS major version as an int, or None if not parseable."""
        try:
            return int(str(ver).split(".")[0])
        except (ValueError, TypeError, IndexError):
            return None

    @staticmethod
    def _device_type(model: str) -> str:
        model = str(model or "")
        if model.lower().startswith("iphone"):
            return "iPhone"
        if model.lower().startswith("ipad"):
            return "iPad"
        return ""

    def _daemon_compat_warning(self, name: str, meta) -> Optional[str]:
        """Return a warning string when the preset's daemon changes were saved
        for a different iOS major version or device type than the one in use;
        None when the preset has no daemon changes or we cannot tell."""
        if not self.preset_manager.preset_has_daemon_changes(name):
            return None
        cur_ver = self.window.device_manager.get_current_device_version() or ""
        cur_model = self.window.device_manager.get_current_device_model() or ""
        pr_ver = (meta.get("ios_version") or "") if meta else ""
        pr_model = (meta.get("device_model") or "") if meta else ""

        pr_major = self._major_version(pr_ver)
        cur_major = self._major_version(cur_ver)
        mismatches = []
        if pr_major is not None and cur_major is not None and pr_major != cur_major:
            mismatches.append(f"iOS {pr_major}x vs current iOS {cur_major}x")
        pr_type = self._device_type(pr_model)
        cur_type = self._device_type(cur_model)
        if pr_type and cur_type and pr_type != cur_type:
            mismatches.append(f"{pr_type} vs current {cur_type}")
        if not mismatches:
            return None
        return (
            "This preset contains daemon modifications that were saved for a "
            "different device:\n\n"
            + "\n".join("• " + m for m in mismatches)
            + "\n\nDaemons are sensitive to the iOS version and device type, and "
              "applying incompatible ones can bootloop your device. "
              "Proceed with caution."
        )

    def _on_preset_delete(self):
        if self.preset_list.currentRow() < 0:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Delete Preset"),
                QCoreApplication.translate("Nugget", "Select a preset to delete first."))
            return
        item_text = self.preset_list.currentItem().text()
        name = self.preset_list.currentItem().data(Qt.UserRole) or item_text.split("\n")[0].strip()
        confirm = QMessageBox.question(
            self, QCoreApplication.translate("Nugget", "Delete Preset"),
            QCoreApplication.translate("Nugget", "Delete preset \"{0}\"?").format(name))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self.preset_manager.delete_preset(name):
            self.refresh_presets()
        else:
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Delete Preset"),
                QCoreApplication.translate("Nugget", "Failed to delete the preset."))

    def _on_preset_export(self):
        if self.preset_list.currentRow() < 0:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Export Preset"),
                QCoreApplication.translate("Nugget", "Select a preset to export first."))
            return
        item_text = self.preset_list.currentItem().text()
        name = self.preset_list.currentItem().data(Qt.UserRole) or item_text.split("\n")[0].strip()
        file_path, _ = QFileDialog.getSaveFileName(
            self, QCoreApplication.translate("Nugget", "Export Preset"),
            f"{name}.json",
            QCoreApplication.translate("Nugget", "JSON Files (*.json)"))
        if not file_path:
            return
        if self.preset_manager.export_preset(name, file_path):
            QMessageBox.information(
                self, QCoreApplication.translate("Nugget", "Export Preset"),
                QCoreApplication.translate("Nugget", "Preset exported to:\n{0}").format(file_path))
        else:
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Export Preset"),
                QCoreApplication.translate("Nugget", "Failed to export preset."))

    def _on_preset_partial_export(self):
        if self.preset_list.currentRow() < 0:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Partial Export"),
                QCoreApplication.translate("Nugget", "Select a preset to export first."))
            return
        item_text = self.preset_list.currentItem().text()
        name = self.preset_list.currentItem().data(Qt.UserRole) or item_text.split("\n")[0].strip()

        from src.gui.dialogs.preset_partial_export import PartialExportDialog
        dialog = PartialExportDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_tweaks()
        if not selected:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Partial Export"),
                QCoreApplication.translate("Nugget",
                    "Select at least one tweak to export."))
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, QCoreApplication.translate("Nugget", "Partial Export"),
            f"{name}.json",
            QCoreApplication.translate("Nugget", "JSON Files (*.json)"))
        if not file_path:
            return
        if self.preset_manager.export_preset(name, file_path, include=selected):
            QMessageBox.information(
                self, QCoreApplication.translate("Nugget", "Partial Export"),
                QCoreApplication.translate("Nugget", "Preset exported to:\n{0}").format(file_path))
        else:
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Partial Export"),
                QCoreApplication.translate("Nugget", "Failed to export preset."))

    def _on_preset_import(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, QCoreApplication.translate("Nugget", "Import Preset"),
            "",
            QCoreApplication.translate("Nugget", "JSON Files (*.json)"))
        if not file_path:
            return
        success, result = self.preset_manager.import_preset(file_path)
        if success:
            self.refresh_presets()
            QMessageBox.information(
                self, QCoreApplication.translate("Nugget", "Import Preset"),
                QCoreApplication.translate("Nugget", "Preset \"{0}\" imported successfully.").format(result))
        else:
            QMessageBox.critical(
                self, QCoreApplication.translate("Nugget", "Import Preset"),
                QCoreApplication.translate("Nugget", "Failed to import preset:\n{0}").format(result))

    def _restart_app(self):
        import os
        import sys
        os.execl(sys.executable, sys.executable, *sys.argv)

    # ---------- about ----------

    def show_about(self):
        from src.gui.dialogs import AboutProgramDialog
        dialog = AboutProgramDialog(self.window)
        dialog.exec()

