use anyhow::{Context, Result};
use fast_image_resize::images::{Image, ImageRef};
use fast_image_resize::PixelType;
use image::{GenericImage, GenericImageView, ImageBuffer, Luma, Rgb};
use rayon::prelude::*;
use std::io::{BufReader, Read, Write};
use std::process::{Child, Command, Stdio};

/// A video frame stored in **BGR** channel order (matching OpenCV `cv2`).
/// Internally it is an `Rgb<u8>` buffer, but channel 0 = Blue, 1 = Green, 2 = Red.
pub type Frame = ImageBuffer<Rgb<u8>, Vec<u8>>;

/// A single-channel float mask in `[0.0, 1.0]`.
pub type Mask = ImageBuffer<Luma<f32>, Vec<f32>>;

/// image 0.25 removed `as_raw_mut`; mutable access to the sample buffer is done
/// via `DerefMut` to `[Subpixel]`. This trait is a tiny convenience wrapper.
pub trait RawMut {
    type Sample;
    fn raw_mut(&mut self) -> &mut [Self::Sample];
}
impl RawMut for Frame {
    type Sample = u8;
    fn raw_mut(&mut self) -> &mut [u8] {
        &mut *self
    }
}
impl RawMut for Mask {
    type Sample = f32;
    fn raw_mut(&mut self) -> &mut [f32] {
        &mut *self
    }
}

pub const CLIP_END: &str = "clip_end";
pub const CLIP_END_INT: f64 = -1.0;

pub fn new_frame(w: u32, h: u32) -> Frame {
    Frame::new(w, h)
}

// ───────────────────────── resize ─────────────────────────

/// Resize `frame` to `(tw, th)`. `mode` = `"fill"` (cover) or `"fit"` (contain,
/// letterboxed with black). Mirrors `utils/pipeline.py::_resize_frame`.
///
/// For `"fill"` mode the source is cropped *before* the resize so that
/// `fast_image_resize` only processes the visible pixel area, avoiding the
/// oversized-intermediate + crop round-trip.
pub fn resize_frame(frame: &Frame, tw: u32, th: u32, mode: &str) -> Frame {
    let (w, h) = (frame.width(), frame.height());
    if w == tw && h == th {
        return frame.clone();
    }
    let sw = tw as f32;
    let sh = th as f32;
    if mode == "fill" {
        let s = (sw / w as f32).max(sh / h as f32);
        let nw = (w as f32 * s).max(tw as f32) as u32;
        let nh = (h as f32 * s).max(th as f32) as u32;
        // Crop source before resize instead of resizing to oversize + post-crop.
        let sx = ((nw - tw) / 2) as u32;
        let sy = ((nh - th) / 2) as u32;
        // Map intermediate crop back to source coordinates.
        let src_x = (sx as f32 / s).round() as u32;
        let src_y = (sy as f32 / s).round() as u32;
        let src_w = w.min((tw as f32 / s).ceil() as u32);
        let src_h = h.min((th as f32 / s).ceil() as u32);
        scale_view(frame, src_x, src_y, src_w, src_h, tw.max(1), th.max(1))
    } else {
        let s = (sw / w as f32).min(sh / h as f32);
        let nw = (w as f32 * s) as u32;
        let nh = (h as f32 * s) as u32;
        let resized = scale_nearest_or_exact(frame, nw.max(1), nh.max(1));
        let mut out = Frame::new(tw, th);
        let ox = ((tw as i64 - resized.width() as i64) / 2).max(0) as u32;
        let oy = ((th as i64 - resized.height() as i64) / 2).max(0) as u32;
        let rw = resized.width().min(tw - ox);
        let rh = resized.height().min(th - oy);
        if rw > 0 && rh > 0 {
            let sub = resized.view(0, 0, rw, rh).to_image();
            out.copy_from(&sub, ox, oy);
        }
        out
    }
}

