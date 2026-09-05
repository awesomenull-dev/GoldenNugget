"""Wallpaper downloader dialog for the PosterBoard page.

Lets the user browse and download wallpapers from Cowabunga and
CaPlayground. Clicking a wallpaper downloads the ``.tendies`` file and
imports it into the PosterBoard tweak immediately, so it shows up on the
Tendies tab ready for Apply.

Everything (catalog fetch, preview images, and the .tendies download) runs
through ``QNetworkAccessManager`` so the UI stays responsive and there are
no background ``QThread`` lifetime issues.
"""

import hashlib
import os
import time
import uuid

from PySide6.QtCore import Qt, QCoreApplication, QTimer, QUrl, QStandardPaths, QByteArray, QSize
from PySide6.QtGui import QPixmap, QMovie
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QScrollArea, QGridLayout, QPushButton, QWidget, QMessageBox,
    QProgressBar, QFrame,
)

from src.tweaks.tweaks import tweaks, TweakID


CARD_W = 150
CARD_H = 300
PREVIEW_H = 200

CATALOG_TTL = 15 * 60


class _WallpaperCard(QFrame):
    """A single wallpaper entry: preview + name + author, click to download."""

    def __init__(self, wallpaper, on_click, parent=None):
        super().__init__(parent)
        self.wallpaper = wallpaper
        self._on_click_cb = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("wallpaperCard")
        self.setStyleSheet("""
            QFrame#wallpaperCard {
                background-color: #1C1C1E;
                border-radius: 12px;
                border: none;
            }
            QFrame#wallpaperCard:hover { background-color: #2C2C2E; }
            QLabel#wpName { color: #FFFFFF; font-size: 13px; font-weight: 600; }
            QLabel#wpAuthor { color: #8E8E93; font-size: 11px; }
            QLabel#wpPreview { background-color: #26262A; border-radius: 8px; }
        """)
        self.setFixedSize(CARD_W, CARD_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.preview_lbl = QLabel(self)
        self.preview_lbl.setObjectName("wpPreview")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setFixedHeight(PREVIEW_H)
        layout.addWidget(self.preview_lbl)
        self._set_loading()
        self._preview_movie = None
        self._preview_path = None
        self.preview_state = "none"
        self._playback_suppressed = False

        name = QLabel(wallpaper.name, self)
        name.setObjectName("wpName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        name.setMaximumHeight(36)
        layout.addWidget(name)

        author = QLabel(wallpaper.author or " ", self)
        author.setObjectName("wpAuthor")
        author.setAlignment(Qt.AlignCenter)
        author.setWordWrap(True)
        author.setMaximumHeight(28)
        layout.addWidget(author)

        layout.addStretch()

    def _set_loading(self):
        self.preview_lbl.setText(QCoreApplication.translate("Nugget", "Loading..."))
        self.preview_lbl.setStyleSheet(
            "background-color: #26262A; border-radius: 8px;"
            "font-size: 13px; color: #6E6E73;"
        )

    def _set_placeholder(self):
        self.preview_lbl.setText("\U0001F5BC\ufe0f")
        self.preview_lbl.setStyleSheet(
            "background-color: #26262A; border-radius: 8px;"
            "font-size: 34px; color: #3A3A3C;"
        )

    def set_preview_file(self, path):
        """Show a cached preview from disk. Animated GIFs run via ``QMovie``
        from the file (no raw bytes kept around); playback is suppressed
        while the dialog is busy downloading, e.g. a .tendies."""
        if not path or self.preview_state in ("ready", "failed"):
            return
        movie = QMovie(path, QByteArray())
        if movie.isValid():
            self.preview_state = "ready"
            self._preview_movie = movie
            self._preview_path = path
            box = QSize(CARD_W - 16, PREVIEW_H)

            def _fit_first_frame(*_):
                size = movie.frameRect().size()
                if not size.isEmpty():
                    try:
                        movie.setScaledSize(size.scaled(box, Qt.KeepAspectRatio))
                        movie.frameChanged.disconnect(_fit_first_frame)
                    except Exception:
                        pass

            movie.frameChanged.connect(_fit_first_frame)
            self.preview_lbl.setMovie(movie)
            if self.preview_lbl.isVisible():
                self.start_playback()
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.preview_state = "ready"
            self._preview_path = path
            self.preview_lbl.setPixmap(pixmap.scaled(
                CARD_W - 16, PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return
        self.preview_state = "failed"
        self._set_placeholder()

    def start_playback(self):
        if self._playback_suppressed:
            return
        movie = self._preview_movie
        if movie is not None:
            try:
                movie.jumpToFrame(0)  # QMovie won't resume from a stopped EOF
            except Exception:
                pass
            movie.start()

    def stop_playback(self):
        movie = self._preview_movie
        if movie is not None:
            movie.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.start_playback()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.stop_playback()

    def mousePressEvent(self, event):
        if self._on_click_cb:
            self._on_click_cb(self.wallpaper)
        super().mousePressEvent(event)


class WallpaperDownloaderDialog(QDialog):
    """Browse + download wallpapers and import them into PosterBoard."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Download Wallpapers"))
        self.setModal(True)
        self.setFixedSize(760, 780)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; }
            QComboBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 14px;
                padding: 8px 12px;
                min-height: 24px;
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background-color: #2C2C2E;
                border: 1px solid #3A3A3C;
                border-radius: 10px;
                color: #FFFFFF;
                selection-background-color: #007AFF;
            }
            QLineEdit {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 14px;
                padding: 8px 12px;
            }
            QScrollArea { background: transparent; border: none; }
            QProgressBar {
                background-color: #1C1C1E;
                border-radius: 4px;
                border: none;
                height: 7px;
                text-align: center;
            }
            QProgressBar::chunk { background-color: #007AFF; border-radius: 4px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Top row: source picker + category + search
        top = QHBoxLayout()
        top.setSpacing(10)

        self.source_drp = QComboBox()
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "All"), "all")
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "Cowabunga"), "cowabunga")
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "CaPlayground"), "caplayground")
        self.source_drp.currentIndexChanged.connect(self._on_source_changed)
        top.addWidget(self.source_drp)

        self.category_drp = QComboBox()
        self.category_drp.currentTextChanged.connect(self._on_category_changed)
        top.addWidget(self.category_drp)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(QCoreApplication.translate("Nugget", "Search wallpapers..."))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        top.addWidget(self.search_box, 1)

        layout.addLayout(top)

        # Status / progress area
        self.status_lbl = QLabel(QCoreApplication.translate("Nugget", "Loading..."))
        self.status_lbl.setStyleSheet("color: #8E8E93; font-size: 13px;")
        layout.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Grid scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._grid_host = QWidget()
        self.grid = QGridLayout(self._grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self._grid_host)
        self.scroll.verticalScrollBar().valueChanged.connect(
            lambda *_: self._load_visible_previews())
        layout.addWidget(self.scroll, 1)

        # Bottom close button
        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 16px;
                font-weight: 600;
                padding: 12px;
                border: none;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._all_wallpapers = []
        self._cards = []
        self._grid_cols = 1
        self._catalog_replies = []
        self._catalog_sources = set()
        self._merge_results = {}
        self._catalog_failed = {}
        self._fetch_gen = 0
        self._preview_replies = []
        self._download_reply = None
        self._download_wallpaper = None
        self._busy = False
        # one manager per dialog; alive as long as the dialog is
        self._nam = QNetworkAccessManager(self)

        from src.controllers.wallpaper_api import (
            CowabungaSource, CaPlaygroundSource,
        )
        self._sources = {
            "cowabunga": CowabungaSource(),
            "caplayground": CaPlaygroundSource(),
        }

        self._cache_root = self._init_cache()

        self._populate_categories()
        self._fetch_wallpapers()

    # --- source / category handling ---

    def _populate_categories(self):
        self.category_drp.blockSignals(True)
        self.category_drp.clear()
        if self.source_drp.currentData() == "cowabunga":
            for cat in ("Custom", "Apple"):
                self.category_drp.addItem(QCoreApplication.translate("Nugget", cat))
        self.category_drp.setEnabled(self.source_drp.currentData() == "cowabunga")
        self.category_drp.blockSignals(False)

    def _on_source_changed(self, *_):
        self._populate_categories()
        self._fetch_wallpapers()

    def _on_category_changed(self, *_):
        self._fetch_wallpapers()

    # --- local cache ---

    def _init_cache(self):
        from src.controllers.wallpaper_api import wallpaper_cache_root
        return wallpaper_cache_root()

    def _hash_key(self, text):
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _catalog_cache_path(self, source_id, category):
        return os.path.join(
            self._cache_root, "catalog",
            f"{source_id}_{self._hash_key(category or '')}.json")

    def _read_catalog_cache(self, source_id, category):
        path = self._catalog_cache_path(source_id, category)
        try:
            if time.time() - os.path.getmtime(path) > CATALOG_TTL:
                return None
            with open(path, "r", encoding="utf-8") as f:
                return self._sources[source_id].parse(f.read())
        except Exception:
            return None

    def _write_catalog_cache(self, source_id, category, raw):
        try:
            with open(self._catalog_cache_path(source_id, category), "w",
                      encoding="utf-8") as f:
                f.write(raw)
        except OSError:
            pass

    def _preview_cache_path(self, url):
        from src.controllers.wallpaper_api import cached_preview_path
        return cached_preview_path(url)

    # --- catalog fetching (async via QNetworkAccessManager) ---

    def _fetch_wallpapers(self):
        self._abort_inflight()
        self._fetch_gen += 1
        gen = self._fetch_gen
        source_id = self.source_drp.currentData()
        category = self.category_drp.currentText() if source_id == "cowabunga" else ""

        self.status_lbl.setText(QCoreApplication.translate("Nugget", "Loading wallpapers..."))
        self.progress.setVisible(True)
        self._clear_cards()
        self._merge_results = {}
        self._catalog_failed = {}
        self._catalog_sources = set()

        targets = []
        if source_id == "all":
            # Dedup prefers cowabunga (already sorted by that name below).
            for sid in ("cowabunga", "caplayground"):
                targets.append((sid, "Custom" if sid == "cowabunga" else ""))
        elif source_id in self._sources:
            targets.append((source_id, category))
        else:
            targets.append(("cowabunga", category))

        for sid, cat in targets:
            try:
                url = self._sources[sid].fetch_url(cat)
            except Exception:
                continue
            cached = self._read_catalog_cache(sid, cat)
            if cached is not None:
                self._merge_results[sid] = cached
                self._catalog_sources.add(sid)
                continue
            self._request_catalog(url, sid, cat, gen)

        if self._catalog_sources and not self._catalog_replies:
            self._finish_catalog_load()
        elif not self._catalog_sources and not self._catalog_replies:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")

    def _request_catalog(self, url, source_id, category, gen):
        reply = self._nam.get(QNetworkRequest(QUrl(url)))
        self._catalog_replies.append((reply, source_id))
        reply.finished.connect(
            lambda r=reply, s=source_id, c=category, g=gen:
                self._on_catalog_reply(r, s, c, g))

    def _on_catalog_reply(self, reply, source_id, category, gen):
        if gen != self._fetch_gen:
            reply.deleteLater()
            return
        if reply in [r for r, _ in self._catalog_replies]:
            self._catalog_replies = [
                (r, s) for (r, s) in self._catalog_replies if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._catalog_failed[source_id] = reply.errorString()
        else:
            try:
                self._merge_results[source_id] = self._sources[source_id].parse(data)
                self._write_catalog_cache(source_id, category, data.decode("utf-8", "replace"))
                self._catalog_sources.add(source_id)
            except Exception as e:
                self._catalog_failed[source_id] = str(e)
        if self._catalog_replies:
            return
        if self._catalog_sources:
            self._finish_catalog_load()
        else:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")

    def _finish_catalog_load(self):
        self.progress.setVisible(False)
        if not self._merge_results:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")
            return
        if self.source_drp.currentData() == "all":
            wallpapers = self._merge_dedupe()
        else:
            wallpapers = next(iter(self._merge_results.values()))
        self.status_lbl.setText(
            QCoreApplication.translate("Nugget", "{} wallpapers").format(len(wallpapers))
            if wallpapers else QCoreApplication.translate("Nugget", "No wallpapers found")
        )
        self._populate_grid(wallpapers)

    def _merge_dedupe(self) -> list:
        """Merge the all-source catalogs, dropping duplicate names.
        Cowabunga is merged first so it wins when both sources expose the
        same wallpaper (it is faster to serve and already localized)."""
        seen = set()
        merged = []
        for sid in ("cowabunga", "caplayground"):
            for wp in self._merge_results.get(sid, []):
                key = wp.name.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    merged.append(wp)
        return merged

    def _on_load_failed(self, message):
        self.progress.setVisible(False)
        self.status_lbl.setText(QCoreApplication.translate("Nugget", "Failed to load wallpapers"))
        self._show_error(
            QCoreApplication.translate("Nugget", "Failed to load wallpapers"), message)

    # --- grid ---

    def _clear_cards(self):
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = []
        self._all_wallpapers = []

    def _populate_grid(self, wallpapers):
        self._clear_cards()
        self._all_wallpapers = list(wallpapers)
        cols = max(1, self.width() // (CARD_W + 16))
        self._grid_cols = cols
        for i, wp in enumerate(wallpapers):
            card = _WallpaperCard(wp, self._on_card_clicked, self._grid_host)
            self.grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)
        # defer one event-loop turn so the freshly added cards finish being
        # shown (isVisible()) before the viewport window is computed
        QTimer.singleShot(0, self._load_visible_previews)
        self._apply_search(self.search_box.text())

    def _apply_search(self, text):
        term = text.strip().lower()
        for card in self._cards:
            matches = (
                term == ""
                or term in card.wallpaper.name.lower()
                or term in card.wallpaper.author.lower()
            )
            card.setVisible(matches)
        # cards brought back into view by clearing the filter need previews
        QTimer.singleShot(0, self._load_visible_previews)

    # --- previews (async via the same manager) ---

    def _load_visible_previews(self):
        """Fetch previews only for cards inside (or next to) the viewport.
        Previews are cached to disk; GIFs stream from the file via QMovie, so
        off-screen cards never decode frames."""
        if not self._cards:
            return
        vbar = self.scroll.verticalScrollBar()
        value = vbar.value()
        view_h = self.scroll.viewport().height()
        row_h = CARD_H + self.grid.spacing()
        cols = self._grid_cols
        top_row = max(0, (value - row_h) // row_h)
        bottom_row = min(len(self._cards) // cols, (value + view_h + row_h) // row_h)
        for row in range(top_row, bottom_row + 1):
            for col in range(cols):
                idx = row * cols + col
                if idx >= len(self._cards):
                    break
                card = self._cards[idx]
                if card.isVisible():
                    self._request_preview(card)

    def _request_preview(self, card):
        if card.preview_state != "none":
            return
        if not self._card_is_valid(card):
            return
        path = self._preview_cache_path(card.wallpaper.preview_url)
        if os.path.exists(path):
            card.set_preview_file(path)
            return
        card.preview_state = "loading"
        reply = self._nam.get(QNetworkRequest(QUrl(card.wallpaper.preview_url)))
        self._preview_replies.append((reply, card, path))
        reply.finished.connect(
            lambda r=reply, c=card, p=path: self._on_preview_reply(r, c, p))

    def _on_preview_reply(self, reply, card, path):
        if reply in [r for r, _, _ in self._preview_replies]:
            self._preview_replies = [
                (r, c, p) for (r, c, p) in self._preview_replies if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError or not data:
            if self._card_is_valid(card):
                card.preview_state = "failed"
                card._set_placeholder()
            return
        # card could have been removed (deleteLater processed) during a refetch
        if not self._card_is_valid(card):
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            card.preview_state = "failed"
            card._set_placeholder()
            return
        card.set_preview_file(path)

    def _pause_previews(self):
        for card in self._cards:
            card._playback_suppressed = True
            card.stop_playback()

    def _resume_previews(self):
        for card in self._cards:
            card._playback_suppressed = False
            if card.isVisible():
                card.start_playback()

    def _card_is_valid(self, card) -> bool:
        import shiboken6
        if not shiboken6.isValid(card):
            return False
        try:
            return shiboken6.isValid(card.preview_lbl)
        except RuntimeError:
            return False

    # --- download + import (async via the same manager) ---

    def _on_card_clicked(self, wallpaper):
        if self._busy:
            return
        self._busy = True
        # Free CPU for the transfer: stop the animated previews while the
        # .tendies downloads so the dialog (and the whole app) stays smooth.
        self._pause_previews()
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Downloading {}...").format(wallpaper.name))
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._download_wallpaper = wallpaper
        self._download_reply = self._nam.get(QNetworkRequest(QUrl(wallpaper.download_url)))
        self._download_reply.downloadProgress.connect(self._on_download_progress)
        self._download_reply.finished.connect(self._on_download_finished)

    def _on_download_progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def _on_download_finished(self):
        reply = self._download_reply
        self._download_reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        reply.deleteLater()

        self._busy = False
        self.progress.setVisible(False)
        self._resume_previews()

        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.status_lbl.setText(QCoreApplication.translate("Nugget", "Download failed"))
            self._show_error(
                QCoreApplication.translate("Nugget", "Download failed"),
                reply.errorString())
            return

        path = self._save_tendie(data, self._download_wallpaper.name)
        if path is None:
            self.status_lbl.setText(QCoreApplication.translate("Nugget", "Import failed"))
            return

        pb = tweaks[TweakID.PosterBoard]
        try:
            if not pb.add_tendie(path):
                QMessageBox.warning(
                    self,
                    QCoreApplication.translate("Nugget", "Import Failed"),
                    QCoreApplication.translate(
                        "Nugget",
                        "Could not import wallpaper: you have reached the "
                        "maximum of 10 descriptors."),
                )
                self.status_lbl.setText(QCoreApplication.translate(
                    "Nugget", "Import skipped (limit reached)"))
                return
        except Exception as e:
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Import Failed"),
                QCoreApplication.translate(
                    "Nugget", "Failed to import wallpaper") + f"\n\n{e}",
            )
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Import failed"))
            return

        pb_page = getattr(self.window, "ios_posterboard", None)
        if pb_page is not None:
            pb_page.refresh_tendies()

        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Imported {}!").format(self._download_wallpaper.name))

    def _save_tendie(self, data: bytes, name: str):
        dest_dir = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.AppDataLocation),
            "downloaded_wallpapers",
        )
        os.makedirs(dest_dir, exist_ok=True)
        safe_name = "".join(
            c for c in name if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_")
        dest = os.path.join(dest_dir, f"{safe_name or 'wallpaper'}_{uuid.uuid4().hex[:8]}.tendies")
        try:
            with open(dest, "wb") as f:
                f.write(data)
            return dest
        except OSError as e:
            self._show_error(
                QCoreApplication.translate("Nugget", "Save Failed"), str(e))
            return None

    # --- cleanup ---

    def _abort_inflight(self):
        self._fetch_gen += 1
        for reply, _ in self._catalog_replies:
            reply.abort()
        self._catalog_replies = []
        self._catalog_sources = set()
        for reply, _, _ in self._preview_replies:
            reply.abort()
        self._preview_replies = []

    def _show_error(self, title, message):
        QMessageBox.warning(self, title, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._all_wallpapers:
            self._populate_grid(self._all_wallpapers)
            self._apply_search(self.search_box.text())

    def closeEvent(self, event):
        self._abort_inflight()
        if self._download_reply is not None:
            self._download_reply.abort()
            self._download_reply = None
        super().closeEvent(event)