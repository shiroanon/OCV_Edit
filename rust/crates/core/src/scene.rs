use crate::effects::MaskSpec;
use crate::effect::{Effect, MaskLoader};
use crate::frame::*;
use anyhow::Result;
use rayon::prelude::*;
use std::sync::Mutex;


/// Supplies decoded source frames for panels by source index + local time.
pub trait FrameProvider {
    fn frame(&mut self, source_index: usize, local_time: f32) -> Option<Frame>;
    fn source_count(&self) -> usize;
}

/// Backing video sources for a grid/layered scene. Each entry is a decoded
/// `VideoSource` plus its (start_time, speed, loop) used to map local time to
/// a source time.
///
/// Sources are opened **lazily** — the ffmpeg process is spawned on the first
/// `frame()` call, not in `from_files()`. This keeps the `apply_edit_plan`
/// phase cheap: 50 grid scenes × 3 sources won't start 150 ffmpeg processes
/// simultaneously, preventing a massive memory spike before rendering begins.
pub struct SceneSources {
    sources: Vec<Option<VideoSource>>,
    file_paths: Vec<String>,
    params: Vec<(f32, f32, bool)>,
}

impl SceneSources {
    pub fn from_files(files: &[(String, f32, f32, bool)]) -> Result<SceneSources> {
        let n = files.len();
        let file_paths = files.iter().map(|(f, _, _, _)| f.clone()).collect();
        let params = files.iter().map(|(_, st, sp, lp)| (*st, *sp, *lp)).collect();
        Ok(SceneSources {
            sources: (0..n).map(|_| None).collect(),
            file_paths,
            params,
        })
    }

    fn ensure_open(&mut self, source_index: usize) {
        if source_index >= self.sources.len() || self.sources[source_index].is_some() {
            return;
        }
        match VideoSource::open(&self.file_paths[source_index]) {
            Ok(src) => self.sources[source_index] = Some(src),
            Err(e) => eprintln!("Failed to open source {source_index}: {e}"),
        }
    }

    /// Kill all ffmpeg decode processes, freeing their memory. Sources are
    /// re-spawned automatically on the next `frame()` call. Call this when a
    /// grid/layered clip is no longer the active clip to keep the total number
    /// of concurrent decoders bounded by the active clip count (instead of the
    /// total scene count, which can easily reach 100+ processes → 10+ GB).
    pub fn close_all(&mut self) {
        for src in &mut self.sources {
            if let Some(s) = src {
                s.close();
            }
        }
    }
}

impl FrameProvider for SceneSources {
    fn frame(&mut self, source_index: usize, local_time: f32) -> Option<Frame> {
        if source_index >= self.sources.len() {
            return None;
        }
        self.ensure_open(source_index);
        let src = self.sources[source_index].as_mut()?;
        let (st, sp, lp) = self.params[source_index];
        let dur = src.duration();
        let src_time = if lp && dur > 0.0 {
            st as f64 + (local_time as f64 * sp as f64) % dur.max(0.0) as f64
        } else {
            st as f64 + (local_time as f64) * sp as f64
        };
        let out = src.read_at(src_time).ok().flatten();
        out
    }
    fn source_count(&self) -> usize {
        self.sources.len()
    }
}

#[derive(Clone)]
pub enum ShapeSpec {
    Rect,
    Ellipse,
    Circle,
    Diamond,
    Wave { num_waves: f32, amplitude: f32, direction: String },
}

pub struct PanelDef {
    pub source_index: usize,
    pub start_time: f32,
    pub speed: f32,
    pub loop_: bool,
    pub flip: Option<i32>,
    pub effects: Vec<(Box<dyn Effect>, f32, f64)>,
    pub shape: ShapeSpec,
    pub z_index: i32,
    pub blend: String,
    pub opacity: f32,
    pub mask: Option<MaskSpec>,
    pub feather: f32,
    pub invert: bool,
    pub position: Option<(f32, f32)>,
    pub size: Option<(f32, f32)>,
    pub anchor: String,
    pub resize_mode: String,
    pub loader: Box<dyn MaskLoader>,
}

