# OpenCV-Transitions: Custom Effects & Transitions Guide

This document outlines the rules, architecture, and best practices for creating new visual effects and transitions in the OpenCV-Transitions pipeline. It is designed to act as a reference for developers and AI agents (Gemini, Claude, ChatGPT, etc.) when tasked with extending the codebase.

## 1. Architecture Overview

The pipeline processes video frames as NumPy arrays in **BGR format** (OpenCV standard).
All custom visual modifications are split into two categories:
- **Effects**: Applied to a single video clip over a specific duration (or statically).
- **Transitions**: Applied between two overlapping clips to blend from `frame1` to `frame2`.

Both inherit from base abstract classes located in `utils/base.py`, which handle the heavy lifting for progress normalization and **easing**.

## 2. Easing Engine

You **do not** need to manually calculate easing curves in your custom classes. The base classes handle easing via their `process()` method and will pass a normalized, eased `progress` float (`0.0` to `1.0`) directly into your `apply()` method.

Easing can be defined during instantiation as:
- A predefined string (e.g., `"linear"`, `"ease_in"`, `"ease_out"`, `"ease_in_out"`).
- A 4-tuple representing a CSS cubic-bezier curve (e.g., `(0.42, 0.0, 0.58, 1.0)`).
- A custom callable function.

---

## 3. Creating a Custom Effect

Effects must inherit from `utils.base.BaseEffect` and are typically placed in `utils/effects.py`.

### Structure:
```python
import cv2
import numpy as np
from utils.base import BaseEffect

class MyCustomEffect(BaseEffect):
    def __init__(self, my_param=1.0, easing="linear"):
        # 1. ALWAYS call super().__init__(easing=easing)
        super().__init__(easing=easing)
        
        # 2. Store your custom parameters
        self.my_param = my_param

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        """
        The core rendering logic.
        
        :param frame: The current video frame (BGR numpy array).
        :param current_time: The current local/global timestamp in seconds.
        :param progress: Eased progress from 0.0 to 1.0 based on the effect's duration.
        :return: The modified frame (MUST be the same shape and type as the input frame).
        """
        # --- DO NOT process easing here. Use 'progress' directly. ---
        
        # Example: Animate a parameter based on progress
        animated_param = self.my_param * progress
        
        # Do OpenCV operations...
        # output_frame = cv2.some_function(frame, animated_param)
        
        return frame # Return the modified frame
```

### Effect Rules:
1. **Inheritance**: Always inherit from `BaseEffect`.
2. **Apply, not Process**: Never override `process()`, only override `apply()`.
3. **Handle Edge Cases**: Ensure your effect doesn't crash if `progress == 0.0` or `progress == 1.0`. For heavy operations (like blurs), if `progress == 0`, simply `return frame` early to save compute.
4. **Preserve Dimensions**: The returned frame must have the exact same dimensions `(H, W, 3)` and dtype (`np.uint8`) as the input `frame`. If you scale the frame, you must crop or pad it back to the original size.

---

## 4. Creating a Custom Transition

Transitions must inherit from `utils.base.BaseTransition` and are typically placed in `utils/transitions.py`.

### Structure:
```python
import cv2
import numpy as np
from utils.base import BaseTransition

class MyCustomTransition(BaseTransition):
    def __init__(self, duration: float = 1.0, easing="linear"):
        # 1. ALWAYS call super().__init__(duration, easing)
        super().__init__(duration, easing)

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        """
        The core blending logic.
        
        :param frame1: The outgoing frame (numpy array).
        :param frame2: The incoming frame (numpy array).
        :param progress: Eased progress from 0.0 to 1.0. (0.0 = 100% frame1, 1.0 = 100% frame2)
        :return: The blended frame.
        """
        # --- DO NOT process easing here. Use 'progress' directly. ---
        
        # Example: Simple crossfade (cv2.addWeighted)
        alpha = progress
        blended = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)
        
        return blended
```

### Transition Rules:
1. **Inheritance**: Always inherit from `BaseTransition`.
2. **Visual Logic Check**: When `progress == 0.0`, the output should visually match `frame1`. When `progress == 1.0`, the output should visually match `frame2`.
3. **Apply, not Process**: Never override `process()`, only override `apply()`.
4. **Same Size Guarantee**: You can safely assume `frame1` and `frame2` will always be the exact same dimensions.

---

## 5. Performance Best Practices

Since OpenCV runs on the CPU by default, video rendering can become a bottleneck. Keep the following in mind:
- **Early Exits**: If an effect's intensity at a given progress is visually zero (e.g., `blur_kernel <= 1` or `alpha == 0`), immediately `return frame` or `return frame1`/`frame2` to bypass heavy compute.
- **Pre-allocation**: When possible, allocate output arrays like `out_frame = np.zeros_like(frame)` instead of creating new arrays inside loops.
- **Vectorized NumPy operations**: Always prefer NumPy matrix operations or built-in OpenCV C++ functions over standard Python `for` loops. For example, use `np.clip` instead of looping through pixels.
- **Color Spaces**: Remember that OpenCV uses **BGR**. If you need to manipulate Saturation or Brightness, convert to HSV (`cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)`), manipulate the specific channel, and convert back to BGR.

