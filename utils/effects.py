from typing import Any, Callable, List, Optional, Tuple, Union

import cv2
import numpy as np

from utils.base import BaseEffect, EasingType
from utils.model_manager import get_yolo_model


class YoloGlowSegEffect(BaseEffect):
    def __init__(
        self,
        model_path: Optional[str] = "models/yolo26s-seg_int8_openvino_model/",
        glow_color: tuple = (0, 255, 255),
        blur_amount: float = 0.038,
        intensity: float = 1.5,
        easing: EasingType = "linear",
    ):
        """
        Creates a glow effect around people using YOLO segmentation.
        :param model_path: Path to the OpenVINO optimized YOLO segmentation model
        :param glow_color: Glow color in BGR format
        :param blur_amount: Gaussian blur kernel size as fraction of frame height (e.g. 0.038 ≈ 41px at 1080p)
        :param intensity: Intensity multiplier for the glow
        """
        super().__init__(easing=easing)
        self._yolo_priority = True
        self.model = get_yolo_model(model_path)
        self.glow_color = glow_color
        self.blur_amount = blur_amount
        self.intensity = intensity

    @staticmethod
    def _norm_kernel(norm: float, frame_dim: int) -> int:
        k = max(3, int(norm * frame_dim))
        return k if k % 2 else k + 1

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        if self.model is None:
            return frame

        # Run inference
        results = self.model.predict(
            source=frame,
            imgsz=320,  # smaller size for speed
            device="cpu",
            verbose=False,
            classes=[0],  # Only detect class 0 (person)
            retina_masks=True,  # Generate masks at original image size to fix letterboxing cutoff
        )

        result = results[0]

        h, w = frame.shape[:2]

        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks = result.masks.data.cpu().numpy()  # (N, H, W)
            combined_mask = np.max(masks, axis=0).astype(np.float16)
            self.last_good_mask = combined_mask.copy()
            self.missed_frames = 0
            # Snap immediately on first-ever detection (don't blend from zeros)
            if (
                not hasattr(self, "prev_mask")
                or self.prev_mask is None
                or self.prev_mask.shape != combined_mask.shape
            ):
                self.prev_mask = combined_mask
            else:
                self.prev_mask = (0.3 * combined_mask + 0.7 * self.prev_mask).astype(
                    np.float16
                )
        else:
            self.missed_frames = getattr(self, "missed_frames", 0) + 1
            last = getattr(self, "last_good_mask", None)
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                # Hold the last confirmed mask; decay slowly
                combined_mask = (last * (0.97**self.missed_frames)).astype(np.float16)
            else:
                combined_mask = np.zeros((h, w), dtype=np.float16)
            if (
                not hasattr(self, "prev_mask")
                or self.prev_mask is None
                or self.prev_mask.shape != combined_mask.shape
            ):
                self.prev_mask = combined_mask
            else:
                self.prev_mask = (0.15 * combined_mask + 0.85 * self.prev_mask).astype(
                    np.float16
                )

        smoothed_mask = self.prev_mask.astype(np.float32)

        # Binarize and convert to uint8 for glow dilation/blur
        combined_mask = (smoothed_mask > 0.25).astype(np.uint8) * 255

        # Early exit if entirely empty after smoothing
        if not np.any(combined_mask):
            return frame

        # Create the glow mask by dilating and blurring the person mask
        dilate_k = self._norm_kernel(0.01, h)
        kernel = np.ones((dilate_k, dilate_k), np.uint8)
        dilated_mask = cv2.dilate(combined_mask, kernel, iterations=1)
        blur_k = self._norm_kernel(self.blur_amount, h)
        glow_mask = cv2.GaussianBlur(dilated_mask, (blur_k, blur_k), 0)

        # Create colored glow layer
        glow_layer = np.zeros_like(frame)
        glow_layer[:] = self.glow_color

        # Apply mask to glow layer
        glow_alpha = (glow_mask / 255.0) * self.intensity
        glow_alpha = np.clip(glow_alpha, 0, 1)

        # Blend the glow onto the original frame
        for c in range(3):
            glow_layer[:, :, c] = glow_layer[:, :, c] * glow_alpha

        # Additive blending for a "glow" look
        output = cv2.add(frame, glow_layer)

        return output


class YoloEmissionEffect(BaseEffect):
    def __init__(
        self,
        model_path: Optional[str] = "models/yolo26s-seg_int8_openvino_model/",
        inner_color: tuple = (180, 220, 255),
        outer_color: tuple = (30, 80, 255),
        inner_radius: float = 0.014,
        outer_radius: float = 0.047,
        intensity: float = 1.0,
        pulse_speed: float = 2.5,
        pulse_amplitude: float = 0.15,
        easing: EasingType = "linear",
    ):
        super().__init__(easing=easing)
        self._yolo_priority = True
        self.model = get_yolo_model(model_path)
        self.inner_color = inner_color
        self.outer_color = outer_color
        self.inner_radius = inner_radius
        self.outer_radius = outer_radius
        self.intensity = intensity
        self.pulse_speed = pulse_speed
        self.pulse_amplitude = pulse_amplitude

    @staticmethod
    def _norm_kernel(norm: float, frame_dim: int) -> int:
        k = max(3, int(norm * frame_dim))
        return k if k % 2 else k + 1

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        if self.model is None:
            return frame

        results = self.model.predict(
            source=frame,
            imgsz=320,
            device="cpu",
            verbose=False,
            classes=[0],
            retina_masks=True,
        )
        result = results[0]
        h, w = frame.shape[:2]
        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks = result.masks.data.cpu().numpy()
            combined_mask = np.max(masks, axis=0).astype(np.float16)
            self.last_good_mask = combined_mask.copy()
            self.missed_frames = 0
            if (
                not hasattr(self, "prev_mask")
                or self.prev_mask is None
                or self.prev_mask.shape != combined_mask.shape
            ):
                self.prev_mask = combined_mask
            else:
                self.prev_mask = (0.3 * combined_mask + 0.7 * self.prev_mask).astype(
                    np.float16
                )
        else:
            self.missed_frames = getattr(self, "missed_frames", 0) + 1
            last = getattr(self, "last_good_mask", None)
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                combined_mask = (last * (0.97**self.missed_frames)).astype(np.float16)
            else:
                combined_mask = np.zeros((h, w), dtype=np.float16)
            if (
                not hasattr(self, "prev_mask")
                or self.prev_mask is None
                or self.prev_mask.shape != combined_mask.shape
            ):
                self.prev_mask = combined_mask
            else:
                self.prev_mask = (0.15 * combined_mask + 0.85 * self.prev_mask).astype(
                    np.float16
                )

        smoothed = self.prev_mask.astype(np.float32)
        binary = (smoothed > 0.25).astype(np.uint8) * 255
        if not np.any(binary):
            return frame

        pulse = 1.0 + self.pulse_amplitude * np.sin(
            current_time * self.pulse_speed * np.pi * 2
        )
        alpha = progress * self.intensity * pulse

        dilate_k = self._norm_kernel(0.01, h)
        kernel = np.ones((dilate_k, dilate_k), np.uint8)
        edge = cv2.dilate(binary, kernel, iterations=1) - cv2.erode(
            binary, kernel, iterations=1
        )

        inner_k = self._norm_kernel(self.inner_radius, h)
        outer_k = self._norm_kernel(self.outer_radius, h)
        inner_glow = cv2.GaussianBlur(edge.astype(np.float32), (inner_k, inner_k), 0)
        outer_glow = cv2.GaussianBlur(edge.astype(np.float32), (outer_k, outer_k), 0)

        inner_glow = inner_glow / 255.0
        outer_glow = outer_glow / 255.0

        emission = np.zeros_like(frame, dtype=np.float32)
        for c in range(3):
            inner_c = inner_glow * self.inner_color[c]
            outer_c = outer_glow * self.outer_color[c]
            combined = np.maximum(inner_c, outer_c)
            emission[:, :, c] = combined * alpha

        frame_f = frame.astype(np.float32)
        output = np.clip(frame_f + emission, 0, 255).astype(np.uint8)
        return output


class ZoomEffect(BaseEffect):
    def __init__(self, start_zoom=1.0, end_zoom=1.5, easing="linear"):
        super().__init__(easing=easing)
        self.start_zoom = start_zoom
        self.end_zoom = end_zoom

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        scale = self.start_zoom + (self.end_zoom - self.start_zoom) * progress

        nh, nw = int(h * scale), int(w * scale)
        if nh <= 0 or nw <= 0:
            return np.zeros_like(frame)

        resized = cv2.resize(frame, (nw, nh))

        # Crop/pad back to original size
        if scale > 1.0:
            y1 = (nh - h) // 2
            x1 = (nw - w) // 2
            return resized[y1 : y1 + h, x1 : x1 + w]
        else:
            out = np.zeros_like(frame)
            y1 = (h - nh) // 2
            x1 = (w - nw) // 2
            out[y1 : y1 + nh, x1 : x1 + nw] = resized
            return out


