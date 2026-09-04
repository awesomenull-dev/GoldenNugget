from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import QMessageBox
import traceback

from src.gui.thread_workers.apply_worker import ApplyAlertMessage


class PBDBThread(QThread):
    progress = Signal(float)
    infoLbl = Signal(str)
    alert = Signal(object)  # ApplyAlertMessage

    def update_label(self, txt: str):
        self.infoLbl.emit(txt)
    def update_progress(self, amt: float):
        self.progress.emit(amt)
    def alert_window(self, msg: ApplyAlertMessage):
        self.alert.emit(msg)
    
    def __init__(self, backup_function):
        super().__init__()
        self.backup_function = backup_function

    def do_work(self):
        self.backup_function(self.update_label, self.update_progress)

    def run(self):
        try:
            self.do_work()
        except Exception as e:
            import logging
            logging.getLogger("GoldenNugget.pb").error(
                "PosterBoard backup failed: %s\n%s", e, traceback.format_exc())
            self.infoLbl.emit("Backup Failed!")
            self.alert.emit(ApplyAlertMessage(
                f"Backup failed: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback.format_exc(),
                exc_type=type(e),
                exc_value=e,
            ))