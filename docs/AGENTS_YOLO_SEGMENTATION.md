# YOLO Person Segmentation — Agent Guide

## Overview

The project uses Ultralytics YOLOv8n-seg (OpenVINO INT8 quantized) for real-time person segmentation. Three effects consume YOLO masks, and the mask system is exposed generically for custom use.

## Model

**Path**: `utils/yolo26s-seg_int8_openvino_model/`
- COCO class 0 only (person)
- Input size: 320×320 (optimized for speed)
- `retina_masks=True` for full-resolution masks (no letterbox cutoff)
- Cached globally via `_yolo_model_cache` to avoid reloads

**Loading**:
```python
from utils.effects import get_yolo_model
model = get_yolo_model("utils/yolo26s-seg_int8_openvino_model/")
# Returns cached instance on subsequent calls
```

## YOLO Effects (3 classes in `utils/effects.py`)

### 1. `YoloGlowSegEffect` — Person Glow

Adds a colored glow around detected people.

```python
YoloGlowSegEffect(
    model_path="utils/yolo26s-seg_int8_openvino_model/",
    glow_color=(0, 255, 255),     # BGR color
    blur_amount=41,                # Gaussian blur kernel (odd)
    intensity=1.5,                 # glow brightness multiplier
)
```

Mask pipeline: YOLO mask → dilate (11×11) → Gaussian blur → additive blend.

### 2. `YoloTextEffect` — Depth-Composited Text

Renders text, then uses YOLO mask to place the person **on top of** the text (cinematic depth).

```python
YoloTextEffect(
    text="TITLE",
    font_path="Audiowide-Regular.ttf",
    font_size=150,
    position="center",             # or (x, y) tuple
    color=(255, 255, 255),         # BGR
    opacity=1.0,
    transition_in=0.5,             # seconds for enter animation
    transition_out=0.5,            # seconds for exit animation
    animate_in="slide_up",         # "fade", "slide_up", "slide_down", "none"
    animate_out="fade",            # "fade", "slide_up", "slide_down", "none"
    stroke_width=0,
    stroke_color=(0, 0, 0),        # BGR
    model_path="utils/yolo26s-seg_int8_openvino_model/",
    depth_composite=True,          # person on top of text
    line_spacing=1.1,
)
```

Duration model: `transition_in → hold → transition_out` (total = `duration` passed to `add_clip_effect`).

When `model_path=None`, text renders without YOLO depth (plain overlay).

Text layer is cached by `(anim_type, phase_p, opacity, w, h)` to avoid re-rendering every frame.

### 3. `YoloSegMaskedEffect` — Selective Subject/Background Effect

Wraps any `BaseEffect` and applies it only to the person or the background.

```python
YoloSegMaskedEffect(
    inner_effect,                            # any BaseEffect instance
    model_path="utils/yolo26s-seg_int8_openvino_model/",
    target="subject",                        # "subject" or "background"
    feather=15,                              # extra edge softening (pixels)
)
```

Examples:
```python
# Desaturate background, keep subject in color
bg_desat = YoloSegMaskedEffect(
    ColorAdjustEffect(start_params={"saturation": 0.0}, end_params={"saturation": 0.0}),
    model_path=MODEL, target="background", feather=15,
)

# Blur just the subject (simulate focus pull)
subject_blur = YoloSegMaskedEffect(
    BlurEffect(start_blur=0, end_blur=31),
    model_path=MODEL, target="subject", feather=10,
)
```

## Temporal Smoothing (EMA)

All YOLO effects use the same robust strategy to prevent mask flicker:

```python
# On successful detection:
prev_mask = 0.3 * new_mask + 0.7 * prev_mask

# On missed frame (up to 15 frames):
combined = last_good_mask * (0.97 ^ missed_frames)
prev_mask = 0.15 * combined + 0.85 * prev_mask

# After 15 consecutive misses:
prev_mask = zeros
```

Final mask pipeline:
1. Binarize at >0.3 threshold
2. Dilate with 11×11 kernel
3. Gaussian blur (21×21) for soft edges
4. Clamp to [0, 1]

## Universal Mask Builder

`build_frame_mask()` in `utils/effects.py` (line 1235) supports all mask types:

```python
from utils.effects import build_frame_mask

mask = build_frame_mask(
    frame,
    mask_type="subject",           # "rect", "ellipse", "polygon", "subject", "background", or ndarray/callable
    mask_params={"cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3},
    feather=10,
    invert=False,
    model_path="utils/yolo26s-seg_int8_openvino_model/",
    local_time=0.0,
    state_holder=some_object,      # stores EMA state across frames
)
```

This is used internally by `Layer.render_frame()` in `LayeredScene` for per-layer YOLO masking.

## Standalone YOLO Demo

`utils/yolo_person_example.py` shows basic model usage:

```python
from ultralytics import YOLO
model = YOLO("yolo26s-seg_int8_openvino_model/")
results = model.predict(source="video.mp4", save=True, imgsz=320, device="cpu", stream=True)
```

## Performance Notes

- Set `model_path=None` to skip YOLO entirely (saves ~30ms/frame on CPU)
- The OpenVINO INT8 model is ~3× faster than the raw PyTorch `.pt`
- YOLO effects are applied per-frame — expect ~30-50ms per call on CPU
- Temporal EMA smoothing adds negligible overhead (<1ms)
