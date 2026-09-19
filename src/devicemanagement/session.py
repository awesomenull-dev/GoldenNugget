"""Single entry point for opening lockdown connections.

Every device conversation should use ``lockdown_session`` so connections are
always closed safely (a rebooted device makes ``close()`` raise, which must
never mask the real result).

Trust/pairing: ``create_using_usbmux`` runs with ``autopair=True`` — when the
host has no (valid) pairing record for the device, lockdownd shows the
"Trust This Computer?" dialog on the device and the call blocks until the user
taps Trust (or the ``pair_timeout`` expires). A client is only yielded once
``ld.paired`` is true, so service starts (ATC sync, AFC, mobilebackup2) can
never hit a silently-unpaired state.
"""
from contextlib import asynccontextmanager
from typing import Optional

from pymobiledevice3.exceptions import NotPairedError
from pymobiledevice3.lockdown import create_using_usbmux


@asynccontextmanager
async def lockdown_session(serial: Optional[str] = None, *,
                           autopair: bool = True,
                           pair_timeout: Optional[float] = 120.0):
    """Open a lockdown connection to the device and close it safely on exit.

    :param serial: usbmux serial of the device (``None`` = first available).
    :param autopair: request the on-device "Trust This Computer?" dialog when
        the host is not (or no longer) paired with the device.
    :param pair_timeout: seconds to wait for the user to accept the trust
        dialog; ``None`` waits forever.
    """
    ld = await create_using_usbmux(
        serial=serial, autopair=autopair, pair_timeout=pair_timeout)
    try:
        if autopair and not getattr(ld, "paired", False):
            # lockdownd accepted the pair request but the session did not
            # validate — treat it as unpaired so no caller reaches a
            # half-trusted client (its service starts would raise later).
            raise NotPairedError("device did not confirm trust")
        yield ld
    finally:
        try:
            await ld.close()
        except Exception:
            pass