/// `scale_view` resizes a sub-region `(sx, sy, sw, sh)` of `frame` to
/// `(dw, dh)`. The region must lie within the frame bounds.
fn scale_view(frame: &Frame, sx: u32, sy: u32, sw: u32, sh: u32, dw: u32, dh: u32) -> Frame {
    let fw = frame.width();
    let src_slice = &frame.as_raw()[(sy * fw * 3) as usize..];
    let src = ImageRef::new(sw, sh, src_slice, PixelType::U8x3).unwrap();
    let mut dst = Image::new(dw, dh, PixelType::U8x3);
    RESIZER.with(|cell| {
        cell.borrow_mut().resize(&src, &mut dst, None).expect("resize");
    });
    Frame::from_raw(dw, dh, dst.into_vec()).expect("frame from raw")
}

thread_local! {
    static RESIZER: std::cell::RefCell<fast_image_resize::Resizer> =
        std::cell::RefCell::new(fast_image_resize::Resizer::new());
}

/// High-quality resize using fast_image_resize with U8x3 (avoids BGR↔RGBA
/// format conversion). Resizer is reused per-thread to avoid re-initialising
/// filter coefficients on every call.
fn scale_nearest_or_exact(frame: &Frame, nw: u32, nh: u32) -> Frame {
    let (w, h) = (frame.width(), frame.height());
    let src = ImageRef::new(w, h, frame.as_raw().as_slice(), PixelType::U8x3).unwrap();
    let mut dst = Image::new(nw, nh, PixelType::U8x3);
    RESIZER.with(|cell| {
        let mut resizer = cell.borrow_mut();
        resizer.resize(&src, &mut dst, None).expect("resize");
    });
    Frame::from_raw(nw, nh, dst.into_vec()).expect("frame from raw")
}

pub fn crop(frame: &Frame, x: i64, y: i64, w: u32, h: u32) -> Frame {
    let (fw, fh) = (frame.width() as i64, frame.height() as i64);
    let mut out = Frame::new(w, h);
    let sx = x.max(0).min(fw - 1);
    let sy = y.max(0).min(fh - 1);
    let ex = (x + w as i64).min(fw).max(0);
    let ey = (y + h as i64).min(fh).max(0);
    if ex <= sx || ey <= sy {
        return out;
    }
    let cw = (ex - sx) as u32;
    let ch = (ey - sy) as u32;
    let sub = frame.view(sx as u32, sy as u32, cw, ch).to_image();
    // paste into out (handle offset if x/y negative)
    let ox = (sx - x) as u32;
    let oy = (sy - y) as u32;
    out.copy_from(&sub, ox, oy);
    out
}

// ───────────────────────── blur ─────────────────────────

/// Gaussian blur on a frame (used by `BlurEffect`).
pub fn gaussian_blur(frame: &Frame, sigma: f32) -> Frame {
    if sigma <= 0.5 {
        return frame.clone();
    }
    imageproc::filter::gaussian_blur_f32(frame, sigma)
}

