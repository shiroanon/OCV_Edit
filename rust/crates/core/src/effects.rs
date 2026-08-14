use crate::effect::{Effect, EasingHolder, MaskLoader, NoMask};
use crate::easing::Easing;
use crate::frame::*;
use crate::text::{render_text, TextOptions, TextPosition};
use animato::{Interpolate, Waveform};
use image::{GenericImage, GenericImageView};
use rayon::prelude::*;
use std::path::{Path, PathBuf};
use std::sync::Arc;

// ───────────────────────── zoom ─────────────────────────

fn scale_about(frame: &Frame, scale: f32, fx: f32, fy: f32) -> Frame {
    let (w, h) = (frame.width(), frame.height());
    if scale <= 0.0 {
        return Frame::new(w, h);
    }
    let nw = (w as f32 * scale).max(1.0) as u32;
    let nh = (h as f32 * scale).max(1.0) as u32;
    let resized = resize_frame(frame, nw, nh, "fill");
    if scale >= 1.0 {
        let x1 = ((fx * nw as f32) - w as f32 / 2.0).clamp(0.0, (nw - w) as f32) as u32;
        let y1 = ((fy * nh as f32) - h as f32 / 2.0).clamp(0.0, (nh - h) as f32) as u32;
        resized.view(x1, y1, w, h).to_image()
    } else {
        let mut out = Frame::new(w, h);
        let ox = ((w - nw) / 2) as i64;
        let oy = ((h - nh) / 2) as i64;
        out.copy_from(&(resized.view(0, 0, nw, nh)).to_image(), ox.max(0) as u32, oy.max(0) as u32);
        out
    }
}

pub struct ZoomEffect {
    start_zoom: f32,
    end_zoom: f32,
    easing: Easing,
}
impl ZoomEffect {
    pub fn new(start_zoom: f32, end_zoom: f32, easing: Easing) -> Self {
        ZoomEffect { start_zoom, end_zoom, easing }
    }
}
impl EasingHolder for ZoomEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for ZoomEffect {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        let scale = self.start_zoom.lerp(&self.end_zoom, progress);
        scale_about(frame, scale, 0.5, 0.5)
    }
}

pub struct ZoomToPoint {
    center: (f32, f32),
    start_zoom: f32,
    end_zoom: f32,
    easing: Easing,
}
impl ZoomToPoint {
    pub fn new(center: (f32, f32), start_zoom: f32, end_zoom: f32, easing: Easing) -> Self {
        ZoomToPoint { center, start_zoom, end_zoom, easing }
    }
}
impl EasingHolder for ZoomToPoint {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for ZoomToPoint {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        let scale = self.start_zoom.lerp(&self.end_zoom, progress);
        scale_about(frame, scale, self.center.0, self.center.1)
    }
}

// ───────────────────────── bounce ─────────────────────────

pub struct BounceEffect {
    pub amplitude: f32,
    pub easing: Easing,
}
impl BounceEffect {
    pub fn new(amplitude: f32, easing: Easing) -> Self {
        BounceEffect { amplitude: amplitude.max(1.0), easing }
    }
}
impl EasingHolder for BounceEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for BounceEffect {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        // parabola bounce: 1.0 → amplitude → 1.0
        let bounce = 1.0 + (self.amplitude - 1.0) * 4.0 * progress * (1.0 - progress);
        scale_about(frame, bounce, 0.5, 0.5)
    }
}

// ───────────────────────── color ─────────────────────────

#[derive(Clone, Default)]
pub struct ColorParams {
    pub saturation: f32,
    pub contrast: f32,
    pub brightness: f32,
    pub gamma: f32,
}
impl Interpolate for ColorParams {
    fn lerp(&self, o: &Self, t: f32) -> Self {
        ColorParams {
            saturation: self.saturation.lerp(&o.saturation, t),
            contrast: self.contrast.lerp(&o.contrast, t),
            brightness: self.brightness.lerp(&o.brightness, t),
            gamma: self.gamma.lerp(&o.gamma, t),
        }
    }
}

