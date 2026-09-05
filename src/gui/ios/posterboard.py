import os

from PySide6.QtCore import Qt, QSize, QCoreApplication, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QScrollArea, QToolButton, QStackedWidget,
    QCheckBox, QComboBox
)
from PySide6.QtGui import QPixmap, QIcon, QImageReader
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from src.gui.ios.components import IOSCard, IOSPrimaryButton
from src.tweaks.tweaks import tweaks, TweakID


class TemplatePreviewCard(QLabel):
    """Clickable preview image that can show full size"""
    def __init__(self, pixmap: QPixmap, preview_name: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(200, 200)
        self.setStyleSheet(
            "QLabel { background-color: #1C1C1E; border-radius: 12px; border: 1px solid #3A3A3C; }"
        )
        self._original_pixmap = pixmap
        self._preview_name = preview_name
        self.setPixmap(pixmap.scaled(190, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class IOSPosterboardPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # the "+ Add Tendies" action lives in the shared header (main window)

        # Reset PosterBoard card — emergency exit for a misbehaving or
        # malformed PosterBoard database (see regression found in 8.3).
        reset_card = IOSCard()
        reset_layout = QVBoxLayout(reset_card)
        reset_layout.setContentsMargins(16, 12, 16, 12)
        reset_layout.setSpacing(8)

        reset_btn = QPushButton(QCoreApplication.translate("Nugget", "Reset PosterBoard"))
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b3b3b;
                border: none;
                border-radius: 10px;
                color: #FF453A;
                font-size: 15px;
                font-weight: 600;
                padding: 12px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)
        reset_btn.clicked.connect(self._reset_posterboard)
        reset_layout.addWidget(reset_btn)

        reset_caption = QLabel(QCoreApplication.translate(
            "Nugget",
            "Emergency reset for when PosterBoard behaves strangely or the "
            "database won't load after a restore. Resets on the next apply."
        ))
        reset_caption.setWordWrap(True)
        reset_caption.setStyleSheet("color: #8E8E93; font-size: 12px;")
        reset_layout.addWidget(reset_caption)

        layout.addWidget(reset_card)

        # Tab bar
        self.tab_stack = QStackedWidget()
        layout.addWidget(self.tab_stack)

        # Tendies tab
        self.tendies_page = self._create_tendies_tab()
        self.tab_stack.addWidget(self.tendies_page)

        # Templates tab
        self.templates_page = self._create_templates_tab()
        self.tab_stack.addWidget(self.templates_page)

        # Video tab
        self.video_page = self._create_video_tab()
        self.tab_stack.addWidget(self.video_page)

        # Bottom tab bar
        tab_bar = QWidget()
        tab_bar.setFixedHeight(56)
        tab_bar.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #1C1C1E;")
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        self.tendies_tab_btn = self._make_tab_button(QCoreApplication.translate("Nugget", "Tendies"), ":/icon/wallpaper.svg", 0)
        self.templates_tab_btn = self._make_tab_button(QCoreApplication.translate("Nugget", "Templates"), ":/icon/photo-stack.svg", 1)
        self.video_tab_btn = self._make_tab_button(QCoreApplication.translate("Nugget", "Video"), ":/icon/play-circle.svg", 2)

        tab_layout.addWidget(self.tendies_tab_btn, 1)
        tab_layout.addWidget(self.templates_tab_btn, 1)
        tab_layout.addWidget(self.video_tab_btn, 1)

        layout.addWidget(tab_bar)

        # Set initial tab
        self._switch_tab(0)

        # Async preview-by-name loader for tendie cards (mirrors the
        # wallpaper downloader: fetch -> cached file -> QImageReader frame).
        self._tendie_nam = QNetworkAccessManager(self)
        self._tendie_preview_replies = []

        # Load existing tendies
        self.refresh_tendies()

    def _make_tab_button(self, text: str, icon_path: str, index: int) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setIconSize(QSize(24, 24))
        from PySide6.QtGui import QIcon
        btn.setIcon(QIcon(icon_path))
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                color: #8E8E93;
                font-size: 11px;
                padding: 8px 0;
                border: none;
            }
            QToolButton:checked {
                color: #007AFF;
            }
        """)
        btn.clicked.connect(lambda: self._switch_tab(index))
        return btn

    def _switch_tab(self, index: int):
        self.tab_stack.setCurrentIndex(index)
        self.tendies_tab_btn.setChecked(index == 0)
        self.templates_tab_btn.setChecked(index == 1)
        self.video_tab_btn.setChecked(index == 2)

    def _create_tendies_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        content = QWidget()
        scroll.setWidget(content)

        self.tendies_grid = QGridLayout(content)
        self.tendies_grid.setContentsMargins(16, 16, 16, 32)
        self.tendies_grid.setSpacing(12)
        self.tendies_grid.setAlignment(Qt.AlignTop)

        # Download wallpapers banner (Cowabunga / CaPlayground)
        self.download_card = self._create_download_card()
        self.tendies_grid.addWidget(self.download_card, 0, 0, 1, 2)

        # Add tendies button
        self.add_tendies_card = self._create_add_tendies_card()
        self.tendies_grid.addWidget(self.add_tendies_card, 1, 0)

        return scroll

    def _create_download_card(self) -> QWidget:
        card = IOSCard()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(88)
        card.mousePressEvent = lambda e: self.open_wallpaper_downloader()

        inner = QHBoxLayout(card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(12)

        icon = QLabel()
        icon.setFixedSize(48, 48)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "QLabel { background-color: #007AFF; border-radius: 12px; font-size: 24px; color: white; }"
        )
        icon.setText("\u2193")
        inner.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(QCoreApplication.translate("Nugget", "Download Wallpapers"))
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF;")
        text_col.addWidget(title)
        subtitle = QLabel(QCoreApplication.translate(
            "Nugget",
            "Browse and import wallpapers from Cowabunga and CaPlayground"))
        subtitle.setStyleSheet("font-size: 12px; color: #8E8E93;")
        text_col.addWidget(subtitle)
        inner.addLayout(text_col, 1)

        chevron = QLabel("\u203A")
        chevron.setStyleSheet("font-size: 26px; color: #8E8E93;")
        inner.addWidget(chevron)

        return card

    def _create_add_tendies_card(self) -> QWidget:
        card = IOSCard()
        card.setFixedSize(140, 160)
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda e: self.show_add_tendies_dialog()

        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 16, 16, 16)
        inner.setSpacing(12)
        inner.setAlignment(Qt.AlignCenter)

        plus_icon = QLabel()
        plus_icon.setFixedSize(64, 64)
        plus_icon.setAlignment(Qt.AlignCenter)
        plus_icon.setStyleSheet(
            "QLabel { background-color: #1C1C1E; border-radius: 12px; border: 2px dashed #3A3A3C; }"
        )
        plus_icon.setText("+")
        plus_icon.setStyleSheet(plus_icon.styleSheet() + "font-size: 36px; color: #007AFF;")
        inner.addWidget(plus_icon, 0, Qt.AlignCenter)

        label = QLabel(QCoreApplication.translate("Nugget", "  Import Files (.tendies)"))
        label.setStyleSheet("font-size: 14px; color: #8E8E93; text-align: center;")
        label.setAlignment(Qt.AlignCenter)
        inner.addWidget(label)

        return card

    def _create_templates_tab(self) -> QWidget:
        """Port of classic templates page - uses template.create_ui() for full functionality"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        scroll.setFrameStyle(QScrollArea.NoFrame)
        
        content = QWidget()
        self.templates_layout = QVBoxLayout(content)
        self.templates_layout.setContentsMargins(16, 16, 16, 32)
        self.templates_layout.setSpacing(12)
        self.templates_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)

        # Import button (classic style)
        import_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "  Import Templates (.batter)"))
        import_btn.clicked.connect(self.show_add_templates_dialog)
        self.templates_import_btn = import_btn
        self.templates_layout.addWidget(import_btn)

        self.templates_placeholder = QLabel(QCoreApplication.translate("Nugget", "No templates added yet"))
        self.templates_placeholder.setStyleSheet("font-size: 15px; color: #8E8E93;")
        self.templates_placeholder.setAlignment(Qt.AlignCenter)
        self.templates_layout.addWidget(self.templates_placeholder)

        # Load existing templates using classic create_ui()
        self._load_templates_list()

        return scroll

    def show_add_templates_dialog(self):
        """Port of classic on_importTemplatesBtn_clicked"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        selected_files, _ = QFileDialog.getOpenFileNames(
            self.window, QCoreApplication.translate("Nugget", "Select Nugget Template Files"), "", "Zip Files (*.batter)"
        )
        if selected_files:
            templates_tweak = tweaks[TweakID.Templates]
            try:
                device_version = self.window.device_manager.get_current_device_version()
            except Exception:
                device_version = None
            for file in selected_files:
                try:
                    templates_tweak.add_template(file, device_version)
                except Exception as e:
                    QMessageBox.warning(self.window, "Import Failed", f"Failed to load template:\n{file}\n\n{str(e)}")
            self._load_templates_list()

    def _load_templates_list(self):
        """Port of classic load_templates_list / load_pb_templates - uses template.create_ui()"""
        from src.tweaks.tweaks import tweaks, TweakID
        templates = tweaks[TweakID.Templates].templates
        if not templates:
            self.templates_placeholder.show()
            return
        self.templates_placeholder.hide()

        # Clear existing template widgets (keep import button and placeholder)
        for i in reversed(range(self.templates_layout.count())):
            widget = self.templates_layout.itemAt(i).widget()
            if widget is not None and widget not in (self.templates_placeholder, self.templates_import_btn):
                widget.deleteLater()

        # Classic approach: call template.create_ui() for each template
        # This creates the full UI with previews, pickers, bundle ID, etc.
        widgets = {}
        for template in templates:
            template.create_ui(self.window, tweaks[TweakID.Templates], widgets, self.templates_layout)

    def _create_video_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        content = QWidget()
        scroll.setWidget(content)

        v_layout = QVBoxLayout(content)
        v_layout.setContentsMargins(16, 16, 16, 32)
        v_layout.setSpacing(16)

        # Thumbnail
        thumb_row = QHBoxLayout()
        thumb_label = QLabel(QCoreApplication.translate("Nugget", "Thumbnail"))
        thumb_label.setStyleSheet("font-size: 15px; color: #FFFFFF; min-width: 100px;")
        self.thumb_btn = QPushButton(QCoreApplication.translate("Nugget", "Choose Freeze Frame (.HEIC)"))
        self.thumb_btn.setCursor(Qt.PointingHandCursor)
        self.thumb_btn.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1E;
                border-radius: 10px;
                color: #007AFF;
                font-size: 15px;
                padding: 12px 24px;
                border: none;
            }
            QPushButton:hover { background-color: #2C2C2E; }
        """)
        self.thumb_btn.clicked.connect(self.on_choose_thumb_clicked)
        thumb_row.addWidget(thumb_label)
        thumb_row.addWidget(self.thumb_btn, 1)
        v_layout.addLayout(thumb_row)

        # Video
        video_row = QHBoxLayout()
        video_label = QLabel(QCoreApplication.translate("Nugget", "Video"))
        video_label.setStyleSheet("font-size: 15px; color: #FFFFFF; min-width: 100px;")
        self.video_btn = QPushButton(QCoreApplication.translate("Nugget", "Choose Video"))
        self.video_btn.setCursor(Qt.PointingHandCursor)
        self.video_btn.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1E;
                border-radius: 10px;
                color: #007AFF;
                font-size: 15px;
                padding: 12px 24px;
                border: none;
            }
            QPushButton:hover { background-color: #2C2C2E; }
        """)
        self.video_btn.clicked.connect(self.on_choose_video_clicked)
        video_row.addWidget(video_label)
        video_row.addWidget(self.video_btn, 1)
        v_layout.addLayout(video_row)

        # Options
        v_layout.addWidget(QLabel(QCoreApplication.translate("Nugget", "Options")))
        self.loop_chk = QCheckBox(QCoreApplication.translate("Nugget", "Loop (use CoreAnimation method)"))
        self.loop_chk.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        self.loop_chk.setChecked(tweaks[TweakID.PosterBoard].loop_video)
        self.loop_chk.toggled.connect(self.on_loop_toggled)
        v_layout.addWidget(self.loop_chk)

        self.reverse_chk = QCheckBox(QCoreApplication.translate("Nugget", "Reverse on Loop"))
        self.reverse_chk.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        self.reverse_chk.setChecked(tweaks[TweakID.PosterBoard].reverse_video)
        self.reverse_chk.toggled.connect(self.on_reverse_toggled)
        v_layout.addWidget(self.reverse_chk)

        self.foreground_chk = QCheckBox(QCoreApplication.translate("Nugget", "Make Foreground (hides clock)"))
        self.foreground_chk.setStyleSheet("color: #FFFFFF; font-size: 15px;")
        self.foreground_chk.setChecked(tweaks[TweakID.PosterBoard].use_foreground)
        self.foreground_chk.toggled.connect(self.on_foreground_toggled)
        v_layout.addWidget(self.foreground_chk)

        # Calculation mode
        calc_row = QHBoxLayout()
        calc_label = QLabel(QCoreApplication.translate("Nugget", "Calculation Mode"))
        calc_label.setStyleSheet("font-size: 15px; color: #FFFFFF; min-width: 100px;")
        self.calc_mode_drp = QComboBox()
        self.calc_mode_drp.addItem(QCoreApplication.translate("Nugget", "Linear"))
        self.calc_mode_drp.addItem(QCoreApplication.translate("Nugget", "Discrete"))
        self.calc_mode_drp.setCurrentIndex(0 if tweaks[TweakID.PosterBoard].calculationMode == 'linear' else 1)
        self.calc_mode_drp.activated.connect(self.on_calc_mode_selected)
        self.calc_mode_drp.setStyleSheet("""
            QComboBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 14px;
                padding: 8px 12px;
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background-color: #2C2C2E;
                border: 1px solid #3A3A3C;
                border-radius: 10px;
                color: #FFFFFF;
                selection-background-color: #007AFF;
            }
        """)
        calc_row.addWidget(calc_label)
        calc_row.addWidget(self.calc_mode_drp, 1)
        v_layout.addLayout(calc_row)

        # Export video loop
        export_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Export Video Loop (.tendies)"))
        export_btn.clicked.connect(self.on_export_video_clicked)
        v_layout.addWidget(export_btn)

        # Discover wallpapers + help
        ext_row = QHBoxLayout()
        discover_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Discover Wallpapers"))
        discover_btn.clicked.connect(self.on_discover_wallpapers)
        help_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Help"))
        help_btn.clicked.connect(self.on_help)
        ext_row.addWidget(discover_btn)
        ext_row.addWidget(help_btn)
        v_layout.addLayout(ext_row)

        v_layout.addStretch()

        self._update_video_labels()

        return scroll

    def _update_video_labels(self):
        pb = tweaks[TweakID.PosterBoard]
        thumb = pb.videoThumbnail if pb.videoThumbnail else None
        video = pb.videoFile if pb.videoFile else None
        self.thumb_btn.setText(QCoreApplication.translate("Nugget", "Choose Freeze Frame (.HEIC)") if not thumb else thumb)
        self.video_btn.setText(QCoreApplication.translate("Nugget", "Choose Video") if not video else video)
        self.reverse_chk.setVisible(pb.loop_video)
        self.foreground_chk.setVisible(pb.loop_video)

    def on_choose_thumb_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        selected_file, _ = QFileDialog.getOpenFileName(
            self.window, QCoreApplication.translate("Nugget", "Select Image File"), "", "Image Files (*.heic)"
        )
        pb = tweaks[TweakID.PosterBoard]
        if selected_file:
            pb.videoThumbnail = selected_file
        else:
            pb.videoThumbnail = None
        self._update_video_labels()

    def on_choose_video_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        selected_file, _ = QFileDialog.getOpenFileName(
            self.window, QCoreApplication.translate("Nugget", "Select Video File"), "", "Video Files (*.mov *.mp4 *.mkv)"
        )
        pb = tweaks[TweakID.PosterBoard]
        if selected_file:
            pb.videoFile = selected_file
        else:
            pb.videoFile = None
        self._update_video_labels()

    def on_loop_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].loop_video = checked
        self.reverse_chk.setVisible(checked)
        self.foreground_chk.setVisible(checked)

    def on_reverse_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].reverse_video = checked

    def on_foreground_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].use_foreground = checked

    def on_calc_mode_selected(self, index: int):
        tweaks[TweakID.PosterBoard].calculationMode = 'linear' if index == 0 else 'discrete'

    def on_export_video_clicked(self):
        import os
        import uuid
        import subprocess
        from shutil import make_archive, rmtree
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        directory = QFileDialog.getExistingDirectory(
            self.window, QCoreApplication.translate("Nugget", "Select Directory"), "",
            QFileDialog.ShowDirsOnly)
        if not directory:
            return
        try:
            path = os.path.join(directory, f"Nugget-Export-{uuid.uuid4()}")
            tweaks[TweakID.PosterBoard].create_video_loop_files(output_dir=path)
            zip_path = path + ".tendies"
            make_archive(path, 'zip', path)
            os.rename(path + '.zip', zip_path)
            rmtree(path)
            print(f"Created at {zip_path}")
            if os.name == 'nt':
                subprocess.Popen(f'explorer "{os.path.normpath(zip_path)}"')
            else:
                subprocess.call(["open", '-R', zip_path])
        except Exception as e:
            QMessageBox.critical(
                self.window, QCoreApplication.translate("QtCore.QCoreApplication", "Error!"),
                type(e).__name__ + ": " + repr(e))

    def on_discover_wallpapers(self):
        self.open_wallpaper_downloader()

    def open_wallpaper_downloader(self):
        """Open the in-app wallpaper downloader (Cowabunga + CaPlayground)."""
        from src.gui.dialogs.wallpaper_downloader import WallpaperDownloaderDialog
        dialog = WallpaperDownloaderDialog(self.window, self)
        dialog.exec()

    def on_help(self):
        from src.gui.dialogs import PBHelpDialog
        dialog = PBHelpDialog()
        dialog.exec()

    def show_add_tendies_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        selected_files, _ = QFileDialog.getOpenFileNames(
            self.window, QCoreApplication.translate("Nugget", "Select PosterBoard Files"), "", "Zip Files (*.tendies)"
        )
        if selected_files:
            for file in selected_files:
                if not tweaks[TweakID.PosterBoard].add_tendie(file):
                    break
            self.refresh_tendies()

    def refresh_tendies(self):
        # stop preview downloads for the cards we are about to destroy
        for reply, *_ in self._tendie_preview_replies:
            reply.abort()
        self._tendie_preview_replies = []

        # Clear existing grid except download and add cards
        keep = (self.add_tendies_card, self.download_card)
        for i in reversed(range(self.tendies_grid.count())):
            widget = self.tendies_grid.itemAt(i).widget()
            if widget and widget not in keep:
                widget.deleteLater()

        tendies = tweaks[TweakID.PosterBoard].tendies
        if not tendies:
            # Ensure download card + add card are the only items
            self.tendies_grid.addWidget(self.download_card, 0, 0, 1, 2)
            self.tendies_grid.addWidget(self.add_tendies_card, 1, 0)
            return

        row = 1
        col = 0
        for tendie in tendies:
            card = self._create_tendie_card(tendie)
            self.tendies_grid.addWidget(card, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1

        # Add the add card at the end
        self.tendies_grid.addWidget(self.add_tendies_card, row, col)

    def _create_tendie_card(self, tendie) -> QWidget:
        card = IOSCard()
        card.setFixedSize(140, 160)
        card.setCursor(Qt.PointingHandCursor)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(8, 8, 8, 8)
        inner.setSpacing(8)
        inner.setAlignment(Qt.AlignTop)

        # Icon from tendie
        icon = QLabel()
        icon.setFixedSize(80, 80)
        icon.setAlignment(Qt.AlignCenter)
        try:
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(tendie.get_icon())
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                icon.setStyleSheet("background-color: #2C2C2E; border-radius: 10px;")
        except Exception:
            icon.setStyleSheet("background-color: #2C2C2E; border-radius: 10px;")
        inner.addWidget(icon, 0, Qt.AlignCenter)

        # Load real preview image by matching the tendie's name against the
        # cached wallpaper catalogs (falls back to the generic icon above).
        self._load_tendie_preview_by_name(card, icon, tendie.name)

        # Name
        name = QLabel(tendie.name.replace(".tendies", ""))
        name.setStyleSheet("font-size: 13px; color: #8E8E93; text-align: center;")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        inner.addWidget(name)

        # Delete button
        del_btn = QToolButton()
        del_btn.setIconSize(QSize(20, 20))
        from PySide6.QtGui import QIcon
        del_btn.setIcon(QIcon(":/icon/trash.svg"))
        del_btn.setStyleSheet(
            "QToolButton { background-color: #1C1C1E; border-radius: 12px; color: #FF3B30; padding: 8px; }"
            "QToolButton:hover { background-color: #FF3B30; color: white; }"
        )
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: self._delete_tendie(tendie))
        inner.addWidget(del_btn, 0, Qt.AlignCenter)

        return card

    # --- tendie preview by name ---

    def _load_tendie_preview_by_name(self, card, icon_lbl, file_name):
        try:
            from src.controllers.wallpaper_api import (
                find_wallpaper_by_name, cached_preview_path,
            )
            wp = find_wallpaper_by_name(file_name)
        except Exception:
            return
        if wp is None:
            return
        path = cached_preview_path(wp.preview_url)
        if os.path.exists(path):
            self._set_tendie_thumbnail(icon_lbl, path)
            return
        reply = self._tendie_nam.get(QNetworkRequest(QUrl(wp.preview_url)))
        self._tendie_preview_replies.append((reply, card, icon_lbl, path))
        reply.finished.connect(
            lambda r=reply, c=card, il=icon_lbl, p=path:
                self._on_tendie_preview(r, c, il, p))

    def _on_tendie_preview(self, reply, card, icon_lbl, path):
        self._tendie_preview_replies = [
            (r, c, i, p) for (r, c, i, p) in self._tendie_preview_replies
            if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError or not data:
            return
        if not self._widget_is_valid(icon_lbl):
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return
        self._set_tendie_thumbnail(icon_lbl, path)

    def _set_tendie_thumbnail(self, icon_lbl, path):
        if not self._widget_is_valid(icon_lbl):
            return
        try:
            image = QImageReader(path).read()
            pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap(path)
            if pixmap.isNull():
                return
            # square cover: expand to fill 80x80, then center-crop
            scaled = pixmap.scaled(
                80, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - 80) // 2
            y = (scaled.height() - 80) // 2
            icon_lbl.setPixmap(scaled.copy(x, y, 80, 80))
        except Exception:
            pass

    def _widget_is_valid(self, widget) -> bool:
        import shiboken6
        try:
            return shiboken6.isValid(widget)
        except RuntimeError:
            return False

    def _delete_tendie(self, tendie):
        from src.tweaks.tweaks import tweaks, TweakID
        if tendie in tweaks[TweakID.PosterBoard].tendies:
            tweaks[TweakID.PosterBoard].tendies.remove(tendie)
        self.refresh_tendies()

    def _reset_posterboard(self):
        """Show dialog to schedule a PosterBoard reset.

        Reuses the existing reset mechanism (tweaks[PosterBoard].resetModes)
        that the classic UI's Reset dropdown drives — this only adds the
        iOS-style dialog, it does not duplicate the reset logic itself.
        """
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox, QMessageBox,
        )

        dialog = QDialog(self.window)
        dialog.setWindowTitle(QCoreApplication.translate("Nugget", "Reset PosterBoard"))
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QCheckBox { color: #FFFFFF; font-size: 14px; spacing: 8px; }
            QCheckBox::indicator { width: 20px; height: 20px; }
            QDialogButtonBox QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                padding: 10px 20px;
                border: none;
                min-width: 80px;
            }
            QDialogButtonBox QPushButton:hover { background-color: #0056CC; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Select what to reset. This is useful if PosterBoard is behaving "
            "strangely or the database is corrupted (malformed) after a restore."
        ))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8E8E93; font-size: 13px;")
        layout.addWidget(desc)

        reset_collections = QCheckBox(QCoreApplication.translate("Nugget", "Collections"))
        reset_collections.setChecked(True)
        layout.addWidget(reset_collections)

        reset_suggested = QCheckBox(QCoreApplication.translate("Nugget", "Suggested Photos"))
        reset_suggested.setChecked(True)
        layout.addWidget(reset_suggested)

        reset_gallery = QCheckBox(QCoreApplication.translate("Nugget", "Gallery Cache"))
        reset_gallery.setChecked(True)
        layout.addWidget(reset_gallery)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec() == QDialog.Accepted:
            selected = []
            if reset_collections.isChecked():
                selected.append("Collections")
            if reset_suggested.isChecked():
                selected.append("Suggested Photos")
            if reset_gallery.isChecked():
                selected.append("Gallery Cache")
            tweaks[TweakID.PosterBoard].resetModes = selected
            QMessageBox.information(
                self.window,
                QCoreApplication.translate("Nugget", "Reset Scheduled"),
                QCoreApplication.translate(
                    "Nugget",
                    "PosterBoard reset has been scheduled. The selected items "
                    "will be cleared on the next apply. Apply your tweaks to "
                    "execute the reset.")
            )
