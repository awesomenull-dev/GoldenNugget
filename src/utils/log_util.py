"""Lightweight log helpers for warm-path modules.

Keep this module stdlib-only: it sits on the tweak-import chain, which must
stay free of the pymobiledevice3 stack (see src/restore/__init__.py).
"""
import logging

_logger = logging.getLogger("GoldenNugget.protective")


def log_info(msg: str) -> None:
    """Log an info message through the session logger."""
    _logger.info(msg)


def log_warn(msg: str) -> None:
    """Log a warning through the session logger."""
    _logger.warning(msg)


def log_error(msg: str) -> None:
    """Log an error through the session logger."""
    _logger.error(msg)