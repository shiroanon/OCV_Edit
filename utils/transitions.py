import cv2
import numpy as np
from utils.base import BaseTransition

class SlideTransition(BaseTransition):
    def __init__(self, duration: float = 1.0, easing: str = "ease_in_out", direction: str = "left"):
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
    def __init__(self, duration: float = 1.0, easing: str = "ease_in_out", mode: str = "in"):
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

