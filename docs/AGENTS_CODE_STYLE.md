# Code Conventions — Agent Guide

When modifying this codebase, follow these conventions.

## File Structure

```
app.py               — VideoPipeline class (orchestrator, render loop)
auto_edit.py          — Auto-editing engine (plan generation, CLI)
utils/
  base.py             — Abstract BaseEffect, BaseTransition
  easing.py           — Easing functions
  effects.py          — All effect implementations
  grid.py             — GridScene, LayeredScene, GridPanel, Layer
  transitions.py      — SlideTransition, ZoomTransition
  yolo_seg.py         — (placeholder, empty)
```

## Imports

- Standard library first, then third-party, then local
- Use explicit imports (no `from module import *`)
- Local imports from `utils.`:

```python
import cv2
import numpy as np
from utils.base import BaseEffect, EasingType
```

## Typing

All function signatures use type annotations:

```python
from typing import Optional, Union, Callable, Tuple, List, Any
import numpy as np

def seek_frame(clip_idx: int, local_output_time: float, target_size: tuple) -> tuple:
    ...
```

## The BaseEffect / BaseTransition Pattern

**Never override `process()`**. Always override `apply()`:

```python
class MyEffect(BaseEffect):
    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        # progress is already eased by process()
        ...
```

## Naming

| Convention | Example |
|---|---|
| Classes: `PascalCase` | `VideoPipeline`, `GridScene`, `ZoomEffect` |
| Methods/functions: `snake_case` | `add_clip()`, `render_frame()`, `_build_effects_from_props()` |
| Private: `_leading_underscore` | `_resolve_dur()`, `_make_alpha()`, `_last_frame` |
| Constants: `UPPER_SNAKE` | `CLIP_END`, `EASING_FUNCTIONS` |
| Dunder: `__init__`, `__del__` | Only for standard Python protocols |

## Docstrings

Follow the existing Google-style docstrings:

```python
def add_clip(
    self,
    filepath: str,
    start_time: float = 0,
    duration: float = -1,
    ...
):
    """One-line summary.

    Args:
        filepath:   Path to the source video file.
        start_time: Offset (seconds) into the source to begin reading.
        duration:   How many seconds the clip occupies in the OUTPUT timeline
                    (-1 = full clip).

    Returns:
        Description of return value, if applicable.
    """
```

## Easing Handling

Effects receive `progress` already eased. Never call easing functions inside `apply()`:

```python
# CORRECT — process() handles easing:
class MyEffect(BaseEffect):
    def apply(self, frame, current_time, progress):
        val = self.start + (self.end - self.start) * progress
        ...

# INCORRECT — do not apply easing in apply():
def apply(self, frame, current_time, progress):
    eased = ease_in(progress)  # WRONG — already eased
```

## EasingType Options

```python
EasingType = Union[str, Tuple[float, float, float, float], Callable[[float], float]]
```

- `"linear"`, `"ease_in"`, `"ease_out"`, `"ease_in_out"`
- `(x1, y1, x2, y2)` — cubic bezier (CSS-style)
- `Callable[[float], float]` — custom function

## Sentinel for Duration

```python
from app import CLIP_END

# CLIP_END = "clip_end" string, resolved to -1.0 internally
pipeline.add_clip_effect(0, effect, duration=CLIP_END)
```

## Frame Handling

- All frames are `np.ndarray` with `dtype=np.uint8`, shape `(H, W, 3)`, BGR order
- Return the **same array unchanged** if no modification is needed (zero-copy)
- Use `.astype(np.float32)` for arithmetic, then clip back to `[0, 255]` and `.astype(np.uint8)`
- Always `del frame` after use in render loops to help GC

## YOLO Temporal Smoothing

All YOLO effects use the same EMA pattern (copy-paste from existing effects):

```python
# Detection branch
prev_mask = 0.3 * new_mask + 0.7 * prev_mask

# Missed frame branch
combined = last_good_mask * (0.97 ** missed_frames)
prev_mask = 0.15 * combined + 0.85 * prev_mask
```

Declare `prev_mask`, `last_good_mask`, `missed_frames` as instance attributes.

## Cache Pattern (YoloTextEffect)

```python
cache_key = (anim_type, round(phase_p, 3), round(text_opacity, 4), w, h)
if cache_key in self._text_layer_cache:
    return self._text_layer_cache[cache_key]
# ... build ...
self._text_layer_cache.clear()
self._text_layer_cache[cache_key] = result
```

Keep only the most recent entry to bound memory.

## Error Handling

- Print warnings, don't raise on recoverable errors (e.g., missing audio streams)
- Use `try/finally` in render to guarantee resource release (`VideoCapture.release()`, temp file cleanup)
- Null-check models: `if self.model is None: return frame`

## Adding a New File

- Place in `utils/` if it's a utility module
- Import from `utils.base` for effects/transitions
- Update imports in `app.py` if the new module is referenced there
