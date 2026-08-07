use ocv_core::frame::VideoSource;
use std::time::Instant;
fn main() {
    let p = std::env::args().nth(1).unwrap();
    let t0 = Instant::now();
    let mut src = VideoSource::open(&p).unwrap();
    println!("opened in {:.2}s", t0.elapsed().as_secs_f32());
    for i in 0..30 {
        let t = Instant::now();
        let f = src.read_frame().unwrap();
        match f {
            Some(fr) => println!("frame {} {}x{} read in {:.3}s", i, fr.width(), fr.height(), t.elapsed().as_secs_f32()),
            None => { println!("frame {i} None"); break; }
        }
    }
    println!("done in {:.2}s", t0.elapsed().as_secs_f32());
}
