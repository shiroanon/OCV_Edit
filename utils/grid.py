"""
utils/grid.py
--------------
Grid-layout scene, layered scene, and panel/layer support for VideoPipeline.

Supports custom grid shapes (circle, ellipse, diamond, custom masks),
overlapping panels with z-ordering and blend modes, and freeform
positioning via position/size overrides on individual panels.
"""

from __future__ import annotations

from typing import List, Optional, Union, Any, Callable

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Shape mask utility
# ---------------------------------------------------------------------------


def make_wave_mask(
    num_waves: int = 4,
    amplitude: float = 0.18,
    direction: str = "right",
) -> Callable:
    """Return a callable ``(time) -> ndarray`` that generates a wavy-edge mask.

    The mask is 1 inside the panel area and 0 in the clipped region.
    Useful as the ``shape`` parameter on :class:`GridPanel`.

    Args:
        num_waves: Number of sine wave oscillations along the edge.
        amplitude: Wave depth as a fraction of the panel width.
        direction: ``"right"`` clips the right side (content on left);
                   ``"left"`` clips the left side (content on right).

    Returns:
        A callable ``(local_time) -> (h, w, 1) float32 mask``.
    """
    def _wave_mask(local_time: float = 0.0) -> np.ndarray:
        nonlocal num_waves, amplitude, direction
        w, h = 1000, 1000
        x = np.arange(w, dtype=np.float32)[np.newaxis, :]
        y_norm = np.arange(h, dtype=np.float32)[:, np.newaxis] / h
        offset = amplitude * w * np.sin(num_waves * 2 * np.pi * y_norm)
        if direction == "right":
            edge = w * 0.65 + offset
            mask = (x < edge).astype(np.float32)
        else:
            edge = w * 0.35 + offset
            mask = (x > edge).astype(np.float32)
        return mask[:, :, np.newaxis]
    return _wave_mask

