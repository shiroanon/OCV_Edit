use crate::easing::Easing;
use crate::effect::{BoxedEffect, EasingHolder, Effect};
use crate::frame::{Frame, RawMut, warp_affine};
use crate::text::{render_text, TextOptions, TextPosition};
use animato::Interpolate;
use image::Rgb;
use imageproc::geometric_transformations::{rotate, Interpolation};

fn scale_about_center(frame: &Frame, scale: f32, cx: f32, cy: f32) -> Frame {
    let (w, h) = frame.dimensions();
    let cx = cx * w as f32;
    let cy = cy * h as f32;
    let mat = [
        [scale, 0.0, cx - scale * cx],
        [0.0, scale, cy - scale * cy],
    ];
    warp_affine(frame, mat, w, h, [0, 0, 0])
}

/// Pure-translation helper: integer pixel shifts are applied via fast row
/// memcpy rather than going through the full bilinear warp_affine path.
fn translate(frame: &Frame, tx: f32, ty: f32) -> Frame {
    let (w, h) = frame.dimensions();
    let dx = tx.round() as i32;
    let dy = ty.round() as i32;

    // Fast path for integer-pixel translations (covers nearly all call sites).
    if (tx - dx as f32).abs() < 0.01 && (ty - dy as f32).abs() < 0.01 {
        return translate_blit(frame, dx, dy);
    }

    // Sub-pixel fallback through warp_affine.
    let mat = [[1.0, 0.0, tx], [0.0, 1.0, ty]];
    warp_affine(frame, mat, w, h, [0, 0, 0])
}

/// Fast integer-pixel translation using row-level `copy_from_slice`.
fn translate_blit(frame: &Frame, dx: i32, dy: i32) -> Frame {
    let (w, h) = (frame.width(), frame.height());
    let mut out = Frame::new(w, h); // zero-filled
    let src = frame.as_raw().as_slice();
    let dst = out.raw_mut();

    let src_y_start = (-dy).max(0) as u32;
    let dst_y_start = dy.max(0) as u32;
    let src_x_start = (-dx).max(0) as u32;
    let dst_x_start = dx.max(0) as u32;

    let copy_w = (w as i32 - dx.abs()).max(0) as u32;
    let copy_h = (h as i32 - dy.abs()).max(0) as u32;

    if copy_w == 0 || copy_h == 0 {
        return out;
    }

    for row in 0..copy_h as usize {
        let sy = (src_y_start as usize + row) * w as usize;
        let dy_off = (dst_y_start as usize + row) * w as usize;
        let s = (sy + src_x_start as usize) * 3;
        let d = (dy_off + dst_x_start as usize) * 3;
        dst[d..d + copy_w as usize * 3].copy_from_slice(&src[s..s + copy_w as usize * 3]);
    }
    out
}

#[derive(Clone)]
pub struct KenBurnsEffect {
    pub easing: Easing,
    pub center: (f32, f32),
    pub zoom_out: f32,
    pub zoom_in: f32,
    pub drift_x: f32,
    pub drift_y: f32,
}
impl EasingHolder for KenBurnsEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for KenBurnsEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let (w, h) = frame.dimensions();
        let e = progress.clamp(0.0, 1.0);
        let scale = self.zoom_out.lerp(&self.zoom_in, e);
        let tx = self.drift_x * (e - 0.5) * w as f32;
        let ty = self.drift_y * (e - 0.5) * h as f32;
        let mut f = scale_about_center(frame, scale, self.center.0, self.center.1);
        if tx.abs() > 0.01 || ty.abs() > 0.01 {
            f = translate(&f, tx, ty);
        }
        f
    }
}

#[derive(Clone)]
pub struct PanelSlideEffect {
    pub easing: Easing,
    pub direction: String,
    pub start_offset: f32,
    pub end_offset: f32,
}
impl EasingHolder for PanelSlideEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for PanelSlideEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let (w, h) = frame.dimensions();
        let e = progress.clamp(0.0, 1.0);
        let off = self.start_offset.lerp(&self.end_offset, e);
        let (tx, ty) = match self.direction.as_str() {
            "up" => (0.0, -off * h as f32),
            "down" => (0.0, off * h as f32),
            "right" => (off * w as f32, 0.0),
            _ => (-off * w as f32, 0.0),
        };
        translate(frame, tx, ty)
    }
}

#[derive(Clone)]
pub struct PanelPulseEffect {
    pub easing: Easing,
    pub start_scale: f32,
    pub pulse_scale: f32,
    pub end_scale: f32,
}
impl EasingHolder for PanelPulseEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for PanelPulseEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let scale = if e < 0.5 {
            self.start_scale.lerp(&self.pulse_scale, e * 2.0)
        } else {
            self.pulse_scale.lerp(&self.end_scale, (e - 0.5) * 2.0)
        };
        scale_about_center(frame, scale, 0.5, 0.5)
    }
}