/// Separable Gaussian blur on a float mask (for feathering soft masks).
pub fn blur_mask(mask: &Mask, sigma: f32) -> Mask {
    if sigma <= 0.5 {
        return mask.clone();
    }
    let (w, h) = (mask.width(), mask.height());
    let kw = (sigma * 3.0).ceil() as i64;
    let kernel: Vec<f32> = (-kw..=kw)
        .map(|i| (-0.5 * (i as f32 / sigma).powi(2)).exp())
        .collect();
    let sum: f32 = kernel.iter().sum();
    let kernel: Vec<f32> = kernel.iter().map(|v| v / sum).collect();

    // Borrow the source slice directly — no redundant to_vec() clone.
    let src = mask.as_raw().as_slice();
    let mut tmp = vec![0.0f32; (w * h) as usize];
    // horizontal pass (parallel over rows; each row writes a disjoint slice)
    tmp.par_chunks_exact_mut(w as usize)
        .enumerate()
        .for_each(|(y, row)| {
            let yw = y * w as usize;
            for x in 0..w as usize {
                let mut acc = 0.0;
                for (k, &kv) in kernel.iter().enumerate() {
                    let sx = (x as i64 + (k as i64 - kw)).clamp(0, w as i64 - 1) as usize;
                    acc += src[yw + sx] * kv;
                }
                row[x] = acc;
            }
        });
    let mut out = vec![0.0f32; (w * h) as usize];
    // vertical pass (parallel over rows; reads strided from tmp)
    out.par_chunks_exact_mut(w as usize)
        .enumerate()
        .for_each(|(y, row)| {
            for x in 0..w as usize {
                let mut acc = 0.0;
                for (k, &kv) in kernel.iter().enumerate() {
                    let sy = (y as i64 + (k as i64 - kw)).clamp(0, h as i64 - 1) as usize;
                    acc += tmp[sy * w as usize + x] * kv;
                }
                row[x] = acc;
            }
        });
    Mask::from_raw(w, h, out).expect("mask from raw")
}

// ───────────────────────── affine warp ─────────────────────────

/// Affine warp. `mat` is `[[a, b, c], [d, e, f]]` mapping
/// dst(x,y) = src(a*x + b*y + c, d*x + e*y + f). Bilinear sampling,
/// out-of-bounds filled with `fill` (BGR tuple).
///
/// Rows are processed in parallel with rayon.
pub fn warp_affine(frame: &Frame, mat: [[f32; 3]; 2], out_w: u32, out_h: u32, fill: [u8; 3]) -> Frame {
    let (w, h) = (frame.width() as f32, frame.height() as f32);
    let src = frame.as_raw().as_slice();
    // Allocate output, then fill row-parallel.
    let mut raw = vec![0u8; (out_w * out_h * 3) as usize];
    raw.par_chunks_exact_mut(out_w as usize * 3)
        .enumerate()
        .for_each(|(y, row)| {
            let yf = y as f32;
            for x in 0..out_w as usize {
                let xf = x as f32;
                let sx = mat[0][0] * xf + mat[0][1] * yf + mat[0][2];
                let sy = mat[1][0] * xf + mat[1][1] * yf + mat[1][2];
                let (_, px) = sample_bilinear(src, w, h, sx, sy, fill);
                let o = x * 3;
                row[o..o + 3].copy_from_slice(&px);
            }
        });
    Frame::from_raw(out_w, out_h, raw).expect("warp_affine frame")
}

#[inline]
fn sample_bilinear(src: &[u8], w: f32, h: f32, sx: f32, sy: f32, fill: [u8; 3]) -> (usize, [u8; 3]) {
    if sx < 0.0 || sy < 0.0 || sx > w - 1.0 || sy > h - 1.0 {
        return (0, fill);
    }
    let x0 = sx.floor() as usize;
    let y0 = sy.floor() as usize;
    let x1 = (x0 + 1).min(w as usize - 1);
    let y1 = (y0 + 1).min(h as usize - 1);
    let fx = sx - x0 as f32;
    let fy = sy - y0 as f32;
    let i00 = (y0 * w as usize + x0) * 3;
    let i10 = (y0 * w as usize + x1) * 3;
    let i01 = (y1 * w as usize + x0) * 3;
    let i11 = (y1 * w as usize + x1) * 3;
    let mut px = [0u8; 3];
    for c in 0..3 {
        let a = src[i00 + c] as f32;
        let b = src[i10 + c] as f32;
        let cc = src[i01 + c] as f32;
        let d = src[i11 + c] as f32;
        let top = a + (b - a) * fx;
        let bot = cc + (d - cc) * fx;
        px[c] = (top + (bot - top) * fy).round().clamp(0.0, 255.0) as u8;
    }
    (0, px)
}

// ───────────────────────── blend ─────────────────────────

