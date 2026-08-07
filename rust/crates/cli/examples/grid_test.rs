use ocv_core::frame::*;
use ocv_core::scene::*;

fn main() -> anyhow::Result<()> {
    let v1 = std::env::args().nth(1).expect("arg1: video path");
    let v2 = std::env::args().nth(2).expect("arg2: video path");
    let files = vec![
        (v1.clone(), 0.0f32, 1.0f32, true),
        (v2.clone(), 0.0f32, 1.0f32, true),
    ];
    let mut sources = SceneSources::from_files(&files)?;
    eprintln!("sources: {} files", sources.source_count());

    let frame0 = sources.frame(0, 0.0);
    match &frame0 {
        Some(f) => {
            let r = f.as_raw();
            let max = r.iter().max().unwrap_or(&0);
            eprintln!("frame0 from source 0 at t=0: {}x{}, max pixel={}", f.width(), f.height(), max);
        }
        None => eprintln!("frame0 from source 0 at t=0: None!"),
    }

    let frame1 = sources.frame(1, 0.0);
    match &frame1 {
        Some(f) => {
            let r = f.as_raw();
            let max = r.iter().max().unwrap_or(&0);
            eprintln!("frame1 from source 1 at t=0: {}x{}, max pixel={}", f.width(), f.height(), max);
        }
        None => eprintln!("frame1 from source 1 at t=0: None!"),
    }

    // Python wave grid layout: side panels with wavy edges overlapping center
    let mut p0 = PanelDef::new(0);
    p0.shape = ShapeSpec::Wave { num_waves: 1.0, amplitude: 0.02, direction: "right".into() };
    p0.position = Some((0.15, 0.5));
    p0.size = Some((0.55, 1.0));
    p0.anchor = "center".into();
    p0.resize_mode = "fill".into();
    let mut p1 = PanelDef::new(1);
    p1.position = Some((0.5, 0.5));
    p1.size = Some((0.70, 1.0));
    p1.anchor = "center".into();
    p1.resize_mode = "fill".into();
    p1.z_index = -1;
    let mut p2 = PanelDef::new(0);
    p2.shape = ShapeSpec::Wave { num_waves: 1.0, amplitude: 0.02, direction: "left".into() };
    p2.position = Some((0.85, 0.5));
    p2.size = Some((0.55, 1.0));
    p2.anchor = "center".into();
    p2.resize_mode = "fill".into();
    let scene = GridScene::new(vec![p0, p1, p2], 1, 3, 15.0);

    let frame = scene.render_frame(0.0, (1920, 1080), &mut sources, 30.0);
    let raw = frame.as_raw();
    let max = raw.iter().max().unwrap_or(&0);
    eprintln!("grid frame at t=0: {}x{}, max pixel={}", frame.width(), frame.height(), max);

    let total = 30;
    let mut sink = VideoSink::create("/tmp/grid_test.mp4", 30.0, 1920, 1080, "libx264")?;
    let start = std::time::Instant::now();
    let mut frame_times = Vec::with_capacity(total);
    for i in 0..total {
        let t = i as f32 / 30.0;
        let t0 = std::time::Instant::now();
        let f = scene.render_frame(t, (1920, 1080), &mut sources, 30.0);
        let render_us = t0.elapsed().as_micros();
        let t1 = std::time::Instant::now();
        sink.write_frame(&f)?;
        let write_us = t1.elapsed().as_micros();
        frame_times.push((render_us, write_us));
        let elapsed = start.elapsed().as_secs_f64();
        let pct = ((i + 1) as f64 / total as f64) * 100.0;
        let eta = if i > 0 { elapsed / (i + 1) as f64 * (total - i - 1) as f64 } else { 0.0 };
        eprint!("\r  [{:3.0}%] frame {}/{} render={}ms write={}ms  {:5.1}s elapsed ~{:5.1}s remaining  ",
            pct, i + 1, total, render_us / 1000, write_us / 1000, elapsed, eta);
    }
    let total_elapsed = start.elapsed().as_secs_f64();
    let avg_render: u128 = frame_times.iter().map(|(r, _)| r).sum::<u128>() / total as u128;
    let avg_write: u128 = frame_times.iter().map(|(_, w)| w).sum::<u128>() / total as u128;
    eprintln!("\r  [100%] {:.1}s total | avg render={}ms write={}ms                         ",
        total_elapsed, avg_render / 1000, avg_write / 1000);
    sink.finish()?;
    eprintln!("Written /tmp/grid_test.mp4  ({:.1}s)", total_elapsed);
    Ok(())
}
