from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea
)

from src.gui.ios.components import IOSSectionHeader, IOSCard, IOSPrimaryButton


class IOSApplyPage(QWidget):
    """Apply / Remove tweaks — rebuilt from the classic Apply page using the
    iOS-style components."""
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
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 32)
        content_layout.setSpacing(8)

        # --- Apply ---
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Apply Tweaks")))

        apply_card = IOSCard()
        apply_layout = QVBoxLayout(apply_card)
        apply_layout.setContentsMargins(16, 12, 16, 12)
        apply_layout.setSpacing(8)

        apply_desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Applies every enabled tweak to your device. The device reboots "
            "when done — remember to turn Find My back on afterwards."))
        apply_desc.setWordWrap(True)
        apply_desc.setStyleSheet("color: #8E8E93; font-size: 13px;")
        apply_layout.addWidget(apply_desc)

        self.apply_btn = IOSPrimaryButton(QCoreApplication.translate(
            "Nugget", "Apply Tweaks"))
        self.apply_btn.clicked.connect(self.window.apply_tweaks_clicked)
        apply_layout.addWidget(self.apply_btn)
        content_layout.addWidget(apply_card)

        # --- Remove ---
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Remove Tweaks")))

        remove_card = IOSCard()
        remove_layout = QVBoxLayout(remove_card)
        remove_layout.setContentsMargins(16, 12, 16, 12)
        remove_layout.setSpacing(8)

        remove_desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Restores the original values for the tweak pages you pick."))
        remove_desc.setWordWrap(True)
        remove_desc.setStyleSheet("color: #8E8E93; font-size: 13px;")
        remove_layout.addWidget(remove_desc)

        self.remove_btn = IOSPrimaryButton(QCoreApplication.translate(
            "Nugget", "Remove Tweaks"))
        self.remove_btn.clicked.connect(self.window.remove_tweaks_clicked)
        remove_layout.addWidget(self.remove_btn)
        content_layout.addWidget(remove_card)

        # --- Progress status ---
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Progress")))

        status_card = IOSCard()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 12, 16, 12)
        status_layout.setSpacing(0)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #FFFFFF; font-size: 14px;")
        status_layout.addWidget(self.status_lbl)
        content_layout.addWidget(status_card)

        content_layout.addStretch()

    def set_status(self, text: str):
        self.status_lbl.setText(text or "")

    def set_busy(self, busy: bool):
        self.apply_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)