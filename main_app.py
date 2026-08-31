import sys
import os
import multiprocessing
import runpy
import warnings
import traceback
import logging

# Add src/qt to path so resources_rc can be found
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "qt"))

# 1. SILENCE WARNINGS
warnings.filterwarnings("ignore")

# Silence noisy Qt Wayland textinput logs (zwp_text_input_v3_leave spam)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false")

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QCoreApplication

from src.controllers.translator import Translator
from src.controllers.settings import Settings
from src.gui.main_window import MainWindow
from src.devicemanagement.device_manager import DeviceManager
from src.tweaks.tweaks import tweaks, TweakID
from src.gui.logger import setup_logging, get_logger
from src.exceptions.crash_handler import install_crash_handler, CrashHandlerApp

# Install the global crash handler as early as possible so any uncaught
# exception during startup is also captured instead of silently killing the app.
install_crash_handler()


def main() -> int:
    """GUI + fallback CLI dispatcher entry point (importable for the wrapper)."""

    # 2. CLI DISPATCHER
    if len(sys.argv) > 1:
        if '-m' in sys.argv:
            try:
                m_index = sys.argv.index('-m')
                # Args: [module_name, arg1, arg2...]
                sys.argv = sys.argv[m_index+1:]
                module_name = sys.argv[0]

                try:
                    # Attempt 1: Run standard module
                    runpy.run_module(module_name, run_name="__main__", alter_sys=True)
                except ImportError as e:
                    # Attempt 2: Handle "is a package" error by targeting __main__ explicitly
                    if "cannot be directly executed" in str(e) or "No module named" in str(e):
                        runpy.run_module(f"{module_name}.__main__", run_name="__main__", alter_sys=True)
                    else:
                        raise
            except Exception as e:
                # Print error to stderr so the main process can read it
                sys.stderr.write(f"Background Process Crash: {e}\n")
                traceback.print_exc()
            sys.exit()

        first_arg = sys.argv[1]
        if first_arg.endswith('.py') and not first_arg.lower().endswith(('.tendies', '.batter')):
            sys.argv = sys.argv[1:]
            try:
                runpy.run_path(sys.argv[0], run_name="__main__")
            except Exception as e:
                sys.stderr.write(f"Script Crash: {e}\n")
                traceback.print_exc()
            sys.exit()

    # 3. GUI STARTUP
    print("Starting GoldenNugget...")

    if "--test-mode" in sys.argv:
        print("TEST MODE ENABLED: Mock device will be created")

    # Setup logging
    log_file = os.environ.get("GOLDENNUGGET_LOG_FILE")
    if "--debug" in sys.argv:
        setup_logging(log_file, logging.DEBUG, capture_pymobiledevice3=True)
    else:
        setup_logging(log_file)

    logger = get_logger(__name__)
    logger.info("Starting GoldenNugget")

    from src.controllers.nugget_logger import init_logging
    init_logging()

    app = CrashHandlerApp([])
    dm = DeviceManager()

    # Test mode: create mock device
    if "--test-mode" in sys.argv:
        from src.devicemanagement.constants import Device
        mock_device = Device(
            udid=0x1234567890ABCDEF,
            usb=True,
            name="Test iPhone 15 Pro",
            version="27.0",
            build="21A5284a",
            model="iPhone15,3",
            hardware="D84AP",
            cpu="t8140",
            locale="en_US"
        )
        mock_device_2 = Device(
            udid=0x1122334455667788,
            usb=True,
            name="Test iPhone 16",
            version="26.6",
            build="26G96",
            model="iPhone17,3",
            hardware="D59AP",
            cpu="t8140",
            locale="en_US"
        )
        dm.data_singleton.current_device = mock_device
        dm.data_singleton.device_available = True
        dm.devices.append(mock_device)
        dm.devices.append(mock_device_2)
        dm.current_device_index = 0
        logger.info("Test mode: Mock devices created")

    QCoreApplication.setOrganizationDomain("com.leemin")
    QCoreApplication.setApplicationName("GoldenNugget")
    settings = Settings("settings")
    translator = Translator(app, settings)
    translator.set_default_locale(translator.get_saved_locale_code())
    translator.load_translations()

    icon_path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "nugget.ico")
    app.setWindowIcon(QtGui.QIcon(icon_path))

    # Restore the preset that was loaded right before the app restarted (pages
    # read the tweak state only once on startup, so the preset must be applied
    # before the window is created). The marker is cleared once applied.
    last_loaded_preset = settings.value("last_loaded_preset", "", type=str)
    if last_loaded_preset:
        try:
            from src.controllers.preset_manager import PresetManager
            if PresetManager().load_preset(last_loaded_preset):
                logger.info("Restored preset: %s", last_loaded_preset)
        except Exception as e:
            logger.error("Failed to restore preset '%s': %s", last_loaded_preset, e)
        finally:
            settings.setValue("last_loaded_preset", "")
            settings.sync()

    widget = MainWindow(device_manager=dm, translator=translator)
    translator.fix_ui_for_rtl(widget.ui)
    widget.resize(800, 600)
    widget.show()

    for arg in sys.argv:
        if arg.endswith('.tendies'):
            tweaks[TweakID.PosterBoard].add_tendie(arg)
        elif arg.endswith('.batter'):
            tweaks[TweakID.Templates].add_template(arg)

    logger.info("GoldenNugget launched.")
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())