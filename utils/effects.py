import cv2
import numpy as np
from ultralytics import YOLO
from utils.base import BaseEffect

class YoloGlowSegEffect(BaseEffect):
    def __init__(self, model_path: str = "yolo26n-seg_int8_openvino_model/", 
                 glow_color: tuple = (0, 255, 255), 
                 blur_amount: int = 41,
                 intensity: float = 1.5,
                 easing="linear"):
        """
        Creates a glow effect around people using YOLO segmentation.
        :param model_path: Path to the OpenVINO optimized YOLO segmentation model
        :param glow_color: Glow color in BGR format
        :param blur_amount: Gaussian blur kernel size (must be odd)
        :param intensity: Intensity multiplier for the glow
        """
        super().__init__(easing=easing)
        self.model = YOLO(model_path)
        self.glow_color = glow_color
        self.blur_amount = blur_amount if blur_amount % 2 != 0 else blur_amount + 1
        self.intensity = intensity

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        # Run inference
        results = self.model.predict(
            source=frame,
            imgsz=320,  # smaller size for speed
            device="cpu",
            verbose=False,
            classes=[0], # Only detect class 0 (person)
            retina_masks=True # Generate masks at original image size to fix letterboxing cutoff
        )
        
        result = results[0]
        
        h, w = frame.shape[:2]

        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks = result.masks.data.cpu().numpy()       # (N, H, W)
            combined_mask = np.max(masks, axis=0).astype(np.float32)
            self.last_good_mask = combined_mask.copy()
            self.missed_frames  = 0
            # Snap immediately on first-ever detection (don't blend from zeros)
            if not hasattr(self, 'prev_mask') or self.prev_mask is None or self.prev_mask.shape != combined_mask.shape:
                self.prev_mask = combined_mask
            else:
                self.prev_mask = 0.3 * combined_mask + 0.7 * self.prev_mask
        else:
            self.missed_frames = getattr(self, 'missed_frames', 0) + 1
            last = getattr(self, 'last_good_mask', None)
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                # Hold the last confirmed mask; decay slowly (0.97^n → ~50% after 23 frames)
                combined_mask = last * (0.97 ** self.missed_frames)
            else:
                combined_mask = np.zeros((h, w), dtype=np.float32)
            if not hasattr(self, 'prev_mask') or self.prev_mask is None or self.prev_mask.shape != combined_mask.shape:
                self.prev_mask = combined_mask
            else:
                self.prev_mask = 0.15 * combined_mask + 0.85 * self.prev_mask

        smoothed_mask = self.prev_mask

        # Binarize and convert to uint8 for glow dilation/blur
        combined_mask = (smoothed_mask > 0.25).astype(np.uint8) * 255

        # Early exit if entirely empty after smoothing
        if not np.any(combined_mask):
            return frame

        # Create the glow mask by dilating and blurring the person mask
        kernel = np.ones((11, 11), np.uint8)
        dilated_mask = cv2.dilate(combined_mask, kernel, iterations=1)
        glow_mask = cv2.GaussianBlur(dilated_mask, (self.blur_amount, self.blur_amount), 0)
        
        # Subtract the original mask to only keep the glow around the person (optional but looks good)
        # glow_mask = cv2.subtract(glow_mask, combined_mask)

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

