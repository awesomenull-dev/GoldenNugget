import logging
import sys

from src.controllers.nugget_logger import init_logging, get_log_path


def setup_logging(log_file: str = None, level: int = logging.INFO,
                  capture_pymobiledevice3: bool = False) -> logging.Logger:
    """Configure application-wide logging (idempotent).

    The rotating session file is owned by ``src.controllers.nugget_logger``
    (one handler, attached to the root AND the ``GoldenNugget`` logger), so the
    ``GOLDENNUGGET_LOG_FILE`` env var and the AppData default both feed the same
    file. This function only manages the console handler and verbosity levels.
    """
    import os
    if log_file:
        os.environ["GOLDENNUGGET_LOG_FILE"] = log_file
    init_logging()

    logger = logging.getLogger("GoldenNugget")
    logger.setLevel(level)
    logger.propagate = False

    # Clear only previously-added console handlers; keep the file handler that
    # nugget_logger attached to this logger.
    console_handlers = [h for h in logger.handlers
                        if isinstance(h, logging.StreamHandler)
                        and not isinstance(h, logging.FileHandler)]
    for h in console_handlers:
        logger.removeHandler(h)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    if capture_pymobiledevice3:
        from src.controllers.nugget_logger import get_file_handler
        pm3 = logging.getLogger("pymobiledevice3")
        pm3.setLevel(logging.DEBUG)
        pm3.propagate = False
        pm3_console = logging.StreamHandler(sys.stdout)
        pm3_console.setFormatter(console_formatter)
        pm3_console.setLevel(logging.DEBUG)
        # Keep the session file handler so debug lines still land in the log;
        # never replace handlers wholesale (that would drop the file handler).
        current = [h for h in pm3.handlers
                   if not isinstance(h, logging.FileHandler)]
        pm3.handlers = current + [get_file_handler(), pm3_console]

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance."""
    if name:
        return logging.getLogger(f"GoldenNugget.{name}")
    return logging.getLogger("GoldenNugget")


# Initialize default logger (console only, quiet) so import never crashes on
# logging before main() configures verbosity.
_logger = setup_logging(level=logging.WARNING)  # Quiet by default