impl PanelDef {
    pub fn new(source_index: usize) -> Self {
        PanelDef {
            source_index,
            start_time: 0.0,
            speed: 1.0,
            loop_: true,
            flip: None,
            effects: Vec::new(),
            shape: ShapeSpec::Rect,
            z_index: 0,
            blend: "normal".into(),
            opacity: 1.0,
            mask: None,
            feather: 0.0,
            invert: false,
            position: None,
            size: None,
            anchor: "center".into(),
            resize_mode: "fit".into(),
            loader: Box::new(crate::effect::NoMask),
        }
    }
}

pub struct GridScene {
    pub panels: Vec<PanelDef>,
    pub rows: u32,
    pub cols: u32,
    pub duration: f32,
    pub col_weights: Vec<f32>,
    pub row_weights: Vec<f32>,
    pub gap: f32,
    pub effects: Vec<(Box<dyn Effect>, f32, f64)>,
    /// Panel indices sorted by z_index (ascending). Pre-computed once in the
    /// constructor so `render_frame` avoids both building a per-frame Vec and
    /// sorting it.
    panel_order: Vec<usize>,
    /// Reusable scratch canvas — allocated once and re-zeroed each frame to
    /// avoid a full `Frame::new` allocation on every `render_frame` call.
    scratch: Mutex<Frame>,
    /// Panel rects are a pure function of the output size, so compute them
    /// once per size instead of rebuilding a Vec on every frame.
    rects_cache: Mutex<Option<(u32, u32, Vec<(i32, i32, u32, u32)>)>>,
}

impl GridScene {
    pub fn new(panels: Vec<PanelDef>, rows: u32, cols: u32, duration: f32) -> Self {
        let n = panels.iter().filter(|p| p.position.is_none()).count();
        if n > (rows * cols) as usize {
            eprintln!("GridScene: too many grid panels for layout");
        }
        let panel_order: Vec<usize> = {
            let mut v: Vec<usize> = (0..panels.len()).collect();
            v.sort_by_key(|&i| panels[i].z_index);
            v
        };
        GridScene {
            panels,
            rows,
            cols,
            duration,
            col_weights: vec![1.0; cols as usize],
            row_weights: vec![1.0; rows as usize],
            gap: 0.003,
            effects: Vec::new(),
            panel_order,
            scratch: Mutex::new(Frame::new(1, 1)),
            rects_cache: Mutex::new(None),
        }
    }

    fn compute_rects(&self, (tw, th): (u32, u32)) -> Vec<(i32, i32, u32, u32)> {
        let gap = (self.gap * tw as f32).max(1.0) as u32;
        let avail_w = tw as i64 - gap as i64 * (self.cols as i64 - 1);
        let avail_h = th as i64 - gap as i64 * (self.rows as i64 - 1);
        let cw_sum: f32 = self.col_weights.iter().copied().sum();
        let rh_sum: f32 = self.row_weights.iter().sum();
        let mut cw: Vec<i64> = self.col_weights.iter().map(|w| {
            if cw_sum <= 0.0 { (avail_w as f32 / self.cols as f32).trunc() as i64 }
            else { (w / cw_sum * avail_w as f32).trunc() as i64 }
        }).collect();
        let mut rh: Vec<i64> = self.row_weights.iter().map(|h| {
            if rh_sum <= 0.0 { (avail_h as f32 / self.rows as f32).trunc() as i64 }
            else { (h / rh_sum * avail_h as f32).trunc() as i64 }
        }).collect();
        // Last-element fixup to match Python: fill any rounding gap
        if !cw.is_empty() {
            let cw_sum_actual: i64 = cw.iter().sum();
            cw[self.cols as usize - 1] = avail_w - (cw_sum_actual - cw[self.cols as usize - 1]);
        }
        if !rh.is_empty() {
            let rh_sum_actual: i64 = rh.iter().sum();
            rh[self.rows as usize - 1] = avail_h - (rh_sum_actual - rh[self.rows as usize - 1]);
        }
        let mut rects = Vec::new();
        let mut y = 0i64;
        for r in 0..self.rows as usize {
            let mut x = 0i64;
            for c in 0..self.cols as usize {
                rects.push((x as i32, y as i32, cw[c] as u32, rh[r] as u32));
                x += cw[c] + gap as i64;
            }
            y += rh[r] + gap as i64;
        }
        rects
    }

