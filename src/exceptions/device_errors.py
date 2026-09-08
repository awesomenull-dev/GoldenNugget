"""Shared error classification for device backup/restore operations."""
import asyncio

import pymobiledevice3.exceptions as pm3_exc


def is_device_locked_error(exc: Exception) -> bool:
    """Check if an exception indicates the device is locked (ErrorCode 208)."""
    msg = str(exc)
    return "ErrorCode" in msg and ("208" in msg or "Device locked" in msg or "MBErrorDomain" in msg)


def is_connection_error(exc: Exception) -> bool:
    """Check if an exception is a transient connection failure worth retrying."""
    msg = str(exc).lower()
    return isinstance(exc, (
        pm3_exc.ConnectionTerminatedError,
        ConnectionError,
        OSError,
        asyncio.TimeoutError,
    )) or "connection" in msg or "incomplete" in msg or "terminated" in msg


def is_transient_restore_error(error) -> bool:
    """True for Phase 3 errors that mean 'device still booting, try again'."""
    name = type(error).__name__
    msg = str(error)
    # ssl.SSLError subclasses OSError, so this covers SSL drops too.
    if isinstance(error, (pm3_exc.ConnectionTerminatedError, OSError)):
        return True
    if "InvalidService" in name:
        return True
    if "NotEnoughDiskSpace" in str(error):
        return True  # device-side purge request — retry after cleanup
    # MBErrorDomain/1: SpringBoard not ready for a restore yet.
    if "SpringBoard" in msg and "ready for a restore" in msg:
        return True
    return "start" in msg.lower() and "service" in msg.lower()
