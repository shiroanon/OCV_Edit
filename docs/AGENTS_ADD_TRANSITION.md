# Adding a New Transition — Agent Guide

## 1. Understand the Base Class

Every transition subclasses `BaseTransition` from `utils/base.py`:

```python
from utils.base import BaseTransition, EasingType
from typing import Union, Tuple, Callable

class MyTransition(BaseTransition):
    def __init__(self, duration: float = 1.0, easing: EasingType = "linear"):
        super().__init__(duration, easing)

    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        # frame1:    outgoing frame (BGR uint8 H,W,3)
        # frame2:    incoming frame (BGR uint8 H,W,3)
        # progress:  eased 0→1 value (0 = all frame1, 1 = all frame2)
        return blended_frame
```

Key contract:
- `process()` applies easing then calls `apply()` — **never override `process()`**
- `progress` is already eased by `process()` before reaching `apply()`
- Both frames are guaranteed same size
- Return a frame of the same dimensions

## 2. File to Edit

Add your class to `utils/transitions.py`. Import `BaseTransition` and `EasingType` from `utils.base`.

## 3. Complete Example

```python
# utils/transitions.py

class WipeTransition(BaseTransition):
    def __init__(self, duration=1.0, easing="ease_in_out", direction="left"):
        super().__init__(duration, easing)
        self.direction = direction

    def apply(self, frame1, frame2, progress):
        h, w = frame1.shape[:2]
        out = frame2.copy()

        if self.direction == "left":
            wipe_x = int(w * progress)
            out[:, :wipe_x] = frame1[:, :wipe_x]
        elif self.direction == "right":
            wipe_x = int(w * (1 - progress))
            out[:, wipe_x:] = frame1[:, wipe_x:]
        elif self.direction == "up":
            wipe_y = int(h * progress)
            out[:wipe_y, :] = frame1[:wipe_y, :]
        elif self.direction == "down":
            wipe_y = int(h * (1 - progress))
            out[wipe_y:, :] = frame1[wipe_y:, :]

        return out
```

## 4. Use It

```python
from utils.transitions import WipeTransition

pipeline.add_transition(WipeTransition(duration=0.5, direction="right", easing="ease_out"))
```

## Existing Transitions (Reference)

| Class | Params | Mechanism |
|---|---|---|
| `SlideTransition` | `direction: "left"\|"right"\|"up"\|"down"` | Offset-based: frame1 slides out, frame2 slides in |
| `ZoomTransition` | `mode: "in"\|"out"\|"inout"\|"outin"` | Scale + center-crop/crossfade via `addWeighted` |

Look at these implementations in `utils/transitions.py` as templates.

## Checklist

- [ ] Subclass `BaseTransition`
- [ ] Implement `apply(frame1, frame2, progress) → np.ndarray`
- [ ] Import from `utils.base` only
- [ ] Add to `utils/transitions.py`
- [ ] Register import in `app.py` if needed by demo code
