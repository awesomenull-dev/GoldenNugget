from PySide6.QtCore import Qt, QCoreApplication, Signal as pyqtSignal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QDialog, QDialogButtonBox, QLineEdit, QSpinBox,
    QVBoxLayout,
)


class TextInputDialog(QDialog):
    """iOS-style text input dialog."""
    def __init__(self, title: str, current_value: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QLineEdit {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.input = QLineEdit()
        self.input.setText(current_value)
        self.input.setPlaceholderText(QCoreApplication.translate("TextInputDialog", "Enter value..."))
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        layout.addWidget(buttons)

    def get_value(self) -> str:
        return self.input.text()


class NumberInputDialog(QDialog):
    """iOS-style number input dialog."""
    def __init__(self, title: str, current_value: int = 0, min_val: int = 0, max_val: int = 999, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #FFFFFF; font-size: 15px; }
            QSpinBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 0; }
            QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.spin = QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(current_value)
        self.spin.setButtonSymbols(QSpinBox.NoButtons)
        self.spin.setStyleSheet("""
            QSpinBox {
                background-color: #1C1C1E;
                border: none;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                padding: 12px 16px;
            }
        """)
        layout.addWidget(self.spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_value(self) -> int:
        return self.spin.value()


class IOSSectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("iosSectionHeader")
        self.setProperty("cls", "iosSectionHeader")
        self.setStyleSheet("font-size: 13px; font-weight: 600; color: #8E8E93; text-transform: uppercase; letter-spacing: 0.5px; padding-left: 4px;")


class IOSCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("iosCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            IOSCard {
                background-color: #1C1C1E;
                border-radius: 12px;
                border: none;
            }
        """)
        # Don't create a default layout - let the caller decide


class IOSNavBar(QWidget):
    """Reusable navigation header.

    One shared instance lives in the main window and is reconfigured per
    page (title / back visibility / right action) instead of every page
    building its own. Safe to reconfigure any number of times — the layout
    structure is built once and only contents/visibility change.
    """
    def __init__(self, title: str = "", on_back=None, right_action=None,
                 window=None, parent=None):
        super().__init__(parent)
        self.setObjectName("iosNavBar")
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background-color: #1C1C1E; border-bottom: 1px solid #3A3A3C;")
        self._on_back = on_back or (window._go_back if hasattr(window, "_go_back") else None)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        # left padding keeps the title centered when the back button hides
        self._left_pad = QWidget(self)
        self._left_pad.setFixedWidth(90)
        layout.addWidget(self._left_pad)

        self.back_btn = QPushButton(QCoreApplication.translate("Nugget", "←  Back"), self)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #007AFF;
                font-size: 17px;
                font-weight: 400;
                border: none;
                padding: 8px 0;
            }
            QPushButton:hover { color: #0066CC; }
        """)
        self.back_btn.clicked.connect(self._handle_back)
        layout.addWidget(self.back_btn)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.title_lbl.setStyleSheet("font-size: 17px; font-weight: 600; color: #FFFFFF;")
        layout.addWidget(self.title_lbl, 1)

        # persistent right slot; contents are swapped per page
        self._right_box = QWidget(self)
        self._right_layout = QHBoxLayout(self._right_box)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.setSpacing(0)
        layout.addWidget(self._right_box)
        self._right_btn = None
        self._left_pad.setVisible(False)

    def set_title(self, title: str):
        self.title_lbl.setText(title)

    def set_back_visible(self, visible: bool):
        self.back_btn.setVisible(visible)
        # pad only when there is no button, so the title stays centered
        self._left_pad.setVisible(not visible)

    def set_right_action(self, label_text: str, callback):
        self._clear_right()
        btn = QPushButton(label_text, self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #007AFF;
                font-size: 15px;
                font-weight: 600;
                border: none;
                padding: 8px 0;
            }
            QPushButton:hover { color: #0066CC; }
        """)
        btn.clicked.connect(callback)
        self._right_layout.addWidget(btn)
        self._right_btn = btn

    def clear_right_action(self):
        self._clear_right()

    def _clear_right(self):
        if self._right_btn is not None:
            self._right_layout.removeWidget(self._right_btn)
            # detach immediately: deleteLater alone may outlive the caller's
            # processEvents pass, leaving a phantom button on screen
            self._right_btn.setParent(None)
            self._right_btn.deleteLater()
            self._right_btn = None

    def _handle_back(self):
        if self._on_back:
            self._on_back()


class IOSSettingsRow(QPushButton):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("iosSettingsRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setText(f"{title}  ›")
        self.setStyleSheet("""
            QPushButton {
                background-color: #1C1C1E;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                text-align: left;
                padding: 14px 16px;
                border: none;
            }
            QPushButton:hover { background-color: #2C2C2E; }
        """)


class IOSPrimaryButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("iosPrimaryButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self.setStyleSheet("""
            QPushButton {
                background-color: #007AFF;
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 17px;
                font-weight: 600;
                border: none;
            }
            QPushButton:hover { background-color: #0066CC; }
            QPushButton:pressed { background-color: #0055AA; }
            QPushButton:disabled { background-color: #3A3A3C; color: #8E8E93; }
        """)


class IOSSwitch(QPushButton):
    """iOS-style toggle switch"""
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(51, 31)
        self.setCursor(Qt.PointingHandCursor)
        self._knob = QLabel(self)
        self._knob.setFixedSize(27, 27)
        self._knob.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._knob.setStyleSheet("background-color: #FFFFFF; border-radius: 13px; border: none;")
        self.toggled.connect(self._update_style)
        self._update_style()

    def _update_style(self):
        checked = self.isChecked()
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {'#30D158' if checked else '#3A3A3C'};
                border-radius: 15px;
                border: none;
            }}
        """)
        self._knob.move(22 if checked else 2, 2)


class IOSValueLabel(QLabel):
    """Label showing current value in parentheses"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("color: #8E8E93; font-size: 14px;")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