pub struct ColorAdjustEffect {
    start: ColorParams,
    end: ColorParams,
    easing: Easing,
}
impl ColorAdjustEffect {
    pub fn new(start: ColorParams, end: ColorParams, easing: Easing) -> Self {
        ColorAdjustEffect { start, end, easing }
    }
}
impl EasingHolder for ColorAdjustEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for ColorAdjustEffect {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        let p = self.start.lerp(&self.end, progress);
        adjust_color(frame, p.saturation, p.contrast, p.brightness, p.gamma)
    }
}

// ───────────────────────── blur ─────────────────────────

pub struct BlurEffect {
    start_blur: f32,
    end_blur: f32,
    easing: Easing,
}
impl BlurEffect {
    pub fn new(start_blur: f32, end_blur: f32, easing: Easing) -> Self {
        BlurEffect { start_blur, end_blur, easing }
    }
}
impl EasingHolder for BlurEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for BlurEffect {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        let (w, h) = (frame.width(), frame.height());
        let dim = (w.min(h)) as f32;
        let blur = self.start_blur.lerp(&self.end_blur, progress);
        if blur <= 0.0 {
            return frame.clone();
        }
        let k = (blur * dim).round() as i32;
        if k <= 1 {
            return frame.clone();
        }
        let sigma = (0.3 * ((k - 1) as f32 / 2.0 - 1.0) + 0.8).max(0.5);
        gaussian_blur(frame, sigma)
    }
}

// ───────────────────────── rgb shift ─────────────────────────

pub struct RGBShiftEffect {
    start_shift: f32,
    end_shift: f32,
    angle_deg: f32,
    easing: Easing,
}
impl RGBShiftEffect {
    pub fn new(start_shift: f32, end_shift: f32, angle_deg: f32, easing: Easing) -> Self {
        RGBShiftEffect { start_shift, end_shift, angle_deg, easing }
    }
}
impl EasingHolder for RGBShiftEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for RGBShiftEffect {
    fn apply(&self, frame: &Frame, _t: f32, progress: f32, _fi: u64) -> Frame {
        let (w, h) = (frame.width(), frame.height());
        let dim = (w.min(h)) as f32;
        let shift = self.start_shift.lerp(&self.end_shift, progress);
        let amt = shift * dim;
        if amt.abs() < 0.5 {
            return frame.clone();
        }
        let a = self.angle_deg.to_radians();
        let dx = amt * a.cos();
        let dy = amt * a.sin();
        let src = frame.as_raw().as_slice().to_vec();
        let mut out = Frame::new(w, h);
        let d = out.raw_mut();
        let fw = w as f32;
        let fh = h as f32;
        for y in 0..h {
            for x in 0..w {
                let o = ((y * w + x) * 3) as usize;
                // R shifted +, B shifted -
                let (rx, ry) = (x as f32 + dx, y as f32 + dy);
                let (bx, by) = (x as f32 - dx, y as f32 - dy);
                d[o + 2] = sample_clamp(&src, fw, fh, rx, ry, 2);
                d[o + 1] = sample_clamp(&src, fw, fh, x as f32, y as f32, 1);
                d[o] = sample_clamp(&src, fw, fh, bx, by, 0);
            }
        }
        out
    }
}

#[inline]
fn sample_clamp(src: &[u8], w: f32, h: f32, x: f32, y: f32, c: usize) -> u8 {
    let xi = x.clamp(0.0, w - 1.0).round() as usize;
    let yi = y.clamp(0.0, h - 1.0).round() as usize;
    src[(yi * w as usize + xi) * 3 + c]
}

// ───────────────────────── flip ─────────────────────────

