# Grid and Layered Scene System — Agent Guide

Both systems live in `utils/grid.py`. They produce composite frames rendered by `VideoPipeline`.

---

## Architecture

```
BasePanel  (shared frame decoding + effects)
  ├── GridPanel  (grid cell + shape / overlap / blend / YOLO mask / freeform pos)
  └── Layer      (freeform layer with mask, blend, YOLO)
```

---

## GridScene — Multi-Panel Layout with Shapes & Overlap

### GridPanel (one cell)

```python
from utils.grid import GridPanel

panel = GridPanel(
    filepath="video.mp4",          # source video (omit if ref_panel is set)
    start_time=0.0,                # offset into source
    speed=1.0,                     # playback speed
    loop=True,                     # loop when source ends
    flip=None,                     # "h", "v", "both", or None
    ref_panel=None,                # share another panel's decoded frames
    resize_mode="fit",             # "fill" or "fit"

    # --- New: Shape & overlap ---
    shape="rect",                  # "rect", "ellipse", "circle", "diamond",
                                   #   or callable(time) -> ndarray mask
    z_index=0,                     # draw order (higher = on top)
    blend_mode="normal",           # "normal", "multiply", "screen", "add",
                                   #   "overlay", "difference"
    opacity=1.0,                   # float or callable(time)
    mask_type=None,                # "subject", "background", "rect", "ellipse",
                                   #   "polygon", ndarray, callable
    mask_params=None,              # dict of mask parameters
    feather=0,                     # mask edge blur radius
    invert=False,                  # invert mask
    yolo_model_path=None,          # for YOLO subject/background masks

    # --- New: Freeform position override ---
    position=None,                 # (x, y) — normalized floats, pixel ints,
                                   #   or callable(time). If set, overrides grid.
    size=None,                     # (w, h) — overrides grid cell size.
    anchor="center",               # "center", "top-left", "top-right",
                                   #   "bottom-left", "bottom-right"
)

panel.add_effect(my_effect, start_time=0.0, duration=-1)
```

**ref_panel**: When set, `filepath` is ignored. The panel reuses the reference panel's decoded frames but can apply different flip/effects independently. Useful for mirrored panels without doubling memory.

### GridScene (the container)

```python
from utils.grid import GridPanel, GridScene

scene = GridScene(
    panels=[p_left, p_center, p_right],       # List[GridPanel]
    layout=(1, 3),                              # (rows, cols) — for grid-mode panels
    duration=6.0,                               # output duration (seconds)
    col_weights=[1, 2, 1],                     # relative width ratios
    row_weights=None,                           # default equal heights
    gap=4,                                      # pixel gap between panels
    keep_audio=None,                            # index of panel for audio
)

# Scene-level effects (applied to composited canvas)
scene.add_effect(RGBShiftEffect(start_shift=0, end_shift=40), start_time=4.5, duration=1.5)
```

### Pipeline Integration

```python
pipeline.add_grid_scene(scene)
```

Transitions work between grid scenes and clips normally.

### How It Renders

1. `_compute_rects()` divides output into cell rectangles (with gap, weight ratios)
2. For each `GridPanel`:
   - `get_frame()` → `apply_effects()` → resize → shape mask → feature mask → blend composite
3. Panels are drawn in `z_index` order (higher = on top)
4. Apply scene-level effects on full canvas

### Custom Shapes

```python
# Circle panel
p = GridPanel("video.mp4", shape="circle")

# Diamond panel
p = GridPanel("video.mp4", shape="diamond")

# Custom mask via callable (pulsating circle)
p = GridPanel("video.mp4", shape=lambda t: make_circle_mask(w, h, radius=0.3 + 0.1*sin(t)))
```

### Overlapping Panels

Panels with `z_index` > 0 are drawn on top of lower-index panels. Use `blend_mode` to control how overlapping pixels combine:

```python
p_bg  = GridPanel("bg.mp4",  z_index=0)           # bottom layer
p_fg  = GridPanel("fg.mp4",  z_index=1,            # on top
                  blend_mode="screen",
                  mask_type="subject",              # YOLO subject extraction
                  yolo_model_path="models/yolo/")
```

### Freeform Positioning

When `position` is set, the panel is placed at that position instead of the grid:

```python
p = GridPanel("video.mp4",
    position=lambda t: (0.5 + 0.3 * math.sin(t), 0.5),  # animated position
    size=(0.4, 0.4),                                      # 40% of frame
)
```

---

## LayeredScene — Multi-Layer Composite

### Layer (one layer)

```python
from utils.grid import Layer

layer = Layer(
    filepath="video.mp4",
    start_time=0.0,
    speed=1.0,
    loop=True,
    flip=None,
    ref_layer=None,               # share another layer's frames
    resize_mode="fit",
    position=(0.5, 0.5),          # normalized float, pixel int, or callable(time)
    size=None,                     # (w, h) in pixels/floats, or callable(time)
    anchor="center",               # "center", "top-left", "top-right",
                                   #   "bottom-left", "bottom-right"
    opacity=1.0,                   # float 0-1 or callable(time)
    blend_mode="normal",           # "normal", "multiply", "screen", "add",
                                   #   "overlay", "difference"
    mask_type=None,                # "rect", "ellipse", "polygon", "subject",
                                   #   "background", ndarray, callable
    mask_params=None,              # dict passed to mask builder
    feather=0,                     # mask edge blur radius
    invert=False,                  # invert mask
    yolo_model_path=None,          # for "subject"/"background" masks
)

layer.add_effect(my_effect)
```

### LayeredScene (the container)

```python
from utils.grid import Layer, LayeredScene

scene = LayeredScene(
    layers=[bg_layer, subject_layer, overlay_layer],  # bottom → top
    duration=5.0,
    keep_audio=None,
)
```

### Pipeline Integration

```python
pipeline.add_layered_scene(scene)
```

### Blend Modes

| Mode | Formula |
|------|---------|
| `normal` | `layer` |
| `multiply` | `canvas * layer / 255` |
| `screen` | `255 - (255-canvas) * (255-layer) / 255` |
| `add` | `min(255, canvas + layer)` |
| `overlay` | `<128 ? 2*c*l/255 : 255 - 2*(255-c)*(255-l)/255` |
| `difference` | `abs(canvas - layer)` |

### How It Renders

1. Creates empty black canvas
2. For each `Layer` (bottom→top): get frame → apply effects → resize → mask → blend → composite
3. Apply scene-level effects

---

## Complete Examples

- `grid_edit.py` — 1×3 grid with mirrored panel, YOLO glow, per-panel effects, scene-level zoom/RGB shift
- `test_layered.py` — 3-layer composite: semitransparent bg + YOLO-masked subject + elliptical screen overlay
- `grid_overlap.py` — 1×3 grid with YOLO subject overlapping adjacent panels, shape-masked panels, blend modes

## Key Patterns

- **ref_panel / ref_layer**: Zero-cost frame sharing. The reference opens the VideoCapture once.
- **Callable position/opacity/size**: Enables animation without effect classes.
  ```python
  position=lambda t: (0.5 + 0.3 * math.sin(t), 0.5)
  ```
- **YOLO mask per panel**: Each panel can have its own `mask_type="subject"` or `"background"` with independent temporal smoothing.
- **Shape masks**: Visual outline for panels — circles, diamonds, ellipses, or custom.
- **Z-index overlap**: Panels with higher `z_index` render on top, enabling overlapping composites within a grid.
