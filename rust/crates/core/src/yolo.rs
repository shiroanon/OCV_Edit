//! Real YOLO person-segmentation mask loader (replaces the `NoMask` stub).
//!
//! Runs a YOLO-seg ONNX model (e.g. `models/yolo26s-seg.onnx`) on the frame
//! and returns a soft person mask (COCO class 0) used by the depth-composite
//! "text behind person" effect. Mirrors `utils/effects.py::YoloTextEffect`.

use crate::effect::MaskLoader;
use crate::frame::{Frame, Mask, RawMut};
use image::{imageops, GrayImage, Rgb, RgbImage};
use ndarray::Array4;
use ort::session::Session;
use std::sync::{Mutex, OnceLock};

const INPUT: u32 = 640;

// One shared session for the process (model load is expensive).
static SESSION: OnceLock<Mutex<Option<Session>>> = OnceLock::new();

fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-x).exp())
}

pub struct YoloSegMaskLoader {
    model_path: String,
}

impl YoloSegMaskLoader {
    pub fn new(model_path: impl Into<String>) -> Self {
        Self {
            model_path: model_path.into(),
        }
    }
}

impl MaskLoader for YoloSegMaskLoader {
    fn load(&self, frame: &Frame, _fi: u64) -> Option<Mask> {
        let fw = frame.width();
        let fh = frame.height();
        if fw == 0 || fh == 0 {
            return None;
        }
        let buf = frame.as_raw();

        // --- preprocess: BGR frame -> RGB, letterboxed to INPUT×INPUT, CHW f32 ---
        let mut rgb = RgbImage::new(fw, fh);
        for (i, px) in rgb.pixels_mut().enumerate() {
            let b = buf[i * 3];
            let g = buf[i * 3 + 1];
            let r = buf[i * 3 + 2];
            *px = Rgb([r, g, b]);
        }
        let scale = (INPUT as f32 / fw as f32).min(INPUT as f32 / fh as f32);
        let nw = (fw as f32 * scale) as u32;
        let nh = (fh as f32 * scale) as u32;
        let small = imageops::resize(&rgb, nw, nh, imageops::FilterType::Triangle);
        let mut canvas = RgbImage::new(INPUT, INPUT);
        for px in canvas.pixels_mut() {
            *px = Rgb([114, 114, 114]);
        }
        let dx = ((INPUT - nw) / 2) as i64;
        let dy = ((INPUT - nh) / 2) as i64;
        imageops::replace(&mut canvas, &small, dx, dy);

        let plane = (INPUT * INPUT) as usize;
        let mut blob = vec![0f32; 3 * plane];
        for y in 0..INPUT as usize {
            for x in 0..INPUT as usize {
                let p = canvas.get_pixel(x as u32, y as u32);
                let idx = y * INPUT as usize + x;
                blob[idx] = p[0] as f32 / 255.0;
                blob[plane + idx] = p[1] as f32 / 255.0;
                blob[2 * plane + idx] = p[2] as f32 / 255.0;
            }
        }
        let arr = Array4::from_shape_vec((1, 3, INPUT as usize, INPUT as usize), blob).ok()?;
        let input = ort::value::Tensor::from_array(arr).ok()?;

        // --- run (shared session) ---
        let cell = SESSION.get_or_init(|| Mutex::new(None));
        let mut guard = cell.lock().ok()?;
        if guard.is_none() {
            *guard = Some(Session::builder().ok()?.commit_from_file(&self.model_path).ok()?);
        }
        let session = guard.as_mut().unwrap();
        let outputs = session.run(ort::inputs!["images" => input]).ok()?;
        let out0 = outputs["output0"].try_extract_array::<f32>().ok()?;
        let out1 = outputs["output1"].try_extract_array::<f32>().ok()?;

        // out0: (1, 300, 38) = [cx, cy, w, h, conf, class, 32 mask-coeffs]
        // out1: (1, 32, 160, 160) proto masks
        // Zero-copy views: reshape without cloning.
        let det = out0.into_shape_with_order([300usize, 38usize]).ok()?;

        let mut mask640 = vec![0f32; plane];
        for k in 0..300usize {
            let conf = det[[k, 4]];
            let cls = det[[k, 5]].round() as i32;
            if conf < 0.3 || cls != 0 {
                continue;
            }
            let cx = det[[k, 0]];
            let cy = det[[k, 1]];
            let w = det[[k, 2]];
            let h = det[[k, 3]];
            let mut coeffs = [0f32; 32];
            for c in 0..32 {
                coeffs[c] = det[[k, 6 + c]];
            }
            // person mask @ 160×160
            let mut mask160 = vec![0f32; 160 * 160];
            for yy in 0..160usize {
                for xx in 0..160usize {
                    let mut s = 0f32;
                    for c in 0..32usize {
                        s += coeffs[c] * out1[[0, c, yy, xx]];
                    }
                    mask160[yy * 160 + xx] = sigmoid(s);
                }
            }
            let g160 = GrayImage::from_raw(160, 160, mask160.iter().map(|v| (v * 255.0) as u8).collect())?;
            let g640 = imageops::resize(&g160, INPUT, INPUT, imageops::FilterType::Triangle);
            let x1 = (cx - w / 2.0).max(0.0) as i32;
            let y1 = (cy - h / 2.0).max(0.0) as i32;
            let x2 = (cx + w / 2.0).min(INPUT as f32) as i32;
            let y2 = (cy + h / 2.0).min(INPUT as f32) as i32;
            if x2 <= x1 || y2 <= y1 {
                continue;
            }
            for yy in y1..y2 {
                for xx in x1..x2 {
                    let v = g640.get_pixel(xx as u32, yy as u32)[0] as f32 / 255.0;
                    let o = (yy as usize) * INPUT as usize + xx as usize;
                    if v > mask640[o] {
                        mask640[o] = v;
                    }
                }
            }
        }

        // inverse letterbox: mask640[dy..dy+nh, dx..dx+nw] -> (fw, fh)
        let mut gmask = GrayImage::from_raw(INPUT, INPUT, mask640.iter().map(|v| (v * 255.0) as u8).collect())?;
        let sub = imageops::crop(&mut gmask, dx as u32, dy as u32, nw, nh).to_image();
        let orig = imageops::resize(&sub, fw, fh, imageops::FilterType::Triangle);
        let mut out = Mask::new(fw, fh);
        for (i, px) in orig.as_raw().iter().enumerate() {
            out.raw_mut()[i] = (*px as f32 / 255.0).clamp(0.0, 1.0);
        }
        Some(out)
    }
}