pub struct FlipEffect {
    code: i32,
    easing: Easing,
}
impl FlipEffect {
    pub fn new(mode: &str) -> Self {
        let code = match mode {
            "v" => 0,
            "both" => -1,
            _ => 1,
        };
        FlipEffect { code, easing: Easing::Linear }
    }
}
impl EasingHolder for FlipEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for FlipEffect {
    fn apply(&self, frame: &Frame, _t: f32, _p: f32, _fi: u64) -> Frame {
        flip_frame(frame, self.code)
    }
}

// ───────────────────────── masked ─────────────────────────

pub enum MaskSpec {
    Static(Mask),
    Rect { x: f32, y: f32, w: f32, h: f32, norm: bool },
    Ellipse { cx: f32, cy: f32, rx: f32, ry: f32, norm: bool },
    Polygon { points: Vec<(f32, f32)>, norm: bool },
}

pub struct MaskedEffect {
    inner: Box<dyn Effect>,
    spec: MaskSpec,
    feather: f32,
    invert: bool,
    cached: std::sync::Mutex<Option<(u32, u32, Arc<Mask>)>>,
    easing: Easing,
}
impl MaskedEffect {
    pub fn new(inner: Box<dyn Effect>, spec: MaskSpec, feather: f32, invert: bool) -> Self {
        MaskedEffect {
            inner,
            spec,
            feather,
            invert,
            cached: std::sync::Mutex::new(None),
            easing: Easing::Linear,
        }
    }
    fn build_mask(&self, fw: u32, fh: u32) -> Arc<Mask> {
        let mut alpha = match &self.spec {
            MaskSpec::Static(m) => m.clone(),
            MaskSpec::Rect { x, y, w, h, norm } => rect_mask((fw, fh), *x, *y, *w, *h, *norm),
            MaskSpec::Ellipse { cx, cy, rx, ry, norm } => {
                ellipse_mask((fw, fh), *cx, *cy, *rx, *ry, *norm)
            }
            MaskSpec::Polygon { points, norm } => polygon_mask((fw, fh), points, *norm),
        };
        if self.feather > 0.0 {
            let k = (self.feather * fh as f32).max(3.0);
            alpha = blur_mask(&alpha, k / 3.0);
        }
        if self.invert {
            for v in alpha.raw_mut() {
                *v = 1.0 - *v;
            }
        }
        Arc::new(alpha)
    }
}
impl EasingHolder for MaskedEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for MaskedEffect {
    fn apply(&self, frame: &Frame, t: f32, progress: f32, fi: u64) -> Frame {
        let (fw, fh) = (frame.width(), frame.height());
        let alpha = {
            let mut c = self.cached.lock().unwrap();
            match &*c {
                Some((w, h, m)) if *w == fw && *h == fh => Arc::clone(m),
                _ => {
                    let m = self.build_mask(fw, fh);
                    *c = Some((fw, fh, Arc::clone(&m)));
                    m
                }
            }
        };
        let effected = self.inner.process(frame, t, progress, fi);
        composite_masked(frame, &effected, &alpha)
    }
}

// ───────────────────────── YOLO-mask-consuming effects ─────────────────────────
// These apply the *visual* logic in Rust; the mask itself comes from the Python
// pre-pass (see `python/yolo_masks.py`). `NoMask` => effect no-ops.