#[derive(Clone)]
pub struct PanelBounceEffect {
    pub easing: Easing,
    pub direction: String,
    pub amplitude: f32,
}
impl EasingHolder for PanelBounceEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for PanelBounceEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let (w, h) = frame.dimensions();
        let b = Easing::EaseOutBounce.apply(progress.clamp(0.0, 1.0));
        let dist = self.amplitude * b;
        let (tx, ty) = match self.direction.as_str() {
            "up" => (0.0, -dist * h as f32),
            "down" => (0.0, dist * h as f32),
            "right" => (dist * w as f32, 0.0),
            _ => (-dist * w as f32, 0.0),
        };
        translate(frame, tx, ty)
    }
}

#[derive(Clone)]
pub struct PanelSpinEffect {
    pub easing: Easing,
    pub max_angle: f32,
}
impl EasingHolder for PanelSpinEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for PanelSpinEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let angle = self.max_angle.to_radians() * (std::f32::consts::PI * e).sin();
        let (w, h) = frame.dimensions();
        rotate(
            frame,
            (w as f32 / 2.0, h as f32 / 2.0),
            angle,
            Interpolation::Bilinear,
            Rgb([0u8, 0u8, 0u8]),
        )
    }
}

#[derive(Clone)]
pub struct GridScanEffect {
    pub easing: Easing,
    pub num_bars: f32,
    pub bar_speed: f32,
    pub bar_width: f32,
}
impl EasingHolder for GridScanEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridScanEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let t = e * self.bar_speed;
        let bw = self.bar_width;
        let num_bars = self.num_bars;
        let src = frame.as_raw().as_slice();
        let mut raw = src.to_vec();

        // Precompute per-column multipliers to avoid recomputing sin() inside the inner loop.
        let col_mults: Vec<f32> = (0..w).map(|x| {
            let v = (x as f32 / w as f32 * num_bars + t).fract();
            let bright = (0.5 + 0.5 * (2.0 * std::f32::consts::PI * v).sin()).powf(2.0);
            if bright < bw { 1.0 } else { 1.0 - (bright - bw).min(1.0) * 0.6 }
        }).collect();

        for y in 0..h as usize {
            for x in 0..w as usize {
                let m = col_mults[x];
                let o = (y * w as usize + x) * 3;
                raw[o]     = (raw[o] as f32 * m) as u8;
                raw[o + 1] = (raw[o + 1] as f32 * m) as u8;
                raw[o + 2] = (raw[o + 2] as f32 * m) as u8;
            }
        }
        Frame::from_raw(w, h, raw).expect("GridScanEffect")
    }
}

#[derive(Clone)]
pub struct GridFlashEffect {
    pub easing: Easing,
    pub intensity: f32,
}
impl EasingHolder for GridFlashEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridFlashEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let a = self.intensity * (std::f32::consts::PI * e).sin().max(0.0);
        if a <= 0.0 {
            return frame.clone();
        }
        // Direct additive blend against white: avoids allocating a solid frame.
        let src = frame.as_raw().as_slice();
        let mut raw = vec![0u8; src.len()];
        for (o, d) in raw.iter_mut().zip(src.iter()) {
            *o = (*d as f32 + 255.0 * a).min(255.0) as u8;
        }
        Frame::from_raw(frame.width(), frame.height(), raw).expect("GridFlashEffect")
    }
}

#[derive(Clone)]
pub struct GridGlitchEffect {
    pub easing: Easing,
    pub intensity: f32,
}
impl EasingHolder for GridGlitchEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridGlitchEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let bands = 8u32;
        let bh = h / bands;
        let mut out = frame.clone();
        let ow = w as usize;
        let src = frame.as_raw();
        let dst = out.raw_mut();
        for b in 0..bands {
            let seed = ((fi.wrapping_mul(2654435761) ^ (b as u64 * 40503)) % 1000) as f32 / 1000.0;
            let mag = (self.intensity * 30.0 * e) as i32;
            let dx = (((seed - 0.5) * 2.0) * mag as f32) as i32;
            if dx == 0 {
                continue;
            }
            let y0 = (b * bh) as usize;
            let y1 = ((b + 1) * bh).min(h) as usize;
            let dx_clamped = dx.clamp(-(w as i32), w as i32);

            for y in y0..y1 {
                let row = y * ow * 3;
                if dx_clamped >= 0 {
                    let sw = (w as i32 - dx_clamped) as usize;
                    dst[row + dx_clamped as usize * 3..row + dx_clamped as usize * 3 + sw * 3]
                        .copy_from_slice(&src[row..row + sw * 3]);
                    // Fill left gap with black
                    for x in 0..dx_clamped as usize * 3 {
                        dst[row + x] = 0;
                    }
                } else {
                    let sw = (w as i32 + dx_clamped) as usize;
                    dst[row..row + sw * 3]
                        .copy_from_slice(&src[row + (-dx_clamped) as usize * 3..row + (-dx_clamped) as usize * 3 + sw * 3]);
                    // Fill right gap with black
                    for x in (sw * 3)..(ow * 3) {
                        dst[row + x] = 0;
                    }
                }
            }
        }
        out
    }
}

