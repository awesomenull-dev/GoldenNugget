import asyncio
import sqlite3

from src.restore.protective import _validate_sqlite_db


from PySide6.QtWidgets import QWizard, QWizardPage, QLabel, QVBoxLayout, QProgressBar, QSizePolicy, QCheckBox, QMessageBox
from PySide6.QtCore import QSize, Qt, QStandardPaths

from os import path, makedirs
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
from shutil import rmtree

from src.devicemanagement.session import lockdown_session
from src.restore.protective import check_disk_space_for_backup

from src.exceptions.nugget_exception import NuggetException
from src.devicemanagement.constants import is_supported_by_fork
from src.gui.thread_workers.apply_worker import ApplyAlertMessage
from src.gui.thread_workers.pb_worker import PBDBThread
from src.tweaks.tweaks import tweaks, TweakID


async def backup_posterboard_database(udid: str, update_label=lambda x: None, update_progress=lambda x: None) -> str:
    """Back up the device and return the extracted PosterBoard sqlite db path."""
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.exceptions.device_errors import is_connection_error as _is_connection_error

    app_data_path = path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), 'Backups')
    if not path.exists(app_data_path):
        makedirs(app_data_path)
    backup_folder = path.join(app_data_path, udid)
    # check if a full backup is needed (makes it faster)
    needs_full = False
    if path.exists(backup_folder):
        files_to_verify = ["Info.plist", "Manifest.db", "Manifest.plist", "Status.plist"]
        for file in files_to_verify:
            if not path.exists(path.join(backup_folder, file)):
                needs_full = True
                break

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        async with lockdown_session(udid) as service_provider:
            if attempt == 1:
                await check_disk_space_for_backup(service_provider, path=app_data_path)
            # hard-block fetching the database from an unsupported (old) iOS version
            if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                raise NuggetException(
                    "This version of iOS is not supported by this fork.\n\n"
                    "GoldenNugget only supports iOS 26.2 and newer. "
                    "Please use the original Nugget for iOS 26.1 and earlier.")
            try:
                async with Mobilebackup2Service(service_provider) as backup_client:
                    await backup_client.backup(full=needs_full, backup_directory=app_data_path, progress_callback=update_progress)
            except Exception as e:
                if _is_device_locked_error(e):
                    raise NuggetException("Device locked during backup. Please unlock your device, keep it awake (tap screen periodically), and try again.")
                if _is_connection_error(e) and attempt < max_retries:
                    delay = min(2 ** attempt, 15)
                    update_label(f"Connection lost, retrying in {delay}s... (attempt {attempt}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                raise
            break  # Success
        # lockdown_session closes the connection safely on every path

    # get the file, reading the sqlite db first to get the file id
    update_label("Getting the file...")
    db_path = path.join(backup_folder, "Manifest.db")
    if not _validate_sqlite_db(db_path):
        raise NuggetException("Backup manifest (Manifest.db) is not a valid SQLite database. The backup may have failed or been interrupted.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # resolve by file name: the store dir's structure version varies by iOS
    cursor.execute(
        "SELECT fileID FROM Files WHERE domain = ? AND relativePath LIKE ? ORDER BY relativePath DESC",
        ("AppDomain-com.apple.PosterBoard",
         "%PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"))
    fileID = cursor.fetchone()
    conn.close()
    if fileID is None or len(fileID) == 0:
        raise NuggetException("Could not find sqlite database in the backup!")
    fileID = fileID[0]
    db_file_path = path.join(backup_folder, fileID[:2], fileID)
    if not path.exists(db_file_path):
        raise NuggetException("The database file doesn't exist!")
    return db_file_path

class PosterBoardDBWizard(QWizard):
    def __init__(self, udid: str, pbDBLbl: QLabel, update_savedIds_list=lambda x: None):
        super().__init__()
        self.udid = udid
        self.pbDBLbl = pbDBLbl
        self.backup_in_progress = False
        self.delete_backup_when_done = False
        self.backup_successful = False
        self.update_savedIds_list = update_savedIds_list

        # only show cancel and next/finish buttons
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setButtonLayout([QWizard.WizardButton.CancelButton, QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])

        # progress bar for the backup progress
        self.backupInfoLbl = QLabel("Please enter your password on your device to continue")
        self.progressBar = QProgressBar()
        sizePolicy = QSizePolicy()
        sizePolicy.setHeightForWidth(self.progressBar.sizePolicy().hasHeightForWidth())
        self.progressBar.setSizePolicy(sizePolicy)
        self.progressBar.setMinimumSize(QSize(250, 0))
        self.progressBar.setValue(0)
        self.progressBar.setAlignment(Qt.AlignCenter)

        self.addPage(self.createPage1())
        self.addPage(self.createBackupProgPage())
        self.addPage(self.createFinalPage())

        self.setWindowTitle("Fetch Database File")

    # PAGES
    def on_deleteBackupChk_toggled(self, enabled: bool):
        self.delete_backup_when_done = enabled
    def createPage1(self) -> QWizardPage:
        # information page telling the user about backing up
        page = QWizardPage()
        page.setTitle("Notice")
        message = QLabel("In order to get the file, Nugget needs to back up your device.")
        delBkLbl = QLabel("If you do not delete the backup, this process will be faster when getting the file again.")
        delBkChk = QCheckBox("Delete Backup When Complete")
        delBkChk.toggled.connect(self.on_deleteBackupChk_toggled)
        contLbl = QLabel("\nWould you like to continue?")
        layout = QVBoxLayout(page)
        layout.addWidget(message)
        layout.addWidget(delBkLbl)
        layout.addWidget(delBkChk)
        layout.addWidget(contLbl)
        page.setLayout(layout)
        return page
    
    def createFinalPage(self) -> QWizardPage:
        # just say whether backup was successful
        page = QWizardPage()
        page.setTitle("Backup Complete")
        message = QLabel("Successfully got the file")
        layout = QVBoxLayout(page)
        layout.addWidget(message)
        page.setLayout(layout)
        return page
    
    def createBackupProgPage(self) -> QWizardPage:
        # show the progress bar of the backup
        page = QWizardPage()
        page.setTitle("Backing Up Device...")
        layout = QVBoxLayout(page)
        layout.addWidget(self.backupInfoLbl)
        layout.addWidget(self.progressBar)
        page.setLayout(layout)
        return page
    
    def update_progress_bar(self, percent):
        print(f'backup progress: {percent}')
        if percent == 0.0:
            self.backupInfoLbl.setText("Preparing device for backup...")
        else:
            self.progressBar.setValue(int(percent))
            self.backupInfoLbl.setText(f'Backing up...  {percent:6.1f}%')

    def update_progress_lbl(self, txt: str):
        # hacky workaround
        if txt.startswith('sqlite'):
            self.pbDBLbl.setText(txt)
        else:
            self.backupInfoLbl.setText(txt)

    def finish_backup_thread(self):
        if self.backup_successful:
            self.update_savedIds_list()
            self.setButtonLayout([QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])
        self.backup_in_progress = False
        # self.next()

    def alert_message(self, msg: ApplyAlertMessage):
        if msg.detailed_txt:
            QMessageBox.critical(self, msg.title, f"{msg.txt}\n\n{msg.detailed_txt}")
        else:
            QMessageBox.critical(self, msg.title, msg.txt)
    
    def start_device_backup(self, update_label=lambda x: None, update_progress=lambda x: None):
        asyncio.run(self._start_device_backup(update_label, update_progress))
    async def _start_device_backup(self, update_label=lambda x: None, update_progress=lambda x: None):
        try:
            app_data_path = path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), 'Backups')
            backup_folder = path.join(app_data_path, self.udid)
            db_file_path = await backup_posterboard_database(self.udid, update_label, update_progress)
            if not tweaks[TweakID.PosterBoard].config_manager.update_database_file(db_file_path, self.udid):
                raise NuggetException("The database is not of the correct format!")
            update_label("sqlite: Selected")

            # delete backup files if wanted
            if self.delete_backup_when_done:
                update_label("Deleting backup...")
                rmtree(backup_folder)

            # re-enable next button
            self.backup_successful = True
            update_label("Success!") # TODO: Place this somewhere else so that we can call self.next()
            # self.setButtonLayout([QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])
        except Exception as e:
            update_label("Backup Failed!")
            print(repr(e))
    
    # OVERWRITTEN FUNCTIONS
    def initializePage(self, id):
        if id == 1:
            # start the backup
            # disable next button until backup is done
            self.setButtonLayout([QWizard.WizardButton.CancelButton, QWizard.WizardButton.Stretch])
            self.backup_in_progress = True
            self.worker_thread = PBDBThread(backup_function=self.start_device_backup)
            self.worker_thread.progress.connect(self.update_progress_bar)
            self.worker_thread.infoLbl.connect(self.update_progress_lbl)
            self.worker_thread.alert.connect(self.alert_message)
            self.worker_thread.finished.connect(self.finish_backup_thread)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.start()
        return super().initializePage(id)