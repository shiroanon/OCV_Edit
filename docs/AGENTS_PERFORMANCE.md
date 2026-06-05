# Performance Optimization — Agent Guide

## YOLO Model

The OpenVINO INT8 model at `utils/yolo26n-seg_int8_openvino_model/` is already optimized.
- **Input size 320×320** (not full resolution) — this is the primary speed lever
- **INT8 quantization** gives ~3× speedup over FP16 on CPU
- **`retina_masks=True`** ensures masks aren't clipped by letterboxing (no quality loss at 320px)
- The model is **globally cached** in `_yolo_model_cache` — never reloaded

**Avoid YOLO when not needed**: Set `model_path=None` on `YoloTextEffect` or skip YOLO effects entirely to save ~30-50ms/frame.

## Frame Seeking Optimizations

`app.py` and `utils/grid.py` share the same smart seeking pattern:

```python
# 1. Same frame → use cache (zero-cost)
if src_frame_idx == last_idx:
    return cached_frame

# 2. Sequential (next frame) → just read (fastest path)
if src_frame_idx == last_idx + 1:
    cap.read()

# 3. Short jump forward (<5 frames) → grab() (faster than set)
elif src_frame_idx > last_idx and src_frame_idx - last_idx < 5:
    for _ in range(delta - 1):
        cap.grab()
    cap.read()

# 4. Large/backward jump → cap.set() (required)
else:
    cap.set(CAP_PROP_POS_FRAMES, idx)
    cap.read()
```

This avoids the expensive `cap.set()` syscall for the common case of sequential or near-sequential access.

## Lazy Loading

- `VideoCapture` objects are opened only when first needed in the render loop (`_open_cap()`)
- Captures are released immediately after a clip finishes rendering (`_release_cap()`)
- Temp audio WAV files are processed one at a time (never full decode to RAM)

## Memory Management

```python
# Explicit frame deletion helps GC
del frame
del blended

# GC collect between clips
gc.collect()
```

- Audio segments: each clip's audio is extracted to a separate temp WAV, processed one at a time
- Merging: only two segments are in memory at once during crossfade
- `YoloTextEffect._text_layer_cache`: cleared to one entry per frame

## OpenCV VideoWriter Settings

- Codec: `mp4v` (software, widely compatible)
- Output resolution: default 1980×1080 — smaller sizes render faster
- FPS: 30 default — lower FPS = fewer frames to process

## GLSL/GPU Path

`GLSLEffect` uses `moderngl` for GPU acceleration:
- GL context created once (singleton)
- Texture/FBO resources recreated only on resolution change
- Fast path: in-place shader without CPU↔GPU transfers (if the whole pipeline could run on GPU)
- Current bottleneck: each frame requires CPU→GPU upload + GPU→CPU readback

## Effect Processing Order

Effects are applied in registration order. The pipeline processes:

```
Local effects (per clip) → Transition blend → Global effects
```

Minimize the number of simultaneous effects. Every `BaseEffect.process()` call adds overhead.

## ZoomTransition Performance

`ZoomTransition` calls `cv2.resize()` twice per frame (once for each frame). This is the most expensive transition. `SlideTransition` is cheaper (only array slicing, no resize).

## Resize Modes

- `"fill"` (zoom-crop): uses `max()` scale → potentially smaller memory allocation
- `"fit"` (letterbox): creates a full-size black canvas → more memory per frame
- Prefer `"fill"` for marginal speed gain

## General Tips

1. **Profile first** — YOLO inference is nearly always the bottleneck
2. **Reduce YOLO calls** — use `build_frame_mask()` with geometric shapes instead of YOLO where possible
3. **Lower output resolution** — 1280×720 is 44% fewer pixels than 1920×1080
4. **Reduce duration** — fewer frames = faster render
5. **Avoid `GLSLEffect` on integrated GPUs** — CPU→GPU→CPU transfer dominates
6. **Use `ref_panel`** in `GridPanel` to share decoded frames instead of opening duplicate VideoCaptures