pub struct GlowEffect {
    glow_color: [u8; 3],
    blur_frac: f32,
    intensity: f32,
    loader: Box<dyn MaskLoader>,
    easing: Easing,
}
impl GlowEffect {
    pub fn new(glow_color: [u8; 3], blur_frac: f32, intensity: f32, loader: Box<dyn MaskLoader>) -> Self {
        GlowEffect { glow_color, blur_frac, intensity, loader, easing: Easing::Linear }
    }
}
impl EasingHolder for GlowEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GlowEffect {
    fn apply(&self, frame: &Frame, _t: f32, _p: f32, fi: u64) -> Frame {
        let mask = match self.loader.load(frame, fi) {
            Some(m) => m,
            None => return frame.clone(),
        };
        let (w, h) = (frame.width(), frame.height());
        // binarize + dilate + blur -> glow
        let mut bin = Mask::new(w, h);
        for (i, v) in mask.as_raw().as_slice().iter().enumerate() {
            bin.raw_mut()[i] = if *v > 0.25 { 1.0 } else { 0.0 };
        }
        let dilate_k = ((0.01 * h as f32).max(3.0) as usize) | 1;
        let dilated = dilate_mask(&bin, dilate_k);
        let blur_k = (self.blur_frac * h as f32).max(3.0);
        let glow = blur_mask(&dilated, blur_k / 3.0);
        let mut out = frame.clone();
        let d = out.raw_mut();
        for i in 0..(w * h) as usize {
            let a = (glow.as_raw().as_slice()[i] * self.intensity).clamp(0.0, 1.0);
            for c in 0..3 {
                let base = d[i * 3 + c] as f32;
                let added = self.glow_color[c] as f32 * a;
                d[i * 3 + c] = (base + added).clamp(0.0, 255.0) as u8;
            }
        }
        out
    }
}

pub struct EmissionEffect {
    inner_color: [u8; 3],
    outer_color: [u8; 3],
    inner_radius: f32,
    outer_radius: f32,
    intensity: f32,
    pulse_speed: f32,
    pulse_amp: f32,
    loader: Box<dyn MaskLoader>,
    easing: Easing,
}
impl EmissionEffect {
    pub fn new(
        inner_color: [u8; 3],
        outer_color: [u8; 3],
        inner_radius: f32,
        outer_radius: f32,
        intensity: f32,
        pulse_speed: f32,
        pulse_amp: f32,
        loader: Box<dyn MaskLoader>,
    ) -> Self {
        EmissionEffect {
            inner_color,
            outer_color,
            inner_radius,
            outer_radius,
            intensity,
            pulse_speed,
            pulse_amp,
            loader,
            easing: Easing::Linear,
        }
    }
}
impl EasingHolder for EmissionEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for EmissionEffect {
    fn apply(&self, frame: &Frame, t: f32, progress: f32, fi: u64) -> Frame {
        let mask = match self.loader.load(frame, fi) {
            Some(m) => m,
            None => return frame.clone(),
        };
        let (w, h) = (frame.width(), frame.height());
        let mut bin = Mask::new(w, h);
        for (i, v) in mask.as_raw().as_slice().iter().enumerate() {
            bin.raw_mut()[i] = if *v > 0.25 { 1.0 } else { 0.0 };
        }
        let dilate_k = ((0.01 * h as f32).max(3.0) as usize) | 1;
        let edge = dilate_mask(&bin, dilate_k);
        // edge mask via dilate - erode approx: subtract shrunk
        let shrunk = erode_mask(&bin, dilate_k);
        let mut edge_only = Mask::new(w, h);
        for i in 0..(w * h) as usize {
            edge_only.raw_mut()[i] =
                (edge.as_raw().as_slice()[i] - shrunk.as_raw().as_slice()[i]).max(0.0);
        }
        let inner_k = (self.inner_radius * h as f32).max(3.0);
        let outer_k = (self.outer_radius * h as f32).max(3.0);
        let inner_g = blur_mask(&edge_only, inner_k / 3.0);
        let outer_g = blur_mask(&edge_only, outer_k / 3.0);
        let wave = Waveform::Sine {
            frequency: self.pulse_speed,
            amplitude: self.pulse_amp,
            phase: 0.0,
        };
        let pulse = 1.0 + wave.sample(t);
        let alpha = progress * self.intensity * pulse;
        let mut out = frame.clone();
        let d = out.raw_mut();
        for i in 0..(w * h) as usize {
            let ig = inner_g.as_raw().as_slice()[i];
            let og = outer_g.as_raw().as_slice()[i];
            for c in 0..3 {
                let inner_c = ig * self.inner_color[c] as f32;
                let outer_c = og * self.outer_color[c] as f32;
                let e = inner_c.max(outer_c) * alpha;
                let base = d[i * 3 + c] as f32;
                d[i * 3 + c] = (base + e).clamp(0.0, 255.0) as u8;
            }
        }
        out
    }
}

