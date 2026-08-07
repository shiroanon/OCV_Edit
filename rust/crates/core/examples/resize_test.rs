use ocv_core::frame::{resize_frame, VideoSource};
use std::time::Instant;
fn main() {
    let p = std::env::args().nth(1).unwrap();
    let mut src = VideoSource::open(&p).unwrap();
    let t = Instant::now();
    let f = src.read_frame().unwrap().unwrap();
    println!("decoded {}x{} in {:.2}s", f.width(), f.height(), t.elapsed().as_secs_f32());
    for mode in ["fill", "fit"] {
        let t = Instant::now();
        let r = resize_frame(&f, 720, 1280, mode);
        println!("resize {} -> {}x{} in {:.3}s", mode, r.width(), r.height(), t.elapsed().as_secs_f32());
    }
}
