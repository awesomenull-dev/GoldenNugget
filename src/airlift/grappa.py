"""macOS Grappa token for AirLift (ATC) sync.

The ATC daemon on iOS 27 requires a "Grappa" blob in HostInfo/RequestingSync.
On macOS the genuine token is produced at runtime by Apple's private framework
(CoreFP -> AirTrafficDevice / AirTrafficHost).  This module mirrors the flow
published in the AirCard project (ios-app/GrappaHelper.m): build an
ATGrappaSession of host type and ask it for clientRequestData for the device
the daemon announced (version=1, deviceType=0, protocolVersion=1).

AirLift sync is therefore macOS-only for the token path -- on any other
platform there is no Apple runtime that can speak Grappa.  A table of
*authentic* CoreFP tokens for exactly the (1,0,1) combo is kept available so a
developer can probe whether some daemon accepts a static token via the
GOLDENNUGGET_ATC_GRAPPA env override (see airlift/__init__.py).
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Optional

logger = logging.getLogger("GoldenNugget.airlift.grappa")


# From AirCard ios-app/GrappaHelper.m: authentic Grappa client tokens produced
# by Apple's CoreFP for (version=1, deviceType=0, protocolVersion=1).
AUTHENTIC_GRAPPA_TOKENS: list[bytes] = [
    bytes.fromhex(
        "01012ba6a01f2ccf66a02613d5b72e0bc916004058a001a6874d18b5bd7b3395e25d79fa3ffcc67e718106d485c51540b828d1620e9f94f582d3bcc6f97e9088c923095ad8d36ab568fb45df61e286d25354b04c"
    ),
    bytes.fromhex(
        "0101efa33b1586f410087474b2ccaf8cdb4d0040e5aee6017fdcf774a51c1980b4238076e86218af5a5f169470df90b73f4fc893a22da94fb9745c10f23df0620cfe3f19be3f2ab37d2f7590d8597ab51ebcced0"
    ),
    bytes.fromhex(
        "0101aab479a6d8226f3e1d7a57a2501337e50240e54444b5f1d04101205a7a2f3d148d18440e2edef03d37fcdc7423c0bb441b4c4a355169d511d67ae3466fdf8865e69a8aed45867801ea8e1bbb48889ba0b834"
    ),
    bytes.fromhex(
        "010194ab2ece86e05d7313e4075a947ab3be0240c9237c46b3c519d2ec297304413dab741827016e5eb9af8792bc2b3d6f12be25397931f41bffb887d042b97057c03ed8d72a3acb72378d30f7a073e3d7590f62"
    ),
    bytes.fromhex(
        "01018cec0ea2c25446c90133d435eaafb0150240c6c28dd42f62f8907133c462fc8b6def05e543ab2d59952f6eb3b38e382d492cd2881beceaeaea67fc1331f77fca50fde6bed35622009670e6d6e4a36b09c088"
    ),
    bytes.fromhex(
        "0101243b2587f14dd812751c6710730f46d50440fe2e5e9ccfe70200487e14c131412381fd7c214241b182ca04ebe0c1f3cdd54ac17eef31705c06289e02f672fa8c0d9dff167f1c925df876d5814d3265f55b06"
    ),
    bytes.fromhex(
        "01016f8908f8f972bdc8fe99002f7648e86c024011a469c4320bb7e44137756dde3ecfbff08a55081e532c12a06101c6ae5283a014512d977eafad06c34b1f116422f6bf72ef56f8d734d37db287b170be7a3a82"
    ),
    bytes.fromhex(
        "01015c5fcc103d0460f5bbfd48c387806e8e0340e3323ed780fbeccc2908c059d9a81e75976bf058b411f62a9a6e1df7ba307f69226942373f484690799b230bc60e99036f40eae25229aff6bb31ab74820e68a9"
    ),
    bytes.fromhex(
        "0101f3f542aaa17252a8f81b3dc5b007adc304408d2496cee3af54113ffa9fba392b4143d4c38e4d79680e8e9feb554e450c1f89220c02375a9063b3a62bf61f62bd073991ebf215c6c2e28938d1aa53ed580c02"
    ),
    bytes.fromhex(
        "0101fc26f7e89d1635d86b5c886df69f526a0040038b6c33049f6bd5cc526b4ee7ccce614135d2c73f8326d9af6d28399a231510917493d4fdaa395b4d1c1e1b09bdf3fe6fb7e16ad6d5f5cc18b93730874e6f4e"
    ),
]

_lock = threading.Lock()
_cached: Optional[bytes] = None
_cache_tried = False


def is_macos() -> bool:
    return sys.platform == "darwin"


def _device_info() -> dict:
    return {"version": 1, "deviceType": 0, "protocolVersion": 1}


def get_grappa_token(force_refresh: bool = False) -> Optional[bytes]:
    """Return a genuine Grappa client token, or None when unavailable.

    macOS: resol ved at runtime from the private AirTraffic frameworks via
    plain ctypes objc_msgSend (no pyobjc).  Any other platform -> None.
    """
    global _cached, _cache_tried
    if not _cache_tried or force_refresh:
        with _lock:
            _cached = _macos_token()
            _cache_tried = True
    return _cached


def _macos_token() -> Optional[bytes]:
    if not is_macos():
        return None
    try:
        import ctypes
        import ctypes.util
    except ImportError:  # pragma: no cover
        return None

    class _ObjCObject(ctypes.Structure):
        pass

    try:
        libobjc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
    except OSError as exc:
        logger.warning("grappa: cannot load objc/CoreFoundation: %s", exc)
        return None

    libobjc.objc_getClass.restype = ctypes.c_void_p
    libobjc.objc_getClass.argtypes = [ctypes.c_char_p]
    libobjc.sel_registerName.restype = ctypes.c_void_p
    libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    cf.CFDictionaryCreate.restype = ctypes.c_void_p
    cf.CFDictionaryCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    cf.CFNumberCreate.restype = ctypes.c_void_p
    cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
    cf.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None

    handle = None
    for path in (
        "/System/Library/PrivateFrameworks/AirTrafficDevice.framework/AirTrafficDevice",
        "/System/Library/PrivateFrameworks/AirTrafficHost.framework/AirTrafficHost",
    ):
        try:
            handle = ctypes.cdll.LoadLibrary(path)
            break
        except OSError:
            continue
    if handle is None:
        logger.warning("grappa: no AirTraffic private framework on this host")
        return None

    alloc = libobjc.objc_msgSend
    msg = libobjc.objc_msgSend

    try:
        cls = libobjc.objc_getClass(b"ATGrappaSession")
        if not cls:
            logger.warning("grappa: ATGrappaSession class not found")
            return None

        session = msg(cls, libobjc.sel_registerName(b"alloc"))
        if not session:
            return None
        init_sel = libobjc.sel_registerName(b"initWithType:")
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        session = msg(session, init_sel, 1)
        if not session:
            return None

        info = _cf_dictionary(libobjc, cf, cf, _device_info())
        if not info:
            return None

        est_sel = libobjc.sel_registerName(
            b"establishHostSessionWithDeviceInfo:clientRequestData:"
        )
        out_ptr = ctypes.c_void_p()
        msg.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        msg.restype = ctypes.c_void_p
        err = msg(session, est_sel, info, ctypes.byref(out_ptr))
        cf.CFRelease(info)
        if err:
            logger.warning("grappa: establishHostSession failed (err=%x)", err)
            return None
        data = out_ptr.value
        if not data:
            logger.warning("grappa: host session yielded no clientRequestData")
            return None

        length = cf.CFDataGetLength(data)
        ptr = cf.CFDataGetBytePtr(data)
        token = bytes(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte * length)).contents) if ptr else b""
        if not token:
            logger.warning("grappa: empty clientRequestData")
            return None
        logger.info("grappa: obtained %d-byte token from AirTraffic frameworks", len(token))
        return token
    except Exception as exc:  # noqa: BLE001 - never break the caller
        logger.warning("grappa: token generation failed: %s", exc)
        return None


def _cf_dictionary(libobjc, cf, _, mapping: dict) -> Optional[int]:
    kCFTypeDictionaryKeyCallBacks = 412  # pointer-sized struct; we cheat with NULL
    keys = (ctypes.c_void_p * len(mapping))()
    vals = (ctypes.c_void_p * len(mapping))()
    kCFStringEncodingUTF8 = 0x8000100
    kCFNumberIntType = 3
    for idx, (key, value) in enumerate(mapping.items()):
        k = cf.CFStringCreateWithCString(None, key.encode("utf-8"), kCFStringEncodingUTF8)
        if not k:
            return 0
        num = ctypes.c_int(int(value))
        v = cf.CFNumberCreate(None, kCFNumberIntType, ctypes.byref(num))
        if not v:
            return 0
        keys[idx], vals[idx] = k, v
    d = cf.CFDictionaryCreate(None, keys, vals, len(mapping),
                              None, None)
    for k, v in zip(keys, vals):
        cf.CFRelease(k)
        cf.CFRelease(v)
    return d or 0