    pub fn render_frame(&self, local_time: f32, output_size: (u32, u32), provider: &mut dyn FrameProvider, fps: f32) -> Frame {
        let (tw, th) = output_size;

        // Reuse scratch canvas instead of allocating a new one every frame.
        let mut canvas_guard = self.scratch.lock().unwrap();
        let canvas: &mut Frame = &mut *canvas_guard;
        if canvas.width() != tw || canvas.height() != th {
            *canvas = Frame::new(tw, th);
        } else {
            for v in canvas.raw_mut() { *v = 0; }
        }

        let rects = {
            let mut cache = self.rects_cache.lock().unwrap();
            let (cw, ch) = output_size;
            match &*cache {
                Some((w, h, r)) if *w == cw && *h == ch => r.clone(),
                _ => {
                    let r = self.compute_rects(output_size);
                    *cache = Some((cw, ch, r.clone()));
                    r
                }
            }
        };

        // Pre-fetch each source once so panels sharing the same source_index
        // don't each trigger a separate decode (and possible off-by-one frame).
        let n_src = provider.source_count();
        let mut cached: Vec<Option<Frame>> = Vec::with_capacity(n_src);
        for si in 0..n_src {
            cached.push(provider.frame(si, local_time));
        }

        // Iterate panels in pre-computed z-order (no per-frame sort, no
        // render_items Vec allocation).
        let mut grid_idx = 0usize;
        for &pi in &self.panel_order {
            let panel = &self.panels[pi];
            let src_frame = match &cached[panel.source_index] {
                Some(f) => f,
                None => {
                    if panel.position.is_none() {
                        grid_idx += 1;
                    }
                    continue;
                }
            };

            let mut frame = apply_panel_effects_full(src_frame, &panel.effects, local_time, self.duration, fps);
            if let Some(code) = panel.flip {
                frame = flip_frame(&frame, code);
            }

            let (px, py, pw, ph) = if let Some((nx, ny)) = panel.position {
                resolve_rect(panel, output_size, (nx, ny), local_time)
            } else {
                if grid_idx >= rects.len() {
                    grid_idx += 1;
                    continue;
                }
                let r = rects[grid_idx];
                grid_idx += 1;
                (r.0, r.1, r.2, r.3)
            };

            composite_panel(canvas, &frame, px, py, pw, ph, panel, local_time, output_size, (tw, th), fps);
        }

        for (eff, st, dur) in &self.effects {
            let fi = (local_time * fps).round() as u64;
            if let Some(f) = apply_effect_timed(canvas, eff, *st, *dur, local_time, self.duration, fi) {
                *canvas = f;
            }
        }

        // Return a fresh handle — the scratch stays locked until the
        // caller reads the canvas, then the lock is released when we
        // drop canvas_guard after the clone.
        canvas.clone()
    }
}

pub struct LayeredScene {
    pub layers: Vec<PanelDef>,
    pub duration: f32,
    pub effects: Vec<(Box<dyn Effect>, f32, f64)>,
    scratch: Mutex<Frame>,
}

impl LayeredScene {
    pub fn new(layers: Vec<PanelDef>, duration: f32) -> Self {
        LayeredScene { layers, duration, effects: Vec::new(), scratch: Mutex::new(Frame::new(1, 1)) }
    }

    pub fn render_frame(&self, local_time: f32, output_size: (u32, u32), provider: &mut dyn FrameProvider, fps: f32) -> Frame {
        let (tw, th) = output_size;
        // Reuse scratch canvas instead of allocating a new one every frame.
        let mut canvas_guard = self.scratch.lock().unwrap();
        let canvas: &mut Frame = &mut *canvas_guard;
        if canvas.width() != tw || canvas.height() != th {
            *canvas = Frame::new(tw, th);
        } else {
            for v in canvas.raw_mut() { *v = 0; }
        }
        for layer in &self.layers {
            let mut frame = match provider.frame(layer.source_index, local_time) {
                Some(f) => f,
                None => continue,
            };
            frame = apply_panel_effects_full(&frame, &layer.effects, local_time, self.duration, fps);
            if let Some(code) = layer.flip {
                frame = flip_frame(&frame, code);
            }
            let (px, py, pw, ph) = if let Some(pos) = layer.position {
                resolve_rect(layer, output_size, pos, local_time)
            } else {
                (0, 0, tw, th)
            };
            composite_panel(canvas, &frame, px, py, pw, ph, layer, local_time, output_size, (tw, th), fps);
        }
        for (eff, st, dur) in &self.effects {
            let fi = (local_time * fps).round() as u64;
            if let Some(f) = apply_effect_timed(canvas, eff, *st, *dur, local_time, self.duration, fi) {
                *canvas = f;
            }
        }
        canvas.clone()
    }
}

