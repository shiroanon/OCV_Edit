use crate::effect::{EasingHolder, Transition};
use crate::easing::Easing;
use crate::frame::*;
use animato::Interpolate;

pub struct SlideTransition {
    direction: String,
    easing: Easing,
}
impl SlideTransition {
    pub fn new(direction: &str, easing: Easing) -> Self {
        SlideTransition { direction: direction.to_string(), easing }
    }
}
impl EasingHolder for SlideTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for SlideTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let (h, w) = (frame1.height(), frame1.width());
        let mut out = Frame::new(w, h);
        let ox = (w as f32 * progress) as i32;
        let oy = (h as f32 * progress) as i32;
        match self.direction.as_str() {
            "left" => {
                if ox < w as i32 {
                    let sx = ox.max(0) as u32;
                    let sw = (w - sx).min(w);
                    blit_sub(frame1, sx, 0, sw, h, &mut out, 0, 0);
                }
                if ox > 0 {
                    let sw = ox as u32;
                    blit_sub(frame2, 0, 0, sw, h, &mut out, (w as i32 - ox) as u32, 0);
                }
            }
            "right" => {
                let neg = -ox;
                if neg <= 0 {
                    let sw = (w as i32 + neg).max(0) as u32;
                    blit_sub(frame1, 0, 0, sw, h, &mut out, 0, 0);
                }
                if neg <= 0 {
                    let sx = (w as i32 + neg).max(0) as u32;
                    let sw = (-neg).max(0) as u32;
                    blit_sub(frame2, sx, 0, sw, h, &mut out, sx, 0);
                }
            }
            "up" => {
                if oy < h as i32 {
                    let sy = oy.max(0) as u32;
                    let sh = (h - sy).min(h);
                    blit_sub(frame1, 0, sy, w, sh, &mut out, 0, 0);
                }
                if oy > 0 {
                    let sh = oy as u32;
                    blit_sub(frame2, 0, 0, w, sh, &mut out, 0, (h as i32 - oy) as u32);
                }
            }
            "down" => {
                let neg = -oy;
                if neg <= 0 {
                    let sh = (h as i32 + neg).max(0) as u32;
                    blit_sub(frame1, 0, 0, w, sh, &mut out, 0, 0);
                }
                if neg <= 0 {
                    let sy = (h as i32 + neg).max(0) as u32;
                    let sh = (-neg).max(0) as u32;
                    blit_sub(frame2, 0, sy, w, sh, &mut out, 0, sy);
                }
            }
            _ => out = frame2.clone(),
        }
        out
    }
}

pub struct ZoomTransition {
    mode: String,
    easing: Easing,
}
impl ZoomTransition {
    pub fn new(mode: &str, easing: Easing) -> Self {
        ZoomTransition { mode: mode.to_string(), easing }
    }
}
impl EasingHolder for ZoomTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for ZoomTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let (h, w) = (frame1.height(), frame1.width());
        let (s1, s2) = match self.mode.as_str() {
            "in" => (1.0 + progress, 2.0 - progress),
            "out" => (1.0 - progress * 0.5, 0.5 + progress * 0.5),
            "inout" => (1.0 + progress, 0.5 + progress * 0.5),
            "outin" => (1.0 - progress * 0.5, 2.0 - progress),
            _ => (1.0, 1.0),
        };
        let f1 = scale_about_crop(frame1, s1);
        let f2 = scale_about_crop(frame2, s2);
        add_weighted(&f1, 1.0 - progress, &f2, progress)
    }
}

fn scale_about_crop(frame: &Frame, scale: f32) -> Frame {
    let (h, w) = (frame.height(), frame.width());
    let nw = (w as f32 * scale).max(1.0) as u32;
    let nh = (h as f32 * scale).max(1.0) as u32;
    let r = resize_frame(frame, nw, nh, "fill");
    if scale >= 1.0 {
        let x1 = ((nw - w) / 2) as u32;
        let y1 = ((nh - h) / 2) as u32;
        let mut out = Frame::new(w, h);
        blit_sub(&r, x1, y1, w, h, &mut out, 0, 0);
        out
    } else {
        let mut out = Frame::new(w, h);
        let ox = ((w - nw) / 2) as u32;
        let oy = ((h - nh) / 2) as u32;
        blit_sub(&r, 0, 0, nw, nh, &mut out, ox, oy);
        out
    }
}