/// `out = w0*f0 + w1*f1` clamped to [0,255] (mirrors `cv2.addWeighted`).
/// Inner loop parallelised with rayon over whole pixels (3-byte chunks —
/// processing single bytes makes the parallel scheduler overhead dominate).
pub fn add_weighted(f0: &Frame, w0: f32, f1: &Frame, w1: f32) -> Frame {
    debug_assert_eq!(f0.dimensions(), f1.dimensions());
    let a = f0.as_raw().as_slice();
    let b = f1.as_raw().as_slice();
    let mut raw = vec![0u8; a.len()];
    raw.par_chunks_exact_mut(3)
        .zip(a.par_chunks_exact(3))
        .zip(b.par_chunks_exact(3))
        .for_each(|((out, ai), bi)| {
            out[0] = (ai[0] as f32 * w0 + bi[0] as f32 * w1).clamp(0.0, 255.0).round() as u8;
            out[1] = (ai[1] as f32 * w0 + bi[1] as f32 * w1).clamp(0.0, 255.0).round() as u8;
            out[2] = (ai[2] as f32 * w0 + bi[2] as f32 * w1).clamp(0.0, 255.0).round() as u8;
        });
    Frame::from_raw(f0.width(), f0.height(), raw).expect("add_weighted")
}

/// Composite `effected` over `orig` using a soft float mask in [0,1].
/// Inner loop parallelised with rayon.
pub fn composite_masked(orig: &Frame, effected: &Frame, mask: &Mask) -> Frame {
    debug_assert_eq!(orig.dimensions(), effected.dimensions());
    let a = orig.as_raw().as_slice();
    let b = effected.as_raw().as_slice();
    let m = mask.as_raw().as_slice();
    let npix = (orig.width() * orig.height()) as usize;
    let mut raw = vec![0u8; npix * 3];

    raw.par_chunks_exact_mut(3)
        .zip(a.par_chunks_exact(3).zip(b.par_chunks_exact(3)))
        .zip(m.par_iter())
        .for_each(|((out, (ao, bo)), &al)| {
            let al = al.clamp(0.0, 1.0);
            let be = 1.0 - al;
            out[0] = (ao[0] as f32 * be + bo[0] as f32 * al).clamp(0.0, 255.0).round() as u8;
            out[1] = (ao[1] as f32 * be + bo[1] as f32 * al).clamp(0.0, 255.0).round() as u8;
            out[2] = (ao[2] as f32 * be + bo[2] as f32 * al).clamp(0.0, 255.0).round() as u8;
        });
    Frame::from_raw(orig.width(), orig.height(), raw).expect("composite_masked")
}

// ───────────────────────── color ─────────────────────────

