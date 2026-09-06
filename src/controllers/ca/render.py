"""QPainter rendering of CAML scenes (lock-screen wallpaper preview).

Faithful port of CAPlayground's ``LayerRenderer`` + child renderers and the
``coordinates`` / ``layerApplication`` helpers. Compose rules mirror the CSS
model: each layer is a positioned box whose transform (translate -> rotate ->
scale, all about the anchor point) maps content onto the scene, blend modes /
filters are composited through a per-layer bitmap, and the children render in
array order without z-sorting.

Fidelity notes (deliberate, matching the user's request not to over-engineer):
* ``liquidGlass`` layers render fully transparent (children still drawn).
* ``rotateX`` / ``rotateY`` / perspective are not simulated (flat 2D).
* ``CAEmitterLayer`` degrades to a static sprite per cell at ``emitterPosition``.
* gyro parallax (``wallpaperParallaxGroups``) is parsed but not rendered.
"""

from __future__ import annotations

import math
import copy as _copy
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from src.controllers.tendie_preview import decode_image_bytes
from .animate import layer_animation_overrides, scene_loop_duration
from .models import CADocument, GradientColor, Layer, Vec2

_QM = QPainter.CompositionMode

# CAPlayground lib/blending.ts ids -> Qt composition modes. The four HSL-based
# ones below are handled in numpy (Qt has no matching composition mode).
_BLEND_MODES: Dict[str, QPainter.CompositionMode] = {
    "normalBlendMode": _QM.CompositionMode_SourceOver,
    "colorBurnBlendMode": _QM.CompositionMode_ColorBurn,
    "colorDodgeBlendMode": _QM.CompositionMode_ColorDodge,
    "darkenBlendMode": _QM.CompositionMode_Darken,
    "differenceBlendMode": _QM.CompositionMode_Difference,
    "exclusionBlendMode": _QM.CompositionMode_Exclusion,
    "lightenBlendMode": _QM.CompositionMode_Lighten,
    "multiplyBlendMode": _QM.CompositionMode_Multiply,
    "overlayBlendMode": _QM.CompositionMode_Overlay,
    "screenBlendMode": _QM.CompositionMode_Screen,
}