pub struct SegMaskedEffect {
    inner: Box<dyn Effect>,
    target: String,
    feather: f32,
    loader: Box<dyn MaskLoader>,
    easing: Easing,
}
impl SegMaskedEffect {
    pub fn new(inner: Box<dyn Effect>, target: &str, feather: f32, loader: Box<dyn MaskLoader>) -> Self {
        SegMaskedEffect {
            inner,
            target: target.to_string(),
            feather,
            loader,
            easing: Easing::Linear,
        }
    }
}
impl EasingHolder for SegMaskedEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for SegMaskedEffect {
    fn apply(&self, frame: &Frame, t: f32, progress: f32, fi: u64) -> Frame {
        let mask = match self.loader.load(frame, fi) {
            Some(m) => m,
            None => return frame.clone(),
        };
        let (w, h) = (frame.width(), frame.height());
        let mut bin = Mask::new(w, h);
        for (i, v) in mask.as_raw().as_slice().iter().enumerate() {
            bin.raw_mut()[i] = if *v > 0.3 { 1.0 } else { 0.0 };
        }
        let dilate_k = ((0.01 * h as f32).max(3.0) as usize) | 1;
        let dilated = dilate_mask(&bin, dilate_k);
        let mut alpha = blur_mask(&dilated, (0.019 * h as f32).max(3.0) / 3.0);
        if self.feather > 0.0 {
            alpha = blur_mask(&alpha, (self.feather * h as f32).max(3.0) / 3.0);
        }
        if self.target == "background" {
            for v in alpha.raw_mut() {
                *v = 1.0 - *v;
            }
        }
        let effected = self.inner.process(frame, t, progress, fi);
        composite_masked(frame, &effected, &alpha)
    }
}

