import cv2
import numpy as np
from utils.base import BaseTransition, EasingType
from typing import Union, Tuple, Callable

class SlideTransition(BaseTransition):
    def __init__(self, duration: float = 1.0, easing: EasingType = "ease_in_out", direction: str = "left"):
        super().__init__(duration, easing)
        self.direction = direction

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]
        out_frame = np.zeros_like(frame1)

        offset_x, offset_y = 0, 0
        if self.direction == "left":
            offset_x = int(w * progress)
        elif self.direction == "right":
            offset_x = -int(w * progress)
        elif self.direction == "up":
            offset_y = int(h * progress)
        elif self.direction == "down":
            offset_y = -int(h * progress)

        # Draw frame1 shifted out and frame2 shifted in
        if self.direction == "left":
            out_frame[:, :max(0, w - offset_x)] = frame1[:, offset_x:w]
            out_frame[:, max(0, w - offset_x):] = frame2[:, :offset_x]
        elif self.direction == "right":
            # Right means frame1 moves right, frame2 comes from left
            out_frame[:, -offset_x:] = frame1[:, :w + offset_x]
            out_frame[:, :-offset_x] = frame2[:, w + offset_x:]
        elif self.direction == "up":
            out_frame[:max(0, h - offset_y), :] = frame1[offset_y:h, :]
            out_frame[max(0, h - offset_y):, :] = frame2[:offset_y, :]
        elif self.direction == "down":
            out_frame[-offset_y:, :] = frame1[:h + offset_y, :]
            out_frame[:-offset_y, :] = frame2[h + offset_y:, :]

        return out_frame

class ZoomTransition(BaseTransition):
    def __init__(self, duration: float = 1.0, easing: EasingType = "ease_in_out", mode: str = "in"):
        super().__init__(duration, easing)
        self.mode = mode # "in", "out", "inout", "outin"

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]
        
        # Calculate scale factor based on mode
        scale1 = 1.0
        scale2 = 1.0
        alpha = progress

        if self.mode == "in":
            scale1 = 1.0 + progress
            scale2 = 2.0 - progress
        elif self.mode == "out":
            scale1 = 1.0 - (progress * 0.5)
            scale2 = 0.5 + (progress * 0.5)
        elif self.mode == "inout":
            scale1 = 1.0 + progress
            scale2 = 0.5 + (progress * 0.5)
        elif self.mode == "outin":
            scale1 = 1.0 - (progress * 0.5)
            scale2 = 2.0 - progress

        def scale_and_crop(frame, scale):
            nh, nw = int(h * scale), int(w * scale)
            if nh <= 0 or nw <= 0:
                return np.zeros_like(frame)
            resized = cv2.resize(frame, (nw, nh))
            
            # Crop to original size
            if scale > 1.0:
                y1 = (nh - h) // 2
                x1 = (nw - w) // 2
                return resized[y1:y1+h, x1:x1+w]
            # Pad to original size
            else:
                out = np.zeros_like(frame)
                y1 = (h - nh) // 2
                x1 = (w - nw) // 2
                out[y1:y1+nh, x1:x1+nw] = resized
                return out

        f1_zoomed = scale_and_crop(frame1, scale1)
        f2_zoomed = scale_and_crop(frame2, scale2)

        # Crossfade between zoomed frames
        blended = cv2.addWeighted(f1_zoomed, 1.0 - alpha, f2_zoomed, alpha, 0)
        return blended


class GridWipeTransition(BaseTransition):
    """Reveals the next clip in a grid-like block pattern.

    The frame is divided into *cols* × *rows* blocks. Each block
    flips from frame1 to frame2 in a staggered left→right / top→bottom order.

    :param cols: Number of horizontal blocks (default 6).
    :param rows: Number of vertical blocks (default 4).
    :param stagger: Stagger direction — ``"row"`` (left→right per row, default)
                    or ``"col"`` (top→bottom per column).
    :param easing: Easing spec (applied per-block).
    """
    def __init__(
        self,
        duration: float = 1.0,
        easing: EasingType = "ease_in_out",
        cols: int = 6,
        rows: int = 4,
        stagger: str = "row",
    ):
        super().__init__(duration, easing)
        self.cols = max(1, cols)
        self.rows = max(1, rows)
        self.stagger = stagger

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]
        out = frame1.copy()

        bh = h // self.rows
        bw = w // self.cols

        for r in range(self.rows):
            for c in range(self.cols):
                # Stagger: each block has its own local progress
                if self.stagger == "col":
                    idx = c * self.rows + r
                else:
                    idx = r * self.cols + c
                total = self.cols * self.rows
                local_p = (progress * total - idx) / (total - idx)
                local_p = max(0.0, min(1.0, local_p))

                y1 = r * bh
                y2 = (r + 1) * bh if r < self.rows - 1 else h
                x1 = c * bw
                x2 = (c + 1) * bw if c < self.cols - 1 else w

                if local_p >= 1.0:
                    out[y1:y2, x1:x2] = frame2[y1:y2, x1:x2]
                elif local_p > 0.0:
                    a = local_p
                    sub1 = frame1[y1:y2, x1:x2].astype(np.float32)
                    sub2 = frame2[y1:y2, x1:x2].astype(np.float32)
                    blended = cv2.addWeighted(sub1, 1.0 - a, sub2, a, 0)
                    out[y1:y2, x1:x2] = blended.astype(np.uint8)

        return out