# CSS/NPM blend modes Qt does not provide natively -> composited in numpy.
_HSL_KINDS: Dict[str, str] = {
    "hueBlendMode": "hue",
    "saturationBlendMode": "saturation",
    "colorBlendMode": "color",
    "luminosityBlendMode": "luminosity",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def find_by_id(layer: Layer, wanted: str) -> Optional[Layer]:
    if layer.id == wanted:
        return layer
    for child in layer.children:
        hit = find_by_id(child, wanted)
        if hit is not None:
            return hit
    return None


def apply_state_overrides(root: Layer, overrides: Optional[dict], state: Optional[str]) -> Layer:
    """Deep-copy ``root`` and apply per-state overrides (port of applyOverrides)."""
    import copy as _copy

    if not overrides or not state or state == "Base State":
        return _copy.deepcopy(root)

    clone = _copy.deepcopy(root)
    listing = overrides.get(state) or []
    if (not listing) and len(state) >= 2 and state[-6:] in (" Light",):
        base = state.rsplit(" ", 1)[0]
        listing = overrides.get(base) or []
    for o in listing:
        target_id = (str(o.get("targetId") or "")).strip()
        target = find_by_id(clone, target_id) or find_by_id(clone, o.get("targetId"))
        if target is None:
            continue
        kp = (str(o.get("keyPath") or "")).lower()
        v = o.get("value")
        if kp == "position.y" and isinstance(v, (int, float)):
            target.position.y = float(v)
        elif kp == "position.x" and isinstance(v, (int, float)):
            target.position.x = float(v)
        elif kp == "zposition" and isinstance(v, (int, float)):
            target.zPosition = float(v)
        elif kp == "bounds.size.width" and isinstance(v, (int, float)):
            target.size.w = float(v)
        elif kp == "bounds.size.height" and isinstance(v, (int, float)):
            target.size.h = float(v)
        elif kp == "transform.scale.xy" and isinstance(v, (int, float)):
            target.scale = float(v)
        elif kp in ("transform.rotation", "transform.rotation.z") and isinstance(v, (int, float)):
            target.rotation = float(v)
        elif kp == "transform.rotation.x" and isinstance(v, (int, float)):
            target.rotationX = float(v)
        elif kp == "transform.rotation.y" and isinstance(v, (int, float)):
            target.rotationY = float(v)
        elif kp == "opacity" and isinstance(v, (int, float)):
            target.opacity = float(v)
        elif kp == "cornerradius" and isinstance(v, (int, float)):
            target.cornerRadius = float(v)
        elif kp == "borderwidth" and isinstance(v, (int, float)):
            target.borderWidth = float(v)
        elif kp == "fontsize" and isinstance(v, (int, float)):
            target.fontSize = float(v)
        elif kp == "backgroundcolor" and isinstance(v, str):
            target.backgroundColor = v
        elif kp == "bordercolor" and isinstance(v, str):
            target.borderColor = v
        elif kp == "color" and isinstance(v, str):
            target.color = v
    return clone


def interpolated_state_root(
    root: Layer,
    overrides: Optional[dict],
    from_state: str,
    to_state: str,
    progress: float,
) -> Layer:
    """Build a layer tree with state overrides interpolated between two states.

    Numeric overrides for the same ``(targetId, keyPath)`` are blended by
    ``progress`` (0..1); values that only exist in the target state snap in.
    Non-numeric values (colors, strings) hold the source value and switch at
    ``progress == 1``, matching how a snapped edge lands at the end of a
    transition.
    """
    if not overrides:
        return _copy.deepcopy(root)
    from_list = overrides.get(from_state) or []
    to_list = overrides.get(to_state) or []
    p = max(0.0, min(1.0, float(progress)))
    to_map = {
        (str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()): o.get("value")
        for o in to_list
    }
    interp = []
    from_keys = set()
    for o in from_list:
        target_id = str(o.get("targetId") or "")
        key_path = str(o.get("keyPath") or "")
        from_keys.add((target_id, key_path.lower()))
        fv = o.get("value")
        tv = to_map.get((target_id, key_path.lower()))
        if isinstance(fv, (int, float)) and isinstance(tv, (int, float)):
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": fv + (tv - fv) * p})
        else:
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": tv if p >= 1.0 else fv})
    for o in to_list:
        target_id = str(o.get("targetId") or "")
        key_path = str(o.get("keyPath") or "")
        if (target_id, key_path.lower()) not in from_keys:
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": o.get("value")})
    return apply_state_overrides(root, {"__transition__": interp}, "__transition__")


def state_transition_spec(doc: Optional[CADocument]) -> Optional[Tuple[str, str, float, float, float]]:
    """Describe a playable Locked<->Unlock poster transition.

    Returns ``(from_state, to_state, open_duration, close_duration, hold)`` for
    scenes like the Minecraft chest whose "animation" is the state machine
    (the lid flies away, the treasure interior swells) rather than a looping
    CA animation, or ``None`` when the states are identical.
    """
    if doc is None or not doc.stateOverrides:
        return None
    lock_list = doc.stateOverrides.get("Locked") or []
    unlock_list = doc.stateOverrides.get("Unlock") or []
    if not lock_list or not unlock_list:
        return None
    to_map = {
        (str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()): o.get("value")
        for o in unlock_list
    }
    diffs = 0
    for o in lock_list:
        fv = o.get("value")
        tv = to_map.get((str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()))
        if isinstance(fv, (int, float)) and isinstance(tv, (int, float)) and abs(fv - tv) > 1e-6:
            diffs += 1
    if diffs == 0:
        return None
    duration = 0.55  # CAPlayground posters use the system unlock cadence by default
    for t in (doc.stateTransitions or []):
        if getattr(t, "toState", None) == "Unlock":
            ds = [el.duration for el in t.elements if getattr(el, "duration", None)]
            if ds:
                duration = max(0.1, max(ds))
            break
    return ("Locked", "Unlock", duration, duration, 0.9)


def home_state(doc: Optional[CADocument]) -> Optional[str]:
    """Return the unlocked (home-screen) state name for ``doc`` if rendering
    it visibly changes the picture, else ``None``.

    Prefers a state whose name starts with ``Unlock`` (``Unlock``,
    ``Unlock Light``, ``Unlock Dark`` ...) and returns it only when a render
    of that state actually differs from the default scene (the one the
    lock-screen loop shows). Scenes without a distinct home appearance (e.g.
    Super Mario's ``Unlock`` state, which is visually identical to ``Locked``)
    return ``None`` so the preview stays on its loop while unlocked.
    """
    if doc is None or not doc.stateOverrides or not doc.states:
        return None
    mig = None
    for s in doc.states:
        if str(s).lower().startswith("unlock"):
            mig = str(s)
            break
    if mig is None:
        return None
    try:
        base = CAMLRenderer(doc).render(0.0)
        home = CAMLRenderer(doc, state=mig).render(0.0)
    except Exception:
        return None
    if base is None or base.isNull() or home is None or home.isNull():
        return None
    if base.size() != home.size():
        return mig
    if bytes(base.bits()) == bytes(home.bits()):
        return None
    return mig


def _hex_color(hex_str: Optional[str], alpha: float = 1.0) -> Optional[QColor]:
    if not hex_str:
        return None
    text = hex_str.strip()
    m = text.lower()
    if not m.startswith("#"):
        m = "#" + m
    h = m.lstrip("#")
    if len(h) >= 8:
        h = h[:6]
    elif len(h) < 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return QColor(r, g, b, int(_clamp(alpha, 0.0, 1.0) * 255))


def _rounded_rect_path(w: float, h: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, radius)
    t = min(r, w / 2.0, h / 2.0)
    path.addRoundedRect(QRectF(0.0, 0.0, w, h), t, t)
    return path


def _apply_filters(img: QImage, filters) -> QImage:
    """GPU-free approximation of the CSS filters CAPlayground maps onto layers."""
    if not filters:
        return img
    enabled = [f for f in filters if f.enabled]
    if not enabled:
        return img
    try:
        import numpy as np
        import io
        from PIL import Image
    except Exception:
        return img

    from PySide6.QtCore import QBuffer, QByteArray

    buf = QBuffer()
    buf.setData(QByteArray())
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    try:
        pil = Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")
    except Exception:
        return img

    for flt in enabled:
        ft = flt.type
        value = flt.value
        try:
            if ft == "gaussianBlur":
                from PIL import ImageFilter
                pil = pil.filter(ImageFilter.GaussianBlur(radius=max(0.0, value)))
            elif ft == "colorContrast":
                from PIL import ImageEnhance
                pil = ImageEnhance.Contrast(pil).enhance(max(0.0, value))
            elif ft == "colorSaturate":
                from PIL import ImageEnhance
                pil = ImageEnhance.Color(pil).enhance(max(0.0, value))
            elif ft == "colorInvert":
                arr = np.asarray(pil).copy()
                arr[..., :3] = 255 - arr[..., :3]
                pil = Image.fromarray(arr, "RGBA")
            elif ft == "colorHueRotate":
                pil = _hue_rotate_pil(pil, value, np)
            elif ft == "CISepiaTone":
                pil = _sepia_pil(pil, value, np)
        except Exception:
            continue

    try:
        arr = np.asarray(pil)
        rgba = np.ascontiguousarray(arr)
        from PySide6.QtGui import QImage as _QI
        out = _QI(rgba.data, rgba.shape[1], rgba.shape[0], 4 * rgba.shape[1], _QI.Format.Format_RGBA8888).copy()
        return out
    except Exception:
        return img


def _hue_rotate_pil(pil, degrees: float, np):
    arr = np.asarray(pil).astype(np.float32) / 255.0
    rgb = arr[..., :3]
    alpha = arr[..., 3]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc
    h = np.zeros_like(maxc)
    mask = delta != 0
    h = np.where(mask & (maxc == r), 60.0 * (((g - b) / np.where(mask, delta, 1.0)) % 6.0), h)
    h = np.where(mask & (maxc == g), 60.0 * (((b - r) / np.where(mask, delta, 1.0)) + 2.0), h)
    h = np.where(mask & (maxc == b), 60.0 * (((r - g) / np.where(mask, delta, 1.0)) + 4.0), h)
    s = np.where(maxc != 0, delta / np.where(maxc, maxc, 1.0), 0.0)
    v = maxc
    h = np.mod(h + degrees, 360.0)
    floor_h = np.floor(h / 60.0)
    f = h / 60.0 - floor_h
    pp = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    h6 = np.mod(floor_h, 6.0).astype(np.float32)
    out = np.empty_like(rgb)
    for i, (h_, p_, q_, t_) in enumerate([(0, [v, t, pp]), (1, [q, v, pp]), (2, [pp, v, t]), (3, [pp, q, v]), (4, [t, pp, v]), (5, [v, pp, q])]):
        mask_i = h6 == i
        out[..., 0] = np.where(mask_i, h_[0], out[..., 0])
        out[..., 0] = np.where(mask_i, h_[0], out[..., 0])
        out[..., 1] = np.where(mask_i, h_[1], out[..., 1])
        out[..., 2] = np.where(mask_i, h_[2], out[..., 2])
    out = np.stack([out[..., 0], out[..., 1], out[..., 2], alpha], axis=-1)
    out = np.clip(out, 0.0, 1.0)
    from PIL import Image as _I
    return _I.fromarray((out * 255.0).astype(np.uint8), "RGBA")


def _sepia_pil(pil, factor: float, np):
    arr = np.asarray(pil).astype(np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3:]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    sr = r * 0.393 + g * 0.769 + b * 0.189
    sg = r * 0.349 + g * 0.686 + b * 0.168
    sb = r * 0.272 + g * 0.534 + b * 0.131
    f = max(0.0, min(1.0, factor))
    out = rgb * (1.0 - f) + np.stack([sr, sg, sb], axis=-1) * f
    out = np.clip(out, 0.0, 255.0)
    from PIL import Image as _I
    return _I.fromarray(np.concatenate([out, alpha], axis=-1).astype(np.uint8), "RGBA")


def _rgb_to_hsl(rgb: "np.ndarray") -> "np.ndarray":
    import numpy as np
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    h = np.empty_like(mx)
    h[:] = 0.0
    nz = delta > 0
    h = np.where(nz & (mx == r), 60.0 * (((g - b) / np.where(nz, delta, 1.0)) % 6.0), h)
    h = np.where(nz & (mx == g), 60.0 * (((b - r) / np.where(nz, delta, 1.0)) + 2.0), h)
    h = np.where(nz & (mx == b), 60.0 * (((r - g) / np.where(nz, delta, 1.0)) + 4.0), h)
    light = (mx + mn) / 2.0
    denom = np.where((light == 0) | (light == 1), np.full_like(light, 1e-6), 1.0 - np.abs(2.0 * light - 1.0))
    s = np.where(nz, delta / denom, 0.0)
    return np.stack([h, s, light], axis=-1)


def _hsl_to_rgb_hsl(h: float, s: float, l: float) -> "np.ndarray":
    import numpy as np
    c = (1.0 - np.abs(2.0 * l - 1.0)) * s
    hx = np.mod(h / 60.0, 6.0)
    x = c * (1.0 - np.abs(np.mod(hx, 2.0) - 1.0))
    m = (l - c / 2.0)[..., None]
    rgb = np.empty((*np.shape(hx), 3), dtype=np.float32)
    c2 = c[..., None]
    x2 = x[..., None]
    cond0 = hx < 1
    cond1 = (hx >= 1) & (hx < 2)
    cond2 = (hx >= 2) & (hx < 3)
    cond3 = (hx >= 3) & (hx < 4)
    cond4 = (hx >= 4) & (hx < 5)
    cond5 = hx >= 5
    rgb[..., 0] = np.where(cond0, c2, np.where(cond1, x2, np.where(cond2, 0, np.where(cond3, 0, np.where(cond4, x2, c2)))))
    rgb[..., 1] = np.where(cond0, x2, np.where(cond1, c2, np.where(cond2, c2, np.where(cond3, 0, np.where(cond4, 0, c2)))))
    rgb[..., 2] = np.where(cond0, 0, np.where(cond1, 0, np.where(cond2, x2, np.where(cond3, c2, np.where(cond4, c2, 0)))))
    return rgb + m


def _hsl_blend(src: QImage, kind: str) -> QImage:
    """HSL-family blend on an offscreen layer is approximated as a replace of
    the layer's own pixels (a preview approximation -- the four CSS blend ids
    map through this path only when Qt cannot natively produce them)."""
    try:
        import numpy as np
        from PIL import Image
        import io
    except Exception:
        return src
    from PySide6.QtCore import QBuffer, QByteArray

    buf = QBuffer()
    buf.setData(QByteArray())
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    src.save(buf, "PNG")
    buf.close()
    try:
        pil = Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")
    except Exception:
        return src
    arr = np.asarray(pil).astype(np.float32) / 255.0
    alpha = arr[..., 3:4]
    rgb = arr[..., :3]
    hsl = _rgb_to_hsl(rgb)
    rgb_out = _hsl_to_rgb_hsl(hsl[..., 0], hsl[..., 1], hsl[..., 2])
    rgb_out = np.clip(rgb_out, 0.0, 1.0)
    back_alpha = 1.0
    out_rgb = rgb_out * alpha + rgb * (1.0 - alpha)
    out_alpha = alpha + back_alpha * (1.0 - alpha)
    final = np.clip(np.concatenate([out_rgb, out_alpha[..., :1]], axis=-1), 0.0, 1.0)
    buf2 = np.ascontiguousarray((final * 255.0).astype(np.uint8))
    return QImage(buf2.data, final.shape[1], final.shape[0], 4 * final.shape[1], QImage.Format.Format_RGBA8888).copy()


class CAMLRenderer:
    """Render a parsed :class:`CADocument` to a QImage at any wall-clock time."""

    def __init__(
        self,
        doc: CADocument,
        size: Optional[Tuple[int, int]] = None,
        state: str = "Locked",
        backdrop: Optional[str] = None,
    ):
        self.doc = doc
        root = doc.root
        self.scene_w = root.size.w if root else 390.0
        self.scene_h = root.size.h if root else 844.0
        self.scene_flipped = int(root.geometryFlipped or 0) if root else 0
        self.width, self.height = size or (int(self.scene_w), int(self.scene_h))
        self.state = state
        self.backdrop = backdrop or (root.backgroundColor if root else None)
        self._images: Dict[str, Optional[QImage]] = {}
        self._painted_layers = 0

    # -- asset access ------------------------------------------------------ #

    def _image_for(self, name: Optional[str]) -> Optional[QImage]:
        """Resolve an asset path to a cached QImage (never requires a display).
        CAML ``contents`` strings URL-encode spaces (``assets/a%20b.png``),
        so the basename is matched both raw and decoded."""
        if not name:
            return None
        keys = [name.split("/")[-1]]
        try:
            decoded = unquote(keys[0])
            if decoded not in keys:
                keys.append(decoded)
        except Exception:
            pass
        for key in keys:
            if key in self._images:
                return self._images[key]
            data = self.doc.assets.get(key)
            if data:
                img = decode_image_bytes(data)
                if img is not None and not img.isNull():
                    self._images[key] = img
                    return img
                self._images[key] = None
        return None

    # -- top level --------------------------------------------------------- #

    def render(self, t_ms: float = 0.0) -> QImage:
        root = apply_state_overrides(self.doc.root, self.doc.stateOverrides, self.state)
        return self._paint_root(root, t_ms)

    def render_state_transition(
        self,
        from_state: str = "Locked",
        to_state: str = "Unlock",
        progress: float = 0.0,
        t_ms: float = 0.0,
    ) -> QImage:
        """Render the poster state transition (e.g. chest opening): each
        numeric state override is interpolated ``from_state`` -> ``to_state``
        by ``progress``; non-numeric values snap in at the end."""
        root = interpolated_state_root(
            self.doc.root, self.doc.stateOverrides, from_state, to_state, progress)
        return self._paint_root(root, t_ms)

    def _paint_root(self, root: Layer, t_ms: float = 0.0) -> QImage:
        layers = root.children if root else []

        target = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)

        bg = _hex_color(self.backdrop)
        if bg is not None:
            target.fill(bg)

        p = QPainter(target)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        kx = self.width / self.scene_w if self.scene_w > 0 else 1.0
        ky = self.height / self.scene_h if self.scene_h > 0 else 1.0
        if kx != 1.0 or ky != 1.0:
            p.scale(kx, ky)

        use_y_up = self.scene_flipped == 0
        parent_h = self.scene_h

        bg_layers = [l for l in layers if l.name == "BACKGROUND"]
        fg_layers = [l for l in layers if l.name != "BACKGROUND"]
        for top_layers in (bg_layers, fg_layers):
            for layer in top_layers:
                self._draw_layer(p, layer, use_y_up, parent_h, t_ms, 0.0)

        p.end()
        return target

    # -- per-layer ---------------------------------------------------------- #

    def _draw_layer(
        self,
        p: QPainter,
        layer: Layer,
        use_y_up: bool,
        parent_h: float,
        t_ms: float,
        delay_ms: float,
    ):
        ovs = layer_animation_overrides(layer.animations, t_ms, delay_ms)
        if ovs.get("hidden") == 1 or layer.visible is False:
            return

        w = float(ovs.get("bounds.size.width", layer.size.w or 0.0))
        h = float(ovs.get("bounds.size.height", layer.size.h or 0.0))
        if w <= 0 or h <= 0:
            return
        x = float(ovs.get("position.x", layer.position.x))
        y = float(ovs.get("position.y", layer.position.y))
        rotation = float(ovs.get("transform.rotation.z", layer.rotation or 0.0))
        opacity = float(ovs.get("opacity", layer.opacity if layer.opacity is not None else 1.0))
        bg_color = ovs.get("backgroundColor", layer.backgroundColor)
        scale = layer.scale if layer.scale else 1.0

        next_use_y_up = (not use_y_up) if (layer.geometryFlipped or 0) == 1 else use_y_up
        ap = layer.anchorPoint
        ax = float(ap.x if ap is not None and ap.x is not None else 0.5)
        ay = float(ap.y if ap is not None and ap.y is not None else 0.5)
        rot = rotation * (-1 if next_use_y_up else 1)

        # CSS top/left placement: the box is positioned by its top-left
        # corner, while CAML `position` is the ANCHOR point in parent coords.
        # In a Y-up parent the y coordinate is measured from the BOTTOM of the
        # parent (so walk up to its height), and the box top edge sits
        # (1-ay)*h above the anchor.
        anchor_x = x
        anchor_y = (parent_h - y) if use_y_up else y
        box_top_left_dx = -ax * w
        box_top_left_dy = -(1.0 - ay) * h

        filters = [f for f in layer.filters if f.enabled] if layer.filters else []
        blend = _BLEND_MODES.get(layer.blendMode)
        hsl_kind = _HSL_KINDS.get(layer.blendMode)
        need_offscreen = bool(filters) or hsl_kind is not None or (
            blend is not None and blend != _QM.CompositionMode_SourceOver)

        p.save()
        p.translate(anchor_x, anchor_y)
        p.rotate(rot)
        if scale != 1.0:
            p.scale(scale, scale)
        p.translate(box_top_left_dx, box_top_left_dy)

        if need_offscreen:
            off = QImage(max(1, math.ceil(w)), max(1, math.ceil(h)), QImage.Format.Format_ARGB32_Premultiplied)
            off.fill(Qt.GlobalColor.transparent)
            op = QPainter(off)
            self._paint_layer_content(op, layer, w, h, next_use_y_up, t_ms, delay_ms, bg_color)
            op.end()
            if filters:
                off = _apply_filters(off, filters)
            if hsl_kind is not None:
                off = _hsl_blend(off, hsl_kind)
            if blend is not None:
                p.setCompositionMode(blend)
            if opacity < 0.999:
                p.setOpacity(_clamp(opacity, 0.0, 1.0))
            p.drawImage(QRectF(0.0, 0.0, w, h), off)
        else:
            if opacity < 0.999:
                p.setOpacity(_clamp(opacity, 0.0, 1.0))
            self._paint_layer_content(p, layer, w, h, next_use_y_up, t_ms, delay_ms, bg_color)

        p.restore()
        self._painted_layers += 1

    def _paint_layer_content(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        next_use_y_up: bool,
        t_ms: float,
        delay_ms: float,
        bg_color: Optional[str],
    ):
        # Clip to the layer box when masksToBounds (rounded when a radius is set).
        if layer.masksToBounds:
            p.save()
            radius = layer.cornerRadius or 0.0
            t = min(radius, w / 2.0, h / 2.0)
            p.setClipPath(_rounded_rect_path(w, h, t))

        corner = min(layer.cornerRadius or 0.0, w / 2.0, h / 2.0)
        is_shape = layer.type == "shape"
        if is_shape and layer.shape == "circle":
            corner = 9999.0
        if layer.type == "shape" and not bg_color and layer.fill:
            bg_color = layer.fill

        # Background fill (all layer kinds honour backgroundColor like the TSX div).
        fill = _hex_color(bg_color, layer.backgroundOpacity if layer.backgroundOpacity is not None else 1.0)
        if fill is not None and fill.alpha() > 0 and not layer.type == "liquidGlass" and bg_color:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(_rounded_rect_path(w, h, corner))
            p.restore()

        self._paint_inner(p, layer, w, h, next_use_y_up, t_ms, delay_ms)

        # Border (stroke inside the box edge, CSS-style).
        if layer.borderWidth and layer.borderWidth > 0 and layer.borderColor:
            col = _hex_color(layer.borderColor)
            if col is not None:
                p.save()
                pen = QPen(col, float(layer.borderWidth))
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                inset = layer.borderWidth / 2.0
                p.drawPath(_rounded_rect_path(w - inset * 2.0, h - inset * 2.0, max(0.0, corner - inset)).translated(inset, inset))
                p.restore()

        if layer.masksToBounds:
            p.restore()

    def _paint_inner(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        use_y_up: bool,
        t_ms: float,
        delay_ms: float,
    ):
        ltype = layer.type
        if ltype == "image":
            img = self._image_for(layer.src)
            if img is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), img)
        elif ltype == "text":
            self._paint_text(p, layer, w, h)
        elif ltype == "gradient":
            self._paint_gradient(p, layer, w, h, t_ms, delay_ms)
        elif ltype == "liquidGlass":
            pass  # rendered fully transparent (per requirements)
        elif ltype == "emitter":
            self._paint_emitter(p, layer, use_y_up)
        elif ltype == "video":
            self._paint_video(p, layer, w, h, t_ms)
        elif ltype == "shape":
            pass  # filled above

        if ltype == "replicator":
            self._paint_replicator_children(p, layer, w, h, use_y_up, t_ms, delay_ms)
        elif ltype == "video":
            if layer.syncWWithState:
                self._paint_video_sync_children(p, layer, w, h)
        else:
            for child in layer.children:
                self._draw_layer(p, child, use_y_up, h, t_ms, delay_ms)

    # -- content renderers -------------------------------------------------- #

    def _paint_text(self, p: QPainter, layer: Layer, w: float, h: float):
        if not layer.text:
            return
        family = layer.fontFamily or "Helvetica Neue"
        size = layer.fontSize or 14.0
        font = QFont()
        font.setFamily(family)
        font.setPixelSize(max(1, int(size)))
        p.setFont(font)
        col = _hex_color(layer.color) or QColor(0, 0, 0)
        p.setPen(col)

        flags = Qt.AlignmentFlag.AlignTop
        align = layer.align or "left"
        if align == "center":
            flags |= Qt.AlignmentFlag.AlignHCenter
        elif align == "right":
            flags |= Qt.AlignmentFlag.AlignRight
        elif align == "justified":
            flags |= Qt.AlignmentFlag.AlignJustify
        else:
            flags |= Qt.AlignmentFlag.AlignLeft
        if (layer.wrapped or 1) == 1:
            flags |= Qt.TextFlag.TextWordWrap.value
        else:
            flags |= Qt.TextFlag.TextSingleLine.value
        p.drawText(QRectF(0.0, 0.0, w, h), int(flags), layer.text)

    def _paint_gradient(self, p: QPainter, layer: Layer, w: float, h: float, t_ms: float, delay_ms: float):
        ovs = layer_animation_overrides(layer.animations, t_ms, delay_ms)
        colors_override = ovs.get("colors")
        resolved: List[GradientColor] = colors_override if colors_override is not None else layer.colors
        if not resolved:
            return
        sp = layer.startPoint or Vec2(0.0, 0.0)
        ep = layer.endPoint or Vec2(1.0, 1.0)
        start_x, start_y = sp.x * 100.0, sp.y * 100.0
        end_x, end_y = ep.x * 100.0, ep.y * 100.0
        grad_type = layer.gradientType or "axial"

        def make_stops(grad, colors, positions):
            for color, pos in zip(colors, positions):
                c = _hex_color(color.color, color.opacity if color.opacity is not None else 1.0)
                if c is not None:
                    grad.setColorAt(pos, c)

        same_point = abs(start_x - end_x) < 0.01 and abs(start_y - end_y) < 0.01
        if same_point:
            first = resolved[0]
            fill = _hex_color(first.color, first.opacity if first.opacity is not None else 1.0)
            if fill is not None:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawRect(QRectF(0.0, 0.0, w, h))
                p.restore()
            return

        n = len(resolved)
        positions = [i / (n - 1) for i in range(n)] if n > 1 else [0.0]

        if grad_type == "radial":
            cx = start_x / 100.0 * w
            cy = (1.0 - start_y / 100.0) * h
            radius = math.hypot(max(cx, w - cx), max(cy, h - cy))
            grad = QRadialGradient(QPointF(cx, cy), max(1.0, radius))
            make_stops(grad, resolved, positions)
        elif grad_type == "conic":
            dx = end_x - start_x
            dy = -(end_y - start_y)
            angle = math.atan2(dy, dx) + math.pi / 2.0
            cx = start_x / 100.0 * w
            cy = (1.0 - start_y / 100.0) * h
            grad = QConicalGradient(QPointF(cx, cy), math.degrees(angle))
            make_stops(grad, resolved, positions)
        else:
            dx = end_x - start_x
            dy = -(end_y - start_y)
            angle_deg = math.degrees(math.atan2(dy, dx)) + 90.0
            rad = math.radians(angle_deg)
            dir_x, dir_y = math.sin(rad), -math.cos(rad)
            cx, cy = 50.0, 50.0
            ts = []
            if abs(dir_x) > 1e-6:
                ts.append((0.0 - cx) / dir_x)
                ts.append((100.0 - cx) / dir_x)
            if abs(dir_y) > 1e-6:
                ts.append((0.0 - cy) / dir_y)
                ts.append((100.0 - cy) / dir_y)
            t0, t1 = min(ts), max(ts)
            sx = (cx + t0 * dir_x) / 100.0 * w
            sy = (cy + t0 * dir_y) / 100.0 * h
            ex2 = (cx + t1 * dir_x) / 100.0 * w
            ey2 = (cy + t1 * dir_y) / 100.0 * h
            grad = QLinearGradient(QPointF(sx, sy), QPointF(ex2, ey2))
            make_stops(grad, resolved, positions)

        p.save()
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(0.0, 0.0, w, h))
        p.restore()

    def _paint_emitter(self, p: QPainter, layer: Layer, use_y_up: bool):
        if not layer.emitterCells:
            return
        ex = layer.emitterPosition.x
        ey = layer.emitterPosition.y
        if use_y_up:
            ey = -ey
        for cell in layer.emitterCells:
            img = self._image_for(cell.src) if cell.src else None
            if img is None:
                continue
            s = cell.scale if cell.scale else 1.0
            target_w = max(1, img.width() * s)
            target_h = max(1, img.height() * s)
            rect = QRectF(ex - target_w / 2.0, ey - target_h / 2.0, target_w, target_h)
            p.save()
            p.setOpacity(_clamp(cell.alpha, 0.0, 1.0))
            p.rotate(cell.spin)
            p.drawImage(rect, img)
            p.restore()

    def _paint_video(self, p: QPainter, layer: Layer, w: float, h: float, t_ms: float):
        frame_count = layer.frameCount
        if frame_count <= 0:
            return
        fps = layer.fps or 30.0
        duration = layer.duration if layer.duration else frame_count / fps
        if duration <= 0:
            return
        auto_rev = layer.autoReverses
        local_t = (t_ms / 1000.0) % duration
        if auto_rev:
            cycle = duration * 2.0
            m = (t_ms / 1000.0) % cycle
            local_t = m if m <= duration else (cycle - m)
        frame_index = int(local_t * fps) % frame_count
        img = self._video_frame(layer, frame_index)
        if img is not None:
            p.drawImage(QRectF(0.0, 0.0, w, h), img)

    def _video_frame(self, layer: Layer, index: int) -> Optional[QImage]:
        prefix = layer.framePrefix or f"{layer.id}_frame_"
        ext = layer.frameExtension or ".jpg"
        candidates = [
            f"{prefix}{index}{ext}",
            f"{index}{ext}",
            f"{prefix}{index}",
            f"{layer.id}_frame_{index}{ext}",
        ]
        for name in candidates:
            img = self._image_for(name)
            if img is not None:
                return img
        return None

    def _paint_video_sync_children(self, p: QPainter, layer: Layer, w: float, h: float):
        children = layer.children
        if not children:
            return
        top_child = max(children, key=lambda c: c.zPosition or 0.0)
        if top_child.type == "image":
            img = None
            for i, child in enumerate(children):
                if child.id == top_child.id:
                    img = self._video_frame(layer, i)
                    break
            if img is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), img)

    def _paint_replicator_children(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        use_y_up: bool,
        t_ms: float,
        delay_ms: float,
    ):
        count = max(1, layer.instanceCount or 1)
        tx = layer.instanceTranslation.x
        ty = layer.instanceTranslation.y
        flipped = (layer.geometryFlipped or 0) == 1
        ap = layer.anchorPoint
        ax = float(ap.x if ap is not None and ap.x is not None else 0.5)
        ay = float(ap.y if ap is not None and ap.y is not None else 0.5)
        ox = ax * w
        oy = ((1.0 - ay) * h) if use_y_up else (ay * h)
        current_s = t_ms / 1000.0
        for i in range(count):
            if layer.instanceDelay and current_s < i * layer.instanceDelay:
                continue
            txi = tx * i
            tyi = ty * i if flipped else -ty * i
            rot_i = layer.instanceRotation * i
            instance_delay = layer.instanceDelay * 1000.0 * i
            p.save()
            p.translate(ox, oy)
            p.translate(txi, tyi)
            p.rotate(rot_i)
            p.translate(-ox, -oy)
            for child in layer.children:
                self._draw_layer(p, child, use_y_up, h, t_ms, delay_ms + instance_delay)
            p.restore()


# --------------------------------------------------------------------------- #
# Convenience helpers
# --------------------------------------------------------------------------- #

def render_document(doc: CADocument, t_ms: float = 0.0, state: str = "Locked",
                    size: Optional[Tuple[int, int]] = None) -> Optional[QImage]:
    if doc is None or doc.root is None:
        return None
    if state not in doc.stateOverrides and doc.stateOverrides and doc.states:
        state = doc.states[0]
    renderer = CAMLRenderer(doc, size=size, state=state)
    return renderer.render(t_ms)


def document_loop_duration(doc: CADocument) -> float:
    """Seconds of the longest infinite animation cycle (0 = static scene)."""
    if doc is None or doc.root is None:
        return 0.0
    longest = 0.0

    def walk(layer: Layer):
        nonlocal longest
        longest = max(longest, scene_loop_duration(layer.animations))
        for child in layer.children:
            walk(child)

    walk(doc.root)
    return longest


def document_has_motion(doc: CADocument) -> bool:
    return document_loop_duration(doc) > 0.0