class ZoomToPoint(BaseEffect):
    """
    Zoom centered on a specific point (TikTok-style focus pull).

    :param center: (x, y) focal point. Normalized 0-1 floats, pixel ints,
                   or a callable(current_time) -> (x, y). Default: center (0.5, 0.5).
    :param start_zoom: starting scale (1.0 = full frame).
    :param end_zoom: ending scale.
    :param easing: easing spec.
    """

    def __init__(
        self, center=(0.5, 0.5), start_zoom=1.0, end_zoom=1.6, easing="ease_in_out"
    ):
        super().__init__(easing=easing)
        self.center = center  # stored as-is; resolved each frame
        self.start_zoom = start_zoom
        self.end_zoom = end_zoom

    @staticmethod
    def _resolve_center(center, h, w, current_time):
        """Return (cx, yx) in pixel coords, handling all three input types."""
        if callable(center):
            nx, ny = center(current_time)  # type: ignore
        elif isinstance(center, (int, float)):
            # single number → treat as both x and y (corner shortcut)
            nx = ny = float(center)
        else:
            nx, ny = center[0], center[1]
        # Clamp to [0, 1] for normalized inputs
        if nx <= 1.0 and ny <= 1.0 and nx >= 0 and ny >= 0:
            # likely normalized — but allow pixel values > 1 too by checking magnitude
            cx = int(nx * w)
            cy = int(ny * h)
        else:
            cx, cy = int(nx), int(ny)
        return cx, cy

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        scale = self.start_zoom + (self.end_zoom - self.start_zoom) * progress

        nh, nw = int(h * scale), int(w * scale)
        if nh <= 0 or nw <= 0:
            return np.zeros_like(frame)

        # Resize the full frame
        resized = cv2.resize(frame, (nw, nh))

        # Compute focal point in the *resized* image
        cx_src, cy_src = self._resolve_center(self.center, h, w, current_time)
        # Scale that point up too
        cx_src = int(cx_src * scale)
        cy_src = int(cy_src * scale)

        # We want cx_src, cy_src to land at the center of the output (w//2, h//2)
        y1 = cy_src - h // 2
        x1 = cx_src - w // 2

        # Clamp
        if scale > 1.0:
            # Crop
            y1 = max(0, min(y1, nh - h))
            x1 = max(0, min(x1, nw - w))
            return resized[y1 : y1 + h, x1 : x1 + w]
        else:
            # Pad
            out = np.zeros_like(frame)
            # Where the resized image sits in the output canvas
            oy = max(0, -y1)
            ox = max(0, -x1)
            sy = max(0, y1)
            sx = max(0, x1)
            sh = min(nh - sy, h - oy)
            sw = min(nw - sx, w - ox)
            if sh > 0 and sw > 0:
                out[oy : oy + sh, ox : ox + sw] = resized[sy : sy + sh, sx : sx + sw]
            return out


class ColorAdjustEffect(BaseEffect):
    def __init__(self, start_params: dict, end_params: dict, easing="linear"):
        """
        Animates color adjustments over time.
        Parameters for dicts:
        - saturation (default 1.0)
        - contrast (default 1.0)
        - brightness (additive offset, default 0.0)
        - gamma (default 1.0)
        """
        super().__init__(easing=easing)
        self.start_params = self._default_params(start_params)
        self.end_params = self._default_params(end_params)

    def _default_params(self, params):
        return {
            "saturation": params.get("saturation", 1.0),
            "contrast": params.get("contrast", 1.0),
            "brightness": params.get("brightness", 0.0),
            "gamma": params.get("gamma", 1.0),
        }

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        p = self.start_params
        e = self.end_params

        sat = p["saturation"] + (e["saturation"] - p["saturation"]) * progress
        con = p["contrast"] + (e["contrast"] - p["contrast"]) * progress
        bri = p["brightness"] + (e["brightness"] - p["brightness"]) * progress
        gam = p["gamma"] + (e["gamma"] - p["gamma"]) * progress

        out = frame  # work on original; copy only if we must modify it

        # Saturation
        if abs(sat - 1.0) > 1e-4:
            hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat, 0, 255)
            out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        # Contrast and Brightness
        if abs(con - 1.0) > 1e-4 or abs(bri) > 1e-4:
            out = cv2.convertScaleAbs(out, alpha=con, beta=bri)

        # Gamma correction
        if abs(gam - 1.0) > 1e-4:
            invGamma = 1.0 / gam
            table = np.array(
                [((i / 255.0) ** invGamma) * 255 for i in range(256)], dtype=np.uint8
            )
            out = cv2.LUT(out, table)

        # If none of the branches ran, return original unchanged
        return out


class BlurEffect(BaseEffect):
    def __init__(self, start_blur=0.0, end_blur=0.019, easing="linear"):
        """
        Applies a Gaussian blur that animates over time.
        :param start_blur: Starting blur kernel size as fraction of min(w,h) (0 = no blur)
        :param end_blur: Ending blur kernel size as fraction of min(w,h) (e.g. 0.019 ≈ 21px at 1080p)
        """
        super().__init__(easing=easing)
        self.start_blur = start_blur
        self.end_blur = end_blur

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        frame_dim = min(h, w)

        blur_norm = self.start_blur + (self.end_blur - self.start_blur) * progress
        kernel = max(1, int(blur_norm * frame_dim))

        if kernel % 2 == 0:
            kernel += 1

        if kernel <= 1:
            return frame

        return cv2.GaussianBlur(frame, (kernel, kernel), 0)