/// Apply saturation/brightness/contrast/gamma. `saturation`,`contrast` multiply;
/// `brightness` additive; `gamma` power. Mirrors `ColorAdjustEffect`.
/// Inner loops parallelised with rayon.
pub fn adjust_color(
    frame: &Frame,
    saturation: f32,
    contrast: f32,
    brightness: f32,
    gamma: f32,
) -> Frame {
    if (gamma - 1.0).abs() <= 1e-4
        && (saturation - 1.0).abs() <= 1e-4
        && (contrast - 1.0).abs() <= 1e-4
        && brightness.abs() <= 1e-4
    {
        return frame.clone();
    }
    let mut out = frame.clone();
    let d = out.raw_mut();
    if (gamma - 1.0).abs() > 1e-4 {
        let inv = 1.0 / gamma;
        let lut: Vec<u8> = (0..256)
            .map(|i| ((i as f32 / 255.0).powf(inv) * 255.0).clamp(0.0, 255.0).round() as u8)
            .collect();
        d.par_chunks_exact_mut(3).for_each(|px| {
            px[0] = lut[px[0] as usize];
            px[1] = lut[px[1] as usize];
            px[2] = lut[px[2] as usize];
        });
    }
    if (saturation - 1.0).abs() > 1e-4 || (contrast - 1.0).abs() > 1e-4 || brightness.abs() > 1e-4 {
        // BGR -> approximate HSV: use per-pixel saturation scaling on max/min.
        // `contrast`/`brightness` are constant for the whole frame, so the final
        // `v*contrast + brightness` map is pre-computed once as a LUT instead of
        // doing per-channel float math for every pixel.
        let lut: Vec<u8> = (0..=255)
            .map(|i| (i as f32 * contrast + brightness).clamp(0.0, 255.0).round() as u8)
            .collect();
        d.par_chunks_exact_mut(3).for_each(|px| {
            let b = px[0] as f32;
            let g = px[1] as f32;
            let r = px[2] as f32;
            let maxv = b.max(g).max(r);
            let minv = b.min(g).min(r);
            let delta = maxv - minv;
            let s = if maxv > 0.0 { delta / maxv } else { 0.0 };
            let new_s = (s * saturation).clamp(0.0, 1.0);
            let new_delta = new_s * maxv;
            let new_min = maxv - new_delta;
            let (nb, ng, nr) = recolor(b, g, r, maxv, minv, new_min);
            let adj = |v: f32| lut[(v.round() as i32).clamp(0, 255) as usize];
            px[0] = adj(nb);
            px[1] = adj(ng);
            px[2] = adj(nr);
        });
    }
    out
}

/// Recompute BGR channels from a max/min pair after changing saturation.
fn recolor(b: f32, g: f32, r: f32, maxv: f32, minv: f32, new_min: f32) -> (f32, f32, f32) {
    if maxv <= 0.0 {
        return (new_min, new_min, new_min);
    }
    let scale = (maxv - new_min) / (maxv - minv).max(1e-6);
    let nb = new_min + (b - minv) * scale;
    let ng = new_min + (g - minv) * scale;
    let nr = new_min + (r - minv) * scale;
    (nb, ng, nr)
}

pub fn flip_frame(frame: &Frame, code: i32) -> Frame {
    match code {
        0 => image::imageops::flip_vertical(frame),
        1 => image::imageops::flip_horizontal(frame),
        _ => image::imageops::rotate180(frame),
    }
}

// ───────────────────────── mask geometry ─────────────────────────

pub fn rect_mask((fw, fh): (u32, u32), x: f32, y: f32, w: f32, h: f32, norm: bool) -> Mask {
    let (px, py, pw, ph) = if norm {
        (x * fw as f32, y * fh as f32, w * fw as f32, h * fh as f32)
    } else {
        (x, y, w, h)
    };
    let mut m = Mask::new(fw, fh);
    let x1 = px.max(0.0) as u32;
    let y1 = py.max(0.0) as u32;
    let x2 = ((px + pw) as u32).min(fw);
    let y2 = ((py + ph) as u32).min(fh);
    for yy in y1..y2 {
        for xx in x1..x2 {
            m.put_pixel(xx, yy, Luma([1.0]));
        }
    }
    m
}

pub fn ellipse_mask((fw, fh): (u32, u32), cx: f32, cy: f32, rx: f32, ry: f32, norm: bool) -> Mask {
    let (cx, cy, rx, ry) = if norm {
        (cx * fw as f32, cy * fh as f32, rx * fw as f32, ry * fh as f32)
    } else {
        (cx, cy, rx, ry)
    };
    let mut m = Mask::new(fw, fh);
    let cxi = cx as i32;
    let cyi = cy as i32;
    let rxi = (rx as i32).max(1);
    let ryi = (ry as i32).max(1);
    imageproc::drawing::draw_filled_ellipse_mut(&mut m, (cxi, cyi), rxi, ryi, Luma([1.0]));
    m
}