class ZoomEffect(BaseEffect):
    def __init__(self, start_zoom=1.0, end_zoom=1.5, easing="linear"):
        super().__init__(easing=easing)
        self.start_zoom = start_zoom
        self.end_zoom = end_zoom

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
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
            return resized[y1:y1+h, x1:x1+w]
        else:
            out = np.zeros_like(frame)
            y1 = (h - nh) // 2
            x1 = (w - nw) // 2
            out[y1:y1+nh, x1:x1+nw] = resized
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
            "gamma": params.get("gamma", 1.0)
        }

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        p = self.start_params
        e = self.end_params
        
        sat = p["saturation"] + (e["saturation"] - p["saturation"]) * progress
        con = p["contrast"] + (e["contrast"] - p["contrast"]) * progress
        bri = p["brightness"] + (e["brightness"] - p["brightness"]) * progress
        gam = p["gamma"] + (e["gamma"] - p["gamma"]) * progress
        
        out = frame.copy()
        
        # Saturation
        if sat != 1.0:
            hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] *= sat
            hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
            out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
            
        # Contrast and Brightness
        if con != 1.0 or bri != 0.0:
            out = cv2.convertScaleAbs(out, alpha=con, beta=bri)
            
        # Gamma correction
        if gam != 1.0:
            invGamma = 1.0 / gam
            table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
            out = cv2.LUT(out, table)
            
        return out

class BlurEffect(BaseEffect):
    def __init__(self, start_blur=0, end_blur=21, easing="linear"):
        """
        Applies a Gaussian blur that animates over time.
        :param start_blur: Starting blur kernel size (0 for no blur)
        :param end_blur: Ending blur kernel size
        """
        super().__init__(easing=easing)
        self.start_blur = start_blur
        self.end_blur = end_blur

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        blur_val = self.start_blur + (self.end_blur - self.start_blur) * progress
        blur_val = int(blur_val)
        
        # Kernel size must be odd
        if blur_val % 2 == 0:
            blur_val += 1
            
        if blur_val <= 1:
            return frame
            
        return cv2.GaussianBlur(frame, (blur_val, blur_val), 0)