class RGBShiftEffect(BaseEffect):
    def __init__(self, start_shift=0.0, end_shift=0.019, angle=0.0, easing="linear"):
        """
        Shifts the Red and Blue channels in opposite directions to create a chromatic aberration effect.
        :param start_shift: Starting shift amount as fraction of min(w,h) (e.g. 0.019 ≈ 20px at 1080p)
        :param end_shift: Ending shift amount as fraction of min(w,h)
        :param angle: Angle of the shift in degrees (0 = horizontal, 90 = vertical)
        """
        super().__init__(easing=easing)
        self.start_shift = start_shift
        self.end_shift = end_shift
        self.angle_rad = np.deg2rad(angle)

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        frame_dim = min(h, w)

        shift_norm = self.start_shift + (self.end_shift - self.start_shift) * progress
        shift_amount = shift_norm * frame_dim

        if abs(shift_amount) < 0.5:
            return frame

        # Calculate shift components based on angle
        dx = shift_amount * np.cos(self.angle_rad)
        dy = shift_amount * np.sin(self.angle_rad)

        b, g, r = cv2.split(frame)

        def shift_channel(channel, shift_x, shift_y):
            M = np.array([[1, 0, shift_x], [0, 1, shift_y]], dtype=np.float32)
            return cv2.warpAffine(channel, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

        # Shift Red channel in positive direction, Blue channel in negative direction
        r_shifted = shift_channel(r, dx, dy)
        b_shifted = shift_channel(b, -dx, -dy)

        return cv2.merge((b_shifted, g, r_shifted))


class YoloTextEffect(BaseEffect):
    """
    Renders text with a custom font on the video frame, then uses YOLO person
    segmentation to composite the subject *in front of* the text — creating a
    cinematic depth-layering effect where the person stands between the camera
    and the title/caption.

    Duration model
    --------------
    The total on-screen time is set via add_clip_effect(..., duration=<total>).
    The total is split into three phases:

        |<-- transition_in -->|<------- hold ------->|<-- transition_out -->|
        0                                                               total

    Parameters
    ----------
    text            : str   — string to display
    font_path       : str   — path to .ttf/.otf file; None = PIL default
    font_size       : float — font size as fraction of frame height (default 0.074 ≈ 80pt at 1080p)
    position        : (x, y) tuple or preset string:
                      "center", "top_center", "bottom_center",
                      "top_left", "bottom_left", "top_right", "bottom_right"
    color           : (B, G, R)  — text color in BGR
    opacity         : float — peak text opacity 0.0–1.0 (default 1.0)
    transition_in   : float — seconds for the enter animation (default 0.5)
    transition_out  : float — seconds for the exit animation  (default 0.5)
    animate_in      : str   — "fade", "slide_up", "slide_down", "none"
    animate_out     : str   — "fade", "slide_up", "slide_down", "none"
    stroke_width    : float — outline width as fraction of frame height (0.0 = no outline)
    stroke_color    : (B, G, R) — outline color in BGR
    model_path      : str   — YOLO seg model path; None = no depth composite
    depth_composite : bool  — composite person on top of text if True
    easing          : easing spec (applied within each transition phase)
    """

    def __init__(
        self,
        text: str,
        font_path: Optional[str] = None,
        font_size: float = 0.074,
        position: Union[str, Tuple[int, int]] = "bottom_center",
        color: tuple = (255, 255, 255),
        opacity: float = 1.0,
        transition_in: float = 0.5,
        transition_out: float = 0.5,
        animate_in: str = "slide_up",  # "fade", "slide_up", "slide_down", "none"
        animate_out: str = "fade",  # "fade", "slide_up", "slide_down", "none"
        stroke_width: float = 0.0,
        stroke_color: tuple = (0, 0, 0),
        model_path: Optional[str] = None,
        depth_composite: bool = True,
        line_spacing: float = 1.1,
        easing: EasingType = "linear",
    ):
        super().__init__(easing=easing)
        self._yolo_priority = True
        self.text = text
        self.font_path = font_path
        self.font_size = font_size
        self.position = position
        self.color_rgba = (*color[::-1], 255)  # BGR → RGBA
        self.stroke_color_rgba = (*stroke_color[::-1], 255)
        self.opacity = opacity
        self.transition_in = transition_in
        self.transition_out = transition_out
        self.animate_in = animate_in
        self.animate_out = animate_out
        self.stroke_width = stroke_width
        self.depth_composite = depth_composite and (model_path is not None)
        self.line_spacing = line_spacing
        self.prev_mask: Optional[np.ndarray] = None
        # Cache for the rendered text layer — avoids re-drawing on every frame
        # when the phase/opacity haven't changed (e.g. during the hold phase).
        self._text_layer_cache = {}  # key → (text_np, text_alpha, text_bgr)

        # YOLO model
        self.model = (
            get_yolo_model(model_path) if self.depth_composite and model_path else None
        )

        # PIL font — lazily created in _get_font() when resolution is known
        self._font: Any = None
        self._last_font_h = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_font(self, h: int):
        abs_size = max(8, int(self.font_size * h))
        if self._font is not None and self._last_font_h == h:
            return self._font
        self._last_font_h = h
        from PIL import ImageFont
        try:
            if self.font_path:
                self._font = ImageFont.truetype(self.font_path, abs_size)
            else:
                try:
                    self._font = ImageFont.load_default(size=abs_size)
                except TypeError:
                    self._font = ImageFont.load_default()
        except Exception:
            self._font = None
        return self._font

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        """
        Returns a soft float32 (H, W) person mask in [0, 1] using robust temporal smoothing.
        The mask is NOT binarized — soft edges allow smooth per-pixel compositing.
        """
        h, w = frame.shape[:2]
        if self.model is None:
            return np.zeros((h, w), dtype=np.float32)

        results = self.model.predict(
            source=frame,
            imgsz=320,
            device="cpu",
            verbose=False,
            classes=[0],
            retina_masks=True,
        )
        result = results[0]

        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks = result.masks.data.cpu().numpy()
            combined = np.max(masks, axis=0).astype(np.float16)
            self.last_good_mask = combined.copy()
            self.missed_frames = 0
            # Snap on first-ever detection: don't blend from zeros
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                # Slow EMA so the mask boundary doesn't jump frame-to-frame
                self.prev_mask = (0.3 * combined + 0.7 * self.prev_mask).astype(
                    np.float16
                )
        else:
            self.missed_frames = getattr(self, "missed_frames", 0) + 1
            last = getattr(self, "last_good_mask", None)
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                # Hold last confirmed mask, decaying at ~3% per missed frame
                combined = (last * (0.97**self.missed_frames)).astype(np.float16)
            else:
                combined = np.zeros((h, w), dtype=np.float16)
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                # Very slow release when no detection
                self.prev_mask = (0.15 * combined + 0.85 * self.prev_mask).astype(
                    np.float16
                )

        # Step 1: Binarize at threshold so the interior of the person becomes a HARD 1.0.
        binary = (self.prev_mask.astype(np.float32) > 0.3).astype(np.uint8) * 255

        if not np.any(binary):
            return np.zeros((h, w), dtype=np.float32)

        # Step 2: Dilate to expand past YOLO's slightly-too-tight silhouette.
        dk = max(3, int(0.01 * h))
        dk = dk if dk % 2 else dk + 1
        dilate_k = np.ones((dk, dk), np.uint8)
        dilated = cv2.dilate(binary, dilate_k, iterations=1)

        # Step 3: Feather ONLY the edges with a small blur.
        #         Center stays at 1.0; only the boundary transitions to 0.
        sk = max(3, int(0.019 * h))
        sk = sk if sk % 2 else sk + 1
        soft = cv2.GaussianBlur(dilated.astype(np.float32), (sk, sk), 0) / 255.0

        return np.clip(soft, 0.0, 1.0)

    def _get_wrapped_lines(self, draw, max_width: int, font, stroke_width: int):
        """Splits the text into lines that fit within max_width."""
        words = self.text.split(" ")
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox(
                (0, 0), test_line, font=font, stroke_width=stroke_width
            )
            if (bbox[2] - bbox[0]) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def _calc_position(
        self, draw, lines: list, w: int, h: int, anim_type: str, anim_phase_p: float
    ):
        """Calculates the list of (tx, ty) for each line."""
        font = self._get_font(h)
        abs_stroke = max(0, int(self.stroke_width * h))
        abs_font_size = max(8, int(self.font_size * h))
        line_height = int(abs_font_size * self.line_spacing)

        # Calculate total height and max width of the block
        total_tw = 0
        line_data = []
        for line in lines:
            bbox = draw.textbbox(
                (0, 0), line, font=font, stroke_width=abs_stroke
            )
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            total_tw = max(total_tw, tw)
            line_data.append((tw, th))

        total_th = (
            len(lines) * line_height - (line_height - line_data[-1][1]) if lines else 0
        )

        margin = max(10, int(0.031 * w))
        presets = {
            "center": ((w - total_tw) // 2, (h - total_th) // 2),
            "top_center": ((w - total_tw) // 2, margin),
            "bottom_center": ((w - total_tw) // 2, h - total_th - margin),
            "top_left": (margin, margin),
            "bottom_left": (margin, h - total_th - margin),
            "top_right": (w - total_tw - margin, margin),
            "bottom_right": (w - total_tw - margin, h - total_th - margin),
        }

        if isinstance(self.position, (tuple, list)):
            start_x, start_y = int(self.position[0]), int(self.position[1])
        else:
            start_x, start_y = presets.get(self.position, presets["bottom_center"])

        # Animation offset
        if anim_type == "slide_up":
            start_y += int((1.0 - anim_phase_p) * h * 0.25)
        elif anim_type == "slide_down":
            start_y -= int((1.0 - anim_phase_p) * h * 0.25)

        # Return list of (x, y) for each line
        # If centered, each line needs its own x to be truly centered horizontally
        positions = []
        for i, (tw, th) in enumerate(line_data):
            cur_x = start_x
            if self.position in ["center", "top_center", "bottom_center"]:
                cur_x = (w - tw) // 2
            cur_y = start_y + i * line_height
            positions.append((cur_x, cur_y))

        return positions

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        """
        current_time = seconds since this effect started (set by the pipeline).
        progress     = current_time / total_effect_duration (0→1).
        """
        h, w = frame.shape[:2]

        # --- Derive total effect duration from current_time and progress ---
        # (avoids needing to store it separately)
        total_dur = (
            (current_time / progress)
            if progress > 0.001
            else max(self.transition_in + self.transition_out, 0.001)
        )

        t_in = min(self.transition_in, total_dur)
        t_out = min(self.transition_out, total_dur - t_in)
        hold_start = t_in
        hold_end = total_dur - t_out

        # --- Determine which phase we're in, and compute per-phase progress ---
        if current_time < hold_start and t_in > 0:
            # ── In-transition ──
            phase_p = current_time / t_in  # 0→1
            anim_type = self.animate_in
            if anim_type == "fade":
                text_opacity = phase_p * self.opacity
            else:
                text_opacity = self.opacity  # position handles the slide

        elif current_time > hold_end and t_out > 0:
            # ── Out-transition ──
            phase_p = (current_time - hold_end) / t_out  # 0→1
            anim_type = self.animate_out
            if anim_type == "fade":
                text_opacity = (1.0 - phase_p) * self.opacity
            else:
                text_opacity = self.opacity

        else:
            # ── Hold phase: fully visible at rest position ──
            phase_p = 1.0
            anim_type = "none"
            text_opacity = self.opacity

        if text_opacity <= 0.0:
            return frame

        # --- Build RGBA text layer via PIL (cached when phase hasn't changed) ---
        cache_key = (
            anim_type,
            round(phase_p, 3),  # quantise to skip trivial float drift
            round(text_opacity, 4),
            w,
            h,
        )
        if cache_key in self._text_layer_cache:
            text_alpha, text_bgr = self._text_layer_cache[cache_key]
        else:
            from PIL import Image, ImageDraw

            text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(text_layer)
            font = self._get_font(h)
            abs_stroke = max(0, int(self.stroke_width * h))

            # Wrap text to fit width (with ~4% margin on each side)
            max_tw = int(w * 0.92)
            lines = self._get_wrapped_lines(draw, max_tw, font, abs_stroke)

            line_positions = self._calc_position(draw, lines, w, h, anim_type, phase_p)

            text_fill = (*self.color_rgba[:3], int(text_opacity * 255))
            stroke_fill = (*self.stroke_color_rgba[:3], int(text_opacity * 255))

            for i, line in enumerate(lines):
                tx, ty = line_positions[i]
                draw.text(
                    (tx, ty),
                    line,
                    font=font,
                    fill=text_fill,
                    stroke_width=abs_stroke,
                    stroke_fill=stroke_fill if abs_stroke > 0 else None,
                )

            text_np = np.array(text_layer, dtype=np.float32)  # (H, W, 4)
            text_alpha = text_np[:, :, 3:4] / 255.0  # (H, W, 1)
            text_bgr = text_np[:, :, :3][:, :, ::-1]  # RGB → BGR
            del text_layer
            del text_np

            # Keep only the most recent cache entry to bound memory
            self._text_layer_cache.clear()
            self._text_layer_cache[cache_key] = (text_alpha, text_bgr)

        output = frame.astype(np.float32)
        output = output * (1.0 - text_alpha) + text_bgr * text_alpha

        # --- Depth composite: person pixels restore on top of text ---
        if self.depth_composite and self.model is not None:
            person_mask = self._get_mask(frame)[:, :, np.newaxis]  # (H, W, 1)
            output = (
                output * (1.0 - person_mask) + frame.astype(np.float32) * person_mask
            )

        return np.clip(output, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Mask builder helpers
# ---------------------------------------------------------------------------


def rect_mask(
    frame_size: tuple,
    x: float,
    y: float,
    width: float,
    height: float,
    normalized: bool = True,
) -> np.ndarray:
    """
    Build a float32 (H, W) binary mask for a rectangle.

    Args:
        frame_size: (width, height) of the output frame.
        x, y:       Top-left corner. Normalized [0, 1] when ``normalized=True``,
                    otherwise pixel coordinates.
        width, height: Rectangle size (normalized or pixels, matching *x/y*).
        normalized: If True all coordinates are expressed as fractions of the
                    frame dimensions. Default True.

    Returns:
        float32 mask of shape (H, W) with 1.0 inside the rect, 0.0 outside.
    """
    fw, fh = frame_size
    if normalized:
        px, py = int(x * fw), int(y * fh)
        pw, ph = int(width * fw), int(height * fh)
    else:
        px, py, pw, ph = int(x), int(y), int(width), int(height)

    mask = np.zeros((fh, fw), dtype=np.float32)
    x1, y1 = max(0, px), max(0, py)
    x2, y2 = min(fw, px + pw), min(fh, py + ph)
    mask[y1:y2, x1:x2] = 1.0
    return mask


def ellipse_mask(
    frame_size: tuple,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    normalized: bool = True,
) -> np.ndarray:
    """
    Build a float32 (H, W) binary mask for an ellipse.

    Args:
        frame_size: (width, height) of the output frame.
        cx, cy:     Centre of the ellipse (normalized or pixels).
        rx, ry:     Semi-axes (normalized or pixels).
        normalized: If True all coordinates are fractions of frame dims.

    Returns:
        float32 mask with 1.0 inside the ellipse.
    """
    fw, fh = frame_size
    if normalized:
        cx, cy = int(cx * fw), int(cy * fh)
        rx, ry = int(rx * fw), int(ry * fh)
    else:
        cx, cy, rx, ry = int(cx), int(cy), int(rx), int(ry)

    mask = np.zeros((fh, fw), dtype=np.float32)
    cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 1.0, -1)
    return mask


def polygon_mask(
    frame_size: tuple,
    points: list,
    normalized: bool = True,
) -> np.ndarray:
    """
    Build a float32 (H, W) binary mask for a filled polygon.

    Args:
        frame_size: (width, height) of the output frame.
        points:     List of (x, y) tuples (normalized or pixels).
        normalized: If True coordinates are fractions of frame dims.

    Returns:
        float32 mask with 1.0 inside the polygon.
    """
    fw, fh = frame_size
    if normalized:
        pts = [(int(px * fw), int(py * fh)) for px, py in points]
    else:
        pts = [(int(px), int(py)) for px, py in points]

    mask = np.zeros((fh, fw), dtype=np.float32)
    poly = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [poly], 1.0)
    return mask


# ---------------------------------------------------------------------------
# MaskedEffect wrapper
# ---------------------------------------------------------------------------


class MaskedEffect(BaseEffect):
    """
    Constrains any ``BaseEffect`` to a specific region of the frame.

    The *unaffected* portion of the frame is left untouched; the *affected*
    region is blended using a soft alpha mask so you can feather the edges
    for a seamless look.

    Mask can be provided as:
      • A pre-built float32 numpy array (H, W) with values 0–1.
      • A string shorthand (``"rect"``, ``"ellipse"``, ``"polygon"``) together
        with the matching ``region`` keyword arguments.

    Parameters
    ----------
    effect : BaseEffect
        The wrapped effect instance (e.g. ``BlurEffect()``, ``ZoomEffect()``…).
    mask : np.ndarray | str
        Either a pre-built float32 (H, W) mask **or** one of the string
        shorthands: ``"rect"``, ``"ellipse"``, ``"polygon"``.
    frame_size : tuple (width, height)
        Required when *mask* is a string so the helper can build the mask.
    feather : float
        Gaussian blur radius as fraction of frame height applied to the mask
        to soften the edges. 0 = hard edge, larger values = smoother blend.
        Default 0.
    invert : bool
        If True, the effect is applied *outside* the mask instead of inside.
        Default False.
    normalized : bool
        Passed to the mask builders when *mask* is a string. Default True.

    Region keyword arguments (used when *mask* is a string)
    --------------------------------------------------------
    For ``"rect"``    → ``x``, ``y``, ``width``, ``height``
    For ``"ellipse"`` → ``cx``, ``cy``, ``rx``, ``ry``
    For ``"polygon"`` → ``points`` (list of (x, y) tuples)

    Examples
    --------
    # Blur only the bottom-center quarter of the frame (normalized coords):
    blur = BlurEffect(start_blur=0.0, end_blur=0.038)
    masked = MaskedEffect(
        blur,
        mask="rect",
        frame_size=(1920, 1080),
        x=0.25, y=0.75, width=0.5, height=0.25,
        feather=0.037,
    )
    pipeline.add_clip_effect(clip_idx=0, effect=masked, duration=3.0)

    # Vignette-style: invert an ellipse so everything *outside* is darkened:
    color = ColorAdjustEffect(
        start_params={"brightness": -80, "saturation": 0.5},
        end_params={"brightness": -80, "saturation": 0.5},
    )
    vignette = MaskedEffect(
        color,
        mask="ellipse",
        frame_size=(1920, 1080),
        cx=0.5, cy=0.5, rx=0.4, ry=0.4,
        feather=0.111,
        invert=True,
    )
    pipeline.add_clip_effect(clip_idx=0, effect=vignette, duration=CLIP_END)
    """

    def __init__(
        self,
        effect: BaseEffect,
        mask,
        frame_size: Optional[tuple] = None,
        feather: float = 0.0,
        invert: bool = False,
        normalized: bool = True,
        **region_kwargs,
    ):
        # MaskedEffect inherits easing from the wrapped effect — do NOT pass
        # easing again because the inner effect has already captured it.
        super().__init__(easing="linear")
        self.inner_effect = effect
        self.feather = feather
        self.invert = invert
        self._frame_size = frame_size

        # Build / store the mask -----------------------------------------
        if isinstance(mask, np.ndarray):
            # Pre-built mask: just store it (will be rescaled lazily if needed)
            self._static_mask = mask.astype(np.float32)
            self._mask_type = "static"
        elif isinstance(mask, str):
            if frame_size is None:
                raise ValueError(
                    "frame_size=(width, height) is required when mask is a string."
                )
            self._mask_type = mask.lower()
            self._region_kw = region_kwargs
            self._normalized = normalized
            self._static_mask = self._build_mask(frame_size)
        else:
            raise TypeError(f"mask must be an ndarray or string, got {type(mask)}")

        # Pre-apply feathering once (only for static-sized frames)
        self._cached_alpha: Optional[np.ndarray] = None
        if self._frame_size is not None:
            self._cached_alpha = self._make_alpha(self._static_mask)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_mask(self, frame_size: tuple) -> np.ndarray:
        """Build the raw binary mask from string shorthand + region kwargs."""
        kw = self._region_kw
        n = self._normalized
        mt = self._mask_type
        if mt == "rect":
            return rect_mask(frame_size, kw["x"], kw["y"], kw["width"], kw["height"], n)
        elif mt == "ellipse":
            return ellipse_mask(frame_size, kw["cx"], kw["cy"], kw["rx"], kw["ry"], n)
        elif mt == "polygon":
            return polygon_mask(frame_size, kw["points"], n)
        else:
            raise ValueError(
                f"Unknown mask type '{mt}'. Use 'rect', 'ellipse', or 'polygon'."
            )

    def _make_alpha(self, raw_mask: np.ndarray) -> np.ndarray:
        """Apply feathering + invert and return a (H, W, 1) float32 alpha."""
        alpha = raw_mask.copy()
        if self.feather > 0:
            h = alpha.shape[0]
            k = max(3, int(self.feather * h))
            k = k if k % 2 else k + 1
            alpha = cv2.GaussianBlur(alpha, (k, k), 0)
        if self.invert:
            alpha = 1.0 - alpha
        alpha = np.clip(alpha, 0.0, 1.0)
        return alpha[:, :, np.newaxis]  # (H, W, 1) for broadcast

    def _get_alpha(self, frame: np.ndarray) -> np.ndarray:
        """
        Returns the (H, W, 1) alpha for the current frame.
        Rebuilds the mask lazily if the frame resolution doesn't match the
        cached one (e.g. first call when frame_size wasn't provided).
        """
        fh, fw = frame.shape[:2]
        if self._cached_alpha is not None and self._cached_alpha.shape[:2] == (fh, fw):
            return self._cached_alpha

        # Need to build / rescale
        if self._mask_type == "static":
            # Rescale the static mask to match current frame
            resized = cv2.resize(
                self._static_mask, (fw, fh), interpolation=cv2.INTER_LINEAR
            )
            self._cached_alpha = self._make_alpha(resized)
        else:
            raw = self._build_mask((fw, fh))
            self._cached_alpha = self._make_alpha(raw)

        return self._cached_alpha

    # ------------------------------------------------------------------
    # BaseEffect interface
    # ------------------------------------------------------------------

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        """
        1. Run the inner effect on the full frame.
        2. Blend the result back using the feathered mask so only the masked
           region shows the effect.
        """
        # The inner effect already has its own easing baked in; call its
        # process() (not apply()) so easing is applied correctly.
        effected = self.inner_effect.process(frame, current_time, progress)

        alpha = self._get_alpha(frame)  # (H, W, 1) float32

        orig = frame.astype(np.float32)
        effected_f = effected.astype(np.float32)

        blended = orig * (1.0 - alpha) + effected_f * alpha
        return np.clip(blended, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# YoloSegMaskedEffect
# ---------------------------------------------------------------------------


class YoloSegMaskedEffect(BaseEffect):
    """
    Uses live YOLO person segmentation as a per-frame alpha mask to apply
    any ``BaseEffect`` selectively to the **subject** or the **background**.

    This is the dynamic counterpart of ``MaskedEffect``: instead of a fixed
    geometric region the mask is re-inferred on every frame and temporally
    smoothed to remove flicker — using exactly the same EMA strategy as
    ``YoloGlowSegEffect`` and ``YoloTextEffect``.

    Parameters
    ----------
    effect : BaseEffect
        The effect to apply inside the mask.  Any existing effect works:
        ``BlurEffect``, ``ColorAdjustEffect``, ``ZoomEffect``,
        ``RGBShiftEffect``, etc.
    model_path : str
        Path to the YOLO segmentation model (OpenVINO or .pt).
    target : str
        ``"subject"`` — effect is applied to the person only (default).
        ``"background"`` — effect is applied everywhere *except* the person.
    feather : float
        Extra Gaussian blur radius as fraction of frame height added on top
        of the built-in YOLO soft mask to further soften the edge.
        0 = use the mask as-is.
    easing : str | tuple | callable
        Easing applied to the overall *progress* value passed to the inner
        effect.  Defaults to ``"linear"`` (inner effect's own easing handles
        the rest).

    Examples
    --------
    Desaturate the background while the subject stays in full colour::

        from utils.effects import ColorAdjustEffect, YoloSegMaskedEffect, CLIP_END

        bg_desat = YoloSegMaskedEffect(
            ColorAdjustEffect(
                start_params={"saturation": 0.0},
                end_params={"saturation": 0.0},
            ),
            model_path="models/yolo26n-seg_openvino_model/",
            target="background",
            feather=0.014,
        )
        pipeline.add_clip_effect(clip_idx=0, effect=bg_desat)

    Blur only the subject::

        from utils.effects import BlurEffect, YoloSegMaskedEffect

        subject_blur = YoloSegMaskedEffect(
            BlurEffect(start_blur=0.0, end_blur=0.029),
            model_path="models/yolo26n-seg_openvino_model/",
            target="subject",
            feather=0.009,
        )
        pipeline.add_clip_effect(clip_idx=0, effect=subject_blur, duration=3.0)

    Cinematic colour grade on the background (warm highlights)::

        bg_grade = YoloSegMaskedEffect(
            ColorAdjustEffect(
                start_params={"brightness": 20, "contrast": 1.1, "saturation": 0.6},
                end_params={"brightness": 20, "contrast": 1.1, "saturation": 0.6},
            ),
            model_path="models/yolo26n-seg_openvino_model/",
            target="background",
            feather=0.019,
        )
    """

    def __init__(
        self,
        effect: BaseEffect,
        model_path: Optional[str] = None,
        target: str = "subject",  # "subject" | "background"
        feather: float = 0.0,
        easing: EasingType = "linear",
    ):
        super().__init__(easing=easing)
        self._yolo_priority = True
        self.inner_effect = effect
        self.model = get_yolo_model(model_path)
        self.target = target.lower()
        self.feather = feather

        # Temporal smoothing state (mirrors YoloGlowSegEffect / YoloTextEffect)
        self.prev_mask: Optional[np.ndarray] = None
        self.last_good_mask: Optional[np.ndarray] = None
        self.missed_frames = 0

    # ------------------------------------------------------------------
    # Mask inference (same robust EMA as the other Yolo effects)
    # ------------------------------------------------------------------

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        """
        Returns a soft float32 (H, W, 1) alpha in [0, 1].
        - 1.0  = person pixel  (when target="subject",    effect is applied here)
        - 0.0  = background    (when target="background", effect is applied here after invert)
        """
        h, w = frame.shape[:2]

        if self.model is None:
            return np.zeros((h, w), dtype=np.float16)

        results = self.model.predict(
            source=frame,
            imgsz=320,
            device="cpu",
            verbose=False,
            classes=[0],  # person only
            retina_masks=True,
        )
        result = results[0]

        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks = result.masks.data.cpu().numpy()  # (N, H, W)
            combined = np.max(masks, axis=0).astype(np.float16)  # union of all persons
            self.last_good_mask = combined.copy()
            self.missed_frames = 0
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                self.prev_mask = (0.3 * combined + 0.7 * self.prev_mask).astype(
                    np.float16
                )
        else:
            self.missed_frames += 1
            last = self.last_good_mask
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                combined = (last * (0.97**self.missed_frames)).astype(np.float16)
            else:
                combined = np.zeros((h, w), dtype=np.float16)
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                self.prev_mask = (0.15 * combined + 0.85 * self.prev_mask).astype(
                    np.float16
                )

        # ── Binarize → dilate → soft-feather (same 3-step pipeline as YoloTextEffect) ──
        binary = (self.prev_mask.astype(np.float32) > 0.3).astype(np.uint8) * 255
        if not np.any(binary):
            return np.zeros((h, w, 1), dtype=np.float32)

        dk = max(3, int(0.01 * h))
        dk = dk if dk % 2 else dk + 1
        dilate_k = np.ones((dk, dk), np.uint8)
        dilated = cv2.dilate(binary, dilate_k, iterations=1)
        sk = max(3, int(0.019 * h))
        sk = sk if sk % 2 else sk + 1
        soft = cv2.GaussianBlur(dilated.astype(np.float32), (sk, sk), 0) / 255.0

        # Optional extra feathering requested by the user
        if self.feather > 0:
            k = max(3, int(self.feather * h))
            k = k if k % 2 else k + 1
            soft = cv2.GaussianBlur(soft.astype(np.float32), (k, k), 0)

        alpha = np.clip(soft, 0.0, 1.0)

        # Invert for "background" target
        if self.target == "background":
            alpha = 1.0 - alpha

        return alpha[:, :, np.newaxis]  # (H, W, 1) for broadcast

    # ------------------------------------------------------------------
    # BaseEffect interface
    # ------------------------------------------------------------------

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        """
        1. Run the wrapped effect on the *whole* frame to get the effected version.
        2. Blend original ↔ effected using the live YOLO mask as alpha.
        """
        # Inner effect: call process() so its own easing is applied
        effected = self.inner_effect.process(frame, current_time, progress)

        alpha = self._get_mask(frame)  # (H, W, 1) float32

        orig = frame.astype(np.float32)
        effected_f = effected.astype(np.float32)

        # alpha=1 → show effected,  alpha=0 → show original
        blended = orig * (1.0 - alpha) + effected_f * alpha
        return np.clip(blended, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# FlipEffect
# ---------------------------------------------------------------------------


class FlipEffect(BaseEffect):
    """Mirrors or flips the frame.

    Args:
        mode: ``"h"``    – horizontal mirror (left ↔ right)  [default]
              ``"v"``    – vertical flip    (top ↔ bottom)
              ``"both"`` – 180° rotation (flip both axes)
    """

    def __init__(self, mode: str = "h"):
        super().__init__(easing="linear")
        if mode not in ("h", "v", "both"):
            raise ValueError("FlipEffect mode must be 'h', 'v', or 'both'")
        self._cv_code = {"h": 1, "v": 0, "both": -1}[mode]

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        return cv2.flip(frame, self._cv_code)


# ---------------------------------------------------------------------------
# GLSL Shader and Custom Masking Helpers
# ---------------------------------------------------------------------------

_gl_context = None


def get_gl_context():
    global _gl_context
    if _gl_context is None:
        import moderngl

        _gl_context = moderngl.create_context(standalone=True)
    return _gl_context


class GLSLEffect(BaseEffect):
    """
    Applies a custom GLSL fragment shader to the video frame.
    Supports time, progress, resolution, texture input, and custom uniforms.
    """

    def __init__(
        self,
        fragment_shader_code: str,
        vertex_shader_code: Optional[str] = None,
        uniforms: Optional[dict] = None,
        easing: EasingType = "linear",
    ):
        super().__init__(easing=easing)
        self.fragment_shader_code = fragment_shader_code
        self.vertex_shader_code = (
            vertex_shader_code
            or """
        #version 330
        in vec2 in_vert;
        in vec2 in_uv;
        out vec2 v_uv;
        void main() {
            gl_Position = vec4(in_vert, 0.0, 1.0);
            v_uv = in_uv;
        }
        """
        )
        self.uniforms = uniforms or {}

        # GPU state variables
        self.ctx = None
        self.prog = None
        self.vao = None
        self.vbo = None
        self.tex_in = None
        self.tex_out = None
        self.fbo = None
        self.last_res = None

    def _init_gl(self, w: int, h: int):
        import moderngl

        self.ctx = get_gl_context()
        self.prog = self.ctx.program(
            vertex_shader=self.vertex_shader_code,
            fragment_shader=self.fragment_shader_code,
        )

        vertices = np.array(
            [
                -1.0,
                -1.0,
                0.0,
                0.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                -1.0,
                1.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ],
            dtype="f4",
        )
        self.vbo = self.ctx.buffer(vertices.tobytes())
        self.vao = self.ctx.vertex_array(
            self.prog, [(self.vbo, "2f 2f", "in_vert", "in_uv")]
        )

        self.tex_in = self.ctx.texture((w, h), 3)
        self.tex_out = self.ctx.texture((w, h), 3)
        self.fbo = self.ctx.framebuffer(color_attachments=[self.tex_out])
        self.last_res = (w, h)

    def _release_gl(self):
        if self.vbo:
            try:
                self.vbo.release()
            except Exception:
                pass
            self.vbo = None
        if self.vao:
            try:
                self.vao.release()
            except Exception:
                pass
            self.vao = None
        if self.tex_in:
            try:
                self.tex_in.release()
            except Exception:
                pass
            self.tex_in = None
        if self.tex_out:
            try:
                self.tex_out.release()
            except Exception:
                pass
            self.tex_out = None
        if self.fbo:
            try:
                self.fbo.release()
            except Exception:
                pass
            self.fbo = None
        self.prog = None
        self.last_res = None

    def __del__(self):
        try:
            self._release_gl()
        except Exception:
            pass

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        if self.last_res != (w, h):
            self._release_gl()
            self._init_gl(w, h)

        assert (
            self.tex_in is not None
            and self.fbo is not None
            and self.prog is not None
            and self.vao is not None
            and self.ctx is not None
        )

        import moderngl

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Upload
        self.tex_in.write(rgb_frame.tobytes())

        # Bind and render
        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.tex_in.use(0)

        # Set default uniforms if they are in program
        if "tex" in self.prog:
            self.prog["tex"].value = 0
        if "resolution" in self.prog:
            self.prog["resolution"].value = (float(w), float(h))
        if "time" in self.prog:
            self.prog["time"].value = float(current_time)
        if "progress" in self.prog:
            self.prog["progress"].value = float(progress)

        # Set custom uniforms
        for name, val in self.uniforms.items():
            if name in self.prog:
                if isinstance(val, (tuple, list)):
                    self.prog[name].value = tuple(val)
                elif isinstance(val, np.ndarray):
                    self.prog[name].value = tuple(val.tolist())
                else:
                    self.prog[name].value = val

        self.vao.render(moderngl.TRIANGLE_STRIP)

        # Read back
        out_bytes = self.fbo.read(components=3, alignment=1)
        out_rgb = np.frombuffer(out_bytes, dtype=np.uint8).reshape((h, w, 3))

        # Convert RGB to BGR
        return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)


def build_frame_mask(
    frame: np.ndarray,
    mask_type: Optional[Union[str, np.ndarray, Callable]],
    mask_params: Optional[dict] = None,
    feather: float = 0.0,
    invert: bool = False,
    model_path: Optional[str] = None,
    local_time: float = 0.0,
    state_holder: Optional[Any] = None,
) -> Optional[np.ndarray]:
    """
    Builds a float32 mask of shape (H, W, 1) in [0, 1] for a given frame.
    Supports geometric shapes ("rect", "ellipse", "polygon"), YOLO ("subject", "background"),
    custom numpy arrays, and callables.

    state_holder: An object (like a panel or effect instance) to store temporal smoothing state
                  for YOLO masks.
    """
    h, w = frame.shape[:2]

    if mask_type is None:
        return None

    if isinstance(mask_type, np.ndarray):
        # Resize static mask to match frame
        if mask_type.shape[:2] != (h, w):
            mask = cv2.resize(
                mask_type.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR
            )
        else:
            mask = mask_type.astype(np.float32)
        if len(mask.shape) == 2:
            mask = mask[:, :, np.newaxis]
    elif callable(mask_type):
        mask = mask_type((w, h), local_time)
        if not isinstance(mask, np.ndarray):
            return None
        mask = mask.astype(np.float32)
        if len(mask.shape) == 2:
            mask = mask[:, :, np.newaxis]
    elif isinstance(mask_type, str):
        mt = mask_type.lower()
        params = mask_params or {}
        if mt in ("rect", "ellipse", "polygon"):
            # Geometric masks
            if mt == "rect":
                raw = rect_mask(
                    (w, h),
                    params.get("x", 0.0),
                    params.get("y", 0.0),
                    params.get("width", 1.0),
                    params.get("height", 1.0),
                    params.get("normalized", True),
                )
            elif mt == "ellipse":
                raw = ellipse_mask(
                    (w, h),
                    params.get("cx", 0.5),
                    params.get("cy", 0.5),
                    params.get("rx", 0.5),
                    params.get("ry", 0.5),
                    params.get("normalized", True),
                )
            else:  # polygon
                raw = polygon_mask(
                    (w, h), params.get("points", []), params.get("normalized", True)
                )
            mask = raw[:, :, np.newaxis]
        elif mt in ("subject", "background"):
            # YOLO mask
            model = get_yolo_model(model_path)
            if model is None:
                return np.zeros((h, w, 1), dtype=np.float32)

            results = model.predict(
                source=frame,
                imgsz=320,
                device="cpu",
                verbose=False,
                classes=[0],
                retina_masks=True,
            )
            result = results[0]

            has_detection = result.masks is not None and len(result.masks.data) > 0

            # Retrieve smoothing state from state_holder if available
            prev_mask = (
                getattr(state_holder, "_yolo_prev_mask", None) if state_holder else None
            )
            last_good_mask = (
                getattr(state_holder, "_yolo_last_good_mask", None)
                if state_holder
                else None
            )
            missed_frames = (
                getattr(state_holder, "_yolo_missed_frames", 0) if state_holder else 0
            )

            if has_detection:
                masks = result.masks.data.cpu().numpy()
                combined = np.max(masks, axis=0).astype(np.float16)
                last_good_mask = combined.copy()
                missed_frames = 0
                if prev_mask is None or prev_mask.shape != combined.shape:
                    prev_mask = combined
                else:
                    prev_mask = (0.3 * combined + 0.7 * prev_mask).astype(np.float16)
            else:
                missed_frames += 1
                if (
                    last_good_mask is not None
                    and last_good_mask.shape == (h, w)
                    and missed_frames <= 15
                ):
                    combined = (last_good_mask * (0.97**missed_frames)).astype(
                        np.float16
                    )
                else:
                    combined = np.zeros((h, w), dtype=np.float16)
                if prev_mask is None or prev_mask.shape != combined.shape:
                    prev_mask = combined
                else:
                    prev_mask = (0.15 * combined + 0.85 * prev_mask).astype(np.float16)

            # Save smoothing state back to state_holder
            if state_holder:
                state_holder._yolo_prev_mask = prev_mask
                state_holder._yolo_last_good_mask = last_good_mask
                state_holder._yolo_missed_frames = missed_frames

            binary = (prev_mask.astype(np.float32) > 0.3).astype(np.uint8) * 255
            if not np.any(binary):
                mask = np.zeros((h, w, 1), dtype=np.float32)
            else:
                dk = max(3, int(0.01 * h))
                dk = dk if dk % 2 else dk + 1
                dilate_k = np.ones((dk, dk), np.uint8)
                dilated = cv2.dilate(binary, dilate_k, iterations=1)
                bk = params.get("blur_kernel")
                if bk is not None and bk == 0:
                    mask = dilated.astype(np.float32)[:, :, np.newaxis] / 255.0
                else:
                    sk = max(3, int(0.019 * h))
                    sk = sk if sk % 2 else sk + 1
                    soft = cv2.GaussianBlur(dilated.astype(np.float32), (sk, sk), 0) / 255.0
                    mask = soft[:, :, np.newaxis]

            if mt == "background":
                mask = 1.0 - mask
        else:
            raise ValueError(f"Unknown mask type: {mt}")
    else:
        return None

    # Apply extra feathering if requested
    if feather > 0:
        k = max(3, int(feather * h))
        k = k if k % 2 else k + 1
        mask_s = cv2.GaussianBlur(np.asarray(mask, dtype=np.float32), (k, k), 0.0)
        if len(mask_s.shape) == 2:
            mask = mask_s[:, :, np.newaxis]
        else:
            mask = mask_s

    if invert:
        mask = 1.0 - mask

    return np.clip(mask, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Ken Burns: slow cinematic drift + zoom via GLSL
# ---------------------------------------------------------------------------

_KEN_BURNS_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform vec2 center;      // normalized focal point, e.g. (0.3, 0.6)
uniform float zoom_out;   // start zoom factor (e.g. 1.05)
uniform float zoom_in;    // end zoom factor   (e.g. 1.25)
uniform float drift_x;    // pan amount in UV space, e.g. 0.02
uniform float drift_y;

void main() {
    // Eased progress is supplied as-is; we remap to a smooth 0->1 arc
    float t = progress;

    // Lerp zoom
    float z = mix(zoom_out, zoom_in, t);

    // Center the look
    vec2 focus = center;

    // Drift is time-based + progress-based so it feels alive even on short clips
    vec2 pan = vec2(drift_x, drift_y) * (0.5 + 0.5 * sin(time * 0.15)) * t;

    // Compute UV so that (focus + pan) maps to the center of the screen
    vec2 uv = (v_uv - 0.5) / z + focus + pan;

    // Subtle vignette by darkening edges
    float vig = 1.0 - 0.35 * length(v_uv - 0.5);

    vec3 col = texture(tex, uv).rgb;
    col *= vig;

    fragColor = vec4(col, 1.0);
}
"""


class KenBurnsEffect(GLSLEffect):
    """
    Cinematic slow-zoom drift effect for still images or slow-motion clips.

    Defaults produce a gentle "push in + drift" feel. Tune the params to taste.

    :param center: focal point in normalized 0-1 coords, e.g. (0.35, 0.65)
    :param zoom_out: starting scale (1.0 = full frame)
    :param zoom_in:  ending scale
    :param drift_x/y: drift amplitude in UV space (~0.01-0.05 is subtle)
    :param easing: easing spec applied to the whole sequence
    """

    def __init__(
        self,
        center: tuple = (0.5, 0.5),
        zoom_out: float = 1.06,
        zoom_in: float = 1.18,
        drift_x: float = 0.02,
        drift_y: float = 0.01,
        easing: EasingType = "ease_in_out",
    ):
        super().__init__(
            fragment_shader_code=_KEN_BURNS_SHADER,
            uniforms={
                "center": tuple(float(v) for v in center),
                "zoom_out": float(zoom_out),
                "zoom_in": float(zoom_in),
                "drift_x": float(drift_x),
                "drift_y": float(drift_y),
            },
            easing=easing,
        )


# ---------------------------------------------------------------------------
# Grid-optimised panel effects
# ---------------------------------------------------------------------------


class PanelSlideEffect(BaseEffect):
    """Slides panel content in/out from a direction.

    Useful for grid panels: each panel can slide independently on beat,
    creating a dynamic staggered reveal.

    :param direction: ``"left"``, ``"right"``, ``"up"``, ``"down"``.
    :param start_offset: Normalised offset at progress=0 (1.0 = fully slid out).
    :param end_offset:   Normalised offset at progress=1 (0.0 = rest position).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        direction: str = "left",
        start_offset: float = 1.0,
        end_offset: float = 0.0,
        easing: EasingType = "ease_out",
    ):
        super().__init__(easing=easing)
        self.direction = direction
        self.start_offset = start_offset
        self.end_offset = end_offset

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        offset = self.start_offset + (self.end_offset - self.start_offset) * progress
        shift = int(offset * w)
        out = np.zeros_like(frame)

        if self.direction == "left":
            if shift >= 0:
                out[:, : max(0, w - shift)] = frame[:, min(w, shift) :]
            else:
                s = min(w, -shift)
                out[:, w - s :] = frame[:, :s]
        elif self.direction == "right":
            if shift >= 0:
                out[:, min(w, shift) :] = frame[:, : max(0, w - shift)]
            else:
                s = min(w, -shift)
                out[:, :s] = frame[:, w - s :]
        elif self.direction == "up":
            if shift >= 0:
                out[: max(0, h - shift), :] = frame[min(h, shift) :, :]
            else:
                s = min(h, -shift)
                out[h - s :, :] = frame[:s, :]
        elif self.direction == "down":
            if shift >= 0:
                out[min(h, shift) :, :] = frame[: max(0, h - shift), :]
            else:
                s = min(h, -shift)
                out[:s, :] = frame[h - s :, :]

        return out


class PanelPulseEffect(BaseEffect):
    """Brief scale pulse — zoom in then back out.

    Designed for beat-synced emphasis on grid panels.
    At ``progress=0`` the panel is at ``start_scale``,
    at ``progress=0.5`` it peaks toward ``pulse_scale``,
    then returns to ``end_scale`` at ``progress=1``.

    :param start_scale:  Scale at progress=0 (typically 1.0).
    :param pulse_scale:  Peak scale at the middle of the effect (e.g. 1.15).
    :param end_scale:    Scale at progress=1 (typically 1.0).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        start_scale: float = 1.0,
        pulse_scale: float = 1.15,
        end_scale: float = 1.0,
        easing: EasingType = "ease_out",
    ):
        super().__init__(easing=easing)
        self.start_scale = start_scale
        self.pulse_scale = pulse_scale
        self.end_scale = end_scale

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]

        # Bounce curve: peak at midpoint
        t = progress
        if t < 0.5:
            # 0 → 0.5 : start → pulse
            p = t / 0.5
            scale = self.start_scale + (self.pulse_scale - self.start_scale) * p
        else:
            # 0.5 → 1.0 : pulse → end
            p = (t - 0.5) / 0.5
            scale = self.pulse_scale + (self.end_scale - self.pulse_scale) * p

        nh, nw = int(h * scale), int(w * scale)
        if nh <= 0 or nw <= 0:
            return np.zeros_like(frame)

        resized = cv2.resize(frame, (nw, nh))

        if scale >= 1.0:
            y1 = (nh - h) // 2
            x1 = (nw - w) // 2
            return resized[y1 : y1 + h, x1 : x1 + w]
        else:
            out = np.zeros_like(frame)
            y1 = (h - nh) // 2
            x1 = (w - nw) // 2
            out[y1 : y1 + nh, x1 : x1 + nw] = resized
            return out


# ---------------------------------------------------------------------------
# Grid Scene-level GLSL effects
# ---------------------------------------------------------------------------

_GRID_SCAN_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float num_bars;
uniform float bar_speed;
uniform float bar_width;

void main() {
    vec4 col = texture(tex, v_uv);

    // Scanning bars that travel across the frame
    float bar_pos = fract(time * bar_speed);
    float bar_coord = v_uv.x;
    float bar = 1.0 - smoothstep(0.0, bar_width, abs(bar_coord - bar_pos));

    // Second bar from the opposite side
    float bar2 = 1.0 - smoothstep(0.0, bar_width, abs((1.0 - bar_coord) - bar_pos));

    float scan = max(bar, bar2) * 0.3 * (1.0 - progress);
    col.rgb += scan;

    // Subtle scanline overlay
    float scanline = sin(v_uv.y * num_bars * 3.14159 * 2.0) * 0.04;
    col.rgb += scanline;

    fragColor = col;
}
"""


class GridScanEffect(GLSLEffect):
    """Scanning-bar overlay across the composited grid.

    Creates animated horizontal bars + scanlines that travel across the frame.
    Intensity fades with progress so it can be used as a beat flash.

    :param num_bars:   Number of scanlines (default 240).
    :param bar_speed:  Travel speed of the bright bars (default 0.8).
    :param bar_width:  Normalised width of the bright bars (default 0.05).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        num_bars: float = 240.0,
        bar_speed: float = 0.8,
        bar_width: float = 0.05,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_SCAN_SHADER,
            uniforms={
                "num_bars": float(num_bars),
                "bar_speed": float(bar_speed),
                "bar_width": float(bar_width),
            },
            easing=easing,
        )


# ---------------------------------------------------------------------------
# More Grid GLSL effects
# ---------------------------------------------------------------------------

_GRID_FLASH_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float intensity;

void main() {
    vec4 col = texture(tex, v_uv);
    // Pulse flash that peaks then fades
    float flash = 1.0 - abs(progress * 2.0 - 1.0);
    flash = pow(flash, 2.0) * intensity;
    col.rgb += flash;
    fragColor = col;
}
"""


class GridFlashEffect(GLSLEffect):
    """Brightness flash/pulse over the composited frame.

    Peaks at the midpoint of the effect duration, then fades.
    Useful for beat hits across the entire grid.

    :param intensity: Peak brightness boost (0.0–1.0+, default 0.5).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        intensity: float = 0.5,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_FLASH_SHADER,
            uniforms={"intensity": float(intensity)},
            easing=easing,
        )


_GRID_GLITCH_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float intensity;

void main() {
    vec2 uv = v_uv;

    // Random slice displacement
    float slice = floor(uv.y * 200.0 + sin(time * 20.0) * 50.0);
    float glitch = step(0.97, fract(sin(slice * 437.58 + time * 5.0)));
    glitch *= 1.0 - progress;

    uv.x += glitch * 0.05 * intensity;

    vec4 col = texture(tex, uv);

    // RGB split on glitched areas
    if (glitch > 0.01) {
        col.r = texture(tex, uv + vec2(0.015 * intensity, 0.0)).r;
        col.b = texture(tex, uv - vec2(0.015 * intensity, 0.0)).b;
    }

    fragColor = col;
}
"""


class GridGlitchEffect(GLSLEffect):
    """Digital glitch distortion over the composited grid.

    Random horizontal slice displacement + RGB split on active glitch areas.
    Intensity fades with progress for timed beat effects.

    :param intensity: Glitch strength multiplier (default 1.0).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        intensity: float = 1.0,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_GLITCH_SHADER,
            uniforms={"intensity": float(intensity)},
            easing=easing,
        )


_GRID_WAVE_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float frequency;
uniform float amplitude;
uniform float speed;

void main() {
    float wave_amp = amplitude * (1.0 - progress);
    float wave = sin(v_uv.y * frequency + time * speed) * wave_amp;
    vec2 uv = vec2(v_uv.x + wave, v_uv.y);
    fragColor = texture(tex, uv);
}
"""


class GridWaveWarpEffect(GLSLEffect):
    """Wave warp distortion across the composited frame.

    Creates a horizontal wave displacement that travels vertically.
    Amplitude fades with progress.

    :param frequency: Wave frequency (default 20.0).
    :param amplitude: Wave amplitude in UV space (default 0.03).
    :param speed: Wave travel speed (default 5.0).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        frequency: float = 20.0,
        amplitude: float = 0.03,
        speed: float = 5.0,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_WAVE_SHADER,
            uniforms={
                "frequency": float(frequency),
                "amplitude": float(amplitude),
                "speed": float(speed),
            },
            easing=easing,
        )


_GRID_PIXELATE_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float max_pixels;
uniform float min_pixels;

void main() {
    float pixel_count = mix(min_pixels, max_pixels, 1.0 - progress);
    vec2 uv = floor(v_uv * pixel_count) / pixel_count;
    fragColor = texture(tex, uv);
}
"""


class GridPixelateEffect(GLSLEffect):
    """Progressive pixelation — starts sharp, ends blocky (or vice versa).

    Useful for beat-driven stutter effects on the grid composite.

    :param max_pixels: Minimum pixelation (most detail), default 400.0.
    :param min_pixels: Maximum pixelation (largest blocks), default 20.0.
    :param easing: Easing spec.
    """

    def __init__(
        self,
        max_pixels: float = 400.0,
        min_pixels: float = 20.0,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_PIXELATE_SHADER,
            uniforms={
                "max_pixels": float(max_pixels),
                "min_pixels": float(min_pixels),
            },
            easing=easing,
        )


_GRID_CHROMATIC_SHADER = """\
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;
uniform float intensity;
uniform float angle;

void main() {
    float a = radians(angle);
    vec2 dir = vec2(cos(a), sin(a));
    float offset = intensity * progress * 0.02;

    float r = texture(tex, v_uv + dir * offset).r;
    float g = texture(tex, v_uv).g;
    float b = texture(tex, v_uv - dir * offset).b;

    fragColor = vec4(r, g, b, 1.0);
}
"""


class GridChromaticEffect(GLSLEffect):
    """Chromatic aberration that animates with progress.

    Red/Blue channels shift in opposite directions along *angle*,
    growing stronger as progress increases — great for build-up effects.

    :param intensity: Shift strength (default 1.0).
    :param angle: Shift direction in degrees (default 0.0 = horizontal).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        intensity: float = 1.0,
        angle: float = 0.0,
        easing: EasingType = "linear",
    ):
        super().__init__(
            fragment_shader_code=_GRID_CHROMATIC_SHADER,
            uniforms={
                "intensity": float(intensity),
                "angle": float(angle),
            },
            easing=easing,
        )


# ---------------------------------------------------------------------------
# Per-panel dynamic effects
# ---------------------------------------------------------------------------


class PanelBounceEffect(BaseEffect):
    """Quick vertical/horizontal bounce for beat emphasis on a grid panel.

    Shifts the panel content in *direction* by *amplitude* (normalised),
    then returns to rest — a single bounce cycle.

    :param direction: ``"up"``, ``"down"``, ``"left"``, ``"right"``.
    :param amplitude: Peak displacement as fraction of frame size (default 0.08).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        direction: str = "up",
        amplitude: float = 0.08,
        easing: EasingType = "ease_out",
    ):
        super().__init__(easing=easing)
        self.direction = direction
        self.amplitude = amplitude

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]

        # Bounce: 0→peak→0 over the effect duration
        t = progress
        if t < 0.5:
            p = t / 0.5
            offset = self.amplitude * p
        else:
            p = (t - 0.5) / 0.5
            offset = self.amplitude * (1.0 - p)

        shift = int(offset * (h if self.direction in ("up", "down") else w))
        out = np.zeros_like(frame)

        if self.direction == "up":
            if shift >= 0:
                out[: h - shift, :] = frame[shift:, :]
            else:
                out[-shift:, :] = frame[: h + shift, :]
        elif self.direction == "down":
            if shift >= 0:
                out[shift:, :] = frame[: h - shift, :]
            else:
                out[: h + shift, :] = frame[-shift:, :]
        elif self.direction == "left":
            if shift >= 0:
                out[:, : w - shift] = frame[:, shift:]
            else:
                out[:, -shift:] = frame[:, : w + shift]
        elif self.direction == "right":
            if shift >= 0:
                out[:, shift:] = frame[:, : w - shift]
            else:
                out[:, : w + shift] = frame[:, -shift:]

        return out


class PanelSpinEffect(BaseEffect):
    """Brief rotation wobble for a grid panel.

    Rotates the panel slightly (up to *max_angle* degrees) and back,
    creating a snap-to-attention effect on beat.

    :param max_angle: Peak rotation in degrees (default 3.0).
    :param easing: Easing spec.
    """

    def __init__(
        self,
        max_angle: float = 3.0,
        easing: EasingType = "ease_out",
    ):
        super().__init__(easing=easing)
        self.max_angle = max_angle

    def apply(
        self, frame: np.ndarray, current_time: float, progress: float
    ) -> np.ndarray:
        h, w = frame.shape[:2]

        # Wobble: 0→peak→0
        t = progress
        if t < 0.5:
            p = t / 0.5
            angle = self.max_angle * p
        else:
            p = (t - 0.5) / 0.5
            angle = self.max_angle * (1.0 - p)

        center = (w // 2, h // 2)
        rot = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(frame, rot, (w, h), borderMode=cv2.BORDER_REPLICATE)
