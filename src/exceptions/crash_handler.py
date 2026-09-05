"""Global crash handler for the GoldenNugget GUI.

Catches uncaught Python exceptions and surfaces them in a non-fatal dialog so
the user can either copy the details (with the recent session log) for a bug
report, open the log file, or dismiss it and keep working without losing the
current session.

Two entry points are hooked:

* ``sys.excepthook`` — for exceptions that escape the interpreter (outside the
  Qt event loop).
* ``QApplication.notify`` (via :class:`CrashHandlerApp`) — for exceptions
  raised inside Qt event handlers / slots, which PySide6 otherwise lets die
  silently after a printed traceback.

Apply/reset failures are routed through the same dialog: the worker threads
report them via :class:`ApplyAlertMessage`, and the main window opens
:func:`show_error_dialog` so the error is *parsed* exactly like a crash
(severity + likely cause + friendly text) and the same Copy/Report buttons are
available.

Use :func:`install_crash_handler` once at startup and
:class:`CrashHandlerApp` instead of a bare ``QApplication``.
"""

import sys
import traceback
import logging
import os
from typing import Callable, Optional
from urllib.parse import quote

from PySide6.QtCore import QCoreApplication, QObject, QEvent, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit

from src.controllers.nugget_logger import get_log_path, get_log_tail
from src.exceptions.device_errors import is_connection_error, is_device_locked_error

logger = logging.getLogger("GoldenNugget.crash")

ISSUES_URL = "https://github.com/awesomenull-dev/GoldenNugget/issues/new"


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


def _classify(exc_type, exc_value) -> dict:
    """Turn a caught exception into user-friendly metadata.

    Returns a dict with ``severity`` (Fatal/Serious/Moderate/Minor), ``fault``
    (approximate attribution) and ``friendly`` (a plain-language description).
    """
    try:
        name = getattr(exc_type, "__name__", "Error") or "Error"
    except Exception:
        name = "Error"
    msg = ""
    try:
        msg = str(exc_value)
    except Exception:
        pass
    try:
        module = getattr(exc_type, "__module__", "") or ""
    except Exception:
        module = ""

    # Defaults
    severity, fault, friendly = "Serious", "Unknown", f"An error occurred ({name})."

    # --- Device locked ---
    if is_device_locked_error(exc_value):
        severity, fault, friendly = "Moderate", "Your device", \
            "Your device is locked. Unlock it and keep it awake, then try again."
    # --- File / OS / user-data issues (subclasses of OSError, so they MUST be
    # checked before the generic connection/OSError branch below). ---
    elif issubclass(exc_type, FileNotFoundError):
        severity, fault, friendly = "Minor", "Your files or setup", \
            "GoldenNugget couldn't find a file or folder it needed."
    elif issubclass(exc_type, PermissionError):
        severity, fault, friendly = "Minor", "Your files or setup", \
            "GoldenNugget didn't have permission to access a file or folder."
    elif issubclass(exc_type, FileExistsError):
        severity, fault, friendly = "Minor", "Your files or setup", \
            "GoldenNugget tried to create something that already exists."
    elif issubclass(exc_type, (IsADirectoryError, NotADirectoryError)):
        severity, fault, friendly = "Minor", "Your files or setup", \
            "A file path was used as a folder (or a folder as a file)."
    # --- Device / connection ---
    elif is_connection_error(exc_value) or "terminated" in msg.lower():
        severity, fault, friendly = "Moderate", "Your device or connection", \
            "GoldenNugget couldn't communicate with your device."
    # --- Out of memory ---
    elif issubclass(exc_type, MemoryError):
        severity, fault, friendly = "Fatal", "Your computer", \
            "Your computer ran out of memory. Close some programs and try again."
    # --- App logic / programming errors ---
    elif name == "NuggetException" or module.startswith("src."):
        severity, fault, friendly = "Serious", "The app (GoldenNugget)", \
            "GoldenNugget hit an internal problem."
    elif issubclass(exc_type, (TypeError, ValueError, KeyError, IndexError,
                               AttributeError, ImportError, NameError, OSError)):
        severity, fault, friendly = "Serious", "The app (GoldenNugget)", \
            "GoldenNugget hit an internal problem."

    return {
        "severity": severity,
        "fault": fault,
        "friendly": friendly,
        "type_name": name,
    }


