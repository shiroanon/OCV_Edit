# Rust Port — Agent Guide

The Rust port of OCV_Edit lives under `rust/` and mirrors the Python `utils/` modules. It is a multi-crate workspace; `ocv-core` contains the rendering engine, `ocv-auto` deserializes the Python editor's `plan.json` and applies it, `ocv-cli` provides the CLI entry point, and `ocv-gpu` is a work-in-progress GPU-accelerated offload.

---

## Workspace Layout

```
rust/
├── Cargo.toml                  # workspace root
├── crates/
│   ├── core/                   # ocv-core — rendering engine
│   │   ├── src/
│   │   │   ├── lib.rs          # module declarations
│   │   │   ├── scene.rs        # GridScene, LayeredScene, PanelDef, ShapeSpec
│   │   │   ├── frame.rs        # Frame/Mask types, resize, blit, blend, VideoSource/Sink
│   │   │   ├── pipeline.rs     # VideoPipeline (orchestrator)
│   │   │   ├── effect.rs       # Effect/Transition/MaskLoader traits
│   │   │   ├── effects.rs      # Core effect implementations
│   │   │   ├── effects_grid.rs # Grid-specific effects (KenBurns, glitch, flash, etc.)
│   │   │   ├── transitions.rs  # Transition implementations
│   │   │   ├── easing.rs       # Easing functions
│   │   │   ├── text.rs         # Text rendering (ab_glyph)
│   │   │   ├── audio.rs        # Audio extraction/muxing
│   │   │   └── yolo.rs         # YOLO segmentation (ONNX Runtime via `ort`)
│   │   └── Cargo.toml
│   ├── auto/                   # ocv-auto — plan deserialization + application
│   │   ├── src/
│   │   │   ├── plan.rs         # Structs mirroring plan.json
│   │   │   ├── apply.rs        # apply_edit_plan(), apply_wave_grid()
│   │   │   ├── effects_map.rs  # Effect type string → Rust object
│   │   │   ├── config.rs       # Configuration
│   │   │   └── generate.rs     # Plan generation (for testing)
│   │   └── Cargo.toml
│   ├── cli/                    # ocv-cli — binary entry point
│   │   ├── examples/grid_test.rs
│   │   └── src/
│   └── gpu/                    # ocv-gpu — WIP GPU renderer
│       └── src/
├── server/                     # Python FastAPI preview server
└── frontend/                   # Svelte frontend
```

---

## Data Model — Key Types

### `Frame` / `Mask` (`frame.rs`)

| Type | Definition | Channel order |
|------|-----------|---------------|
| `Frame` | `ImageBuffer<Rgb<u8>, Vec<u8>>` | BGR (to match OpenCV) |
| `Mask` | `ImageBuffer<Luma<f32>, Vec<f32>>` | single-channel float [0,1] |

Declare new frames with `Frame::new(w, h)` (zero-initialized, black). Use `RawMut` trait for direct mutable access to the pixel buffer.

### `PanelDef` (`scene.rs`)

One-to-one with Python's `GridPanel`/`Layer`. Fields:

| Field | Type | Python equivalent | Notes |
|-------|------|-------------------|-------|
| `source_index` | `usize` | `filepath` | Index into `SceneSources`, not a path |
| `start_time` | `f32` | `start_time` | |
| `speed` | `f32` | `speed` | |
| `loop_` | `bool` | `loop` | Trailing underscore because `loop` is a Rust keyword |
| `flip` | `Option<i32>` | `flip` | 0=vertical, 1=horizontal, else=180° |
| `effects` | `Vec<(Effect, f32, f64)>` | `effects` | (effect, start_time, duration) triples |
| `shape` | `ShapeSpec` | `shape` | enum, not callable — no wave mask support |
| `z_index` | `i32` | `z_index` | |
| `blend` | `String` | `blend_mode` | "normal", "multiply", "screen", "add", "overlay", "difference" |
| `opacity` | `f32` | `opacity` | static float only (no callable) |
| `mask` | `Option<MaskSpec>` | `mask_type`/`mask_params` | geometric masks only |
| `feather` | `f32` | `feather` | |
| `invert` | `bool` | `invert` | |
| `position` | `Option<(f32,f32)>` | `position` | static tuple only (no callable) |
| `size` | `Option<(f32,f32)>` | `size` | static tuple only (no callable) |
| `anchor` | `String` | `anchor` | "center", "top-left", "top-right", "bottom-left", "bottom-right" |
| `resize_mode` | `String` | `resize_mode` | "fit" or "fill" |
| `loader` | `Box<dyn MaskLoader>` | YOLO mask machinery | Always `NoMask` (YOLO not wired into grid) |

### `ShapeSpec` (`scene.rs`)

```rust
enum ShapeSpec { Rect, Ellipse, Circle, Diamond }
```

No callable or numpy-array shape support (unlike Python).

### `SceneSources` (`scene.rs`)

Owns a set of decoded `VideoSource`s, each with `(start_time, speed, loop)` metadata. Panels reference sources by index so multiple panels can share the same source without redundant decodes.

---

## Scene Rendering

### `GridScene::render_frame()`

1. Pre-fetches all source frames into a cache (`cached[source_index]`)
2. For each panel:
   - Clone from cache → `apply_panel_effects()` → `flip_frame()`
   - Resolve rect: either grid position (`compute_rects`) or freeform (`resolve_rect`)
   - Push `(z_index, panel_index, frame, rect)` into `render_items`
