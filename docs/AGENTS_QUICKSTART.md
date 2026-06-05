# OpenCV-Transitions — AI Agent Quickstart

## What This Project Does

A Python declarative video editing pipeline. You build a timeline of clips, transitions, and effects in code, then render to MP4. Supports OpenCV GPU (optional via moderngl GLSL shaders) and **YOLO person segmentation** for AI-driven selective effects (subject/background isolation, glow, depth compositing).

## Key Files

| File | Purpose |
|---|---|
| `app.py` | `VideoPipeline` class — core render engine |
| `auto_edit.py` | Auto-editing engine — beat alignment, plan generation, CLI |
| `utils/effects.py` | All effect implementations (10 classes) |
| `utils/grid.py` | `GridScene`, `LayeredScene`, `GridPanel`, `Layer` |
| `utils/transitions.py` | `SlideTransition`, `ZoomTransition` |
| `utils/easing.py` | Easing functions (linear, ease-in/out, cubic-bezier) |
| `utils/base.py` | Abstract `BaseEffect` & `BaseTransition` |

## Minimum Dependencies

`opencv-python`, `numpy`, `ultralytics`, `mutagen`, `pydub`, `Pillow`, `moderngl` (optional). System `ffmpeg` required.

## Minimal Pipeline (10 lines)

```python
from app import VideoPipeline
from utils.transitions import ZoomTransition

pipeline = VideoPipeline(fps=30, output_size=(1920, 1080))
pipeline.add_clip("video1.mp4", duration=5.0)
pipeline.add_transition(ZoomTransition(duration=0.3))
pipeline.add_clip("video2.mp4", duration=3.0)
pipeline.render("output.mp4")
```

## Quick Patterns

- **Add effect to clip**: `pipeline.add_clip_effect(clip_idx=0, effect=my_effect, duration=2.0)`
- **GSAP-style animation**: `pipeline.to(clip_idx=0, duration=2.0, blur=25, zoom=1.3, easing="ease_out")`
- **Grid scene**: Build `GridPanel` list → wrap in `GridScene` → `pipeline.add_grid_scene(scene)`
- **Layered scene**: Build `Layer` list → wrap in `LayeredScene` → `pipeline.add_layered_scene(scene)`
- **YOLO effect**: `YoloSegMaskedEffect(inner_effect, model_path="utils/yolo26n-seg_int8_openvino_model/", target="background")`

## YOLO Model Path

`utils/yolo26n-seg_int8_openvino_model/` (OpenVINO INT8, class 0=person only, imgsz=320)
