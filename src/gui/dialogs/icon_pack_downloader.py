"""Online icon-pack downloader dialog for the Icon Themes page.

Port of Cowabunga's ``CowabungaAPI`` + ``ThemesExploreView``: fetches
``icon-themes.json`` from the leminlimez/Cowabunga-explore-repo, shows the
available packs with previews, and downloads + imports the chosen one into
the ``IconThemesTweak`` immediately (so it shows on the page ready for Apply),
exactly like the wallpaper downloader does for ``.tendies``.

All network traffic runs through ``QNetworkAccessManager`` so the UI stays
responsive and there are no background ``QThread`` lifetime issues.
"""

import os
import tempfile

from PySide6.QtCore import Qt, QCoreApplication, QUrl, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QWidget, QMessageBox, QFrame,
)

from src.controllers.icon_themes_api import (
    catalog_url, parse_catalog, DownloadableTheme,
)
from src.tweaks.tweaks import tweaks, TweakID
from src.gui.theme import ColorThemeManager

CARD_W = 180
CARD_H = 250
PREVIEW_H = 130

# preview downloads run a few at a time so long grids can't pile up requests
PREVIEW_CONCURRENCY = 4


class _ThemeCard(QFrame):
    """A downloadable pack entry: preview + name + author/version."""

    def __init__(self, theme: DownloadableTheme, on_click, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("iconPackCard")
        self.setFixedSize(CARD_W, CARD_H)
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.preview_lbl = QLabel(self)
        self.preview_lbl.setObjectName("ipPreview")
        self.preview_lbl.setFixedHeight(PREVIEW_H)
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setText(QCoreApplication.translate("Nugget", "Loading..."))
        self.preview_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.preview_lbl)

        name = QLabel(theme.name, self)
        name.setObjectName("ipName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(name)

        meta_parts = [theme.author, theme.version]
        meta = [m for m in meta_parts if m]
        meta_lbl = QLabel(" · ".join(meta) or " ", self)
        meta_lbl.setObjectName("ipMeta")
        meta_lbl.setAlignment(Qt.AlignCenter)
        meta_lbl.setWordWrap(True)
        meta_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(meta_lbl)

        if theme.description:
            desc = QLabel(theme.description, self)
            desc.setObjectName("ipDesc")
            desc.setWordWrap(True)
            desc.setAlignment(Qt.AlignCenter)
            desc.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(desc)
        layout.addStretch()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._on_click is not None):
            self._on_click(self)
        super().mouseReleaseEvent(event)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QFrame#iconPackCard {{
                background-color: {c.bg_secondary};
                border-radius: 12px;
                border: none;
            }}
            QFrame#iconPackCard:hover {{ background-color: {c.surface_hover}; }}
            QLabel#ipPreview {{
                background-color: {c.bg_tertiary};
                border-radius: 8px;
                color: {c.text_disabled};
                font-size: 13px;
            }}
            QLabel#ipName {{ color: {c.text_primary}; font-size: 14px; font-weight: 600; }}
            QLabel#ipMeta {{ color: {c.text_secondary}; font-size: 11px; }}
            QLabel#ipDesc {{ color: {c.text_secondary}; font-size: 11px; }}
        """)

    def set_preview(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                CARD_W - 16, PREVIEW_H, Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
            self.preview_lbl.setPixmap(scaled)
            return
        self.preview_lbl.setText("\U0001F5BC\ufe0f")


class IconPackDownloaderDialog(QDialog):
    """Browse + download icon packs from the Cowabunga explore repo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Download Icon Packs"))
        self.setModal(True)
        self.resize(760, 560)

        # themes that got imported by this dialog session
        self.added_bundle_ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.status_lbl = QLabel(
            QCoreApplication.translate("Nugget", "Loading icon packs..."), self)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(10)
        self.scroll.setWidget(self.grid_host)
        layout.addWidget(self.scroll, 1)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"), self)
        close_btn.setObjectName("ipCloseBtn")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._nam = QNetworkAccessManager(self)
        self._catalog_reply = None
        self._preview_replies = []
        self._preview_queue = []
        self._download_reply = None
        self._download_theme = None
        self._downloading = False

        self._cards = []
        self._retheme()
        self._fetch_catalog()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QPushButton#ipCloseBtn {{
                background-color: {c.accent};
                border: none;
                border-radius: 10px;
                color: {c.text_inverse};
                font-size: 14px;
                padding: 10px 20px;
            }}
            QPushButton#ipCloseBtn:hover {{ background-color: {c.accent_hover}; }}
        """)
        for card in self._cards:
            card._retheme()

    # --- catalog ---

    def _fetch_catalog(self):
        url = QUrl(catalog_url())
        self._catalog_reply = self._nam.get(QNetworkRequest(url))
        self._catalog_reply.finished.connect(self._on_catalog_reply)

    def _on_catalog_reply(self):
        reply = self._catalog_reply
        self._catalog_reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError or not data:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget",
                "Could not load icon packs.\nCheck your internet connection and try again."))
            return
        try:
            themes = parse_catalog(data)
        except Exception as e:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Could not load icon packs: {0}").format(e))
            return
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "{0} icon packs available — tap one to download it.").format(len(themes)))
        self._populate(themes)

    def _populate(self, themes):
        # clear previous cards
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards = []
        cols = max(1, (self.width() - 32) // (CARD_W + 10))
        for i, theme in enumerate(themes):
            card = _ThemeCard(theme, self._on_card_click)
            self.grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)
            self._enqueue_preview(card)
        self._drain_preview_queue()

    # --- previews ---

    def _enqueue_preview(self, card):
        self._preview_queue.append(card)
        self._drain_preview_queue()

    def _drain_preview_queue(self):
        while self._preview_queue and len(self._preview_replies) < PREVIEW_CONCURRENCY:
            card = self._preview_queue.pop(0)
            reply = self._nam.get(QNetworkRequest(QUrl(card.theme.preview_url)))
            self._preview_replies.append((reply, card))
            reply.finished.connect(lambda r=reply, c=card: self._on_preview_reply(r, c))

    def _on_preview_reply(self, reply, card):
        if (reply, card) in self._preview_replies:
            self._preview_replies.remove((reply, card))
        data = bytes(reply.readAll())
        reply.deleteLater()
        if data:
            card.set_preview(data)
        self._drain_preview_queue()

    # --- download + import ---

    def _on_card_click(self, card):
        if self._downloading:
            return
        theme = card.theme
        ret = QMessageBox.question(
            self,
            QCoreApplication.translate("Nugget", "Download Icon Pack"),
            QCoreApplication.translate(
                "Nugget",
                "Download the \"{0}\" icon pack?\n\n{1}\n\nAuthor: {2}").format(
                    theme.name, theme.description or "\u2014", theme.author or "\u2014"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._download_theme(theme)

    def _download_theme(self, theme):
        self._downloading = True
        self._download_theme = theme
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Downloading \"{0}\"...").format(theme.name))
        self._download_reply = self._nam.get(
            QNetworkRequest(QUrl(theme.download_url)))
        self._download_reply.finished.connect(self._on_download_reply)

    def _on_download_reply(self):
        reply = self._download_reply
        self._download_reply = None
        self._downloading = False
        if reply is None:
            return
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()
        theme = self._download_theme
        self._download_theme = None
        if err != QNetworkReply.NetworkError.NoError or not data:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Download failed for \"{0}\".").format(theme.name if theme else ""))
            return
        try:
            added, skipped = self._import_zip_bytes(data, theme)
        except Exception as e:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Could not import \"{0}\": {1}").format(
                    theme.name if theme else "", e))
            return
        self.added_bundle_ids.extend([theme.name] * added)
        msg = QCoreApplication.translate(
            "Nugget", "Imported {0} icons from \"{1}\".").format(added, theme.name if theme else "")
        if skipped:
            msg += " " + QCoreApplication.translate(
                "Nugget", "({0} bundles skipped — missing icon files).").format(len(skipped))
        self.status_lbl.setText(msg)

    def _import_zip_bytes(self, data: bytes, theme):
        """Write the zip to a temp file and let the tweak import it."""
        tweak = tweaks[TweakID.IconThemes]
        fd, path = tempfile.mkstemp(prefix="icontheme_dl_", suffix=".zip")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            added, skipped = tweak.import_pack_zip(path, theme_name=theme.name if theme else None)
            if added:
                tweak.set_enabled(True)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if added == 0:
            raise RuntimeError("no icons found in archive")
        return added, skipped