3. Sort `render_items` by `z_index`
4. For each item: `composite_panel()` — resize → layer buffer → **content_mask** → shape_mask → feature_mask → YOLO_loader_mask → opacity → blend composite
5. Apply scene-level effects

### `composite_panel()` — Mask Stack (match Python order)

```
final_mask = content_mask * shape_mask * feature_mask * loader_mask * opacity
```

The **content_mask** (added to match Python) is `1.0` where the resized video frame sits and `0.0` in the black-padding area of "fit" mode. Without it, "fit" mode panels would composite black bars onto the canvas.

---

## Python–Rust Alignment

### Anchors (`resolve_rect`)

Python's `_resolve_panel_rect` has explicit handlers for `"center"`, `"top-left"`, `"top-right"`, `"bottom-left"`, `"bottom-right"`, and an `else` branch that defaults to center. Rust matches this exactly — the `else` / wildcard branch now defaults to `center` behavior (`px -= pw/2; py -= ph/2`).

Python's auto-editor passes `anchor="right"` and `anchor="left"` to panels. These strings have no special handling in Python (fall through to `else` → center). The Rust `resolve_rect` treats them identically now.

### Grid Rect Computation (`compute_rects`)

| Aspect | Python | Rust |
|--------|--------|------|
| Weight → pixel | `int(w * avail_w)` | `(w / sum * avail_w).trunc()` |
| Last-element fixup | `col_widths[-1] = avail_w - sum(...)` | same, added |

Both now use truncation toward zero (not rounding) and fill any sub-pixel gap in the last column/row.

### Wave Grid Layout (`apply_wave_grid` in `auto/src/apply.rs`)

Matches Python `_apply_wave_grid` exactly:

| Panel | Position | Size | Anchor | z_index |
|-------|----------|------|--------|---------|
| Left | `(0.15, 0.5)` | `(0.55, 1.0)` | `"center"` | 0 |
| Center | `(0.5, 0.5)` | `(0.70, 1.0)` | `"center"` | -1 |
| Right | `(0.85, 0.5)` | `(0.55, 1.0)` | `"center"` | 0 |

Column weights are always `[1.0, 2.0, 1.0]` for 3-panel grids.

### content_mask (Critical Fix)

Python multiplies a `content_mask` into the final blend mask so that black padding in "fit" mode is transparent. Rust now does the same — a `Mask::new(pw, ph)` with `1.0` only in the region `[oy..oy+ch, ox..ox+cw]` where the resized frame was placed, multiplied into `final_mask` before shape/feature masks.

---

## Effects (`Effect` trait)

```rust
trait Effect: EasingHolder + Send + Sync {
    fn apply(&self, frame: &Frame, current_time: f32, progress: f32, frame_index: u64) -> Frame;
    fn process(&self, ...) { /* applies easing, then calls apply() */ }
}
```

- Implementors only override `apply()` (never `process()`), matching Python's `BaseEffect.apply()`.
- `progress` is already eased — do not re-apply easing in `apply()`.
- Effects are stored as `Vec<(Box<dyn Effect>, f32, f64)>` where the inner tuple is `(effect, start_time, duration)`.

### Grid-Specific Effects (`effects_grid.rs`)

`KenBurnsEffect`, `PanelSlideEffect`, `PanelPulseEffect`, `PanelBounceEffect`, `PanelSpinEffect`, `GridScanEffect`, `GridFlashEffect`, `GridGlitchEffect`, `GridWaveWarpEffect`, `GridPixelateEffect`, `GridChromaticEffect`, `TextOverlayEffect`

These implement `Effect` and are applied per-panel (for KenBurns, Slide, Pulse, Bounce, Spin) or at the scene level (for Scan, Flash, Glitch, Wave, Pixelate, Chromatic, Text).

---

## Frame Decoding (`VideoSource`)

- Uses `ffmpeg` subprocess with rawvideo `bgr24` output
- Sequential `read_frame()` for forward reads
- `read_at(sec)` seeks via `-ss` if the target is behind current position or >1s ahead
- Native resolution only (no `-s` flag — resize is applied downstream via `resize_frame`)
- Thread-local RGBA scratch buffer avoids per-call allocation during resize

---

## Known Gaps vs Python

| Feature | Python | Rust |
|---------|--------|------|
| Callable position/size/opacity | `lambda t: ...` | Static only |
| Callable shape masks | `callable(time) -> ndarray` | Not supported |
| Wave masks (`make_wave_mask`) | Full implementation | Not implemented |
| YOLO mask wiring in grid | Full temporal smoothing | `NoMask` always |
| ref_panel frame sharing | Explicit ref to panel | Via shared source_index |
| numpy-array masks | Yes | No |

---

## Build & Test

```bash
cd rust

# Build all crates
cargo build

# Run unit tests in core
cargo test -p ocv-core

# Run a specific scene test
cargo test -p ocv-core test_wave_grid_python_layout -- --nocapture

# Build CLI
cargo build -p ocv-cli

# Run CLI grid test
cargo run -p ocv-cli --example grid_test -- /path/to/video1.mp4 /path/to/video2.mp4
```

---

## Adding a New Effect

1. Define the effect struct in `effects.rs` (general) or `effects_grid.rs` (grid-specific)
2. Implement `EasingHolder` and `Effect` traits
3. Register in `auto/src/effects_map.rs` if it should be deserializable from plan.json
4. If it needs a per-frame mask (e.g., YOLO depth), add the `loader: Box<dyn MaskLoader>` parameter to `Effect::process` (the YOLO text effect uses `ThreadLocal<RefCell<...>>` to pass the loader through the pipeline)