pub struct GridWipeTransition {
    cols: u32,
    rows: u32,
    stagger: String,
    easing: Easing,
}
impl GridWipeTransition {
    pub fn new(cols: u32, rows: u32, stagger: &str, easing: Easing) -> Self {
        GridWipeTransition { cols, rows, stagger: stagger.to_string(), easing }
    }
}
impl EasingHolder for GridWipeTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for GridWipeTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let (h, w) = (frame1.height(), frame1.width());
        let mut out = Frame::new(w, h);
        let bh = h / self.rows;
        let bw = w / self.cols;
        let total = (self.cols * self.rows) as f32;
        for r in 0..self.rows {
            for c in 0..self.cols {
                let idx = if self.stagger == "col" {
                    c * self.rows + r
                } else {
                    r * self.cols + c
                } as f32;
                let local_p = ((progress * total - idx) / (total - idx)).clamp(0.0, 1.0);
                let y1 = r * bh;
                let y2 = if r < self.rows - 1 { (r + 1) * bh } else { h };
                let x1 = c * bw;
                let x2 = if c < self.cols - 1 { (c + 1) * bw } else { w };
                let cw = x2 - x1;
                let ch = y2 - y1;
                if local_p >= 1.0 {
                    blit_sub(frame2, x1, y1, cw, ch, &mut out, x1, y1);
                } else if local_p > 0.0 {
                    // Blend sub-regions directly without extracting intermediate frames
                    let src1 = frame1.as_raw();
                    let src2 = frame2.as_raw();
                    let dst = out.raw_mut();
                    let fw = w as usize;
                    for yy in y1..y2 {
                        for xx in x1..x2 {
                            let i = (yy as usize * fw + xx as usize) * 3;
                            let be = 1.0 - local_p;
                            dst[i]     = (src1[i] as f32 * be + src2[i] as f32 * local_p).clamp(0.0, 255.0) as u8;
                            dst[i + 1] = (src1[i + 1] as f32 * be + src2[i + 1] as f32 * local_p).clamp(0.0, 255.0) as u8;
                            dst[i + 2] = (src1[i + 2] as f32 * be + src2[i + 2] as f32 * local_p).clamp(0.0, 255.0) as u8;
                        }
                    }
                } else {
                    // local_p == 0: copy from frame1
                    blit_sub(frame1, x1, y1, cw, ch, &mut out, x1, y1);
                }
            }
        }
        out
    }
}

pub struct FlashTransition {
    color: [u8; 3],
    flash_point: f32,
    easing: Easing,
}
impl FlashTransition {
    pub fn new(color: [u8; 3], flash_point: f32, easing: Easing) -> Self {
        let fp = flash_point.clamp(0.05, 0.95);
        FlashTransition { color, flash_point: fp, easing }
    }
}
impl EasingHolder for FlashTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for FlashTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let fp = self.flash_point;
        let [cr, cg, cb] = self.color;
        // Blend directly against the constant flash colour without allocating
        // a solid-colour Frame.
        let blend_to_color = |f: &Frame, a: f32| -> Frame {
            let src = f.as_raw().as_slice();
            let be = 1.0 - a;
            let mut raw = vec![0u8; src.len()];
            for (i, o) in raw.iter_mut().enumerate() {
                let channel_const = match i % 3 { 0 => cb, 1 => cg, _ => cr } as f32;
                *o = (src[i] as f32 * be + channel_const * a).clamp(0.0, 255.0) as u8;
            }
            Frame::from_raw(f.width(), f.height(), raw).expect("flash blend")
        };

        if progress < fp {
            let a = progress / fp;
            blend_to_color(frame1, a)
        } else if progress < 2.0 * fp {
            let a = 1.0 - (progress - fp) / fp;
            blend_to_color(frame2, a)
        } else {
            frame2.clone()
        }
    }
}

pub struct RadialWipeTransition {
    origin: (f32, f32),
    easing: Easing,
}
impl RadialWipeTransition {
    pub fn new(origin: (f32, f32), easing: Easing) -> Self {
        RadialWipeTransition { origin, easing }
    }
}
impl EasingHolder for RadialWipeTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for RadialWipeTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let (h, w) = (frame1.height(), frame1.width());
        let cx = (self.origin.0 * w as f32) as i32;
        let cy = (self.origin.1 * h as f32) as i32;
        let max_r = (((cx as f32 - 0.0).max((w as i32 - cx) as f32)).powi(2)
            + ((cy as f32).max((h as i32 - cy) as f32)).powi(2))
            .sqrt();
        let radius = progress * max_r;
        let mut out = Frame::new(w, h);
        let od = out.raw_mut();
        let a = frame1.as_raw().as_slice();
        let b = frame2.as_raw().as_slice();
        for y in 0..h {
            for x in 0..w {
                let dist = (((x as i32 - cx) as f32).powi(2) + ((y as i32 - cy) as f32).powi(2)).sqrt();
                let sel = if dist <= radius { b } else { a };
                let o = ((y * w + x) * 3) as usize;
                od[o..o + 3].copy_from_slice(&sel[o..o + 3]);
            }
        }
        out
    }
}

pub struct ZoomInTransition {
    max_zoom: f32,
    blur_peak: f32,
    easing: Easing,
}
impl ZoomInTransition {
    pub fn new(max_zoom: f32, blur_peak: f32, easing: Easing) -> Self {
        ZoomInTransition { max_zoom: max_zoom.max(1.01), blur_peak, easing }
    }
}
impl EasingHolder for ZoomInTransition {
    fn easing(&self) -> &Easing {
        &self.easing
    }
}
impl Transition for ZoomInTransition {
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let (h, w) = (frame1.height(), frame1.width());
        let scale = 1.0_f32.lerp(&self.max_zoom, progress);
        let alpha = progress.powf(3.5);
        let nh = (h as f32 * scale).max(1.0) as u32;
        let nw = (w as f32 * scale).max(1.0) as u32;
        let r = resize_frame(frame1, nw, nh, "fill");
        let x1 = ((nh - h) / 2) as u32;
        let y1 = ((nw - w) / 2) as u32;
        let mut f1 = {
            let mut out = Frame::new(w, h);
            blit_sub(&r, y1, x1, w, h, &mut out, 0, 0);
            out
        };
        if self.blur_peak > 0.0 {
            let sigma = self.blur_peak * (std::f32::consts::PI * progress).sin();
            if sigma > 0.5 {
                f1 = gaussian_blur(&f1, sigma);
            }
        }
        add_weighted(&f1, 1.0 - alpha, frame2, alpha)
    }
}