#[derive(Clone)]
pub struct GridWaveWarpEffect {
    pub easing: Easing,
    pub frequency: f32,
    pub amplitude: f32,
    pub speed: f32,
}
impl EasingHolder for GridWaveWarpEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridWaveWarpEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let src = frame.as_raw().as_slice();
        let mut raw = vec![0u8; (w * h * 3) as usize];
        let stride = w as usize * 3;

        for y in 0..h as usize {
            let amp = self.amplitude * e;
            let dx = (amp
                * (2.0 * std::f32::consts::PI * (y as f32 / h as f32 * self.frequency)
                    + self.speed * e)
                    .sin())
            .round() as i32;
            let src_row = &src[y * stride..(y + 1) * stride];
            let dst_row = &mut raw[y * stride..(y + 1) * stride];
            if dx >= 0 {
                let sw = (w as i32 - dx) as usize;
                let s = &src_row[..sw * 3];
                let d = &mut dst_row[dx as usize * 3..dx as usize * 3 + sw * 3];
                d.copy_from_slice(s);
            } else {
                let sw = (w as i32 + dx) as usize;
                let s = &src_row[(-dx) as usize * 3..(-dx) as usize * 3 + sw * 3];
                let d = &mut dst_row[..sw * 3];
                d.copy_from_slice(s);
            }
        }
        Frame::from_raw(w, h, raw).expect("GridWaveWarpEffect")
    }
}

#[derive(Clone)]
pub struct GridPixelateEffect {
    pub easing: Easing,
    pub max_pixels: f32,
    pub min_pixels: f32,
}
impl EasingHolder for GridPixelateEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridPixelateEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let block = self.max_pixels.lerp(&self.min_pixels, e).max(1.0);
        let tw = (w as f32 / block).max(1.0).round() as u32;
        let th = (h as f32 / block).max(1.0).round() as u32;
        let small = crate::frame::resize_frame(frame, tw, th, "fit");
        crate::frame::resize_frame(&small, w, h, "fill")
    }
}

#[derive(Clone)]
pub struct GridChromaticEffect {
    pub easing: Easing,
    pub intensity: f32,
    pub angle: f32,
}
impl EasingHolder for GridChromaticEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for GridChromaticEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let shift = (self.intensity * 0.02 * e) as i32;
        if shift == 0 {
            return frame.clone();
        }
        let rad = self.angle.to_radians();
        let dx = (rad.cos() * shift as f32).round() as i32;
        let dx = dx.clamp(-(w as i32), w as i32);

        let src = frame.as_raw();
        let npix = (w * h) as usize;
        let mut raw = vec![0u8; npix * 3];

        // Single-pass chromatic: for each pixel, read B from the -dx shifted
        // source, G from original, R from the +dx shifted source — all without
        // allocating intermediate shifted frames.
        for y in 0..h as usize {
            for x in 0..w as usize {
                let o = (y * w as usize + x) * 3;
                // G always from source
                raw[o + 1] = src[o + 1];

                // R from +dx column (clamped to bounds)
                let rx = (x as i32 + dx).clamp(0, w as i32 - 1) as usize;
                let ro = (y * w as usize + rx) * 3;
                raw[o + 2] = src[ro + 2];

                // B from -dx column (clamped to bounds)
                let bx = (x as i32 - dx).clamp(0, w as i32 - 1) as usize;
                let bo = (y * w as usize + bx) * 3;
                raw[o] = src[bo];
            }
        }
        Frame::from_raw(w, h, raw).expect("GridChromaticEffect")
    }
}

#[derive(Clone)]
pub struct TextOverlayEffect {
    pub easing: Easing,
    pub text: String,
    pub font_path: String,
    pub font_size: f32,
    pub position: String,
    pub color: [u8; 3],
    pub opacity: f32,
    pub stroke_width: f32,
    pub stroke_color: [u8; 3],
}
impl EasingHolder for TextOverlayEffect {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Effect for TextOverlayEffect {
    fn apply(&self, frame: &Frame, _lt: f32, progress: f32, _fi: u64) -> Frame {
        let e = progress.clamp(0.0, 1.0);
        let (w, h) = frame.dimensions();
        let alpha = self.opacity * e;
        let opts = TextOptions {
            size: (w, h),
            text: &self.text,
            font_path: Some(&self.font_path),
            font_size_frac: self.font_size,
            position: TextPosition::from_str_or_tuple(&self.position),
            color_bgr: self.color,
            opacity: alpha,
            stroke_width_frac: self.stroke_width,
            stroke_color_bgr: self.stroke_color,
            animate: "none",
            phase_p: 1.0,
            line_spacing: 1.1,
        };
        let (layer, mask) = render_text(&opts);
        crate::frame::composite_masked(frame, &layer, &mask)
    }
}

#[allow(dead_code)]
pub fn boxed_grid_effects_docs() -> Vec<BoxedEffect> {
    vec![]
}