def _log_tail_for_report() -> str:
    """Recent session log tail, bounded, with a header line."""
    try:
        tail = get_log_tail(64 * 1024).rstrip("\n")
        if not tail:
            return ""
        return f"\n\n--- Recent session log ({get_log_path()}) ---\n{tail}"
    except Exception:
        return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[- (2 * limit) // 3:]
    return f"{head}\n... [log truncated ...]\n{tail}"


def _build_issue_body(info: dict, summary: str, traceback_text: str,
                      include_log: bool = True) -> str:
    """Assemble the text pasted into the prefilled GitHub issue."""
    try:
        from src.gui.version import App_Version
        version = str(App_Version)
    except Exception:
        version = "unknown"
    body = (
        "## GoldenNugget Error Report\n\n"
        f"**App version:** {version}\n"
        f"**Severity:** {info['severity']}\n"
        f"**Likely cause:** {info['fault']}\n\n"
        f"**What went wrong:**\n{info['friendly']}\n\n"
        f"**Error:** `{summary}`\n\n"
        "<details><summary>Technical details</summary>\n\n"
        "```\n" + _truncate(traceback_text, 16 * 1024) + "\n```\n\n"
        "</details>\n\n"
    )
    if include_log:
        log_tail = _log_tail_for_report()
        if log_tail:
            body += ("<details><summary>Session log</summary>\n\n"
                     "```\n" + _truncate(log_tail, 24 * 1024) +
                     "\n```\n\n</details>\n\n")
    body += "<!-- Please add any steps you took before this error appeared. -->"
    return body


def _build_issues_url(info: dict, summary: str, traceback_text: str) -> str:
    title = f"Error: {info['severity']} - {info['friendly']}"
    body = _build_issue_body(info, summary, traceback_text, include_log=True)
    return f"{ISSUES_URL}?title={quote(title)}&body={quote(body)}"


def _full_report(info: dict, summary: str, traceback_text: str) -> str:
    """The complete clipboard payload: report + traceback + session log."""
    report = _build_issue_body(info, summary, traceback_text, include_log=True)
    return report.replace("<!-- Please add any steps you took before this error appeared. -->",
                          "").rstrip()


class CrashDialog(QDialog):
    """Modal dialog showing a friendly error summary with 'Report on GitHub',
    'Copy Error', 'Open Log' and 'Continue' buttons.

    ``backup_path`` / ``on_restore`` make the dialog usable for apply failures
    where a protective backup is still on disk and can be restored.
    """

    def __init__(self, parent: Optional[QObject] = None,
                 summary: str = "", traceback_text: str = "", info: Optional[dict] = None,
                 backup_path: Optional[str] = None,
                 on_restore: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle(f"{_app_name()} - Detected an Error")
        self.setModal(True)
        self.resize(640, 480)

        self._traceback_text = traceback_text
        self._backup_path = backup_path
        self._on_restore = on_restore
        info = info or _classify(Exception, Exception())
        self._info = info

        layout = QVBoxLayout(self)

        heading = QLabel(
            "GoldenNugget detected an error. Here's what we know — you can "
            "report it to us, copy the details (with the session log), or "
            "continue working.")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        severity_label = QLabel(f"Severity: {info['severity']}")
        severity_label.setWordWrap(True)
        layout.addWidget(severity_label)

        fault_label = QLabel(f"Likely cause: {info['fault']}")
        fault_label.setWordWrap(True)
        layout.addWidget(fault_label)

        friendly_label = QLabel(info['friendly'])
        friendly_label.setWordWrap(True)
        friendly_label.setStyleSheet("color: #007AFF; font-style: italic;")
        layout.addWidget(friendly_label)

        self._searchable = QPlainTextEdit()
        self._searchable.setReadOnly(True)
        self._searchable.setPlainText(summary)
        self._searchable.setMaximumHeight(64)
        layout.addWidget(self._searchable)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlainText(traceback_text)
        self._details.setPlaceholderText("No technical details available.")
        layout.addWidget(self._details, 1)

        log_path_label = QLabel(f"Log: {get_log_path()}")
        log_path_label.setWordWrap(True)
        log_path_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(log_path_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        if self._backup_path:
            restore_btn = QPushButton("Restore data from backup")
            restore_btn.setToolTip(
                "Restore the protective backup from the failed apply to avoid "
                "data loss.")
            restore_btn.clicked.connect(self._restore)
            buttons.addWidget(restore_btn)

        report_btn = QPushButton("Report on GitHub")
        report_btn.setToolTip(
            "Copies the error details + session log and opens the issue "
            "tracker in your browser with a pre-filled report.")
        report_btn.clicked.connect(lambda: self._report(info, summary, traceback_text))
        buttons.addWidget(report_btn)

        copy_btn = QPushButton("Copy Error")
        copy_btn.setToolTip("Copies the full error report + session log to the clipboard.")
        copy_btn.clicked.connect(self._copy)
        buttons.addWidget(copy_btn)

        open_log_btn = QPushButton("Open Log")
        open_log_btn.setToolTip("Opens the session log file in your preferred text editor.")
        open_log_btn.clicked.connect(self._open_log)
        buttons.addWidget(open_log_btn)

        continue_btn = QPushButton("Continue")
        continue_btn.setDefault(True)
        continue_btn.clicked.connect(self.accept)
        buttons.addWidget(continue_btn)

        layout.addLayout(buttons)

    def _copy(self):
        QApplication.clipboard().setText(_full_report(self._info, self._searchable.toPlainText(),
                                                       self._traceback_text))

    def _open_log(self):
        path = get_log_path()
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _report(self, info: dict, summary: str, traceback_text: str):
        QApplication.clipboard().setText(_full_report(info, summary, traceback_text))
        url = _build_issues_url(info, summary, traceback_text)
        QDesktopServices.openUrl(QUrl(url))

    def _restore(self):
        cb = self._on_restore
        self.accept()
        if cb is not None:
            cb()

    def exec(self) -> int:
        return super().exec()


def show_error_dialog(summary: str, traceback_text: str, info: Optional[dict] = None,
                      backup_path: Optional[str] = None,
                      on_restore: Optional[Callable[[], None]] = None):
    """Show the crash/error dialog on the main thread, if a QApplication exists.

    Also used for apply/reset failures so they get parsed and reported exactly
    like uncaught exceptions.
    """
    app = QApplication.instance()
    if app is None:
        print(f"ERROR: {summary}\n{traceback_text}", file=sys.stderr)
        return
    dialog = CrashDialog(summary=summary, traceback_text=traceback_text,
                         info=info, backup_path=backup_path, on_restore=on_restore)
    dialog.exec()


def _show_crash_dialog(summary: str, traceback_text: str, exc_type=None, exc_value=None):
    """Show the crash dialog on the main thread, if a QApplication exists."""
    app = QApplication.instance()
    info = _classify(exc_type, exc_value) if exc_type is not None else None
    if app is None:
        # No application yet — fall back to printing so nothing is lost.
        print(f"CRASH: {summary}\n{traceback_text}", file=sys.stderr)
        return
    dialog = CrashDialog(summary=summary, traceback_text=traceback_text, info=info)
    dialog.exec()


def _handle_crash(exc_type, exc_value, exc_tb):
    summary, tb = _format_error(exc_type, exc_value, exc_tb)
    if exc_type is not KeyboardInterrupt:
        logger.error("Uncaught exception: %s\n%s", summary, tb)
    try:
        _show_crash_dialog(summary, tb, exc_type, exc_value)
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


def _detect_desktop() -> str:
    """Detect the current desktop environment."""
    if sys.platform == "linux":
        de = (os.environ.get("XDG_CURRENT_DESKTOP")
              or os.environ.get("XDG_SESSION_DESKTOP")
              or os.environ.get("DESKTOP_SESSION")
              or "unknown")
        session_type = os.environ.get("XDG_SESSION_TYPE") or "unknown"
        return f"{de} ({session_type})"
    elif sys.platform == "darwin":
        return "AppKit"
    elif sys.platform == "win32":
        return "Win32"
    else:
        return sys.platform


def print_startup_banner() -> None:
    """Print a startup info banner to the terminal."""
    try:
        from src.gui.version import App_Version, App_Build
        version_str = str(App_Version)
        beta_build = int(App_Build)
    except Exception:
        version_str = "unknown"
        beta_build = 0

    if beta_build > 0:
        version_str += f" (beta {beta_build})"

    frozen = getattr(sys, "frozen", False)
    run_env = "PyInstaller" if frozen else "generic"

    desktop = _detect_desktop()

    is_release = "yes" if (frozen and beta_build == 0) else "no"
    is_beta = "yes" if beta_build > 0 else "no"

    # Only reliable in the official GitHub Actions workspace;
    # always "yes" locally or on other repos.
    off_build = "no" if os.environ.get("GITHUB_ACTIONS") else "yes"

    print(f"GoldenNugget {version_str}")
    print(f"Running on: {sys.platform} ({run_env})")
    print(f"Desktop: {desktop}")
    print(f"IsRelease?: {is_release}")
    print(f"IsBeta?: {is_beta}")
    print(f"Off-Build?: {off_build}")


def install_crash_handler():
    """Install the global uncaught-exception handler.

    Call once before ``QApplication`` is created. The dialog is only shown once
    an application instance exists; exceptions raised before then are logged
    and printed.
    """
    print_startup_banner()
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