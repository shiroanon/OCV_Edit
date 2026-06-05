# Building a Pipeline — Agent Guide

## Pipeline Overview

`VideoPipeline` (in `app.py`) manages a timeline of clips, transitions, and effects, then renders to MP4.

## Constructor

```python
pipeline = VideoPipeline(
    fps=30.0,                    # output frames per second
    output_size=(1920, 1080),    # output frame dimensions (width, height)
    resize_mode="fill",          # "fill" (zoom-crop) or "fit" (letterbox)
)
```

## Adding Clips

```python
pipeline.add_clip(
    filepath="video.mp4",        # path to source video
    start_time=0.0,              # offset into source (seconds)
    duration=-1,                 # -1 = full clip duration; or explicit seconds
    keep_audio=True,             # include this clip's audio
    speed=1.0,                   # playback speed (2.0 = 2x, 0.5 = slomo)
    resize_mode=None,            # override pipeline default ("fill"/"fit")
)
```

Clips loop automatically when source time exceeds source duration.

## Adding Transitions

Transitions blend between clip `N` and clip `N+1`:

```python
from utils.transitions import SlideTransition, ZoomTransition

pipeline.add_transition(SlideTransition(duration=0.5, direction="left"))
pipeline.add_transition(ZoomTransition(duration=0.3, mode="inout"))
```

The `i`-th transition is applied between `clips[i]` and `clips[i+1]`.

## Adding Effects

### Per-Clip Effects

```python
from utils.effects import BlurEffect, ZoomEffect, RGBShiftEffect, ColorAdjustEffect

effect = BlurEffect(start_blur=0, end_blur=21)
pipeline.add_clip_effect(
    clip_idx=0,
    effect=effect,
    start_time=0.0,
    duration=3.0,              # seconds; or CLIP_END for entire clip
)
```

### Global Timeline Effects

```python
pipeline.add_effect(
    effect=my_effect,
    start_time=0.0,
    duration=CLIP_END,
)
```

### Duration Sentinel

Use `CLIP_END` (imported from `app`) to mean "until the clip/pipeline ends":

```python
from app import CLIP_END
pipeline.add_clip_effect(0, my_effect, duration=CLIP_END)
```

## GSAP-Style Shorthand API

Three methods replace manual effect instantiation for common properties:

### Supported Properties
| Property | Type | Neutral | Description |
|---|---|---|---|
| `blur` | int | 0 | Gaussian blur kernel size |
| `rgb_shift` | float | 0.0 | Chromatic aberration pixel offset |
| `rgb_shift_angle` | float | 0.0 | Shift direction in degrees |
| `zoom` | float | 1.0 | Scale factor |
| `saturation` | float | 1.0 | Saturation multiplier |
| `brightness` | float | 0.0 | Additive brightness offset |
| `contrast` | float | 1.0 | Contrast multiplier |
| `gamma` | float | 1.0 | Gamma correction |

### `.to()` — Animate FROM neutral TO given values

```python
pipeline.to(clip_idx=0, duration=1.5, blur=25, zoom=1.3, easing="ease_out")
pipeline.to(clip_idx=0, duration=CLIP_END, saturation=0.0)  # entire clip
```

### `.from_()` — Animate FROM given values TO neutral

```python
pipeline.from_(clip_idx=1, duration=1.0, blur=31, zoom=1.5, easing="ease_in")
```

### `.fromTo()` — Explicit start and end values

```python
pipeline.fromTo(
    clip_idx=1, duration=2.0,
    from_props={"saturation": 0.0, "blur": 15},
    to_props={"saturation": 1.5, "blur": 0},
    easing=(0.42, 0, 0.58, 1)   # cubic-bezier
)
```

### Easing Options

- String: `"linear"`, `"ease_in"`, `"ease_out"`, `"ease_in_out"`
- Tuple: `(x1, y1, x2, y2)` for cubic bezier (CSS-style)
- Callable: `lambda t: t ** 3`

## Rendering

```python
pipeline.render("output.mp4")
```

The render process:
1. Lazy-opens `VideoCapture` per clip
2. Reads source frames with smart seeking (avoids redundant `cap.set()`)
3. Resizes (fill or fit)
4. Applies clip-local effects → transition blending → global effects
5. Writes to temp video
6. Extracts/processes audio per clip via ffmpeg (atempo speed change)
7. Merges audio segments with crossfades via pydub
8. Muxes final video + audio with ffmpeg

## Audio Notes

- `keep_audio=False` on a clip replaces its audio with silence
- Audio is processed as temp WAV files (never full decode to RAM)
- Crossfade duration = preceding transition duration
- Requires `pydub` and `ffmpeg` on system PATH

## Full Example (from `app.py` `__main__`)

```python
pipeline = VideoPipeline(fps=30.0, output_size=(1920, 1080))
pipeline.add_clip("person.mp4", duration=10.0)
pipeline.add_transition(ZoomTransition(duration=0.3, mode="inout"))
pipeline.add_clip("test2.mp4", duration=3.0)

# YOLO glow + text + background desat + blur + color grade
# Then GSAP effects...
pipeline.to(clip_idx=0, duration=5.0, zoom=1.2)
pipeline.from_(clip_idx=1, duration=0.8, brightness=-120, saturation=0.0)

pipeline.render("output.mp4")
```

See `grid_edit.py` and `test_layered.py` for complete working examples.
