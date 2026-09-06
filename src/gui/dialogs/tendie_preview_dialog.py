"""Lock-screen preview dialog for a .tendies file.

Renders the tendie's wallpaper (extracted and decoded locally by
``tendie_preview``) inside an iPhone ``PhoneFrame``. When nothing decodable
exists inside the file itself — container-type tendies, or HEIC-only art on a
platform without a HEIF plugin — a matching catalog preview (already cached
by the PosterBoard cards, or fetched in the background) is shown instead.
"""

import os

from PySide6.QtCore import Qt, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src.gui.ios.phone_frame import PhoneFrame

_MAX_EDGE = 1200  # downscale wallpapers past this long edge for cheap painting


class TendiePreviewDialog(QDialog):

    def __init__(self, tendie, parent=None):
        super().__init__(parent)
        self._tendie = tendie
        self._reply = None
        self._nam = QNetworkAccessManager(self)

        self.setWindowTitle(QCoreApplication.translate(
            "Nugget", "Lock Screen Preview"))
        self.setModal(True)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._frame = PhoneFrame()
        self._frame.setFixedSize(250, 520)
        layout.addWidget(self._frame, 0, Qt.AlignmentFlag.AlignHCenter)

        self._hint = QLabel(QCoreApplication.translate(
            "Nugget", "Loading preview..."))
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            "color: #8E8E93; font-size: 12px; background: transparent;")
        layout.addWidget(self._hint)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background-color: #3A3A3C; color: white; "
            "border: none; border-radius: 12px; padding: 10px 24px; "
            "font-size: 14px; }"
            "QPushButton:hover { background-color: #48484A; }")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._load()

    # ---- loading -------------------------------------------------------

    def _load(self):
        """Prefer a live CAML scene render, then bitmap extraction, then the
        catalog preview."""
        try:
            from src.controllers.ca import (
                CAMLRenderer, document_loop_duration, state_transition_spec,
            )
            from src.controllers.ca.tendie import load_tendie, preferred_scene
            bundle = load_tendie(self._tendie.path)
            doc, _key = preferred_scene(bundle)
            if doc is not None:
                renderer = CAMLRenderer(doc)
                loop = document_loop_duration(doc)
                if loop > 0.5:
                    self._frame.set_ca_scene(renderer, loop)
                    self._hint.setText(QCoreApplication.translate(
                        "Nugget",
                        "Playing the tendie's Core Animation scene. "
                        "Swipe up to unlock."))
                else:
                    transition = state_transition_spec(doc)
                    if transition:
                        self._frame.set_ca_transition(renderer, transition)
                        self._hint.setText(QCoreApplication.translate(
                            "Nugget", "Swipe up to unlock."))
                    else:
                        self._frame.set_ca_scene(renderer, 0.0)
                        self._hint.setText(QCoreApplication.translate(
                            "Nugget",
                            "Rendered from the tendie's Core Animation scene."))
                return
        except Exception:
            pass

        path = None
        try:
            from src.controllers.tendie_preview import extract_tendie_preview
            path = extract_tendie_preview(self._tendie.path)
        except Exception:
            path = None
        if path and os.path.exists(path):
            self._apply_image(path, local=True)
            return

        try:
            from src.controllers.wallpaper_api import (
                find_wallpaper_by_name, cached_preview_path,
            )
            wallpaper = find_wallpaper_by_name(self._tendie.name)
        except Exception:
            wallpaper = None
        if wallpaper is None:
            self._show_placeholder()
            return
        cached = cached_preview_path(wallpaper.preview_url)
        if os.path.exists(cached):
            self._apply_image(cached, local=False)
            return
        self._hint.setText(QCoreApplication.translate(
            "Nugget",
            "Wallpaper not found in the file on this device, fetching a "
            "reference preview..."))
        self._reply = self._nam.get(
            QNetworkRequest(QUrl(wallpaper.preview_url)))
        self._reply.finished.connect(self._on_fetch_done)

    def _on_fetch_done(self):
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        ok = reply.error() == QNetworkReply.NetworkError.NoError and data
        url = reply.url().toString()
        reply.deleteLater()
        if not ok:
            self._show_placeholder()
            return
        try:
            from src.controllers.wallpaper_api import cached_preview_path
            path = cached_preview_path(url)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            self._show_placeholder()
            return
        self._apply_image(path, local=False)

    def _apply_image(self, path, local):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._show_placeholder()
            return
        long_edge = max(pixmap.width(), pixmap.height())
        if long_edge > _MAX_EDGE:
            scale = _MAX_EDGE / long_edge
            pixmap = pixmap.scaled(
                max(1, int(pixmap.width() * scale)),
                max(1, int(pixmap.height() * scale)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self._frame.set_wallpaper(pixmap)
        if local:
            self._hint.setText(QCoreApplication.translate(
                "Nugget",
                "Pre-rendered from the tendie file on this device."))
        else:
            self._hint.setText(QCoreApplication.translate(
                "Nugget",
                "Reference preview from the wallpaper gallery."))

    def _show_placeholder(self):
        self._frame.set_placeholder(QCoreApplication.translate(
            "Nugget",
            "No wallpaper image could be decoded from this file."))
        self._hint.setText(QCoreApplication.translate(
            "Nugget",
            "This tendie bundles device layout data only, or its art uses a "
            "format unavailable on this system."))

    # ---- lifecycle ------------------------------------------------------

    def closeEvent(self, event):
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        super().closeEvent(event)

    def reject(self):
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        super().reject()