def make_shape_mask(
    shape: Union[str, Callable, np.ndarray],
    w: int,
    h: int,
    local_time: float = 0.0,
) -> np.ndarray:
    """Generate a float32 mask of shape (h, w, 1) with values in [0, 1].

    Args:
        shape: ``"rect"``, ``"ellipse"``, ``"circle"``, ``"diamond"``,
               a callable ``(time) -> ndarray``, or a pre-made numpy array.
        w: Width in pixels.
        h: Height in pixels.
        local_time: Current time in seconds (passed to callable shapes).

    Returns:
        (h, w, 1) float32 mask.
    """
    if shape == "rect":
        return np.ones((h, w, 1), dtype=np.float32)

    if callable(shape):
        mask = shape(local_time)
        if not isinstance(mask, np.ndarray):
            return np.ones((h, w, 1), dtype=np.float32)
        if mask.shape[:2] != (h, w):
            mask = cv2.resize(mask.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        if mask.ndim == 2:
            mask = mask[:, :, np.newaxis]
        return mask.astype(np.float32)

    if isinstance(shape, np.ndarray):
        if shape.shape[:2] != (h, w):
            shape = cv2.resize(shape.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        if shape.ndim == 2:
            shape = shape[:, :, np.newaxis]
        return shape.astype(np.float32)

    mask = np.zeros((h, w), dtype=np.float32)
    center = (w // 2, h // 2)

    if shape == "circle":
        radius = min(w, h) // 2
        cv2.circle(mask, center, max(1, radius), 1.0, -1)
    elif shape == "ellipse":
        axes = (max(1, w // 2), max(1, h // 2))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
    elif shape == "diamond":
        pts = np.array([
            [center[0], 0],
            [w - 1, center[1]],
            [center[0], h - 1],
            [0, center[1]],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 1.0)
    else:
        raise ValueError(
            f"Unknown shape: '{shape}' — expected rect/ellipse/circle/diamond or callable"
        )

    return mask[:, :, np.newaxis]


# ---------------------------------------------------------------------------
# Position resolver for freeform panels
# ---------------------------------------------------------------------------

def _resolve_panel_rect(
    panel: Any,
    output_size: tuple,
    local_time: float,
) -> tuple:
    """Resolve ``(px, py, pw, ph)`` for a panel with ``position``/``size`` override."""
    tw, th = output_size

    ly_size = panel.size
    if callable(ly_size):
        ly_size = ly_size(local_time)

    if ly_size is None:
        pw, ph = tw, th
    elif isinstance(ly_size, (tuple, list)):
        lw_val, lh_val = ly_size
        pw = int(lw_val * tw) if isinstance(lw_val, float) else int(lw_val)
        ph = int(lh_val * th) if isinstance(lh_val, float) else int(lh_val)
    else:
        pw, ph = tw, th

    ly_pos = panel.position
    if callable(ly_pos):
        ly_pos = ly_pos(local_time)

    px_val, py_val = ly_pos
    px = int(px_val * tw) if isinstance(px_val, float) else int(px_val)
    py = int(py_val * th) if isinstance(py_val, float) else int(py_val)

    anchor = panel.anchor.lower()
    if anchor == "center":
        px = px - pw // 2
        py = py - ph // 2
    elif anchor == "top-left":
        pass
    elif anchor == "top-right":
        px = px - pw
    elif anchor == "bottom-left":
        py = py - ph
    elif anchor == "bottom-right":
        px = px - pw
        py = py - ph
    else:
        px = px - pw // 2
        py = py - ph // 2

    return (px, py, pw, ph)


# ---------------------------------------------------------------------------
# Blend-mode compositing helper
# ---------------------------------------------------------------------------

def _composite_panel(
    canvas: np.ndarray,
    layer_frame: np.ndarray,
    px: int,
    py: int,
    pw: int,
    ph: int,
    mask: np.ndarray,
    blend_mode: str,
) -> None:
    """Composite *layer_frame* onto *canvas* at ``(px, py)`` with *mask* and *blend_mode*."""
    tw, th = canvas.shape[1], canvas.shape[0]

    c_x1 = max(0, px)
    c_y1 = max(0, py)
    c_x2 = min(tw, px + pw)
    c_y2 = min(th, py + ph)

    l_x1 = max(0, -px)
    l_y1 = max(0, -py)
    l_x2 = l_x1 + (c_x2 - c_x1)
    l_y2 = l_y1 + (c_y2 - c_y1)

    if (c_x2 - c_x1) <= 0 or (c_y2 - c_y1) <= 0:
        return

    sub_canvas = canvas[c_y1:c_y2, c_x1:c_x2].astype(np.float32)
    sub_layer = layer_frame[l_y1:l_y2, l_x1:l_x2].astype(np.float32)
    sub_mask = mask[l_y1:l_y2, l_x1:l_x2]

    if blend_mode == "normal":
        blended = sub_layer
    elif blend_mode == "multiply":
        blended = (sub_canvas * sub_layer) / 255.0
    elif blend_mode == "screen":
        blended = 255.0 - ((255.0 - sub_canvas) * (255.0 - sub_layer)) / 255.0
    elif blend_mode == "add":
        blended = np.minimum(255.0, sub_canvas + sub_layer)
    elif blend_mode == "overlay":
        low = (2.0 * sub_canvas * sub_layer) / 255.0
        high = 255.0 - (2.0 * (255.0 - sub_canvas) * (255.0 - sub_layer)) / 255.0
        blended = np.where(sub_canvas < 128.0, low, high)
    elif blend_mode == "difference":
        blended = np.abs(sub_canvas - sub_layer)
    else:
        blended = sub_layer

    composited = sub_mask * blended + (1.0 - sub_mask) * sub_canvas
    canvas[c_y1:c_y2, c_x1:c_x2] = np.clip(composited, 0.0, 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
# BasePanel — shared frame decoding
# ---------------------------------------------------------------------------

class BasePanel:
    """Shared frame-decoding logic for GridPanel and Layer.

    Handles VideoCapture lifecycle, frame retrieval with loop/speed/offset,
    flip, and effect application.
    """

    def __init__(
        self,
        filepath: Optional[str] = None,
        start_time: float = 0.0,
        speed: float = 1.0,
        loop: bool = True,
        flip: Optional[str] = None,
        effects: Optional[list] = None,
        resize_mode: str = "fit",
    ):
        self.filepath = filepath
        self.start_time = start_time
        self.speed = speed
        self.loop = loop
        self.flip = flip
        self.effects = list(effects) if effects else []
        self.resize_mode = resize_mode

        self._cap = None
        self._source_fps = 30.0
        self._source_duration = 0.0
        self._last_frame = None
        self._last_frame_time = -1.0

        # Controls whether apply_effects sorts YOLO effects first
        self._sort_effects_yolo = False

        # Overlap / shape fields (set by subclasses with appropriate defaults)
        self.shape: Union[str, Callable, np.ndarray] = "rect"
        self.z_index: int = 0
        self.position: Optional[Any] = None  # None = use grid layout
        self.size: Optional[Any] = None
        self.anchor: str = "center"
        self.opacity: Union[float, Callable] = 1.0
        self.blend_mode: str = "normal"
        self.mask_type: Optional[Any] = None
        self.mask_params: Optional[dict] = None
        self.feather: float = 0.0
        self.invert: bool = False
        self.yolo_model_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Effect builder
    # ------------------------------------------------------------------

    def add_effect(self, effect, start_time: float = 0.0, duration: Union[float, str] = -1.0) -> "BasePanel":
        dur = -1.0 if duration == "clip_end" else float(duration)
        self.effects.append({
            "effect":     effect,
            "start_time": start_time,
            "duration":   dur,
        })
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self):
        if self.filepath:
            self._cap = cv2.VideoCapture(self.filepath)
        else:
            self._cap = None
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(f"{type(self).__name__}: cannot open '{self.filepath}'")
        sfps = self._cap.get(cv2.CAP_PROP_FPS)
        self._source_fps = sfps if sfps > 0 else 30.0
        total_frames = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._source_duration = (
            total_frames / self._source_fps if self._source_fps > 0 and total_frames > 0
            else 60.0
        )

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._last_frame = None
        self._last_frame_time = -1.0
        if hasattr(self, "_last_src_idx"):
            delattr(self, "_last_src_idx")

    # ------------------------------------------------------------------
    # Frame retrieval
    # ------------------------------------------------------------------

    def get_raw_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        if self._last_frame_time == output_local_time and self._last_frame is not None:
            return self._last_frame

        cap = self._cap
        if cap is None:
            return None

        src_fps  = self._source_fps
        src_start = self.start_time
        speed    = self.speed
        avail    = self._source_duration - src_start

        if self.loop and avail > 0:
            source_time = src_start + (output_local_time * speed) % avail
        else:
            source_time = src_start + output_local_time * speed

        src_frame_idx = int(source_time * src_fps)

        last_idx = getattr(self, "_last_src_idx", -1)

        if src_frame_idx == last_idx + 1:
            pass
        elif src_frame_idx > last_idx and src_frame_idx - last_idx < 5:
            for _ in range(src_frame_idx - last_idx - 1):
                cap.grab()
        elif src_frame_idx == last_idx and self._last_frame is not None:
            return self._last_frame
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)

        ret, frame = cap.read()
        if not ret:
            if src_frame_idx != last_idx + 1:
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
            ret, frame = cap.read()
            if not ret:
                return None

        self._last_src_idx = src_frame_idx
        self._last_frame = frame
        self._last_frame_time = output_local_time
        return frame

    def get_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        raw_frame = self.get_raw_frame(output_local_time)
        if raw_frame is None:
            return None

        frame = raw_frame.copy()

        if self.flip == "h":
            frame = cv2.flip(frame, 1)
        elif self.flip == "v":
            frame = cv2.flip(frame, 0)
        elif self.flip == "both":
            frame = cv2.flip(frame, -1)

        return frame

    # ------------------------------------------------------------------
    # Effect processing
    # ------------------------------------------------------------------

    def apply_effects(
        self,
        frame: np.ndarray,
        local_time: float,
        panel_duration: float,
    ) -> np.ndarray:
        effs = self.effects
        if self._sort_effects_yolo:
            effs = sorted(effs, key=lambda e: not hasattr(e["effect"], '_yolo_priority'))
        for eff_entry in effs:
            eff_start = eff_entry["start_time"]
            eff_dur   = eff_entry["duration"]
            if eff_dur < 0:
                eff_dur = max(0.001, panel_duration - eff_start)
            eff_end = eff_start + eff_dur

            if eff_start <= local_time <= eff_end:
                progress = (local_time - eff_start) / eff_dur
                progress = min(1.0, max(0.0, progress))
                effect_time = local_time - eff_start
                frame = eff_entry["effect"].process(frame, effect_time, progress)
        return frame


# ---------------------------------------------------------------------------
# GridPanel
# ---------------------------------------------------------------------------

class GridPanel(BasePanel):
    """One cell in a GridScene, with optional shape masking, overlapping,
    blend modes, YOLO masking, and freeform positioning.

    Args:
        filepath:   Source video file path.  Required unless *ref_panel* is set.
        start_time: Offset into the source (seconds) to begin reading.
        speed:      Playback speed multiplier (1.0 = normal).
        loop:       Loop the clip when it reaches its natural end (default True).
        flip:       ``"h"`` = horizontal mirror, ``"v"`` = vertical flip,
                    ``"both"`` = 180° rotation, ``None`` = no flip.
        effects:    Pre-built list of effect dicts.
        ref_panel:  Reference another GridPanel to share its decoded frames.
        resize_mode: ``"fill"`` or ``"fit"`` (default).

        shape:      Visual shape — ``"rect"`` (default), ``"ellipse"``, ``"circle"``,
                    ``"diamond"``, or a callable ``(time) -> ndarray``.
        z_index:    Draw order (higher = on top). Default 0.
        blend_mode: Compositing blend — ``"normal"``, ``"multiply"``, ``"screen"``,
                    ``"add"``, ``"overlay"``, ``"difference"``.
        opacity:    Float in ``[0, 1]`` or callable ``(time) -> float``.
        mask_type:  ``None``, ``"rect"``, ``"ellipse"``, ``"polygon"``,
                    ``"subject"``, ``"background"``, or a numpy array / callable.
        mask_params: Dict of parameters for the mask.
        feather:    Pixel radius to blur the mask edge.
        invert:     Whether to invert the mask.
        yolo_model_path: Path to YOLO model for subject/background masks.

        position:   If set, overrides grid layout position ``(x, y)``.
                    Values can be normalized floats or absolute ints,
                    or a callable ``(time) -> tuple``.
        size:       If set, overrides grid layout cell size ``(w, h)``.
                    Values can be normalized floats or absolute ints,
                    or a callable ``(time) -> tuple``.
        anchor:     Anchor point — ``"center"`` (default), ``"top-left"``,
                    ``"top-right"``, ``"bottom-left"``, ``"bottom-right"``.
    """

    def __init__(
        self,
        filepath: Optional[str] = None,
        start_time: float = 0.0,
        speed: float = 1.0,
        loop: bool = True,
        flip: Optional[str] = None,
        effects: Optional[list] = None,
        ref_panel: Optional["GridPanel"] = None,
        resize_mode: str = "fit",
        # --- shape / overlap params ---
        shape: Union[str, Callable, np.ndarray] = "rect",
        z_index: int = 0,
        blend_mode: str = "normal",
        opacity: Union[float, Callable] = 1.0,
        mask_type: Optional[Any] = None,
        mask_params: Optional[dict] = None,
        feather: float = 0.0,
        invert: bool = False,
        yolo_model_path: Optional[str] = None,
        position: Optional[Any] = None,
        size: Optional[Any] = None,
        anchor: str = "center",
    ):
        if filepath is None and ref_panel is None:
            raise ValueError("GridPanel: provide 'filepath' or 'ref_panel'")
        if flip is not None and flip not in ("h", "v", "both"):
            raise ValueError("GridPanel flip must be 'h', 'v', 'both', or None")

        super().__init__(
            filepath=filepath, start_time=start_time, speed=speed,
            loop=loop, flip=flip, effects=effects, resize_mode=resize_mode,
        )

        self.ref_panel = ref_panel
        self._sort_effects_yolo = True

        self.shape = shape
        self.z_index = z_index
        self.blend_mode = blend_mode.lower()
        self.opacity = opacity
        self.mask_type = mask_type
        self.mask_params = mask_params if mask_params else {}
        self.feather = feather
        self.invert = invert
        self.yolo_model_path = yolo_model_path
        self.position = position
        self.size = size
        self.anchor = anchor

    # ------------------------------------------------------------------
    # Lifecycle — ref-aware
    # ------------------------------------------------------------------

    def open(self):
        if self.ref_panel is not None:
            return
        super().open()

    # ------------------------------------------------------------------
    # Frame retrieval — ref-aware
    # ------------------------------------------------------------------

    def get_raw_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        if self.ref_panel is not None:
            return self.ref_panel.get_raw_frame(output_local_time)
        return super().get_raw_frame(output_local_time)


# ---------------------------------------------------------------------------
# GridScene
# ---------------------------------------------------------------------------

class GridScene:
    """A timeline entry that composites multiple panels.

    Panels can be arranged in a grid layout (rows x cols) or positioned
    freely via per-panel ``position``/``size`` overrides.
    Panels support custom shapes, z-ordering, blend modes, and masks.

    Args:
        panels:      ``List[GridPanel]``. Panels with ``position=None`` are
                     arranged in the grid; others use freeform positioning.
        layout:      ``(rows, cols)`` for grid-mode panels.
        duration:    Output duration in seconds.
        col_weights: Relative column widths (default equal).
        row_weights: Relative row heights (default equal).
        gap:         Normalized gap between grid cells (default 0.003).
        effects:     Full-frame effects applied after compositing all panels.
        keep_audio:  Index of the panel to pull audio from.
    """

    def __init__(
        self,
        panels: List[GridPanel],
        layout: tuple,
        duration: float,
        col_weights: Optional[List[float]] = None,
        row_weights: Optional[List[float]] = None,
        gap: float = 0.003,
        effects: Optional[list] = None,
        keep_audio: Optional[int] = None,
    ):
        rows, cols = layout
        grid_count = sum(1 for p in panels if p.position is None)
        if grid_count > rows * cols:
            raise ValueError(
                f"GridScene: layout {layout} has {rows * cols} grid slots, "
                f"but {grid_count} grid-mode panels need placement (total {len(panels)})"
            )

        self.panels      = panels
        self.rows        = rows
        self.cols        = cols
        self.duration    = float(duration)
        self.gap         = gap
        self.effects     = list(effects) if effects else []
        self.keep_audio  = keep_audio

        cw = list(col_weights) if col_weights else [1.0] * cols
        rw = list(row_weights) if row_weights else [1.0] * rows
        cw_sum = sum(cw)
        rw_sum = sum(rw)
        self.col_weights = [w / cw_sum for w in cw]
        self.row_weights = [w / rw_sum for w in rw]

    # ------------------------------------------------------------------
    # Effect builder
    # ------------------------------------------------------------------

    def add_effect(self, effect, start_time: float = 0.0, duration: Union[float, str] = -1.0) -> "GridScene":
        dur = -1.0 if duration == "clip_end" else float(duration)
        self.effects.append({
            "effect":     effect,
            "start_time": start_time,
            "duration":   dur,
        })
        return self

    # ------------------------------------------------------------------
    # Layout maths
    # ------------------------------------------------------------------

    def _compute_rects(self, output_size: tuple) -> list:
        """Return ``(x, y, w, h)`` for every grid-mode panel in row-major order."""
        tw, th = output_size
        gap    = max(1, int(self.gap * tw))

        avail_w = tw - gap * (self.cols - 1)
        avail_h = th - gap * (self.rows - 1)

        col_widths  = [int(w * avail_w) for w in self.col_weights]
        row_heights = [int(h * avail_h) for h in self.row_weights]

        col_widths[-1]  = avail_w - sum(col_widths[:-1])
        row_heights[-1] = avail_h - sum(row_heights[:-1])

        rects = []
        y = 0
        for r in range(self.rows):
            x = 0
            for c in range(self.cols):
                rects.append((x, y, col_widths[c], row_heights[r]))
                x += col_widths[c] + gap
            y += row_heights[r] + gap
        return rects

    # ------------------------------------------------------------------
    # Frame rendering
    # ------------------------------------------------------------------

    def render_frame(self, output_local_time: float, output_size: tuple) -> np.ndarray:
        """Composite all panels into a single output frame.

        Supports:
          - Grid layout and freeform positioning
          - Shape masking (circle, ellipse, diamond, custom)
          - Z-ordering for overlap
          - Blend modes (normal, multiply, screen, add, overlay, difference)
          - Opacity, YOLO masks, feathering
        """
        from utils.effects import build_frame_mask

        tw, th = output_size
        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        grid_rects = self._compute_rects(output_size)

        # Build render list with z_index
        render_items = []
        grid_idx = 0
        for panel in self.panels:
            frame = panel.get_frame(output_local_time)
            if frame is None:
                if panel.position is None:
                    grid_idx += 1
                continue

            frame = panel.apply_effects(frame, output_local_time, self.duration)
            fh, fw = frame.shape[:2]

            # Determine rect
            if panel.position is not None:
                px, py, pw, ph = _resolve_panel_rect(panel, output_size, output_local_time)
            else:
                if grid_idx >= len(grid_rects):
                    grid_idx += 1
                    continue
                px, py, pw, ph = grid_rects[grid_idx]
                grid_idx += 1

            render_items.append((panel.z_index, panel, frame, (px, py, pw, ph)))

        # Sort by z_index (ascending — lower drawn first)
        render_items.sort(key=lambda x: x[0])

        for _, panel, frame, (px, py, pw, ph) in render_items:
            fh, fw = frame.shape[:2]
            mode = panel.resize_mode

            if mode == "fill":
                scale = max(pw / fw, ph / fh)
            else:
                scale = min(pw / fw, ph / fh)

            nw, nh = int(fw * scale), int(fh * scale)
            if nw <= 0 or nh <= 0:
                continue
            resized = cv2.resize(frame, (nw, nh))

            # Prepare layer frame (cell-sized buffer)
            layer_frame = np.zeros((ph, pw, 3), dtype=np.uint8)

            if mode == "fill":
                y1 = max(0, (nh - ph) // 2)
                x1 = max(0, (nw - pw) // 2)
                layer_frame[:] = resized[y1 : y1 + ph, x1 : x1 + pw]
                content_mask = np.ones((ph, pw, 1), dtype=np.float32)
            else:
                ox = (pw - nw) // 2
                oy = (ph - nh) // 2
                layer_frame[oy : oy + nh, ox : ox + nw] = resized
                content_mask = np.zeros((ph, pw, 1), dtype=np.float32)
                content_mask[oy : oy + nh, ox : ox + nw] = 1.0

            # Shape mask (visual outline — rect, circle, etc.)
            shape_mask = make_shape_mask(panel.shape, pw, ph, output_local_time)

            # Feature mask (YOLO subject/background, geometric, etc.)
            feature_mask = build_frame_mask(
                frame=layer_frame,
                mask_type=panel.mask_type,
                mask_params=panel.mask_params,
                feather=panel.feather,
                invert=panel.invert,
                model_path=panel.yolo_model_path,
                local_time=output_local_time,
                state_holder=panel,
            )

            # Combine masks
            final_mask = shape_mask * content_mask
            if feature_mask is not None:
                final_mask = final_mask * feature_mask

            # Opacity
            _op = panel.opacity
            if callable(_op):
                _op = _op(output_local_time)
            op_val = min(1.0, max(0.0, float(_op)))
            final_mask = final_mask * op_val

            # Composite onto canvas with blend mode
            _composite_panel(canvas, layer_frame, px, py, pw, ph, final_mask, panel.blend_mode)

        # Apply full-frame scene effects
        for eff_entry in sorted(self.effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
            eff_start = eff_entry["start_time"]
            eff_dur   = eff_entry["duration"]
            if eff_dur < 0:
                eff_dur = max(0.001, self.duration - eff_start)
            eff_end = eff_start + eff_dur

            if eff_start <= output_local_time <= eff_end:
                progress    = (output_local_time - eff_start) / eff_dur
                progress    = min(1.0, max(0.0, progress))
                effect_time = output_local_time - eff_start
                canvas = eff_entry["effect"].process(canvas, effect_time, progress)

        return canvas

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def open_panels(self):
        for panel in self.panels:
            panel.open()

    def release_panels(self):
        for panel in self.panels:
            panel.release()


# ---------------------------------------------------------------------------
# Layer — freeform compositing layer
# ---------------------------------------------------------------------------

class Layer(BasePanel):
    """One layer in a LayeredScene.

    Args:
        filepath:   Source video file path.  Required unless *ref_layer* is set.
        start_time: Offset into the source (seconds) to begin reading.
        speed:      Playback speed multiplier (1.0 = normal).
        loop:       Loop the clip when it reaches its natural end (default True).
        flip:       "h" = horizontal mirror, "v" = vertical flip,
                    "both" = 180° rotation, None = no flip.
        effects:    Pre-built list of effect dicts.
        ref_layer:  Reference another Layer to share its decoded frames.
        resize_mode: "fill" or "fit" when scaling the source frame.

        # Sizing and positioning:
        position:   The position of the layer. By default (0.5, 0.5) [center].
        size:       The size of the layer. If None, keeps source size (or fits).
        anchor:     Anchor point. "center" [default], "top-left", "top-right",
                    "bottom-left", "bottom-right".
        opacity:    Opacity of the layer. Float (0.0 to 1.0) or a callable
                    taking local_time.
        blend_mode: "normal", "multiply", "screen", "add", "overlay", "difference".

        # Masking:
        mask_type:   "rect", "ellipse", "polygon", "subject", "background",
                     custom numpy array, or callable.
        mask_params: Dict of parameters for the mask.
        feather:     Pixel radius to apply Gaussian blur to the mask.
        invert:      Whether to invert the mask.
        yolo_model_path: Optional path to YOLO model.
    """

    def __init__(
        self,
        filepath: Optional[str] = None,
        start_time: float = 0.0,
        speed: float = 1.0,
        loop: bool = True,
        flip: Optional[str] = None,
        effects: Optional[list] = None,
        ref_layer: Optional["Layer"] = None,
        resize_mode: str = "fit",
        position: Any = (0.5, 0.5),
        size: Optional[Any] = None,
        anchor: str = "center",
        opacity: Any = 1.0,
        blend_mode: str = "normal",
        mask_type: Optional[Any] = None,
        mask_params: Optional[dict] = None,
        feather: float = 0.0,
        invert: bool = False,
        yolo_model_path: Optional[str] = None,
    ):
        if filepath is None and ref_layer is None:
            raise ValueError("Layer: provide 'filepath' or 'ref_layer'")

        super().__init__(
            filepath=filepath, start_time=start_time, speed=speed,
            loop=loop, flip=flip, effects=effects, resize_mode=resize_mode,
        )

        self.ref_layer = ref_layer
        self._sort_effects_yolo = False

        self.position = position
        self.size = size
        self.anchor = anchor
        self.opacity = opacity
        self.blend_mode = blend_mode.lower()
        self.mask_type = mask_type
        self.mask_params = mask_params if mask_params else {}
        self.feather = feather
        self.invert = invert
        self.yolo_model_path = yolo_model_path

        # YOLO smoothing state
        self._yolo_prev_mask = None
        self._yolo_last_good_mask = None
        self._yolo_missed_frames = 0

    # ------------------------------------------------------------------
    # Lifecycle — ref-aware
    # ------------------------------------------------------------------

    def open(self):
        if self.ref_layer is not None:
            return
        super().open()

    # ------------------------------------------------------------------
    # Frame retrieval — ref-aware
    # ------------------------------------------------------------------

    def get_raw_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        if self.ref_layer is not None:
            return self.ref_layer.get_raw_frame(output_local_time)
        return super().get_raw_frame(output_local_time)


# ---------------------------------------------------------------------------
# LayeredScene
# ---------------------------------------------------------------------------

class LayeredScene:
    """A timeline entry that composites multiple layers on top of each other.

    Args:
        layers:      List[Layer] to blend, from bottom (index 0) to top.
        duration:    Output duration in seconds.
        effects:     Full-frame effects applied after compositing all layers.
        keep_audio:  Index of the layer to pull audio from, or None.
    """

    def __init__(
        self,
        layers: List[Layer],
        duration: float,
        effects: Optional[list] = None,
        keep_audio: Optional[int] = None,
    ):
        self.layers = layers
        self.duration = float(duration)
        self.effects = list(effects) if effects else []
        self.keep_audio = keep_audio

    def add_effect(self, effect, start_time: float = 0.0, duration: Union[float, str] = -1.0) -> "LayeredScene":
        dur = -1.0 if duration == "clip_end" else float(duration)
        self.effects.append({
            "effect":     effect,
            "start_time": start_time,
            "duration":   dur,
        })
        return self

    def open_panels(self):
        for layer in self.layers:
            layer.open()

    def release_panels(self):
        for layer in self.layers:
            layer.release()

    def render_frame(self, output_local_time: float, output_size: tuple) -> np.ndarray:
        tw, th = output_size
        canvas = np.zeros((th, tw, 3), dtype=np.uint8)

        from utils.effects import build_frame_mask

        for layer in self.layers:
            frame = layer.get_frame(output_local_time)
            if frame is None:
                continue

            frame = layer.apply_effects(frame, output_local_time, self.duration)
            fh, fw = frame.shape[:2]

            # Resolve size
            ly_size = layer.size
            if callable(ly_size):
                ly_size = ly_size(output_local_time)

            if ly_size is None:
                lw, lh = tw, th
            elif isinstance(ly_size, (tuple, list)):
                lw_val, lh_val = ly_size
                lw = int(lw_val * tw) if isinstance(lw_val, float) else int(lw_val)
                lh = int(lh_val * th) if isinstance(lh_val, float) else int(lh_val)
            else:
                lw, lh = tw, th

            # Resize
            mode = layer.resize_mode
            if mode == "fill":
                scale = max(lw / fw, lh / fh)
            else:
                scale = min(lw / fw, lh / fh)

            nw, nh = int(fw * scale), int(fh * scale)
            if nw <= 0 or nh <= 0:
                continue
            resized = cv2.resize(frame, (nw, nh))

            layer_frame = np.zeros((lh, lw, 3), dtype=np.uint8)
            if mode == "fill":
                y1 = max(0, (nh - lh) // 2)
                x1 = max(0, (nw - lw) // 2)
                cropped = resized[y1 : y1 + lh, x1 : x1 + lw]
                ch, cw = cropped.shape[:2]
                layer_frame[0:ch, 0:cw] = cropped
            else:
                ox = (lw - nw) // 2
                oy = (lh - nh) // 2
                rh, rw = resized.shape[:2]
                layer_frame[max(0, oy):max(0, oy)+rh, max(0, ox):max(0, ox)+rw] = resized

            # Resolve position
            ly_pos = layer.position
            if callable(ly_pos):
                ly_pos = ly_pos(output_local_time)
            assert isinstance(ly_pos, (tuple, list)) and len(ly_pos) == 2

            px_val, py_val = ly_pos
            px = int(px_val * tw) if isinstance(px_val, float) else int(px_val)
            py = int(py_val * th) if isinstance(py_val, float) else int(py_val)

            # Anchor alignment
            anchor = layer.anchor.lower()
            if anchor == "center":
                x_offset = px - lw // 2
                y_offset = py - lh // 2
            elif anchor == "top-left":
                x_offset = px
                y_offset = py
            elif anchor == "top-right":
                x_offset = px - lw
                y_offset = py
            elif anchor == "bottom-left":
                x_offset = px
                y_offset = py - lh
            elif anchor == "bottom-right":
                x_offset = px - lw
                y_offset = py - lh
            else:
                x_offset = px - lw // 2
                y_offset = py - lh // 2

            # Build mask
            mask = build_frame_mask(
                frame=layer_frame,
                mask_type=layer.mask_type,
                mask_params=layer.mask_params,
                feather=layer.feather,
                invert=layer.invert,
                model_path=layer.yolo_model_path,
                local_time=output_local_time,
                state_holder=layer,
            )

            final_mask = np.ones((lh, lw, 1), dtype=np.float32)
            if mask is not None:
                final_mask = mask

            _op = layer.opacity
            if callable(_op):
                _op = _op(output_local_time)
            op_val = min(1.0, max(0.0, float(_op)))
            final_mask = final_mask * op_val

            _composite_panel(canvas, layer_frame, x_offset, y_offset, lw, lh, final_mask, layer.blend_mode)

        # Apply full-frame scene effects
        for eff_entry in sorted(self.effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
            eff_start = eff_entry["start_time"]
            eff_dur   = eff_entry["duration"]
            if eff_dur < 0:
                eff_dur = max(0.001, self.duration - eff_start)
            eff_end = eff_start + eff_dur

            if eff_start <= output_local_time <= eff_end:
                progress    = (output_local_time - eff_start) / eff_dur
                progress    = min(1.0, max(0.0, progress))
                effect_time = output_local_time - eff_start
                canvas = eff_entry["effect"].process(canvas, effect_time, progress)

        return canvas
