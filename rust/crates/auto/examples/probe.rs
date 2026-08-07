use ocv_auto::metadata::{load_audio_metadata, scan_videos};

fn main() {
    let audio = std::env::args().nth(1).expect("audio path");
    let vdir = std::env::args().nth(2).expect("videos dir");
    match load_audio_metadata(&audio) {
        Ok(m) => {
            let (mut maj, mut min) = (0usize, 0usize);
            for s in &m.segments { maj += s.major.len(); min += s.minor.len(); }
            println!("AUDIO OK: segments={} major={} minor={} dur={:?}", m.segments.len(), maj, min, m.duration);
        }
        Err(e) => println!("AUDIO FAIL: {e}"),
    }
    let vids = scan_videos(&vdir);
    println!("VIDEOS scanned: {}", vids.len());
    for v in vids.iter().take(3) {
        println!("  {} acts={} interval={:?} tags={:?}", v.file, v.actpoints.len(), v.interval, v.tags);
    }
}