class RGBShiftEffect(BaseEffect):
    def __init__(self, start_shift=0.0, end_shift=20.0, angle=0.0, easing="linear"):
        """
        Shifts the Red and Blue channels in opposite directions to create a chromatic aberration effect.
        :param start_shift: Starting shift amount in pixels
        :param end_shift: Ending shift amount in pixels
        :param angle: Angle of the shift in degrees (0 = horizontal, 90 = vertical)
        """
        super().__init__(easing=easing)
        self.start_shift = start_shift
        self.end_shift = end_shift
        self.angle_rad = np.deg2rad(angle)

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        shift_amount = self.start_shift + (self.end_shift - self.start_shift) * progress
        
        if abs(shift_amount) < 0.5:
            return frame
            
        h, w = frame.shape[:2]
        
        # Calculate shift components based on angle
        dx = shift_amount * np.cos(self.angle_rad)
        dy = shift_amount * np.sin(self.angle_rad)
        
        b, g, r = cv2.split(frame)
        
        def shift_channel(channel, shift_x, shift_y):
            M = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
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
    font_size       : int   — font size in points (default 80)
    position        : (x, y) tuple or preset string:
                      "center", "top_center", "bottom_center",
                      "top_left", "bottom_left", "top_right", "bottom_right"
    color           : (B, G, R)  — text color in BGR
    opacity         : float — peak text opacity 0.0–1.0 (default 1.0)
    transition_in   : float — seconds for the enter animation (default 0.5)
    transition_out  : float — seconds for the exit animation  (default 0.5)
    animate_in      : str   — "fade", "slide_up", "slide_down", "none"
    animate_out     : str   — "fade", "slide_up", "slide_down", "none"
    stroke_width    : int   — outline width in pixels (0 = no outline)
    stroke_color    : (B, G, R) — outline color in BGR
    model_path      : str   — YOLO seg model path; None = no depth composite
    depth_composite : bool  — composite person on top of text if True
    easing          : easing spec (applied within each transition phase)
    """

    def __init__(
        self,
        text: str,
        font_path: str = None,
        font_size: int = 80,
        position = "bottom_center",
        color: tuple = (255, 255, 255),
        opacity: float = 1.0,
        transition_in: float = 0.5,
        transition_out: float = 0.5,
        animate_in: str = "slide_up",   # "fade", "slide_up", "slide_down", "none"
        animate_out: str = "fade",      # "fade", "slide_up", "slide_down", "none"
        stroke_width: int = 0,
        stroke_color: tuple = (0, 0, 0),
        model_path: str = None,
        depth_composite: bool = True,
        easing = "linear"
    ):
        super().__init__(easing=easing)
        self.text             = text
        self.font_size        = font_size
        self.position         = position
        self.color_rgba       = (*color[::-1], 255)          # BGR → RGBA
        self.stroke_color_rgba= (*stroke_color[::-1], 255)
        self.opacity          = opacity
        self.transition_in    = transition_in
        self.transition_out   = transition_out
        self.animate_in       = animate_in
        self.animate_out      = animate_out
        self.stroke_width     = stroke_width
        self.depth_composite  = depth_composite and (model_path is not None)
        self.prev_mask        = None

        # YOLO model
        self.model = YOLO(model_path) if self.depth_composite else None

        # PIL font
        try:
            from PIL import ImageFont
            if font_path:
                self.font = ImageFont.truetype(font_path, font_size)
            else:
                try:
                    self.font = ImageFont.load_default(size=font_size)
                except TypeError:
                    self.font = ImageFont.load_default()
        except Exception:
            self.font = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        """
        Returns a soft float32 (H, W) person mask in [0, 1] using robust temporal smoothing.
        The mask is NOT binarized — soft edges allow smooth per-pixel compositing.
        """
        h, w = frame.shape[:2]
        results = self.model.predict(
            source=frame, imgsz=320, device="cpu",
            verbose=False, classes=[0], retina_masks=True
        )
        result = results[0]

        has_detection = result.masks is not None and len(result.masks.data) > 0

        if has_detection:
            masks    = result.masks.data.cpu().numpy()
            combined = np.max(masks, axis=0).astype(np.float32)
            self.last_good_mask = combined.copy()
            self.missed_frames  = 0
            # Snap on first-ever detection: don't blend from zeros
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                # Slow EMA so the mask boundary doesn't jump frame-to-frame
                self.prev_mask = 0.3 * combined + 0.7 * self.prev_mask
        else:
            self.missed_frames = getattr(self, 'missed_frames', 0) + 1
            last = getattr(self, 'last_good_mask', None)
            if last is not None and last.shape == (h, w) and self.missed_frames <= 15:
                # Hold last confirmed mask, decaying at ~3% per missed frame
                combined = last * (0.97 ** self.missed_frames)
            else:
                combined = np.zeros((h, w), dtype=np.float32)
            if self.prev_mask is None or self.prev_mask.shape != combined.shape:
                self.prev_mask = combined
            else:
                # Very slow release when no detection
                self.prev_mask = 0.15 * combined + 0.85 * self.prev_mask

        # Step 1: Binarize at threshold so the interior of the person becomes a HARD 1.0.
        #         (Using prev_mask directly gives ~0.78 in the center, leaking text through.)
        binary   = (self.prev_mask > 0.3).astype(np.uint8) * 255

        if not np.any(binary):
            return np.zeros((h, w), dtype=np.float32)

        # Step 2: Dilate to expand past YOLO's slightly-too-tight silhouette.
        dilate_k = np.ones((11, 11), np.uint8)
        dilated  = cv2.dilate(binary, dilate_k, iterations=1)

        # Step 3: Feather ONLY the edges with a small blur.
        #         Center stays at 1.0; only the boundary transitions to 0.
        soft     = cv2.GaussianBlur(dilated.astype(np.float32), (21, 21), 0) / 255.0

        return np.clip(soft, 0.0, 1.0)

    def _calc_position(self, draw, w: int, h: int, anim_type: str, anim_phase_p: float):
        """Calculates the (x, y) pixel position, applying slide offset for the given phase."""
        # Measure text bounding box
        bbox = draw.textbbox((0, 0), self.text, font=self.font,
                             stroke_width=self.stroke_width)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        margin = 60

        presets = {
            "center":        ((w - tw) // 2,        (h - th) // 2),
            "top_center":    ((w - tw) // 2,        margin),
            "bottom_center": ((w - tw) // 2,        h - th - margin),
            "top_left":      (margin,                margin),
            "bottom_left":   (margin,                h - th - margin),
            "top_right":     (w - tw - margin,       margin),
            "bottom_right":  (w - tw - margin,       h - th - margin),
        }

        if isinstance(self.position, (tuple, list)):
            tx, ty = int(self.position[0]), int(self.position[1])
        else:
            tx, ty = presets.get(self.position, presets["bottom_center"])

        # anim_phase_p: 0.0 = start of this phase transition, 1.0 = fully in position
        if anim_type == "slide_up":
            ty += int((1.0 - anim_phase_p) * h * 0.25)
        elif anim_type == "slide_down":
            ty -= int((1.0 - anim_phase_p) * h * 0.25)

        return tx, ty

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        """
        current_time = seconds since this effect started (set by the pipeline).
        progress     = current_time / total_effect_duration (0→1).
        """
        from PIL import Image, ImageDraw

        h, w = frame.shape[:2]

        # --- Derive total effect duration from current_time and progress ---
        # (avoids needing to store it separately)
        total_dur = (current_time / progress) if progress > 0.001 else max(self.transition_in + self.transition_out, 0.001)

        t_in  = min(self.transition_in,  total_dur)
        t_out = min(self.transition_out, total_dur - t_in)
        hold_start = t_in
        hold_end   = total_dur - t_out

        # --- Determine which phase we're in, and compute per-phase progress ---
        if current_time < hold_start and t_in > 0:
            # ── In-transition ──
            phase_p   = current_time / t_in            # 0→1
            anim_type = self.animate_in
            if anim_type == "fade":
                text_opacity = phase_p * self.opacity
            else:
                text_opacity = self.opacity            # position handles the slide

        elif current_time > hold_end and t_out > 0:
            # ── Out-transition ──
            phase_p   = (current_time - hold_end) / t_out   # 0→1
            anim_type = self.animate_out
            if anim_type == "fade":
                text_opacity = (1.0 - phase_p) * self.opacity
            else:
                text_opacity = self.opacity

        else:
            # ── Hold phase: fully visible at rest position ──
            phase_p      = 1.0
            anim_type    = "none"
            text_opacity = self.opacity

        if text_opacity <= 0.0:
            return frame

        # --- Build RGBA text layer via PIL ---
        text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw       = ImageDraw.Draw(text_layer)

        tx, ty = self._calc_position(draw, w, h, anim_type, phase_p)

        text_fill   = (*self.color_rgba[:3],         int(text_opacity * 255))
        stroke_fill = (*self.stroke_color_rgba[:3],  int(text_opacity * 255))

        draw.text(
            (tx, ty), self.text,
            font=self.font,
            fill=text_fill,
            stroke_width=self.stroke_width,
            stroke_fill=stroke_fill if self.stroke_width > 0 else None
        )

        # --- Convert PIL RGBA → numpy, then alpha-composite onto frame ---
        text_np    = np.array(text_layer, dtype=np.float32)        # (H, W, 4)
        text_alpha = text_np[:, :, 3:4] / 255.0                    # (H, W, 1)
        text_bgr   = text_np[:, :, :3][:, :, ::-1]                 # RGB → BGR

        output = frame.astype(np.float32)
        output = output * (1.0 - text_alpha) + text_bgr * text_alpha

        # --- Depth composite: person pixels restore on top of text ---
        if self.depth_composite and self.model is not None:
            person_mask = self._get_mask(frame)[:, :, np.newaxis]  # (H, W, 1)
            output = output * (1.0 - person_mask) + frame.astype(np.float32) * person_mask

        return np.clip(output, 0, 255).astype(np.uint8)