pub struct TextEffect {
    text: String,
    font_path: Option<String>,
    font_size_frac: f32,
    position: TextPosition,
    color_bgr: [u8; 3],
    opacity: f32,
    transition_in: f32,
    transition_out: f32,
    animate_in: String,
    animate_out: String,
    stroke_width_frac: f32,
    stroke_color_bgr: [u8; 3],
    line_spacing: f32,
    depth_composite: bool,
    loader: Box<dyn MaskLoader>,
    easing: Easing,
    /// Rendered (layer, mask) from the last frame, keyed by the only
    /// per-frame-varying render inputs (size, quantized phase/opacity,
    /// animation type). Static text reuses the cached glyph rasterization
    /// instead of re-wrapping + re-rasterizing on every frame.
    cached: std::sync::Mutex<Option<((u32, u32), u8, u8, String, Arc<Frame>, Arc<Mask>)>>,
}
impl TextEffect {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        text: &str,
        font_path: Option<&str>,
        font_size_frac: f32,
        position: TextPosition,
        color_bgr: [u8; 3],
        opacity: f32,
        transition_in: f32,
        transition_out: f32,
        animate_in: &str,
        animate_out: &str,
        stroke_width_frac: f32,
        stroke_color_bgr: [u8; 3],
        line_spacing: f32,
        depth_composite: bool,
        loader: Box<dyn MaskLoader>,
    ) -> Self {
        TextEffect {
            text: text.to_string(),
            font_path: font_path.map(|s| s.to_string()),
            font_size_frac,
            position,
            color_bgr,
            opacity,
            transition_in,
            transition_out,
            animate_in: animate_in.to_string(),
            animate_out: animate_out.to_string(),
            stroke_width_frac,
            stroke_color_bgr,
            line_spacing,
            depth_composite,
            loader,
            easing: Easing::Linear,
            cached: std::sync::Mutex::new(None),
        }
    }
}
impl EasingHolder for TextEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for TextEffect {
    fn apply(&self, frame: &Frame, t: f32, _p: f32, fi: u64) -> Frame {
        let (w, h) = (frame.width(), frame.height());
        // derive total duration from t and progress-less phase; we approximate
        // using transition_in/out and current_time (mirrors Python logic).
        let total = (t / _p.clamp(0.001, 1.0)).max(self.transition_in + self.transition_out).max(0.001);
        let t_in = self.transition_in.min(total);
        let t_out = self.transition_out.min((total - t_in).max(0.0));
        let (phase_p, anim_type, text_opacity) = if t < t_in && t_in > 0.0 {
            let pp = t / t_in;
            if self.animate_in == "fade" {
                (pp, "fade", pp * self.opacity)
            } else {
                (pp, self.animate_in.as_str(), self.opacity)
            }
        } else if t > total - t_out && t_out > 0.0 {
            let pp = (t - (total - t_out)) / t_out;
            if self.animate_out == "fade" {
                (pp, "fade", (1.0 - pp) * self.opacity)
            } else {
                (pp, self.animate_out.as_str(), self.opacity)
            }
        } else {
            (1.0, "none", self.opacity)
        };
        if text_opacity <= 0.0 {
            return frame.clone();
        }
        // Cache the rasterized layer+mask so static text is composited from
        // memory instead of re-rendered (wrap + measure + glyph rasterize) on
        // every frame. Keyed on the per-frame-varying inputs; quantization
        // granularity of 1/255 keeps fades visually identical.
        let phase_quant = (phase_p.clamp(0.0, 1.0) * 255.0).round() as u8;
        let op_quant = (text_opacity.clamp(0.0, 1.0) * 255.0).round() as u8;
        let (bgr, alpha) = {
            let mut c = self.cached.lock().unwrap();
            match &*c {
                Some(((cw, ch), pq, oq, at, b, a))
                    if *cw == w && *ch == h && *pq == phase_quant && *oq == op_quant && at == anim_type =>
                {
                    (Arc::clone(b), Arc::clone(a))
                }
                _ => {
                    let (bgr, alpha) = render_text(&TextOptions {
                        size: (w, h),
                        text: &self.text,
                        font_path: self.font_path.as_deref(),
                        font_size_frac: self.font_size_frac,
                        position: self.position,
                        color_bgr: self.color_bgr,
                        opacity: text_opacity,
                        stroke_width_frac: self.stroke_width_frac,
                        stroke_color_bgr: self.stroke_color_bgr,
                        animate: anim_type,
                        phase_p,
                        line_spacing: self.line_spacing,
                    });
                    let bgr = Arc::new(bgr);
                    let alpha = Arc::new(alpha);
                    *c = Some((
                        (w, h),
                        phase_quant,
                        op_quant,
                        anim_type.to_string(),
                        Arc::clone(&bgr),
                        Arc::clone(&alpha),
                    ));
                    (bgr, alpha)
                }
            }
        };
        // composite text over frame
        let mut out = frame.clone();
        let od = out.raw_mut();
        let bd = bgr.as_raw().as_slice();
        let ad = alpha.as_raw().as_slice();
        for i in 0..(w * h) as usize {
            let a = ad[i];
            if a <= 0.0 {
                continue;
            }
            let be = 1.0 - a;
            for c in 0..3 {
                od[i * 3 + c] = (od[i * 3 + c] as f32 * be + bd[i * 3 + c] as f32 * a)
                    .clamp(0.0, 255.0)
                    .round() as u8;
            }
        }
        // depth composite: person restores on top of text
        if self.depth_composite {
            if let Some(person) = self.loader.load(frame, fi) {
                for i in 0..(w * h) as usize {
                    let a = person.as_raw().as_slice()[i].clamp(0.0, 1.0);
                    for c in 0..3 {
                        let cur = od[i * 3 + c] as f32;
                        let per = frame.as_raw().as_slice()[i * 3 + c] as f32;
                        od[i * 3 + c] = (cur * (1.0 - a) + per * a).clamp(0.0, 255.0) as u8;
                    }
                }
            }
        }
        out
    }
}

