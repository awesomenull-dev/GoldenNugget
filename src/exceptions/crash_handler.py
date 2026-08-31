"""Global crash handler for the GoldenNugget GUI.

Catches uncaught Python exceptions and surfaces them in a non-fatal dialog so
the user can either copy the error (for a bug report) or dismiss it and keep
working without losing the current session.

Two entry points are hooked:

* ``sys.excepthook`` — for exceptions that escape the interpreter (outside the
  Qt event loop).
* ``QApplication.notify`` (via :class:`CrashHandlerApp`) — for exceptions
  raised inside Qt event handlers / slots, which PySide6 otherwise lets die
  silently after a printed traceback.

Use :func:`install_crash_handler` once at startup and
:class:`CrashHandlerApp` instead of a bare ``QApplication``.
"""

import sys
import traceback
import logging
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit

logger = logging.getLogger("GoldenNugget.crash")


def _app_name() -> str:
    return QCoreApplication.applicationName() or "GoldenNugget"


def _format_error(exc_type, exc_value, exc_tb) -> str:
    """Return ``(short_summary, full_traceback)`` for the given exception."""
    try:
        summary = f"{exc_type.__name__}: {exc_value}"
    except Exception:
        summary = f"{exc_type.__name__}"
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return summary, tb


class CrashDialog(QDialog):
    """Modal dialog showing a crash with 'Copy Error' and 'Continue' buttons."""

    def __init__(self, parent: Optional[QObject] = None,
                 summary: str = "", traceback_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"{_app_name()} - Unexpected Error")
        self.setModal(True)
        self.resize(560, 360)

        self._traceback_text = traceback_text

        layout = QVBoxLayout(self)

        heading = QLabel(
            "An unexpected error occurred. You can copy the details and "
            "continue working, or close the application.")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(summary_label)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlainText(traceback_text)
        self._details.setPlaceholderText("No traceback details available.")
        layout.addWidget(self._details, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        copy_btn = QPushButton("Copy Error")
        copy_btn.clicked.connect(self._copy)
        buttons.addWidget(copy_btn)

        continue_btn = QPushButton("Continue")
        continue_btn.setDefault(True)
        continue_btn.clicked.connect(self.accept)
        buttons.addWidget(continue_btn)

        layout.addLayout(buttons)

    def _copy(self):
        QApplication.clipboard().setText(self._traceback_text)

    def exec(self) -> int:
        return super().exec()


def _show_crash_dialog(summary: str, traceback_text: str):
    """Show the crash dialog on the main thread, if a QApplication exists."""
    app = QApplication.instance()
    if app is None:
        # No application yet — fall back to printing so nothing is lost.
        print(f"CRASH: {summary}\n{traceback_text}", file=sys.stderr)
        return
    dialog = CrashDialog(summary=summary, traceback_text=traceback_text)
    dialog.exec()


def _handle_crash(exc_type, exc_value, exc_tb):
    summary, tb = _format_error(exc_type, exc_value, exc_tb)
    if exc_type is not KeyboardInterrupt:
        logger.error("Uncaught exception: %s\n%s", summary, tb)
    try:
        _show_crash_dialog(summary, tb)
    except Exception:
        # Never let the crash handler itself crash the app.
        print(f"CRASH: {summary}\n{tb}", file=sys.stderr)


def _excepthook(exc_type, exc_value, exc_tb):
    # Only swallow ordinary exceptions; KeyboardInterrupt should still exit.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _handle_crash(exc_type, exc_value, exc_tb)


class CrashHandlerApp(QApplication):
    """QApplication subclass that routes Qt event-handler exceptions to the
    crash handler instead of silently printing and dropping them."""

    def notify(self, receiver: QObject, event: QEvent) -> bool:
        try:
            return super().notify(receiver, event)
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            _handle_crash(exc_type, exc_value, exc_tb)
            return False


def install_crash_handler():
    """Install the global uncaught-exception handler.

    Call once before ``QApplication`` is created. The dialog is only shown once
    an application instance exists; exceptions raised before then are logged
    and printed.
    """
    sys.excepthook = _excepthook
    # Sys.unraisablehook catches errors in __del__ / finalizers, which would
    # otherwise be reported to stderr and might quietly abort cleanup.
    try:
        import warnings

        def _unraisable(unraisable):
            summary = f"{unraisable.exc_type.__name__}: {unraisable.exc_value}"
            warnings.warn(
                f"Unraisable exception in GoldenNugget: {summary}",
                RuntimeWarning,
                stacklevel=2,
            )

        sys.unraisablehook = _unraisable
    except Exception:
        pass
