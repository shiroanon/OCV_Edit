use fast_image_resize as fir;
use fir::images::{ImageRef, Image};
use fir::{PixelType, ResizeAlg};
use std::time::Instant;
fn main() {
    let (w,h,nw,nh) = (2160u32,3840,720,1280);
    let npix = (w*h) as usize;
    let mut rgba = vec![0u8; npix*4];
    // time conversion only
    let t = Instant::now();
    // (already allocated) simulate conversion
    let conv = t.elapsed();
    let src = ImageRef::new(w, h, &rgba, PixelType::U8x4).unwrap();
    let mut dst = Image::new(nw, nh, PixelType::U8x4);
    let t = Instant::now();
    fir::Resizer::new().resize(&src, &mut dst, None).unwrap();
    println!("resize only: {:.3}s (conv alloc {:.3}s)", t.elapsed().as_secs_f32(), conv.as_secs_f32());
    // try with resize options alpha
    let mut opt = fir::ResizeOptions::new();
    opt.algorithm = ResizeAlg::Nearest;
    let t = Instant::now();
    fir::Resizer::new().resize(&src, &mut dst, Some(&opt)).unwrap();
    println!("nearest resize: {:.3}s", t.elapsed().as_secs_f32());
}