// ───────────────────────── mask morphology helpers ─────────────────────────

/// Separable morphological dilation: two O(w·h·k) passes instead of O(w·h·k²).
pub fn dilate_mask(m: &Mask, k: usize) -> Mask {
    separable_morphology(m, k, true)
}

/// Separable morphological erosion: two O(w·h·k) passes instead of O(w·h·k²).
pub fn erode_mask(m: &Mask, k: usize) -> Mask {
    separable_morphology(m, k, false)
}

/// Two-pass separable morphology (horizontal then vertical). Because max/min
/// pooling is separable, this reduces complexity from O(k²) to O(k) per pixel.
fn separable_morphology(m: &Mask, k: usize, dilate: bool) -> Mask {
    let (w, h) = (m.width(), m.height());
    let r = (k / 2) as i32;
    let src = m.as_raw().as_slice();

    // ── horizontal pass ──────────────────────────────────────────
    let mut tmp = vec![0.0f32; (w * h) as usize];
    tmp.par_chunks_exact_mut(w as usize)
        .enumerate()
        .for_each(|(y, row)| {
            let yw = y * w as usize;
            for x in 0..w as usize {
                let lo = (x as i32 - r).max(0) as usize;
                let hi = (x as i32 + r).min(w as i32 - 1) as usize;
                let acc = if dilate {
                    src[yw + lo..=yw + hi].iter().copied().fold(0.0f32, f32::max)
                } else {
                    src[yw + lo..=yw + hi].iter().copied().fold(1.0f32, f32::min)
                };
                row[x] = acc;
            }
        });

    // ── vertical pass ────────────────────────────────────────────
    let mut out = vec![0.0f32; (w * h) as usize];
    out.par_chunks_exact_mut(w as usize)
        .enumerate()
        .for_each(|(y, row)| {
            for x in 0..w as usize {
                let lo = (y as i32 - r).max(0) as usize;
                let hi = (y as i32 + r).min(h as i32 - 1) as usize;
                let acc = if dilate {
                    (lo..=hi)
                        .map(|ny| tmp[ny * w as usize + x])
                        .fold(0.0f32, f32::max)
                } else {
                    (lo..=hi)
                        .map(|ny| tmp[ny * w as usize + x])
                        .fold(1.0f32, f32::min)
                };
                row[x] = acc;
            }
        });
    Mask::from_raw(w, h, out).expect("mask from raw")
}

// ───────────────────────── file mask loader (M7 pre-pass output) ─────────────────────────

pub struct FileMaskLoader {
    dir: PathBuf,
    prefix: String,
}
impl FileMaskLoader {
    pub fn new(dir: &str, prefix: &str) -> Self {
        FileMaskLoader { dir: Path::new(dir).to_path_buf(), prefix: prefix.to_string() }
    }
    fn path_for(&self, idx: u64) -> PathBuf {
        self.dir.join(format!("{}_{}.png", self.prefix, idx))
    }
}
impl MaskLoader for FileMaskLoader {
    fn load(&self, _frame: &Frame, idx: u64) -> Option<Mask> {
        let p = self.path_for(idx);
        let img = image::open(&p).ok()?;
        let gray = img.to_luma8();
        let (w, h) = (gray.width(), gray.height());
        let mut m = Mask::new(w, h);
        for (i, px) in gray.as_raw().iter().enumerate() {
            m.raw_mut()[i] = *px as f32 / 255.0;
        }
        Some(m)
    }
}

/// Build a mask loader from an optional directory; defaults to `NoMask`.
pub fn make_loader(dir: Option<&str>, prefix: &str) -> Box<dyn MaskLoader> {
    match dir {
        Some(d) if !d.is_empty() => Box::new(FileMaskLoader::new(d, prefix)),
        _ => Box::new(NoMask),
    }
}