fn apply_panel_effects_full(frame: &Frame, effects: &[(Box<dyn Effect>, f32, f64)], local_time: f32, dur: f32, fps: f32) -> Frame {
    let mut result: Option<Frame> = None;
    for (eff, st, d) in effects {
        let ed = if *d < 0.0 { ((dur - *st) as f64).max(0.001) } else { *d };
        if local_time >= *st && local_time <= *st + ed as f32 {
            let p = ((local_time - *st) / ed as f32).clamp(0.0, 1.0);
            let fi = (local_time * fps).round() as u64;
            let input = result.as_ref().unwrap_or(frame);
            result = Some(eff.process(input, local_time - *st, p, fi));
        }
    }
    result.unwrap_or_else(|| frame.clone())
}

/// Returns `Some(new_frame)` if the effect was active, `None` if not.
fn apply_effect_timed(
    frame: &Frame,
    eff: &Box<dyn Effect>,
    st: f32,
    d: f64,
    local_time: f32,
    dur: f32,
    fi: u64,
) -> Option<Frame> {
    let ed = if d < 0.0 { ((dur - st) as f64).max(0.001) } else { d };
    if local_time >= st && local_time <= st + ed as f32 {
        let p = ((local_time - st) / ed as f32).clamp(0.0, 1.0);
        Some(eff.process(frame, local_time - st, p, fi))
    } else {
        None
    }
}

fn resolve_rect(panel: &PanelDef, (tw, th): (u32, u32), (nx, ny): (f32, f32), _t: f32) -> (i32, i32, u32, u32) {
    let (pw, ph) = match panel.size {
        Some((lw, lh)) => (
            (if lw <= 1.0 { lw * tw as f32 } else { lw }).round() as u32,
            (if lh <= 1.0 { lh * th as f32 } else { lh }).round() as u32,
        ),
        None => (tw, th),
    };
    let px = if nx <= 1.0 { nx * tw as f32 } else { nx };
    let py = if ny <= 1.0 { ny * th as f32 } else { ny };
    let (mut px, mut py) = (px, py);
    let anchor = panel.anchor.to_lowercase();
    match anchor.as_str() {
        "center" => {
            px -= pw as f32 / 2.0;
            py -= ph as f32 / 2.0;
        }
        "top-left" => {}
        "top-right" => px -= pw as f32,
        "bottom-left" => py -= ph as f32,
        "bottom-right" => {
            px -= pw as f32;
            py -= ph as f32;
        }
        _ => {
            px -= pw as f32 / 2.0;
            py -= ph as f32 / 2.0;
        }
    }
    (px.round() as i32, py.round() as i32, pw, ph)
}

fn composite_panel(
    canvas: &mut Frame,
    layer_frame: &Frame,
    px: i32,
    py: i32,
    pw: u32,
    ph: u32,
    panel: &PanelDef,
    local_time: f32,
    output_size: (u32, u32),
    (tw, th): (u32, u32),
    fps: f32,
) {
    let (fw, fh) = (layer_frame.width(), layer_frame.height());
    let mode = panel.resize_mode.as_str();
    let scale = if mode == "fill" {
        (pw as f32 / fw as f32).max(ph as f32 / fh as f32)
    } else {
        (pw as f32 / fw as f32).min(ph as f32 / fh as f32)
    };
    let nw = (fw as f32 * scale).max(1.0) as u32;
    let nh = (fh as f32 * scale).max(1.0) as u32;
    let resized = resize_frame(layer_frame, nw, nh, mode);

    let (ox, oy, cw, ch) = if mode == "fill" {
        (0u32, 0u32, pw, ph)
    } else {
        let ox = ((pw as i64 - nw as i64) / 2).max(0) as u32;
        let oy = ((ph as i64 - nh as i64) / 2).max(0) as u32;
        let cw = nw.min(pw - ox);
        let ch = nh.min(ph - oy);
        (ox, oy, cw, ch)
    };

    let mut layer = Frame::new(pw, ph);
    if mode == "fill" {
        let y1 = ((nh - ph) / 2) as u32;
        let x1 = ((nw - pw) / 2) as u32;
        blit_sub(&resized, x1, y1, pw, ph, &mut layer, 0, 0);
    } else if cw > 0 && ch > 0 {
        blit_sub(&resized, 0, 0, cw, ch, &mut layer, ox, oy);
    }

    let mut final_mask = make_shape_mask(&panel.shape, pw, ph, local_time);
    if mode != "fill" {
        let mut content_mask = Mask::new(pw, ph);
        if cw == pw && ch == ph {
            for v in content_mask.raw_mut() { *v = 1.0; }
        } else {
            for yy in oy..(oy + ch).min(ph) {
                for xx in ox..(ox + cw).min(pw) {
                    content_mask.put_pixel(xx, yy, image::Luma([1.0]));
                }
            }
        }
        mul_mask(&mut final_mask, &content_mask);
    }
    if let Some(spec) = &panel.mask {
        let fm = build_feature_mask(spec, pw, ph);
        mul_mask(&mut final_mask, &fm);
    }
    let fi = (local_time * fps).round() as u64;
    if let Some(person) = panel.loader.load(&layer_frame, fi) {
        mul_mask(&mut final_mask, &person);
    }
    let op = panel.opacity.clamp(0.0, 1.0);
    if (op - 1.0).abs() > f32::EPSILON {
        for v in final_mask.raw_mut() { *v *= op; }
    }
    composite_blend(canvas, &layer, px, py, pw, ph, &final_mask, &panel.blend, (tw, th));
}

