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
print("[init] CrashHandler installed")


def _current_ios(dm) -> tuple:
    """(version, model) of the currently selected device, or (None, None)."""
    try:
        version = dm.get_current_device_version()
        model = dm.get_current_device_model()
        return (version or None, model or None)
    except Exception:
        return (None, None)


def _show_kill_message(kill) -> None:
    """Present the remote kill reason to the user before shutting down."""
    tr = lambda s: QCoreApplication.translate("Nugget", s)
    reason = str(kill.get("reason")
                 or tr("This version of iOS is currently not supported."))
    print(f"[init] HotLoad: BLOCKED - {reason}", flush=True)
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(tr("GoldenNugget Disabled"))
    box.setText(tr("GoldenNugget has been disabled by its safety rules."))
    box.setInformativeText(reason)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _hotload_kill_or_none(dm, hotload):
    """Return the active kill rule for the current iOS, or None."""
    version, model = _current_ios(dm)
    try:
        return hotload.kill_rule(version, model)
    except Exception:
        return None


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

    from src.controllers.nugget_logger import init_logging, log_banner
    init_logging()
    log_banner()

    app = CrashHandlerApp([])

    # Force a dark theme matching the Nugget style on every platform, so the
    # app always renders dark regardless of the OS appearance. The Fusion style
    # is required for a custom QPalette to take effect on all platforms (native
    # styles ignore palette tweaks), and the palette covers native widgets,
    # menus, tooltips, dialogs and any widget without an explicit stylesheet.
    app.setStyle("Fusion")
    from PySide6.QtGui import QColor, QPalette
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 32))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 27))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 38))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(30, 30, 32))
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 100, 100))
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(0, 122, 255))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 122, 255))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(120, 120, 120))
    app.setPalette(dark_palette)

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

    # Init chain: CrashHandler -> HotLoad -> GoldenNugget.
    # HotLoad is consulted right here, using the cached local rules, BEFORE the
    # GUI is built. If a remote rule kills the app on this iOS version, we do
    # NOT initialize the window at all — GoldenNugget refuses to start.
    from src.controllers.hotload import HotLoad
    hotload = HotLoad(settings)
    print("[init] HotLoad: checking safety rules...")
    kill = _hotload_kill_or_none(dm, hotload)
    if kill:
        logger.warning("GoldenNugget disabled by HotLoad rules: %s", kill.get("reason"))
        _show_kill_message(kill)
        return 0
    print("[init] HotLoad ok")

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

    # HotLoad: refresh the remote safety rules in the background every launch,
    # and watch for a kill rule to become active while the app is already
    # running. Local caching means applications still use whatever is on disk
    # even if this fetch fails, and it never blocks startup.
    try:
        import threading

        def _watchdog_kill(quiet=True):
            """If a kill rule now applies to the current iOS, terminate the
            running app like a crash (force shutdown, no graceful exit).
            """
            kill = _hotload_kill_or_none(dm, hotload)
            if kill:
                reason = kill.get("reason")
                logger.critical("GoldenNugget killed by HotLoad rules while running: %s", reason)
                print(f"[watchdog] HotLoad: KILLED - {reason}", flush=True)
                if not quiet:
                    _show_kill_message(kill)
                # aborts the GTK/Qt main loop externally — mimics a crash exit.
                os._exit(1)

        def _refresh_hotload():
            try:
                changed = hotload.update()
                if changed:
                    _watchdog_kill(quiet=False)
            except Exception as e:
                logger.debug("HotLoad update failed: %s", e)

        threading.Thread(target=_refresh_hotload, daemon=True).start()

        # Periodic re-check so a kill published after launch still takes the
        # app down even if the refresh thread was skipped or failed.
        from PySide6.QtCore import QTimer
        _kill_timer = QTimer()
        _kill_timer.setInterval(5000)
        _kill_timer.timeout.connect(_watchdog_kill)
        _kill_timer.start()
        app._hotload_kill_timer = _kill_timer  # keep a strong reference
    except Exception as e:
        logger.debug("HotLoad startup check skipped: %s", e)

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