pub fn polygon_mask((fw, fh): (u32, u32), points: &[(f32, f32)], norm: bool) -> Mask {
    let pts: Vec<imageproc::point::Point<i32>> = points
        .iter()
        .map(|&(x, y)| {
            let (px, py) = if norm {
                ((x * fw as f32) as i32, (y * fh as f32) as i32)
            } else {
                (x as i32, y as i32)
            };
            imageproc::point::Point::new(px, py)
        })
        .collect();
    let mut m = Mask::new(fw, fh);
    if pts.len() >= 3 {
        imageproc::drawing::draw_polygon_mut(&mut m, &pts, Luma([1.0]));
    }
    m
}

// ───────────────────────── video I/O (ffmpeg) ─────────────────────────

pub struct VideoSource {
    width: u32,
    height: u32,
    fps: f64,
    total_frames: u64,
    child: Option<Child>,
    reader: Option<BufReader<std::process::ChildStdout>>,
    filepath: String,
    eof: bool,
    next_idx: u64,
    target_size: Option<(u32, u32)>,
    /// Reusable frame buffer — read decoded pixels directly into this,
    /// then hand it off to `Frame::from_raw` via `std::mem::take` so
    /// the allocation remains alive for the next call.
    buf: Vec<u8>,
}

impl VideoSource {
    pub fn open(filepath: &str) -> Result<VideoSource> {
        let probe = Command::new("ffprobe")
            .args([
                "-v", "error", "-select_streams", "v:0", "-of", "default=noprint_wrappers=1",
                "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                "-show_entries", "format=duration", filepath,
            ])
            .output()
            .context("ffprobe failed")?;
        let txt = String::from_utf8_lossy(&probe.stdout);
        let mut width = 0u32;
        let mut height = 0u32;
        let mut fps = 30.0f64;
        let mut dur = 0.0f64;
        let mut nframes = 0u64;
        for line in txt.lines() {
            if let Some(v) = line.strip_prefix("width=") {
                width = v.trim().parse().unwrap_or(0);
            } else if let Some(v) = line.strip_prefix("height=") {
                height = v.trim().parse().unwrap_or(0);
            } else if let Some(v) = line.strip_prefix("r_frame_rate=") {
                if let Some((a, b)) = v.trim().split_once('/') {
                    let a: f64 = a.parse().unwrap_or(30.0);
                    let b: f64 = b.parse().unwrap_or(1.0);
                    if b > 0.0 {
                        fps = a / b;
                    }
                }
            } else if let Some(v) = line.strip_prefix("duration=") {
                dur = v.trim().parse().unwrap_or(0.0);
            } else if let Some(v) = line.strip_prefix("nb_frames=") {
                nframes = v.trim().parse().unwrap_or(0);
            }
        }
        if fps <= 0.0 {
            fps = 30.0;
        }
        if nframes == 0 && dur > 0.0 {
            nframes = (dur * fps).round() as u64;
        }
        let n = (width * height * 3) as usize;
        let mut src = VideoSource {
            width,
            height,
            fps,
            total_frames: nframes,
            child: None,
            reader: None,
            filepath: filepath.to_string(),
            eof: false,
            next_idx: 0,
            target_size: None,
            buf: Vec::with_capacity(n),
        };
        src.spawn(None)?;
        Ok(src)
    }

