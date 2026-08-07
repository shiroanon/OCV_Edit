use ocv_core::effect::{Effect, Transition};
use ocv_core::frame::{resize_frame, VideoSink, VideoSource};
use std::path::{Path, PathBuf};

pub fn test_clip_path(name: &str) -> PathBuf {
    let manifest =
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR must be set (cargo sets it)");
    Path::new(&manifest).join("../../..").join(name)
}

pub fn output_dir() -> PathBuf {
    let dir = PathBuf::from("/tmp/ocv_test_outputs");
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// Render an effect over `num_frames` from a clip, write output video.
///
/// `expect_change`: if true, asserts the mid-effect frame differs from source;
/// if false, asserts they are identical (mask-consuming effect with NoMask).
/// Mid-frame is used (progress ≈ 0.5) rather than start (progress=0, no effect)
/// or end (progress=1, some effects return to identity).
pub fn render_effect(
    effect: &dyn Effect,
    clip: &str,
    output_name: &str,
    num_frames: usize,
    fps: f64,
    output_size: (u32, u32),
    expect_change: bool,
) {
    let clip_path = test_clip_path(clip);
    let mut src =
        VideoSource::open(clip_path.to_str().unwrap()).expect("open video source (ffprobe needed)");

    let mut frames = Vec::with_capacity(num_frames);
    for i in 0..num_frames {
        let local_time = i as f32 / fps as f32;
        let frame = src
            .read_at(local_time as f64)
            .expect("read frame")
            .expect("frame available — clip too short?");
        let frame = resize_frame(&frame, output_size.0, output_size.1, "fill");
        let progress = if num_frames > 1 {
            i as f32 / (num_frames - 1) as f32
        } else {
            1.0
        };
        let result = effect.process(&frame, local_time, progress, i as u64);

        if i == 0 {
            assert_eq!(
                result.dimensions(),
                output_size,
                "output dimensions should match output_size"
            );
        }

        // Assert at mid-frame where effect is strongest
        if i == num_frames / 2 {
            if expect_change {
                assert_ne!(
                    result.as_raw(),
                    frame.as_raw(),
                    "effect should modify pixels (checked at mid-frame)"
                );
            } else {
                assert_eq!(
                    result.as_raw(),
                    frame.as_raw(),
                    "no-op effect should leave pixels unchanged"
                );
            }
        }
        frames.push(result);
    }

    let out_path = output_dir().join(format!("{output_name}.mp4"));
    let mut sink = VideoSink::create(
        out_path.to_str().unwrap(),
        fps,
        output_size.0,
        output_size.1,
        "libx264",
    )
    .expect("create video sink (ffmpeg needed)");
    for f in &frames {
        sink.write_frame(f).expect("write frame");
    }
    sink.finish().expect("finish sink");
    eprintln!("  wrote {output_name}.mp4");
}

/// Render a transition between two clips over `num_frames`, write output video.
///
/// Asserts the last frame of the transition matches the incoming clip (frame2).
pub fn render_transition(
    transition: &dyn Transition,
    clip1: &str,
    clip2: &str,
    output_name: &str,
    num_frames: usize,
    fps: f64,
    output_size: (u32, u32),
) {
    let clip1_path = test_clip_path(clip1);
    let clip2_path = test_clip_path(clip2);
    let mut src1 = VideoSource::open(clip1_path.to_str().unwrap())
        .expect("open video source (ffprobe needed)");
    let mut src2 = VideoSource::open(clip2_path.to_str().unwrap())
        .expect("open video source (ffprobe needed)");

    let mut frames = Vec::with_capacity(num_frames);
    for i in 0..num_frames {
        let local_time = i as f32 / fps as f32;
        let f1 = src1
            .read_at(local_time as f64)
            .expect("read frame")
            .expect("frame available");
        let f2 = src2
            .read_at(local_time as f64)
            .expect("read frame")
            .expect("frame available");
        let f1 = resize_frame(&f1, output_size.0, output_size.1, "fill");
        let f2 = resize_frame(&f2, output_size.0, output_size.1, "fill");
        let progress = if num_frames > 1 {
            i as f32 / (num_frames - 1) as f32
        } else {
            1.0
        };
        let result = transition.process(&f1, &f2, progress);

        assert_eq!(result.dimensions(), output_size);
        if i == num_frames - 1 {
            assert_eq!(
                result.as_raw(),
                f2.as_raw(),
                "transition at progress=1 should match incoming frame"
            );
        }
        frames.push(result);
    }

    let out_path = output_dir().join(format!("{output_name}.mp4"));
    let mut sink = VideoSink::create(
        out_path.to_str().unwrap(),
        fps,
        output_size.0,
        output_size.1,
        "libx264",
    )
    .expect("create video sink (ffmpeg needed)");
    for f in &frames {
        sink.write_frame(f).expect("write frame");
    }
    sink.finish().expect("finish sink");
    eprintln!("  wrote {output_name}.mp4");
}
