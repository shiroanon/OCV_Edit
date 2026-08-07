use clap::Parser;
use ocv_auto::{
    apply_edit_plan, generate_edit_plan, load_audio_metadata, patch_plan, print_edit_plan,
    scan_videos, EditPlan, GenArgs,
};
use ocv_core::pipeline::VideoPipeline;
use std::path::Path;

#[derive(Parser, Debug)]
#[command(author, version, about = "Auto-edit videos by aligning action points to audio beats.")]
struct Args {
    /// Audio file with beat metadata (MP4/M4A with com.shiro.audio atom).
    #[arg(long, default_value = "audios/Yoga [3y21C7r72yw].m4a")]
    audio: String,
    /// Directory of video clips with com.shiro.video metadata atoms.
    #[arg(long, default_value = "videos")]
    videos_dir: String,
    /// Max output duration in seconds.
    #[arg(long)]
    duration: Option<f32>,
    #[arg(long, default_value = "1920")]
    width: u32,
    #[arg(long, default_value = "1080")]
    height: u32,
    #[arg(long, default_value = "60")]
    fps: f64,
    #[arg(long, default_value = "fit")]
    resize_mode: String,
    #[arg(long)]
    random_cursor: bool,
    #[arg(long)]
    no_align: bool,
    #[arg(long, default_value = "0.85")]
    min_speed: f32,
    #[arg(long, default_value = "1.15")]
    max_speed: f32,
    #[arg(long, default_value = "0.18")]
    min_beat_gap: f32,
    #[arg(long, default_value = "0.5")]
    transition_chance: f32,
    #[arg(long, default_value = "0.0")]
    grid_chance: f32,
    #[arg(long)]
    grid_tag: Option<String>,
    /// Keep the source video's original audio only for clips whose video is
    /// tagged with this tag (e.g. "sex"). Others render silent.
    #[arg(long)]
    keep_audio_tag: Option<String>,
    #[arg(long)]
    seed: Option<u64>,
    #[arg(long)]
    save_plan: Option<String>,
    #[arg(long)]
    load_plan: Option<String>,
    #[arg(long)]
    patch_plan: Option<String>,
    #[arg(long)]
    print_only: bool,
    #[arg(long, default_value = "final_auto_edit.mp4")]
    output: String,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let mut plan: EditPlan = if let Some(p) = &args.load_plan {
        eprintln!("Loading plan from {p}...");
        let text = std::fs::read_to_string(p)?;
        serde_json::from_str(&text)?
    } else {
        eprintln!("Loading audio metadata...");
        let audio_meta = load_audio_metadata(&args.audio)?;
        eprintln!("Scanning {} video segments...", &args.videos_dir);
        let videos = scan_videos(&args.videos_dir);
        if videos.is_empty() {
            anyhow::bail!("no video segments found in {}", args.videos_dir);
        }
        eprintln!("Generating edit plan...");
        let gen = GenArgs {
            duration: args.duration,
            resize_mode: args.resize_mode.clone(),
            min_beat_gap: args.min_beat_gap,
            grid_chance: args.grid_chance,
            transition_chance: args.transition_chance,
            random_cursor: args.random_cursor,
            no_align: args.no_align,
            min_speed: args.min_speed,
            max_speed: args.max_speed,
            grid_tag: args.grid_tag.clone(),
            seed: args.seed,
            audio_path: args.audio.clone(),
            keep_audio_tag: args.keep_audio_tag.clone(),
        };
        generate_edit_plan(&audio_meta, &videos, &gen)?
    };

    // Ensure background audio is set even for loaded plans that lack it
    if plan.audio_path.is_none() {
        plan.audio_path = Some(args.audio.clone());
    }

    if let Some(p) = &args.patch_plan {
        let patch_text = std::fs::read_to_string(p).unwrap_or_else(|_| p.clone());
        let patch: serde_json::Value = serde_json::from_str(&patch_text)?;
        patch_plan(&mut plan, &patch)?;
    }

    if let Some(sp) = &args.save_plan {
        std::fs::write(sp, serde_json::to_string_pretty(&plan)?)?;
        println!("saved plan -> {sp}");
    }

    if args.print_only {
        print_edit_plan(&plan);
        return Ok(());
    }

    let mut pipeline = VideoPipeline::new(args.fps, (args.width, args.height), &args.resize_mode);
    apply_edit_plan(&mut pipeline, &plan)?;

    let out = &args.output;
    if let Some(parent) = Path::new(out).parent() {
        if !parent.as_os_str().is_empty() {
            let _ = std::fs::create_dir_all(parent);
        }
    }
    println!("Rendering {} clips -> {out}", pipeline.clips.len());
    let t0 = std::time::Instant::now();
    pipeline.render(out)?;
    println!("Done in {:.1}s -> {out}", t0.elapsed().as_secs_f32());
    Ok(())
}