---

## 6. GSAP-style Shorthand API

For common, property-based animation, the pipeline exposes a high-level API inspired by [GSAP](https://gsap.com/). These methods automatically build and register the correct effect class(es) from a plain set of keyword properties — no need to manually instantiate effect objects.

### Available Properties

| Property | Type | Default | Description |
|---|---|---|---|
| `blur` | `int` | `0` | Gaussian blur kernel size. `0` = no blur. |
| `rgb_shift` | `float` | `0.0` | Chromatic aberration offset in pixels. |
| `rgb_shift_angle` | `float` | `0.0` | Direction of the RGB shift, in degrees. |
| `zoom` | `float` | `1.0` | Scale factor. `1.0` = original size, `1.5` = 50% zoom-in. |
| `saturation` | `float` | `1.0` | Saturation multiplier. `0.0` = grayscale, `2.0` = vivid. |
| `brightness` | `float` | `0.0` | Additive brightness. `-50` = darker, `+50` = brighter. |
| `contrast` | `float` | `1.0` | Contrast multiplier. |
| `gamma` | `float` | `1.0` | Gamma correction. `<1` = brighter mid-tones, `>1` = darker. |

All three methods also accept:
- `clip_idx` — which clip to apply the effect to.
- `duration` — how long the animation runs in seconds.
- `start_time` — local start time within the clip (default: `0.0`).
- `easing` — a string, 4-tuple bezier, or callable (same as effect constructors).

---

### `pipeline.to()`

Animates **from** the neutral/default value **to** the given property values. Like GSAP's `gsap.to()`.

```python
# Blur in over 2 seconds at the start of clip 0
pipeline.to(clip_idx=0, duration=2.0, blur=31, easing="ease_in")

# Zoom in + add chromatic aberration over the last 1.5 seconds of clip 1
pipeline.to(clip_idx=1, duration=1.5, start_time=1.5, zoom=1.3, rgb_shift=25, rgb_shift_angle=90, easing="ease_out")

# Animate multiple color properties at once
pipeline.to(clip_idx=0, duration=3.0, saturation=2.0, contrast=1.4, brightness=20)
```

---

### `pipeline.from_()`

Animates **from** the given property values **back to** the neutral/default. Like GSAP's `gsap.from()`. Useful for intro reveals.

> **Note**: Python reserves the keyword `from`, so the method is named `from_()` with an underscore.

```python
# Clip 0 starts blurred and clears up
pipeline.from_(clip_idx=0, duration=1.0, blur=41, easing="ease_out")

# Clip 1 starts zoomed in and pulls back out to normal
pipeline.from_(clip_idx=1, duration=2.0, zoom=1.5, easing=(0.42, 0, 0.58, 1))

# Clip 0 fades in from black
pipeline.from_(clip_idx=0, duration=0.8, brightness=-255)
```

---

### `pipeline.fromTo()`

Explicit control over both start **and** end values. Like GSAP's `gsap.fromTo()`. Best used when you need a value to travel between two specific states that aren't the defaults.

```python
# Clip 1: saturation and blur animate together from a "dream" state to normal
pipeline.fromTo(
    clip_idx=1, duration=2.0,
    from_props={"saturation": 0.0, "blur": 21},
    to_props  ={"saturation": 1.5, "blur": 0},
    easing=(0.42, 0, 0.58, 1)
)

# RGB Shift glitch that peaks and subsides
pipeline.fromTo(
    clip_idx=0, duration=0.5, start_time=2.5,
    from_props={"rgb_shift": 0},
    to_props  ={"rgb_shift": 40, "rgb_shift_angle": 30},
    easing="ease_in_out"
)
```

---

### Mixing GSAP and `add_clip_effect()`

GSAP shorthand methods are just convenience wrappers around `add_clip_effect()`. You can freely mix both styles in the same pipeline; they stack and apply in the order they were added.

```python
# Low-level: use a custom effect object
from utils.effects import YoloGlowSegEffect
glow = YoloGlowSegEffect(model_path="utils/yolo26n-seg_int8_openvino_model/", intensity=3)
pipeline.add_clip_effect(clip_idx=0, effect=glow)

# High-level: GSAP shorthand for standard properties
pipeline.to(clip_idx=0, duration=5.0, zoom=1.2, easing="ease_out")
pipeline.from_(clip_idx=0, duration=0.5, blur=25, easing="ease_out")  # blur-in reveal at start
```
