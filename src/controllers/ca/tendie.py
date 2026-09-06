"""Unpack a ``.tendies`` archive into CAML documents + image assets.

Port of CAPlayground's ``lib/ca/ca-file.ts`` (``unpackTendies``): resolves the
``wallpaper.plist`` references to the ``*.ca`` scene folders, falls back to
name matching, resolves the scene caml (via ``index.xml`` ``rootDocument`` or
``main.caml``), and harvests every ``assets/`` file plus inline ``data:``
images into ``CADocument.assets`` (keyed by file name, exactly like the TSX
asset cache).
"""

from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from typing import Dict, List, Optional, Tuple

from .caml import parse_ca_document
from .models import CADocument, TendieBundle

_INDEX_NAMES = ("index.xml", "Index.xml")
_DEFAULT_SCENE = "main.caml"


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _find_wallpaper_plist(paths: List[str]) -> Optional[str]:
    for p in paths:
        if p.lower().endswith("wallpaper.plist"):
            return p
    return None


def _ca_refs_from_plist(xml: bytes) -> List[str]:
    """Extract every ``*.ca`` string-value from the wallpaper plist (binary
    or XML) and every scene filename field that references a ``.ca`` folder."""
    refs: List[str] = []
    try:
        import plistlib
        data = plistlib.loads(xml)
    except Exception:
        data = None

    if isinstance(data, dict):
        def _collect_strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                out = []
                for v in value.values():
                    out.extend(_collect_strings(v))
                return out
            if isinstance(value, (list, tuple)):
                out = []
                for v in value:
                    out.extend(_collect_strings(v))
                return out
            return []

        for s in _collect_strings(data):
            if s.lower().endswith(".ca") and s not in refs:
                refs.append(s)
        return refs

    # XML fallback (plistlib failed for malformed XML).
    text = xml.decode("utf-8", errors="replace")
    for m in re.finditer(r"<string>([^<]+)</string>", text):
        value = m.group(1).strip()
        if value.lower().endswith(".ca") and value not in refs:
            refs.append(value)
    return refs


def _resolve_ca_dir(ca_ref: str, paths: List[str]) -> Optional[str]:
    """Match ``ca_ref`` to a zip directory ending in ``.ca``."""
    norm_ref = _norm(ca_ref)
    lower_ref = norm_ref.lower()

    direct = None
    for p in paths:
        if p.lower().startswith(lower_ref + "/"):
            direct = p
            break
    if direct:
        parts = direct.split("/")
        idx = next((i for i, seg in enumerate(parts) if seg.lower().endswith(".ca")), -1)
        if idx >= 0:
            return "/".join(parts[: idx + 1]) + "/"

    base = norm_ref.split("/")[-1]
    candidate = None
    for p in paths:
        segs = [seg.lower() for seg in p.split("/")]
        if base.lower() in segs:
            candidate = p
            break
    if candidate:
        parts = candidate.split("/")
        idx = next((i for i, seg in enumerate(parts) if seg.lower().endswith(".ca")), -1)
        if idx >= 0:
            return "/".join(parts[: idx + 1]) + "/"
    return None


def _find_ca_path(pattern: str, paths: List[str]) -> Optional[str]:
    """Fallback name matcher mirroring findCAPath."""
    if pattern == "wallpaper.ca":
        for p in paths:
            if "wallpaper.ca" in [seg.lower() for seg in p.split("/")]:
                parts = p.split("/")
                idx = len(parts) - 1 - next(
                    (i for i, seg in enumerate(reversed(parts)) if seg.lower() == "wallpaper.ca"), -1)
                if idx >= 0:
                    return "/".join(parts[: idx + 1]) + "/"
    else:
        for p in paths:
            if any(seg.lower().endswith(".ca") and pattern in seg.lower() for seg in p.split("/")):
                parts = p.split("/")
                idx = next((i for i, seg in enumerate(parts) if seg.lower().endswith(".ca") and pattern in seg.lower()), -1)
                if idx >= 0:
                    return "/".join(parts[: idx + 1]) + "/"
    return None


def _extract_ca_dir(base_dir: str, paths: List[str], zf: zipfile.ZipFile) -> Optional[CADocument]:
    lower = base_dir.lower()
    by_lower = {p.lower(): p for p in paths}

    def get(rel: str) -> Optional[zipfile.ZipInfo]:
        full = _norm(base_dir + rel)
        hit = by_lower.get(full.lower())
        return zf.getinfo(hit or full) if (hit or full in zf.namelist()) else None

    index_entry = None
    for name in _INDEX_NAMES:
        index_entry = get(name)
        if index_entry:
            break
    scene_name = _DEFAULT_SCENE
    if index_entry:
        index_text = zf.read(index_entry).decode("utf-8", errors="replace")
        m = re.search(r"<key>rootDocument</key>\s*<string>(.*?)</string>", index_text, re.DOTALL)
        if m:
            scene_name = m.group(1).strip()

    caml_entry = get(scene_name)
    if not caml_entry:
        base = scene_name.split("/")[-1]
        for p in paths:
            if p.lower().startswith(base_dir.lower()) and (p.split("/")[-1] or "") == base:
                caml_entry = zf.getinfo(p)
                break
    if not caml_entry:
        return None

    caml_text = zf.read(caml_entry).decode("utf-8", errors="replace")
    caml_text, inline_assets = _extract_inline_assets(caml_text)

    doc = parse_ca_document(caml_text)
    if doc is None or doc.root is None:
        return None

    assets: Dict[str, bytes] = {}
    for p in paths:
        if not p.lower().startswith(base_dir.lower()):
            continue
        if p.endswith("/"):
            continue
        if not re.search(r"(^|/)assets/", p, re.IGNORECASE):
            continue
        try:
            data = zf.read(p)
        except (KeyError, OSError, zipfile.BadZipFile):
            continue
        after = re.split(r"assets/", p, flags=re.IGNORECASE)[-1]
        filename = after.split("/")[-1].strip()
        if filename and data and filename not in assets:
            assets[filename] = data

    for name, chunk in inline_assets.items():
        assets.setdefault(name, chunk)

    doc.assets = assets
    return doc