class FlashTransition(BaseTransition):
    """Flash to a solid color and back, revealing the next clip.

    Goes frame1 → color → frame2.  Good for beat cuts and energetic edits.

    :param color: BGR tuple for the flash (default (255, 255, 255) = white).
    :param flash_point: Fraction of transition duration at the flash peak
                        (default 0.35 — flash occurs ~1/3 through).
    :param easing: Easing spec.
    """
    def __init__(
        self,
        duration: float = 1.0,
        easing: EasingType = "ease_in_out",
        color: tuple = (255, 255, 255),
        flash_point: float = 0.35,
    ):
        super().__init__(duration, easing)
        self.color = np.array(color, dtype=np.uint8).reshape(1, 1, 3)
        self.flash_point = max(0.05, min(0.95, flash_point))

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]
        fp = self.flash_point

        if progress < fp:
            # Fade frame1 → flash color
            a = progress / fp
            flash = np.full((h, w, 3), self.color, dtype=np.uint8)
            return cv2.addWeighted(frame1, 1.0 - a, flash, a, 0)
        elif progress < 2.0 * fp:
            # Fade flash color → frame2
            a = (progress - fp) / fp
            flash = np.full((h, w, 3), self.color, dtype=np.uint8)
            return cv2.addWeighted(flash, 1.0 - a, frame2, a, 0)
        else:
            return frame2


class RadialWipeTransition(BaseTransition):
    """Radial wipe — a growing circle reveals the next clip from center.

    :param origin: Normalised (x, y) centre of the wipe (default (0.5, 0.5)).
    :param easing: Easing spec.
    """
    def __init__(
        self,
        duration: float = 1.0,
        easing: EasingType = "ease_in_out",
        origin: tuple = (0.5, 0.5),
    ):
        super().__init__(duration, easing)
        self.origin = origin

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]
        cx = int(self.origin[0] * w)
        cy = int(self.origin[1] * h)
        max_radius = np.sqrt(max(cx, w - cx) ** 2 + max(cy, h - cy) ** 2)

        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
        radius = progress * max_radius

        mask = (dist <= radius).astype(np.float32)

        out = frame1.astype(np.float32) * (1.0 - mask[:, :, np.newaxis])
        out += frame2.astype(np.float32) * mask[:, :, np.newaxis]
        return np.clip(out, 0, 255).astype(np.uint8)


class ZoomInTransition(BaseTransition):
    """Aggressive zoom-in transition — zooms way into frame1, blurs at peak,
    then reveals frame2 underneath.

    Creates a classic "zoom through" feel used in modern video editing.

    :param max_zoom: Peak zoom factor for the outgoing frame (default 5.0).
    :param blur_peak: Max Gaussian blur sigma at midpoint; 0 disables blur (default 3.0).
    :param easing: Easing spec.
    """
    def __init__(
        self,
        duration: float = 0.3,
        easing: EasingType = (0.45, 0, 0.55, 1),
        max_zoom: float = 5.0,
        blur_peak: float = 3.0,
    ):
        super().__init__(duration, easing)
        self.max_zoom = max(max_zoom, 1.01)
        self.blur_peak = blur_peak

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        h, w = frame1.shape[:2]

        # Zoom: 1× → max_zoom
        scale = 1.0 + (self.max_zoom - 1.0) * progress

        # Alpha: steep curve so frame1 stays dominant most of the time
        alpha = progress ** 3.5

        # Scale + crop frame1
        nh, nw = int(h * scale), int(w * scale)
        resized = cv2.resize(frame1, (nw, nh), interpolation=cv2.INTER_LINEAR)
        y1 = (nh - h) // 2
        x1 = (nw - w) // 2
        f1 = resized[y1:y1 + h, x1:x1 + w]

        # Blur ramp: 0 → peak → 0 (sinusoidal)
        if self.blur_peak > 0.0:
            blur_sigma = self.blur_peak * np.sin(np.pi * progress)
            if blur_sigma > 0.5:
                ksize = int(blur_sigma * 6 + 1) | 1
                f1 = cv2.GaussianBlur(f1, (ksize, ksize), blur_sigma)

        # Crossfade
        return cv2.addWeighted(f1, 1.0 - alpha, frame2, alpha, 0)