fn make_shape_mask(shape: &ShapeSpec, pw: u32, ph: u32, local_time: f32) -> Mask {
    let n = (pw * ph) as usize;
    match shape {
        ShapeSpec::Rect => {
            return Mask::from_raw(pw, ph, vec![1.0f32; n]).expect("rect mask");
        }
        ShapeSpec::Circle => {
            let mut m = Mask::new(pw, ph);
            let r = (pw.min(ph) / 2).max(1) as i32;
            imageproc::drawing::draw_filled_circle_mut(&mut m, ((pw / 2) as i32, (ph / 2) as i32), r, image::Luma([1.0]));
            m
        }
        ShapeSpec::Ellipse => {
            let mut m = Mask::new(pw, ph);
            imageproc::drawing::draw_filled_ellipse_mut(&mut m, ((pw / 2) as i32, (ph / 2) as i32), (pw / 2).max(1) as i32, (ph / 2).max(1) as i32, image::Luma([1.0]));
            m
        }
        ShapeSpec::Diamond => {
            let mut m = Mask::new(pw, ph);
            let pts = [
                imageproc::point::Point::new((pw / 2) as i32, 0i32),
                imageproc::point::Point::new(pw as i32 - 1, (ph / 2) as i32),
                imageproc::point::Point::new((pw / 2) as i32, ph as i32 - 1),
                imageproc::point::Point::new(0i32, (ph / 2) as i32),
            ];
            imageproc::drawing::draw_polygon_mut(&mut m, &pts, image::Luma([1.0]));
            m
        }
        ShapeSpec::Wave { num_waves, amplitude, direction } => {
            let mut m = Mask::new(pw, ph);
            let mw = pw as usize;
            let mh = ph as usize;
            let amp = amplitude * mw as f32;
            let edge_base = if direction == "right" { 0.65 } else { 0.35 };
            let raw = m.raw_mut();
            let right = direction == "right";
            raw.par_chunks_mut(mw).enumerate().for_each(|(yy, row)| {
                let y_norm = yy as f32 / mh as f32;
                let offset = amp * (num_waves * 2.0 * std::f32::consts::PI * y_norm).sin();
                let edge_x = (edge_base * mw as f32 + offset).round() as usize;
                if right {
                    let num_on = edge_x.min(mw);
                    for xx in 0..num_on {
                        row[xx] = 1.0;
                    }
                } else {
                    let start = (edge_x + 1).min(mw);
                    for xx in start..mw {
                        row[xx] = 1.0;
                    }
                }
            });
            m
        }
    }
}

fn build_feature_mask(spec: &MaskSpec, pw: u32, ph: u32) -> Mask {
    match spec {
        MaskSpec::Rect { x, y, w, h, norm } => rect_mask((pw, ph), *x, *y, *w, *h, *norm),
        MaskSpec::Ellipse { cx, cy, rx, ry, norm } => ellipse_mask((pw, ph), *cx, *cy, *rx, *ry, *norm),
        MaskSpec::Polygon { points, norm } => polygon_mask((pw, ph), points, *norm),
        MaskSpec::Static(m) => m.clone(),
    }
}

