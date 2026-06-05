# Adding a New Effect — Agent Guide

## 1. Understand the Base Class

Every effect subclasses `BaseEffect` from `utils/base.py`:

```python
from abc import ABC, abstractmethod
from utils.base import BaseEffect, EasingType

class MyEffect(BaseEffect):
    def __init__(self, ..., easing: EasingType = "linear"):
        super().__init__(easing=easing)
        # your params here

    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        # frame:     BGR uint8 (H, W, 3)
        # current_time: seconds since this effect started
        # progress:  eased 0→1 value (applied automatically by process())
        return modified_frame
```

Key contract:
- `process()` applies easing, then calls your `apply()` — **never override `process()`**
- `progress` is already eased; use it to interpolate effect parameters
- `current_time` is useful for time-based effects (wave, oscillation, etc.)

## 2. File to Edit

Add your class to `utils/effects.py`. Import `BaseEffect` and `EasingType` from `utils.base`.

## 3. Register in the GSAP API (optional)

If your effect should be usable via `pipeline.to()` / `pipeline.from_()` / `pipeline.fromTo()`, add a handler in `VideoPipeline._build_effects_from_props()` in `app.py`. You need to:

1. Define a property key (e.g. `"my_param"`)
2. Add a neutral/default value in the `neutral` dict inside `to()` and `from_()` methods
3. Instantiate your effect in `_build_effects_from_props()`

## 4. Complete Example

```python
# utils/effects.py

class WaveEffect(BaseEffect):
    def __init__(self, amplitude: float = 10.0, frequency: float = 3.0, easing="linear"):
        super().__init__(easing=easing)
        self.amplitude = amplitude
        self.frequency = frequency

    def apply(self, frame, current_time, progress):
        h, w = frame.shape[:2]
        # Create a sine-wave displacement map
        x_coords = np.arange(w, dtype=np.float32)
        y_coords = np.arange(h, dtype=np.float32)
        x_map = np.tile(x_coords, (h, 1)).astype(np.float32)
        y_map = np.tile(y_coords, (w, 1)).T.astype(np.float32)

        wave = self.amplitude * np.sin(2 * np.pi * self.frequency * y_map / h + current_time * 4)
        x_map += wave

        return cv2.remap(frame, x_map, y_map, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
```

## 5. Wire into Pipeline (if using GSAP API)

In `app.py`, inside `_build_effects_from_props()` (around line 147):

```python
# --- Wave ---
if "wave" in (from_props.keys() | to_props.keys()):
    effects.append(WaveEffect(
        amplitude=to_props.get("wave", 10.0),
        easing=easing,
    ))
```

And in `to()` / `from_()` add `"wave": 0.0` to the `neutral` dict.

## 6. Use It

```python
# Direct API
pipeline.add_clip_effect(0, WaveEffect(amplitude=20, frequency=4), duration=3.0)

# GSAP API (if wired)
pipeline.to(clip_idx=0, duration=3.0, wave=30, easing="ease_out")
```

## Checklist

- [ ] Subclass `BaseEffect`
- [ ] Implement `apply(frame, current_time, progress) → np.ndarray`
- [ ] Import from `utils.base` only
- [ ] (Optional) Wire into `_build_effects_from_props()` in `app.py`
- [ ] (Optional) Add neutral default to `to()` / `from_()` in `app.py`
- [ ] (Optional) Add `ZoomToPoint` / `KenBurnsEffect` serialization/deserialization in `auto_edit.py`
- [ ] (Optional) Register in `CONFIG["beat_effects"]` in `auto_edit.py` for beat-synced dispatch
