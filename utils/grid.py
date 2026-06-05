"""
utils/grid.py
-------------
Grid-layout scene support for VideoPipeline.

Usage example
-------------
from utils.grid import GridPanel, GridScene
from utils.effects import FlipEffect, ColorAdjustEffect

# Three panels: city, boy, city-mirrored
p_city  = GridPanel("city1.mkv",  loop=True)
p_boy   = GridPanel("boy1.mkv",   loop=True)
p_flip  = GridPanel(ref_panel=p_city, flip="h")   # reuses city1 frames, mirrored

# Add per-panel effects
p_boy.add_effect(ColorAdjustEffect(
    start_params={"saturation": 1.5},
    end_params={"saturation": 1.5},
))

scene = GridScene(
    panels=[p_city, p_boy, p_flip],
    layout=(1, 3),      # 1 row, 3 columns
    duration=6.0,
    col_weights=[1, 2, 1],   # middle panel is 2× wider
    gap=0.002,
)

pipeline.add_grid_scene(scene)
"""

from __future__ import annotations

from typing import List, Optional, Union, Any

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# GridPanel
# ---------------------------------------------------------------------------

class GridPanel:
    """One cell in a GridScene.

    Args:
        filepath:   Source video file path.  Required unless *ref_panel* is set.
        start_time: Offset into the source (seconds) to begin reading.
        speed:      Playback speed multiplier (1.0 = normal).
        loop:       Loop the clip when it reaches its natural end (default True).
        flip:       ``"h"`` = horizontal mirror, ``"v"`` = vertical flip,
                    ``"both"`` = 180° rotation, ``None`` = no flip.
        effects:    Pre-built list of effect dicts
                    ``{"effect": BaseEffect, "start_time": float, "duration": float}``.
                    Prefer using :meth:`add_effect` instead.
        ref_panel:  Reference another GridPanel to share its decoded frames.
                    When set, *filepath* is ignored.  The flip / effects are
                    still applied independently, so you can show the same
                    source video mirrored or colour-graded differently.
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
    ):
        if filepath is None and ref_panel is None:
            raise ValueError("GridPanel: provide 'filepath' or 'ref_panel'")
        if flip is not None and flip not in ("h", "v", "both"):
            raise ValueError("GridPanel flip must be 'h', 'v', 'both', or None")

        self.filepath   = filepath
        self.start_time = start_time
        self.speed      = speed
        self.loop       = loop
        self.flip       = flip
        self.effects    = list(effects) if effects else []
        self.ref_panel  = ref_panel
        self.resize_mode = resize_mode # "fill" or "fit"

        # Runtime state — populated by open()
        self._cap              = None
        self._source_fps       = 30.0
        self._source_duration  = 0.0   # seconds (source)
        self._last_frame       = None  # cached for this output frame (used by ref_panels)
        self._last_frame_time  = -1.0

    # ------------------------------------------------------------------
    # Effect builder
    # ------------------------------------------------------------------

    def add_effect(self, effect, start_time: float = 0.0, duration: float = -1.0) -> "GridPanel":
        """Chain-friendly effect builder.

        Args:
            effect:     Any ``BaseEffect`` instance.
            start_time: Seconds (output-local) when the effect starts.
            duration:   Seconds the effect lasts.  -1 = until panel end.
        """
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
        """Open the underlying VideoCapture.  Called by GridScene.open_panels()."""
        if self.ref_panel is not None:
            return  # shares its reference panel's cap
        if self.filepath:
            self._cap = cv2.VideoCapture(self.filepath)
        else:
            self._cap = None
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(f"GridPanel: cannot open '{self.filepath}'")
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
        """Return the raw, un-flipped, un-resized decoded frame for the given output time."""
        if self.ref_panel is not None:
            return self.ref_panel.get_raw_frame(output_local_time)

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
        
        # Optimization: Avoid redundant seeks
        last_idx = getattr(self, "_last_src_idx", -1)
        
        if src_frame_idx == last_idx + 1:
            # Sequential, just read
            pass
        elif src_frame_idx > last_idx and src_frame_idx - last_idx < 5:
            # Slightly ahead, grab few frames
            for _ in range(src_frame_idx - last_idx - 1):
                cap.grab()
        elif src_frame_idx == last_idx and self._last_frame is not None:
            # Same frame, just use the cached frame
            return self._last_frame
        else:
            # Jump
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
            
        ret, frame = cap.read()
        if not ret:
            # If we fail and it's sequential, maybe we hit EOF, try seeking once just in case
            if src_frame_idx != last_idx + 1:
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
            ret, frame = cap.read()
            if not ret: return None

        self._last_src_idx = src_frame_idx
        self._last_frame = frame
        self._last_frame_time = output_local_time
        return frame

    def get_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        """Return the BGR frame for the given OUTPUT-timeline time.

        Handles looping, speed, source offset, and ref_panel sharing.
        The returned frame is NOT yet effect-processed or resized.
        """
        raw_frame = self.get_raw_frame(output_local_time)
        if raw_frame is None:
            return None

        # Return a copy to avoid in-place mutation side-effects by panel effects
        frame = raw_frame.copy()

        # Apply flip
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
        """Apply all registered panel effects in order."""
        for eff_entry in sorted(self.effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
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
# GridScene
# ---------------------------------------------------------------------------

class GridScene:
    """A timeline entry that composites multiple panels in a grid layout.

    Args:
        panels:      ``List[GridPanel]`` in **row-major** order
                     (left→right, top→bottom).
        layout:      ``(rows, cols)`` tuple.
        duration:    Output duration in seconds.  Required (no auto-detect
                     because panels loop by default).
        col_weights: Relative column widths, e.g. ``[1, 2, 1]`` → 25 / 50 / 25 %.
                     Defaults to equal widths.
        row_weights: Relative row heights.  Defaults to equal heights.
        gap:         Pixel gap between panels (default ``0``).
        effects:     Full-frame ``BaseEffect`` instances applied *after*
                     compositing all panels.  Add via :meth:`add_effect`.
        keep_audio:  Index of the panel to pull audio from, or ``None``
                     for silence (default ``None``).

    Example — 1×3 compilation grid with middle panel doubled in width::

        p_a  = GridPanel("city1.mkv", loop=True)
        p_b  = GridPanel("boy1.mkv",  loop=True)
        p_af = GridPanel(ref_panel=p_a, flip="h")

        scene = GridScene(
            panels=[p_a, p_b, p_af],
            layout=(1, 3),
            duration=6.0,
            col_weights=[1, 2, 1],
            gap=0.002,
        )
        pipeline.add_grid_scene(scene)
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
        if len(panels) != rows * cols:
            raise ValueError(
                f"GridScene: layout {layout} expects {rows * cols} panels, got {len(panels)}"
            )

        self.panels      = panels
        self.rows        = rows
        self.cols        = cols
        self.duration    = float(duration)
        self.gap         = gap
        self.effects     = list(effects) if effects else []
        self.keep_audio  = keep_audio

        # Normalise weights
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
        """Add a full-frame effect (applies over the composited canvas)."""
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
        """Return ``(x, y, w, h)`` for every panel in row-major order."""
        tw, th = output_size
        gap    = max(1, int(self.gap * tw))

        avail_w = tw - gap * (self.cols - 1)
        avail_h = th - gap * (self.rows - 1)

        col_widths  = [int(w * avail_w) for w in self.col_weights]
        row_heights = [int(h * avail_h) for h in self.row_weights]

        # Fix rounding drift in the last cell
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

        Args:
            output_local_time: Seconds elapsed in THIS scene's output timeline.
            output_size:       ``(width, height)`` of the output frame.

        Returns:
            A ``uint8`` BGR numpy array of shape ``(height, width, 3)``.
        """
        canvas = np.zeros((output_size[1], output_size[0], 3), dtype=np.uint8)
        rects  = self._compute_rects(output_size)

        for panel, (px, py, pw, ph) in zip(self.panels, rects):
            frame = panel.get_frame(output_local_time)
            if frame is None:
                continue

            # Apply per-panel effects
            frame = panel.apply_effects(frame, output_local_time, self.duration)

            # Resizing logic (Scale-to-fit or Scale-to-fill)
            fh, fw = frame.shape[:2]
            mode = panel.resize_mode
            
            if mode == "fill":
                scale = max(pw / fw, ph / fh)
            else: # "fit"
                scale = min(pw / fw, ph / fh)
                
            nw, nh = int(fw * scale), int(fh * scale)
            if nw <= 0 or nh <= 0:
                continue
            resized = cv2.resize(frame, (nw, nh))

            if mode == "fill":
                # Crop to fit the cell exactly
                y1 = max(0, (nh - ph) // 2)
                x1 = max(0, (nw - pw) // 2)
                cropped = resized[y1 : y1 + ph, x1 : x1 + pw]
                # Paste onto canvas, ensuring we match the rect size
                ch, cw = cropped.shape[:2]
                canvas[py : py + ch, px : px + cw] = cropped
            else:
                # Centre in panel cell with black bars
                ox = px + (pw - nw) // 2
                oy = py + (ph - nh) // 2
                # Copy resized into canvas, ensuring we don't overflow
                rh, rw = resized.shape[:2]
                canvas[max(0, oy) : max(0, oy) + rh, max(0, ox) : max(0, ox) + rw] = resized

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
    # Lifecycle helpers (called by pipeline render)
    # ------------------------------------------------------------------

    def open_panels(self):
        """Open all panel VideoCaptures.  Non-ref panels are opened first."""
        for panel in self.panels:
            if panel.ref_panel is None:
                panel.open()
        for panel in self.panels:
            if panel.ref_panel is not None:
                panel.open()

    def release_panels(self):
        """Release all panel VideoCaptures."""
        for panel in self.panels:
            panel.release()


# ---------------------------------------------------------------------------
# Layered Layout Scene support
# ---------------------------------------------------------------------------

class Layer:
    """One layer in a LayeredScene.

    Args:
        filepath:   Source video file path. Required unless *ref_layer* is set.
        start_time: Offset into the source (seconds) to begin reading.
        speed:      Playback speed multiplier (1.0 = normal).
        loop:       Loop the clip when it reaches its natural end (default True).
        flip:       "h" = horizontal mirror, "v" = vertical flip, "both" = 180° rotation, None = no flip.
        ref_layer:  Reference another Layer to share its decoded frames.
        
        # Sizing and Positioning:
        position:   The position of the layer. By default (0.5, 0.5) [center].
        size:       The size of the layer (width, height). If None, keeps source size (or fits).
        anchor:     Anchor point of the layer. "center" [default], "top-left", "top-right", "bottom-left", "bottom-right".
        opacity:    Opacity of the layer. Float (0.0 to 1.0) or a callable taking local_time.
        blend_mode: "normal", "multiply", "screen", "add", "overlay", "difference".
        
        # Masking:
        mask_type:   "rect", "ellipse", "polygon", "subject", "background", custom numpy array, or callable.
        mask_params: Dict of parameters for the mask (e.g. x, y, width, height, points, etc.)
        feather:     Pixel radius to apply Gaussian blur to the mask.
        invert:      Whether to invert the mask.
        yolo_model_path: Optional path to YOLO model.
        
        resize_mode: "fill" or "fit" when scaling the source frame to the layer size.
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
        self.filepath = filepath
        self.start_time = start_time
        self.speed = speed
        self.loop = loop
        self.flip = flip
        self.effects = list(effects) if effects else []
        self.ref_layer = ref_layer
        self.resize_mode = resize_mode
        self.position = position
        self.size = size
        self.anchor = anchor
        self.opacity = opacity
        self.blend_mode = blend_mode.lower()
        self.mask_type = mask_type
        self.mask_params = mask_params
        self.feather = feather
        self.invert = invert
        self.yolo_model_path = yolo_model_path
        
        # YOLO smoothing state properties
        self._yolo_prev_mask = None
        self._yolo_last_good_mask = None
        self._yolo_missed_frames = 0

        # Runtime state
        self._cap = None
        self._source_fps = 30.0
        self._source_duration = 0.0
        self._last_frame = None
        self._last_frame_time = -1.0

    def add_effect(self, effect, start_time: float = 0.0, duration: float = -1.0) -> "Layer":
        dur = -1.0 if duration == "clip_end" else float(duration)
        self.effects.append({
            "effect": effect,
            "start_time": start_time,
            "duration": dur,
        })
        return self

    def open(self):
        if self.ref_layer is not None:
            return
        if self.filepath:
            self._cap = cv2.VideoCapture(self.filepath)
        else:
            self._cap = None
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(f"Layer: cannot open '{self.filepath}'")
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

    def get_raw_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        """Return the raw, un-flipped, un-resized decoded frame for the given output time."""
        if self.ref_layer is not None:
            return self.ref_layer.get_raw_frame(output_local_time)

        if self._last_frame_time == output_local_time and self._last_frame is not None:
            return self._last_frame

        cap = self._cap
        if cap is None:
            return None
            
        src_fps = self._source_fps
        src_start = self.start_time
        speed = self.speed
        avail = self._source_duration - src_start

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
            # Same frame, just use the cached frame
            return self._last_frame
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
            
        ret, frame = cap.read()
        if not ret:
            if src_frame_idx != last_idx + 1:
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
            ret, frame = cap.read()
            if not ret: return None

        self._last_src_idx = src_frame_idx
        self._last_frame = frame
        self._last_frame_time = output_local_time
        return frame

    def get_frame(self, output_local_time: float) -> Optional[np.ndarray]:
        raw_frame = self.get_raw_frame(output_local_time)
        if raw_frame is None:
            return None

        # Return a copy to avoid in-place mutation side-effects by layer effects
        frame = raw_frame.copy()

        if self.flip == "h":
            frame = cv2.flip(frame, 1)
        elif self.flip == "v":
            frame = cv2.flip(frame, 0)
        elif self.flip == "both":
            frame = cv2.flip(frame, -1)

        return frame

    def apply_effects(self, frame: np.ndarray, local_time: float, panel_duration: float) -> np.ndarray:
        for eff_entry in self.effects:
            eff_start = eff_entry["start_time"]
            eff_dur = eff_entry["duration"]
            if eff_dur < 0:
                eff_dur = max(0.001, panel_duration - eff_start)
            eff_end = eff_start + eff_dur

            if eff_start <= local_time <= eff_end:
                progress = (local_time - eff_start) / eff_dur
                progress = min(1.0, max(0.0, progress))
                effect_time = local_time - eff_start
                frame = eff_entry["effect"].process(frame, effect_time, progress)
        return frame


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
            "effect": effect,
            "start_time": start_time,
            "duration": dur,
        })
        return self

    def open_panels(self):
        for layer in self.layers:
            if layer.ref_layer is None:
                layer.open()
        for layer in self.layers:
            if layer.ref_layer is not None:
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

            # Apply per-layer effects
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
            else: # "fit"
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
                layer_frame[0 : ch, 0 : cw] = cropped
            else:
                ox = (lw - nw) // 2
                oy = (lh - nh) // 2
                rh, rw = resized.shape[:2]
                layer_frame[max(0, oy) : max(0, oy) + rh, max(0, ox) : max(0, ox) + rw] = resized

            # Resolve position
            ly_pos = layer.position
            if callable(ly_pos):
                ly_pos = ly_pos(output_local_time)
            
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

            # Determine coordinates on canvas
            c_x1 = max(0, x_offset)
            c_y1 = max(0, y_offset)
            c_x2 = min(tw, x_offset + lw)
            c_y2 = min(th, y_offset + lh)

            # Determine coordinates on layer_frame
            l_x1 = max(0, -x_offset)
            l_y1 = max(0, -y_offset)
            l_x2 = l_x1 + (c_x2 - c_x1)
            l_y2 = l_y1 + (c_y2 - c_y1)

            if (c_x2 - c_x1) <= 0 or (c_y2 - c_y1) <= 0:
                continue

            sub_canvas = canvas[c_y1:c_y2, c_x1:c_x2].astype(np.float32)
            sub_layer = layer_frame[l_y1:l_y2, l_x1:l_x2].astype(np.float32)

            # Build and apply mask
            mask = build_frame_mask(
                frame=layer_frame,
                mask_type=layer.mask_type,
                mask_params=layer.mask_params,
                feather=layer.feather,
                invert=layer.invert,
                model_path=layer.yolo_model_path,
                local_time=output_local_time,
                state_holder=layer
            )

            if mask is not None:
                sub_mask = mask[l_y1:l_y2, l_x1:l_x2]
            else:
                sub_mask = np.ones((l_y2 - l_y1, l_x2 - l_x1, 1), dtype=np.float32)

            # Resolve dynamic opacity
            op = layer.opacity
            if callable(op):
                op = op(output_local_time)
            op = min(1.0, max(0.0, float(op)))
            
            sub_mask = sub_mask * op

            # Blend modes
            bm = layer.blend_mode
            if bm == "normal":
                blended = sub_layer
            elif bm == "multiply":
                blended = (sub_canvas * sub_layer) / 255.0
            elif bm == "screen":
                blended = 255.0 - ((255.0 - sub_canvas) * (255.0 - sub_layer)) / 255.0
            elif bm == "add":
                blended = np.minimum(255.0, sub_canvas + sub_layer)
            elif bm == "overlay":
                low = (2.0 * sub_canvas * sub_layer) / 255.0
                high = 255.0 - (2.0 * (255.0 - sub_canvas) * (255.0 - sub_layer)) / 255.0
                blended = np.where(sub_canvas < 128.0, low, high)
            elif bm == "difference":
                blended = np.abs(sub_canvas - sub_layer)
            else:
                blended = sub_layer

            # Composite
            composited = sub_mask * blended + (1.0 - sub_mask) * sub_canvas
            canvas[c_y1:c_y2, c_x1:c_x2] = np.clip(composited, 0.0, 255.0).astype(np.uint8)

        # Apply full-frame scene effects
        for eff_entry in sorted(self.effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
            eff_start = eff_entry["start_time"]
            eff_dur = eff_entry["duration"]
            if eff_dur < 0:
                eff_dur = max(0.001, self.duration - eff_start)
            eff_end = eff_start + eff_dur

            if eff_start <= output_local_time <= eff_end:
                progress = (output_local_time - eff_start) / eff_dur
                progress = min(1.0, max(0.0, progress))
                effect_time = output_local_time - eff_start
                canvas = eff_entry["effect"].process(canvas, effect_time, progress)

        return canvas