fn mul_mask(a: &mut Mask, b: &Mask) {
    let (w, h) = (a.width(), a.height());
    if b.dimensions() != (w, h) {
        return;
    }
    let sa = a.raw_mut();
    let sb = b.as_raw().as_slice();
    sa.par_iter_mut().zip(sb.par_iter()).for_each(|(a, b)| *a *= b);
}

// ── Blend mode dispatch ───────────────────────────────────────────────────────
//
// Using an enum + match instead of a function pointer (`BlendFn = fn(...)`)
// allows LLVM to inline each blend mode into the hot pixel loop, enabling
// auto-vectorisation per blend mode.

#[derive(Clone, Copy)]
enum BlendMode {
    Normal,
    Multiply,
    Screen,
    Add,
    Overlay,
    Difference,
}

impl BlendMode {
    #[inline(always)]
    fn apply(self, c0: f32, c1: f32, c2: f32, l0: f32, l1: f32, l2: f32) -> [f32; 3] {
        match self {
            BlendMode::Normal     => [l0, l1, l2],
            BlendMode::Multiply   => [c0 * l0 / 255.0, c1 * l1 / 255.0, c2 * l2 / 255.0],
            BlendMode::Screen     => [
                255.0 - (255.0 - c0) * (255.0 - l0) / 255.0,
                255.0 - (255.0 - c1) * (255.0 - l1) / 255.0,
                255.0 - (255.0 - c2) * (255.0 - l2) / 255.0,
            ],
            BlendMode::Add        => [(c0 + l0).min(255.0), (c1 + l1).min(255.0), (c2 + l2).min(255.0)],
            BlendMode::Overlay    => {
                let f = |c: f32, l: f32| if c < 128.0 { 2.0 * c * l / 255.0 } else { 255.0 - 2.0 * (255.0 - c) * (255.0 - l) / 255.0 };
                [f(c0, l0), f(c1, l1), f(c2, l2)]
            }
            BlendMode::Difference => [(c0 - l0).abs(), (c1 - l1).abs(), (c2 - l2).abs()],
        }
    }
}