def _extract_inline_assets(caml_text: str) -> Tuple[str, Dict[str, bytes]]:
    """Pull ``data:`` URLs out of the caml into synthetic asset names."""
    assets: Dict[str, bytes] = {}

    def repl(m: re.Match) -> str:
        marker = m.group(1)
        raw = m.group(2)
        try:
            data = base64.b64decode(raw)
        except Exception:
            return m.group(0)
        name = f"_inline_{len(assets)}"
        assets[name] = data
        return f'src="assets/{name}"'

    pattern = r'src="data:[^;]*;base64,([^"]+)"'
    text = re.sub(pattern, repl, caml_text)
    # bare non-base64 data urls are dropped (cannot reconstruct)
    text = re.sub(r'src="data:[^"]*"', 'src="assets/_inline_undefined"', text)
    return text, assets


def load_tendie(tendie_path: str) -> Optional[TendieBundle]:
    """Open a ``.tendies`` zip and parse its scene documents."""
    try:
        zf = zipfile.ZipFile(tendie_path)
    except (zipfile.BadZipFile, OSError):
        return None

    try:
        paths = [_norm(info.filename) for info in zf.infolist()]
        paths = [p for p in paths if not p.endswith("/")]

        if any("com.apple.mercuryposter" in p.lower() for p in paths):
            return None

        floating_dir = background_dir = wallpaper_dir = None

        plist = _find_wallpaper_plist(paths)
        resolved_dirs: List[str] = []
        if plist:
            ca_refs = _ca_refs_from_plist(zf.read(plist))
            for ref in ca_refs:
                d = _resolve_ca_dir(ref, paths)
                if d and d not in resolved_dirs:
                    resolved_dirs.append(d)

        if len(resolved_dirs) == 1:
            wallpaper_dir = resolved_dirs[0]
        elif len(resolved_dirs) >= 2:
            def pick(keyword: str) -> Optional[str]:
                return next((d for d in resolved_dirs if keyword in d.lower()), None)

            floating_dir = pick("floating")
            background_dir = pick("background")
            wallpaper_dir = pick("wallpaper.ca")
            remaining = [d for d in resolved_dirs
                         if d != floating_dir and d != background_dir and d != wallpaper_dir]
            def pick_or(cur: Optional[str], fallback_index: int) -> Optional[str]:
                if cur:
                    return cur
                if fallback_index < len(resolved_dirs):
                    return resolved_dirs[fallback_index]
                return remaining[0] if remaining else None

            background_dir = pick_or(background_dir, 0)
            floating_dir = pick_or(floating_dir, 1)
            if not wallpaper_dir and len(resolved_dirs) > 2:
                wallpaper_dir = resolved_dirs[2]

        if not floating_dir:
            floating_dir = _find_ca_path("floating", paths)
        if not background_dir:
            background_dir = _find_ca_path("background", paths)
        if not wallpaper_dir:
            wallpaper_dir = _find_ca_path("wallpaper.ca", paths)

        bundle = TendieBundle()
        bundle.floating = _extract_ca_dir(floating_dir, paths, zf) if floating_dir else None
        bundle.background = _extract_ca_dir(background_dir, paths, zf) if background_dir else None
        bundle.wallpaper = _extract_ca_dir(wallpaper_dir, paths, zf) if wallpaper_dir else None

        any_root = None
        for d in (bundle.floating, bundle.background, bundle.wallpaper):
            if d and d.root is not None:
                any_root = d.root
                break
        if any_root is not None:
            bundle.width = max(0, int(any_root.size.w or 390))
            bundle.height = max(0, int(any_root.size.h or 844))
            bundle.geometryFlipped = int(any_root.geometryFlipped or 0)
        return bundle
    finally:
        zf.close()


def preferred_scene(bundle: TendieBundle) -> Tuple[Optional[CADocument], str]:
    """Pick the scene for a lock-screen preview.

    The most informative scene wins: longest animation loop first, then scenes
    with a playable state transition (e.g. the chest opening), ties broken by
    the classic floating > background > wallpaper priority.
    """
    from .render import document_loop_duration, state_transition_spec

    def _usable(doc):
        return doc is not None and doc.root is not None and doc.root.children

    candidates = []
    for doc, key in ((bundle.floating, "floating"),
                     (bundle.background, "background"),
                     (bundle.wallpaper, "wallpaper")):
        if _usable(doc):
            candidates.append((doc, key))
    if not candidates:
        if bundle.floating:
            return bundle.floating, "floating"
        if bundle.background:
            return bundle.background, "background"
        return bundle.wallpaper, "wallpaper"
    return max(candidates, key=lambda doc_key: (
        document_loop_duration(doc_key[0]),
        1 if state_transition_spec(doc_key[0]) else 0,
        -len(candidates)))