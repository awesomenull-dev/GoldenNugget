import os

from PySide6.QtCore import Qt, QCoreApplication, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QToolButton, QFileDialog, QDialog, QDialogButtonBox,
    QLineEdit, QMessageBox,
)

from src.gui.ios.components import IOSCard
from src.gui.theme import ColorThemeManager, theme_icon
from src.gui.dialogs.icon_pack_downloader import IconPackDownloaderDialog
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.icon_themes.icon_theme import IconTheme


class IOSIconThemesPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        self._c = ColorThemeManager.instance().colors

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll = scroll
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(16, 16, 16, 32)
        self.content_layout.setSpacing(8)

        hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "Theme a home screen icon with a custom image and label without "
            "jailbreaking. Tapping the icon still opens the real app. "
            "WebClips launch \"Add to Home Screen\" shortcuts, so existing "
            "icon shortcuts stay untouched — remove disabled apps before "
            "themes to avoid collisions."))
        hint.setWordWrap(True)
        self._hint = hint
        self.content_layout.addWidget(hint)

        download_btn = QPushButton(QCoreApplication.translate(
            "Nugget", "Download Icon Packs"))
        download_btn.setObjectName("downloadIconPacks")
        download_btn.setCursor(Qt.PointingHandCursor)
        download_btn.clicked.connect(self.show_download_packs)
        self._download_btn = download_btn
        self.content_layout.addWidget(download_btn)

        self.themes_placeholder = QLabel(QCoreApplication.translate(
            "Nugget", "No icon themes yet. Tap + Add Icon or download a pack."))
        self.themes_placeholder.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(self.themes_placeholder)

        self._themes_box = QVBoxLayout()
        self._themes_box.setSpacing(8)
        self.content_layout.addLayout(self._themes_box)

        self.content_layout.addStretch()

        self._retheme()
        self.refresh_themes()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._c = c
        self._scroll.setStyleSheet(
            f"background-color: {c.bg_primary}; border: none;")
        self._hint.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self._download_btn.setStyleSheet(f"""
            QPushButton#downloadIconPacks {{
                background-color: {c.bg_secondary};
                border: 1px solid {c.border};
                border-radius: 12px;
                color: {c.accent};
                font-size: 14px;
                font-weight: 600;
                padding: 12px;
            }}
            QPushButton#downloadIconPacks:hover {{ background-color: {c.surface_hover}; }}
        """)
        self.themes_placeholder.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 15px; padding: 24px 0;")
        # Rebuild the theme cards so their hardcoded label colors follow the
        # current palette too.
        if hasattr(self, "_themes_box"):
            self.refresh_themes()

    def refresh_themes(self):
        tweak = tweaks[TweakID.IconThemes]
        themes = tweak.themes
        self.themes_placeholder.setVisible(not themes)
        # clear the box
        while self._themes_box.count():
            item = self._themes_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not themes:
            return
        for theme in themes:
            self._themes_box.addWidget(self._create_theme_card(theme))

    def _create_theme_card(self, theme: IconTheme) -> QWidget:
        c = self._c
        card = IOSCard()
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(56, 56)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background-color: {c.bg_secondary}; border-radius: 12px;")
        pixmap = None
        data = theme.get_icon_data()
        if data is None and theme.icon_path and os.path.isfile(theme.icon_path):
            try:
                pixmap = QPixmap(theme.icon_path)
            except Exception:
                pixmap = None
        if pixmap is None or pixmap.isNull():
            icon_lbl.setText(QCoreApplication.translate("Nugget", "?"))
        else:
            icon_lbl.setPixmap(pixmap.scaled(
                52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        bundle_lbl = QLabel(theme.bundle_id)
        bundle_lbl.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {c.text_primary};")
        bundle_lbl.setWordWrap(True)
        text_col.addWidget(bundle_lbl)
        name_text = theme.display_name if theme.display_name else QCoreApplication.translate("Nugget", "Hide label")
        name_lbl = QLabel(name_text)
        name_lbl.setStyleSheet(f"font-size: 12px; color: {c.text_secondary};")
        name_lbl.setWordWrap(True)
        text_col.addWidget(name_lbl)
        row.addLayout(text_col, 1)

        del_btn = QToolButton()
        del_btn.setIconSize(QSize(18, 18))
        del_btn.setIcon(theme_icon(":/icon/trash.svg", c.text_secondary))
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QToolButton {{ background-color: {c.surface_hover}; color: {c.error}; "
            f"border: 1px solid {c.border}; border-radius: 12px; padding: 7px; }}"
            f"QToolButton:hover {{ background-color: {c.error}; color: {c.text_inverse}; }}"
        )
        del_btn.clicked.connect(lambda: self._remove_theme(theme.bundle_id))
        row.addWidget(del_btn)

        return card

    def _remove_theme(self, bundle_id: str):
        tweak = tweaks[TweakID.IconThemes]
        tweak.remove_theme(bundle_id)
        tweak.set_enabled(not tweak.is_empty())
        self.refresh_themes()

    def show_add_icon_dialog(self):
        dialog = IconThemeDialog(self.window)
        if dialog.exec() == QDialog.Accepted:
            theme = dialog.build_theme()
            if theme is None:
                return
            tweak = tweaks[TweakID.IconThemes]
            if not tweak.store_icon(theme):
                QMessageBox.warning(
                    self.window,
                    QCoreApplication.translate("Nugget", "Warning"),
                    QCoreApplication.translate(
                        "Nugget",
                        "Could not store the icon file in the persistent "
                        "folder. The theme may not apply reliably."))
            tweak.add_theme(theme)
            tweak.set_enabled(True)
            self.refresh_themes()

    def show_download_packs(self):
        dialog = IconPackDownloaderDialog(self.window)
        if dialog.exec() == QDialog.Accepted and dialog.added_bundle_ids:
            self.refresh_themes()


class IconThemeDialog(QDialog):
    """Pick an app bundle id, an icon image and an optional label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Add Icon Theme"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self._icon_path = ""
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        bundle_row = QHBoxLayout()
        bundle_row.setSpacing(8)
        bundle_lbl = QLabel(QCoreApplication.translate("Nugget", "App Bundle ID"))
        bundle_lbl.setObjectName("fieldLbl")
        bundle_row.addWidget(bundle_lbl)
        self.bundle_input = QLineEdit()
        self.bundle_input.setObjectName("fieldInput")
        self.bundle_input.setPlaceholderText("com.apple.mobilesafari")
        bundle_row.addWidget(self.bundle_input, 1)
        layout.addLayout(bundle_row)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = QLabel(QCoreApplication.translate("Nugget", "Label"))
        name_lbl.setObjectName("fieldLbl")
        name_row.addWidget(name_lbl)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("fieldInput")
        self.name_input.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Custom label (empty hides it)"))
        name_row.addWidget(self.name_input, 1)
        layout.addLayout(name_row)

        hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "The app bundle id is the same identifier the app icon uses "
            "under the hood (e.g. com.instagram.instagram)."))
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.icon_row = QHBoxLayout()
        self.icon_row.setSpacing(8)
        icon_lbl = QLabel(QCoreApplication.translate("Nugget", "Icon"))
        icon_lbl.setObjectName("fieldLbl")
        self.icon_row.addWidget(icon_lbl)
        self.icon_btn = QPushButton(QCoreApplication.translate("Nugget", "Choose Image (.png)"))
        self.icon_btn.setObjectName("fieldInput")
        self.icon_btn.setCursor(Qt.PointingHandCursor)
        self.icon_btn.clicked.connect(self._choose_icon)
        self.icon_row.addWidget(self.icon_btn, 1)
        layout.addLayout(self.icon_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel[objectName="fieldLbl"] {{ color: {c.text_secondary}; font-size: 13px; }}
            QLabel[objectName="fieldHint"] {{ color: {c.text_secondary}; font-size: 12px; }}
            QLineEdit, QPushButton[objectName="fieldInput"] {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 14px;
                padding: 10px 12px;
            }}
            QPushButton[objectName="fieldInput"]:hover {{ background-color: {c.surface_hover}; }}
            QPushButton {{
                background-color: {c.accent};
                border-radius: 10px;
                color: {c.text_inverse};
                font-size: 14px;
                padding: 10px 20px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {c.accent_hover}; }}
            QPushButton[text="Cancel"] {{ background-color: {c.surface_hover}; color: {c.text_primary}; }}
        """)

    def _choose_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            QCoreApplication.translate("Nugget", "Select Icon Image"),
            "",
            "Images (*.png *.heic *.jpg *.webp)")
        if path:
            self._icon_path = path
            self.icon_btn.setText(os.path.basename(path))

    def _on_accept(self):
        if not self.bundle_input.text().strip():
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Warning"),
                QCoreApplication.translate("Nugget", "Enter the app bundle id."))
            return
        if not self._icon_path:
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Warning"),
                QCoreApplication.translate("Nugget", "Choose an icon image first."))
            return
        self.accept()

    def build_theme(self):
        return IconTheme(
            bundle_id=self.bundle_input.text().strip(),
            display_name=self.name_input.text().strip(),
            icon_path=self._icon_path)