fn composite_blend(canvas: &mut Frame, layer: &Frame, px: i32, py: i32, pw: u32, ph: u32, mask: &Mask, blend: &str, (tw, th): (u32, u32)) {
    let c_x1 = px.max(0) as u32;
    let c_y1 = py.max(0) as u32;
    let c_x2 = ((px + pw as i32).min(tw as i32)).max(0) as u32;
    let c_y2 = ((py + ph as i32).min(th as i32)).max(0) as u32;
    if c_x2 <= c_x1 || c_y2 <= c_y1 {
        return;
    }
    let l_x1 = (c_x1 as i32 - px).max(0) as u32;
    let l_y1 = (c_y1 as i32 - py).max(0) as u32;
    let l = layer.as_raw();
    let m = mask.as_raw();
    let cs = tw as usize;
    let ls = pw as usize;
    let ms = pw as usize;

    let mode = match blend {
        "multiply"   => BlendMode::Multiply,
        "screen"     => BlendMode::Screen,
        "add"        => BlendMode::Add,
        "overlay"    => BlendMode::Overlay,
        "difference" => BlendMode::Difference,
        _            => BlendMode::Normal,
    };

    // Safety: each yy iteration writes to a different row of the canvas
    // (ci = (cy * cs + cx) * 3 where cy is unique per iteration), so
    // there is no data race between parallel row threads.
    let c_addr = canvas.raw_mut().as_mut_ptr() as usize;
    let c_x1 = c_x1 as usize;
    let c_x2 = c_x2 as usize;
    let c_y1 = c_y1 as usize;
    let l_x1 = l_x1 as usize;
    let l_y1 = l_y1 as usize;
    (c_y1..c_y2 as usize).into_par_iter().for_each(|yy| {
        let cy = yy;
        let ly = l_y1 + (yy - c_y1);
        for xx in c_x1..c_x2 {
            let cx = xx;
            let lx = l_x1 + (xx - c_x1);
            let mf = m[ly * ms + lx];
            if mf <= 0.0 {
                continue;
            }
            let ci = (cy * cs + cx) * 3;
            let li = (ly * ls + lx) * 3;
            unsafe {
                let cp = c_addr as *mut u8;
                let cu0 = *cp.add(ci) as f32;
                let cu1 = *cp.add(ci + 1) as f32;
                let cu2 = *cp.add(ci + 2) as f32;
                let lu0 = l[li] as f32; let lu1 = l[li + 1] as f32; let lu2 = l[li + 2] as f32;
                let out = mode.apply(cu0, cu1, cu2, lu0, lu1, lu2);
                let be = 1.0 - mf;
                *cp.add(ci)     = (cu0 * be + out[0] * mf).clamp(0.0, 255.0) as u8;
                *cp.add(ci + 1) = (cu1 * be + out[1] * mf).clamp(0.0, 255.0) as u8;
                *cp.add(ci + 2) = (cu2 * be + out[2] * mf).clamp(0.0, 255.0) as u8;
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::frame::Frame;

    struct TestProvider {
        frames: Vec<Frame>,
    }
    impl FrameProvider for TestProvider {
        fn frame(&mut self, source_index: usize, _local_time: f32) -> Option<Frame> {
            self.frames.get(source_index).cloned()
        }
        fn source_count(&self) -> usize { self.frames.len() }
    }

    fn solid_frame(w: u32, h: u32, r: u8, g: u8, b: u8) -> Frame {
        let mut f = Frame::new(w, h);
        for px in f.raw_mut().chunks_exact_mut(3) {
            px[0] = b; px[1] = g; px[2] = r;
        }
        f
    }

    fn pixel_bgr(frame: &Frame, x: u32, y: u32) -> (u8, u8, u8) {
        let s = frame.width() as usize;
        let i = (y as usize * s + x as usize) * 3;
        (frame.as_raw()[i], frame.as_raw()[i+1], frame.as_raw()[i+2])
    }

    #[test]
    fn test_wave_grid_python_layout() {
        // Validates the Python-matching wave grid layout used by apply_wave_grid:
        //   left  panel: position (0.15, 0.5), size (0.55, 1.0), anchor "center"
        //   right panel: position (0.85, 0.5), size (0.55, 1.0), anchor "center"
        //   center:      position (0.5,  0.5), size (0.70, 1.0), anchor "center", z=-1
        // Source 0 = blue, source 1 = green.
        let blue  = solid_frame(640, 360, 0, 0, 255);
        let green = solid_frame(640, 360, 0, 255, 0);

        let mut p_left = PanelDef::new(0);
        p_left.position = Some((0.15, 0.5));
        p_left.size = Some((0.55, 1.0));
        p_left.anchor = "center".into();
        p_left.resize_mode = "fill".into();

        let mut p_center = PanelDef::new(1);
        p_center.position = Some((0.5, 0.5));
        p_center.size = Some((0.70, 1.0));
        p_center.anchor = "center".into();
        p_center.resize_mode = "fill".into();
        p_center.z_index = -1;

        let mut p_right = PanelDef::new(0);
        p_right.position = Some((0.85, 0.5));
        p_right.size = Some((0.55, 1.0));
        p_right.anchor = "center".into();
        p_right.resize_mode = "fill".into();

        let scene = GridScene::new(vec![p_left, p_center, p_right], 1, 3, 10.0);
        let mut prov = TestProvider { frames: vec![blue, green] };
        let f = scene.render_frame(0.0, (1920, 1080), &mut prov, 30.0);

        // Left panel covers x=-240..816 → at x=100 only left panel is visible
        assert_eq!(pixel_bgr(&f, 100, 540), (255, 0, 0), "x=100: left panel (blue)");
        // At x=600 both left and center overlap; left z=0 > center z=-1 → blue
        assert_eq!(pixel_bgr(&f, 600, 540), (255, 0, 0), "x=600: left panel (blue) on top of center");
        // At x=960 only center panel (no side overlap) → green
        assert_eq!(pixel_bgr(&f, 960, 540), (0, 255, 0), "x=960: center panel (green)");
        // At x=1400 right panel overlaps center; right z=0 > center z=-1 → blue
        assert_eq!(pixel_bgr(&f, 1400, 540), (255, 0, 0), "x=1400: right panel (blue) on top of center");
        // At x=1800 only right panel → blue
        assert_eq!(pixel_bgr(&f, 1800, 540), (255, 0, 0), "x=1800: right panel (blue)");
    }
}
