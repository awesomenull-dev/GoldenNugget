"""Backend -> GUI alert/result message (Qt-free shared type).

``src.gui.thread_workers.apply_worker`` re-exports this class so every existing
``from src.gui.thread_workers.apply_worker import ApplyAlertMessage`` keeps
working; the backend apply/reset path imports it here instead of from the GUI
package.

``icon`` is an opaque renderer tag: GUI callers pass a ``QMessageBox.Icon``,
the backend leaves it ``None`` (meaning "default"/error, which the GUI renders
as ``QMessageBox.Critical``).
"""


class ApplyAlertMessage:
    def __init__(self, txt: str, title: str = "Error!", icon=None,
                 detailed_txt: str = None, backup_path: str = None,
                 exc_type: type = None, exc_value: BaseException = None):
        self.txt = txt
        self.title = title
        self.icon = icon
        self.detailed_txt = detailed_txt
        self.backup_path = backup_path
        self.exc_type = exc_type
        self.exc_value = exc_value