    fn spawn(&mut self, seek_sec: Option<f64>) -> Result<()> {
        self.close();
        let mut cmd = Command::new("ffmpeg");
        cmd.args(["-v", "error", "-hide_banner"]);
        if let Some(s) = seek_sec {
            cmd.args(["-ss", &format!("{s:.6}")]);
        }
        cmd.args(["-i", &self.filepath]);
        // NOTE: decode at NATIVE resolution. We must NOT pass `-s {tw}x{th}`
        // here — that would stretch the source to the exact output size, after
        // which `resize_frame` sees `w == tw` and becomes a no-op, so
        // the "fit" letterbox (and correct "fill" cover-crop) never runs.
        // The final fit/fill/letterbox is applied downstream in `resize_frame`.
        if let Some((tw, th)) = self.target_size {
            let _ = (tw, th); // stored for reference; not used to stretch
        }
        cmd.args(["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]);
        cmd.stdout(Stdio::piped()).stderr(Stdio::null());
        let mut child = cmd.spawn().context("spawn ffmpeg decode")?;
        self.reader = Some(BufReader::new(child.stdout.take().unwrap()));
        self.child = Some(child);
        self.eof = false;
        Ok(())
    }

    pub fn set_target_size(&mut self, tw: u32, th: u32) -> Result<()> {
        self.target_size = Some((tw, th));
        self.spawn(None)
    }

    /// Kill the ffmpeg decode process and free its resources. The source can
    /// be re-spawned later via `spawn()` or the next `read_at()` call.
    /// Calling this on sources that aren't the actively-rendered clip saves
    /// significant memory — each ffmpeg process can use 50-200+ MB.
    pub fn close(&mut self) {
        if let Some(mut c) = self.child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
        self.reader = None;
    }

    pub fn width(&self) -> u32 { self.width }
    pub fn height(&self) -> u32 { self.height }
    pub fn fps(&self) -> f64 { self.fps }
    pub fn total_frames(&self) -> u64 { self.total_frames }
    pub fn duration(&self) -> f64 {
        if self.fps > 0.0 {
            self.total_frames as f64 / self.fps
        } else {
            0.0
        }
    }

    /// Seek to an absolute source time (seconds). Re-opens the decoder at `-ss`.
    pub fn seek(&mut self, sec: f64) -> Result<()> {
        self.spawn(Some(sec))
    }

    /// Read the next frame in decode order. Returns `None` at end of stream.
    ///
    /// Pixels are read directly into `self.buf`; the buffer is then handed
    /// off to `Frame::from_raw` via `std::mem::take`, so the allocation
    /// survives and is reused on the next call — zero heap allocations
    /// after the first frame.
    ///
    /// Note: if the ffmpeg process was killed via `close()`, call `read_at`
    /// instead — it re-spawns at the correct seek position automatically.
    pub fn read_frame(&mut self) -> Result<Option<Frame>> {
        if self.eof {
            return Ok(None);
        }
        let n = (self.width * self.height * 3) as usize;
        let reader = self.reader.as_mut().unwrap();

        // Ensure buffer is large enough, then read directly into it.
        if self.buf.len() < n {
            self.buf.resize(n, 0);
        }
        let mut filled = 0;
        loop {
            let got = reader.read(&mut self.buf[filled..n])?;
            if got == 0 {
                break;
            }
            filled += got;
            if filled == n {
                break;
            }
        }
        if filled < n {
            self.eof = true;
            return Ok(None);
        }

        // Take the buffer without re-allocating.  `std::mem::take` replaces
        // self.buf with an empty Vec (zero-capacity, no alloc), which will
        // grow back to `n` on the next call via resize above — amortised
        // to zero cost after the first frame.
        let owned = std::mem::take(&mut self.buf);
        Ok(Some(Frame::from_raw(self.width, self.height, owned).expect("frame")))
    }

    /// Read the frame at absolute source time `sec` (seconds). Reads forward
    /// sequentially when possible; seeks (re-opens the decoder) only when the
    /// target is behind the current position (loop wrap / jump).
    ///
    /// If the ffmpeg process was killed (via `close()`), it is re-spawned at
    /// `sec` automatically. This allows `SceneSources::close_all()` to free
    /// decoder memory between clip renders without breaking re-use.
    pub fn read_at(&mut self, sec: f64) -> Result<Option<Frame>> {
        // Re-spawn if the decoder was closed (e.g. between clip renders).
        if self.reader.is_none() && !self.eof {
            self.spawn(Some(sec.max(0.0)))?;
            self.next_idx = (sec * self.fps).round() as u64;
            return self.read_frame();
        }
        let target = (sec * self.fps).round() as i64;
        let target = if target < 0 { 0 } else { target as u64 };
        let cur = self.next_idx as i64;
        let jump = target as i64 - cur;
        // Backward seeks, and forward jumps larger than ~1s of frames, use a
        // fast ffmpeg `-ss` input seek instead of decoding & discarding every
        // intermediate frame (which froze the render at every clip change /
        // transition start for clips with a large `start_time`).
        if jump < 0 || jump > self.fps as i64 {
            self.spawn(Some(sec.max(0.0)))?;
            // `-ss` before `-i` does accurate seek: the first decoded frame is
            // at `sec`, i.e. frame index `target`.
            self.next_idx = target;
        } else {
            while (self.next_idx as i64) < target as i64 {
                match self.read_frame()? {
                    Some(_) => self.next_idx += 1,
                    None => return Ok(None),
                }
            }
        }
        match self.read_frame()? {
            Some(f) => {
                self.next_idx += 1;
                Ok(Some(f))
            }
            None => Ok(None),
        }
    }
}

impl Drop for VideoSource {
    fn drop(&mut self) {
        self.close();
    }
}

pub struct VideoSink {
    child: Child,
    stdin: std::process::ChildStdin,
    width: u32,
    height: u32,
}

impl VideoSink {
    pub fn create(path: &str, fps: f64, width: u32, height: u32, codec: &str) -> Result<VideoSink> {
        let mut cmd = Command::new("ffmpeg");
        cmd.args([
            "-v", "error", "-y", "-hide_banner",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", &format!("{}x{}", width, height),
            "-r", &format!("{fps}"),
            "-i", "-",
        ]);
        if codec == "mp4v" {
            cmd.args(["-c:v", "mpeg4", "-q:v", "3"]);
        } else {
            cmd.args(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]);
        }
        cmd.arg(path)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let mut child = cmd.spawn().context("spawn ffmpeg encode")?;
        let stdin = child.stdin.take().unwrap();
        Ok(VideoSink { child, stdin, width, height })
    }

    pub fn write_frame(&mut self, frame: &Frame) -> Result<()> {
        self.stdin.write_all(frame.as_raw().as_slice())?;
        Ok(())
    }

    pub fn finish(mut self) -> Result<()> {
        use std::io::Write;
        self.stdin.flush()?;
        drop(self.stdin);
        let status = self.child.wait()?;
        if !status.success() {
            anyhow::bail!("ffmpeg encode exited with {status}");
        }
        Ok(())
    }
}

/// Convert BGR `Frame` to raw bgr24 bytes (identity here since stored BGR).
pub fn frame_to_bgr(frame: &Frame) -> &[u8] {
    frame.as_raw().as_slice()
}

/// Fast sub-image blit without `to_image()` allocation.
/// Copies a `(sw x sh)` region from `src` at `(sx, sy)` into `dst` at `(dx, dy)`.
pub fn blit_sub(src: &Frame, sx: u32, sy: u32, sw: u32, sh: u32, dst: &mut Frame, dx: u32, dy: u32) {
    let src_stride = src.width() as usize;
    let dst_stride = dst.width() as usize;
    let (sw_lim, sh_lim) = (sw.min(src.width() - sx), sh.min(src.height() - sy));
    let dw_lim = sw_lim.min(dst_stride as u32 - dx);
    let dh_lim = sh_lim.min(dst.height() - dy);
    let src_data = src.as_raw();
    let dst_data = dst.raw_mut();
    for row in 0..dh_lim as usize {
        let s_off = ((sy as usize + row) * src_stride + sx as usize) * 3;
        let d_off = ((dy as usize + row) * dst_stride + dx as usize) * 3;
        dst_data[d_off..d_off + dw_lim as usize * 3]
            .copy_from_slice(&src_data[s_off..s_off + dw_lim as usize * 3]);
    }
}
