use anyhow::Result;
use ocv_core::audio::detect_beats;
use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use serde_json::json;
use std::collections::HashSet;

use crate::config::{BeatEffectCfg, ChanceEffect, default_config};
use crate::metadata::{AudioMeta, VideoData};
use crate::plan::{ClipSpec, EditPlan, EffectSpec, PanelSpec, SceneSpec, TransitionSpec};
use crate::select::{
    EffectCtx, EffectPoint, GridCtx, PointKind, select_effects, select_grid, select_transition,
};

#[derive(Debug, Clone)]
pub struct GenArgs {
    pub duration: Option<f32>,
    pub resize_mode: String,
    pub min_beat_gap: f32,
    pub grid_chance: f32,
    pub transition_chance: f32,
    pub random_cursor: bool,
    pub no_align: bool,
    pub min_speed: f32,
    pub max_speed: f32,
    pub grid_tag: Option<String>,
    pub seed: Option<u64>,
    pub audio_path: String,
    /// Videos carrying this tag keep their original source audio; all others
    /// are rendered silent (their background music still plays if set). Every
    /// tagged video is forced into the plan (deduplicated by file) so all of
    /// their audio clips appear; the render duration is extended if too short.
    pub keep_audio_tag: Option<String>,
    /// Use the metadata-driven selectors (grid/effects/transitions). When a
    /// selector is disabled, the legacy chance-based logic is used instead.
    pub smart_grid: bool,
    pub smart_effects: bool,
    pub smart_transitions: bool,
}

impl Default for GenArgs {
    fn default() -> Self {
        GenArgs {
            duration: None,
            resize_mode: "fit".into(),
            min_beat_gap: 0.18,
            grid_chance: 0.5,
            transition_chance: 0.7,
            random_cursor: true,
            no_align: false,
            min_speed: 0.85,
            max_speed: 1.25,
            grid_tag: None,
            seed: None,
            audio_path: String::new(),
            keep_audio_tag: None,
            smart_grid: true,
            smart_effects: true,
            smart_transitions: true,
        }
    }
}

fn eff(effect_type: &str, start_time: f32, duration: f32, params: serde_json::Value) -> EffectSpec {
    EffectSpec {
        effect_type: effect_type.into(),
        params,
        start_time: Some(start_time),
        duration: Some(duration as f64),
        easing: None,
    }
}

/// Add a gentle default zoom effect to a clip that has no effects, so no
/// clip is completely static.
fn ensure_base_effect(out: &mut Vec<EffectSpec>, dur: f32) {
    if out.is_empty() && dur > 0.1 {
        out.push(eff(
            "ZoomEffect", 0.0, dur,
            json!({"start_zoom":1.0,"end_zoom":1.03,"easing":"ease_in_out"}),
        ));
    }
}

fn apply_common_beat_effects(out: &mut Vec<EffectSpec>, cfg: &BeatEffectCfg, beats: &[(f32, f32)], rng: &mut StdRng) {
    for (_, local_t) in beats {
        out.push(eff(
            "ZoomEffect",
            *local_t,
            cfg.zoom.duration,
            json!({"start_zoom": cfg.zoom.start_zoom, "end_zoom": cfg.zoom.end_zoom, "easing": "ease_out"}),
        ));
        let mut triggered: Vec<EffectSpec> = Vec::new();
        if let Some(ztp) = &cfg.zoom_to_point {
            if rng.gen::<f32>() < ztp.chance {
                let cx = ztp.params.get("center_x").copied().unwrap_or(0.5);
                let cy = ztp.params.get("center_y").copied().unwrap_or(0.5);
                let sz = ztp.params.get("start_zoom").copied().unwrap_or(1.05);
                let ez = ztp.params.get("end_zoom").copied().unwrap_or(1.15);
                triggered.push(eff(
                    "ZoomToPoint",
                    *local_t,
                    ztp.duration,
                    json!({"center": [cx, cy], "start_zoom": sz, "end_zoom": ez, "easing": "ease_in_out"}),
                ));
            }
        }
        if let Some(kb) = &cfg.ken_burns {
            if rng.gen::<f32>() < kb.chance {
                triggered.push(eff("KenBurnsEffect", *local_t, kb.duration, json!(kb.params)));
            }
        }
        if let Some(ye) = &cfg.yolo_emission {
            if rng.gen::<f32>() < ye.chance {
                let p = &ye.params;
                triggered.push(eff(
                    "YoloEmissionEffect",
                    *local_t,
                    ye.duration,
                    json!({
                        "inner_color": [p.get("inner_color_r").copied().unwrap_or(180.0) as u8, p.get("inner_color_g").copied().unwrap_or(220.0) as u8, p.get("inner_color_b").copied().unwrap_or(255.0) as u8],
                        "outer_color": [p.get("outer_color_r").copied().unwrap_or(30.0) as u8, p.get("outer_color_g").copied().unwrap_or(80.0) as u8, p.get("outer_color_b").copied().unwrap_or(255.0) as u8],
                        "inner_radius": p.get("inner_radius").copied().unwrap_or(0.042),
                        "outer_radius": p.get("outer_radius").copied().unwrap_or(0.142),
                        "intensity": p.get("intensity").copied().unwrap_or(0.8),
                        "pulse_speed": p.get("pulse_speed").copied().unwrap_or(2.5),
                        "pulse_amplitude": p.get("pulse_amplitude").copied().unwrap_or(0.15),
                        "easing": "ease_in_out",
                    }),
                ));
            }
        }
        if let Some(rs) = &cfg.rgb_shift {
            if rng.gen::<f32>() < rs.chance {
                triggered.push(eff(
                    "RGBShiftEffect",
                    *local_t,
                    rs.duration,
                    json!({"start_shift": rs.params.get("start_shift").copied().unwrap_or(0.083), "end_shift": rs.params.get("end_shift").copied().unwrap_or(0.0), "angle": 0.0, "easing": "linear"}),
                ));
            }
        }
        let max = cfg.max_common_panel as usize;
        if triggered.len() > max {
            triggered.shuffle(rng);
            triggered.truncate(max);
        }
        out.extend(triggered);
    }
}

fn add_pulse_effects(out: &mut Vec<EffectSpec>, cfg: &BeatEffectCfg, clip_start: f32, clip_end: f32, detected: &[f32]) {
    let amp = cfg.beat_bounce.amplitude;
    for &bt in detected {
        if bt > clip_start && bt < clip_end {
            let local_t = bt - clip_start;
            out.push(eff("BounceEffect", local_t, 0.12, json!({"amplitude": amp, "easing": "linear"})));
        }
    }
}

fn apply_panel_effects(out: &mut Vec<EffectSpec>, cfg: &BeatEffectCfg, beats: &[(f32, f32)], rng: &mut StdRng) {
    for (_, local_t) in beats {
        let mut triggered: Vec<EffectSpec> = Vec::new();
        if let Some(ps) = &cfg.panel_slide {
            if rng.gen::<f32>() < ps.chance {
                let dir = if rng.gen::<bool>() { "left" } else { "right" };
                triggered.push(eff("PanelSlideEffect", *local_t, ps.duration, json!({"direction": dir, "start_offset": 1.0, "end_offset": 0.0, "easing": "ease_out"})));
            }
        }
        if let Some(pp) = &cfg.panel_pulse {
            if rng.gen::<f32>() < pp.chance {
                triggered.push(eff("PanelPulseEffect", *local_t, pp.duration, json!({"start_scale": 1.0, "pulse_scale": 1.12, "end_scale": 1.0, "easing": "ease_out"})));
            }
        }
        if let Some(pb) = &cfg.panel_bounce {
            if rng.gen::<f32>() < pb.chance {
                let dir = if rng.gen::<bool>() { "up" } else { "down" };
                triggered.push(eff("PanelBounceEffect", *local_t, pb.duration, json!({"direction": dir, "amplitude": 0.06, "easing": "ease_out"})));
            }
        }
        if let Some(pn) = &cfg.panel_spin {
            if rng.gen::<f32>() < pn.chance {
                triggered.push(eff("PanelSpinEffect", *local_t, pn.duration, json!({"max_angle": 3.0, "easing": "ease_out"})));
            }
        }
        let max = cfg.max_common_panel as usize;
        if triggered.len() > max {
            triggered.shuffle(rng);
            triggered.truncate(max);
        }
        out.extend(triggered);
    }
}

fn apply_grid_frame_effects(out: &mut Vec<EffectSpec>, cfg: &BeatEffectCfg, beats: &[(f32, f32)], rng: &mut StdRng) {
    let grid_efx: &[(Option<&ChanceEffect>, &str, serde_json::Value)] = &[
        (cfg.grid_scan.as_ref(), "GridScanEffect", json!({"num_bars": 240.0, "bar_speed": 0.8, "bar_width": 0.05, "easing": "linear"})),
        (cfg.grid_flash.as_ref(), "GridFlashEffect", json!({"intensity": 0.4, "easing": "linear"})),
        (cfg.grid_glitch.as_ref(), "GridGlitchEffect", json!({"intensity": 0.8, "easing": "linear"})),
        (cfg.grid_wave.as_ref(), "GridWaveWarpEffect", json!({"frequency": 20.0, "amplitude": 0.03, "speed": 5.0, "easing": "linear"})),
        (cfg.grid_pixelate.as_ref(), "GridPixelateEffect", json!({"max_pixels": 400.0, "min_pixels": 25.0, "easing": "linear"})),
        (cfg.grid_chromatic.as_ref(), "GridChromaticEffect", json!({"intensity": 1.0, "angle": 0.0, "easing": "linear"})),
    ];
    for (_, local_t) in beats {
        let mut triggered: Vec<EffectSpec> = Vec::new();
        for (ce, typ, params) in grid_efx {
            if let Some(c) = ce {
                if rng.gen::<f32>() < c.chance {
                    triggered.push(eff(typ, *local_t, c.duration, params.clone()));
                }
            }
        }
        let max = cfg.max_grid_frame as usize;
        if triggered.len() > max {
            triggered.shuffle(rng);
            triggered.truncate(max);
        }
        out.extend(triggered);
    }
}

fn make_transition_body(cfg: &crate::config::TransitionsCfg, rng: &mut StdRng, t_type: &str, beat_gap: f32) -> TransitionSpec {
    let duration = (beat_gap * 0.3).clamp(cfg.min_duration, cfg.max_duration);
    let params = match t_type {
        "zoom" => json!({"mode": cfg.zoom_modes.choose(rng).cloned().unwrap_or("in".into()), "easing": "ease_in_out"}),
        "slide" => json!({"direction": cfg.slide_directions.choose(rng).cloned().unwrap_or("up".into()), "easing": "ease_in_out"}),
        "grid_wipe" => json!({"cols": cfg.grid_wipe_cols, "rows": cfg.grid_wipe_rows, "stagger": cfg.stagger_choices.choose(rng).cloned().unwrap_or("row".into()), "easing": "ease_in_out"}),
        "flash" => json!({"color": cfg.flash_color, "flash_point": 0.35, "easing": "ease_in_out"}),
        "radial_wipe" => json!({"origin": [0.5, 0.5], "easing": "ease_in_out"}),
        "zoom_in" => json!({"max_zoom": 5.0, "blur_peak": 3.0, "easing": "ease_in_out"}),
        _ => json!({}),
    };
    TransitionSpec {
        transition_type: t_type.to_string(),
        params,
        duration,
        easing: None,
    }
}

fn make_transition(
    cfg: &crate::config::TransitionsCfg,
    args: &GenArgs,
    rng: &mut StdRng,
    last_type: Option<&str>,
    is_grid_transition: bool,
    beat_gap: f32,
) -> Option<TransitionSpec> {
    if rng.gen::<f32>() >= args.transition_chance {
        return None;
    }

    // weighted selection with repeat avoidance and grid-awareness
    let total_weight: f32 = cfg.types.iter().enumerate().map(|(i, t)| {
        let mut w = cfg.types_weights.get(i).copied().unwrap_or(0.1);
        if last_type == Some(t.as_str()) {
            w = 0.0;
        }
        if is_grid_transition {
            match t.as_str() {
                "grid_wipe" => w *= 3.0,
                "flash" => w *= 2.0,
                _ => {}
            }
        }
        w.max(0.0)
    }).sum();

    let chosen = if total_weight <= 0.0 {
        // fallback: use original weights when all were zeroed (single type)
        cfg.types.choose_weighted(rng, |item| {
            cfg.types.iter().position(|x| x == item)
                .and_then(|i| cfg.types_weights.get(i))
                .copied()
                .unwrap_or(0.1)
        }).cloned().unwrap_or_else(|_| "zoom".into())
    } else {
        let mut roll = rng.gen::<f32>() * total_weight;
        let mut chosen = "zoom";
        for (i, t) in cfg.types.iter().enumerate() {
            let mut w = cfg.types_weights.get(i).copied().unwrap_or(0.1);
            if last_type == Some(t.as_str()) {
                w = 0.0;
            }
            if is_grid_transition {
                match t.as_str() {
                    "grid_wipe" => w *= 3.0,
                    "flash" => w *= 2.0,
                    _ => {}
                }
            }
            if roll < w {
                chosen = t;
                break;
            }
            roll -= w;
        }
        chosen.to_string()
    };

    Some(make_transition_body(cfg, rng, &chosen, beat_gap))
}

/// Number of distinct clips usable as grid side panels for `v_seg`: excludes
/// the main clip and, when `grid_tag` is set, clips carrying that tag (they
/// are reserved for the main panel).
fn count_side_candidates(videos: &[VideoData], v_seg: &VideoData, grid_tag: Option<&str>) -> usize {
    videos
        .iter()
        .filter(|v| v.file != v_seg.file)
        .filter(|v| match grid_tag {
            Some(gt) => !v.tags.iter().any(|t| t == gt),
            None => v.tags.iter().all(|t| !v_seg.tags.contains(t)),
        })
        .count()
}

/// `suggestedtrans` of the audio segment covering global time `t` (falls back
/// to the first segment without an interval).
fn suggested_transitions_for(audio_meta: &AudioMeta, t: f32) -> Vec<String> {
    let mut no_interval: Vec<String> = Vec::new();
    for seg in &audio_meta.segments {
        match seg.interval {
            Some([s, e]) => {
                if t >= s && t < e {
                    return seg.suggestedtrans.clone();
                }
            }
            None => {
                if no_interval.is_empty() {
                    no_interval = seg.suggestedtrans.clone();
                }
            }
        }
    }
    no_interval
}

/// Build the metadata *points* that drive the smart effect selector for one
/// clip: audio minor beats (subtle), major beats (strong), plus the selected
/// video's actpoints (action) and peakpoints (climax) projected onto the clip's
/// local timeline. `video_to_local` maps a source video time to clip-local time.
fn smart_effect_points(
    filtered: &[f32],
    majors: &[f32],
    interval_start: f32,
    interval_end: f32,
    baseline: f32,
    v_seg: &VideoData,
    v_lo: f32,
    v_hi: f32,
    video_to_local: impl Fn(f32) -> f32,
) -> Vec<EffectPoint> {
    let mut pts = Vec::new();
    for &m in filtered {
        if m > interval_start && m < interval_end {
            pts.push(EffectPoint { local_t: m - baseline, kind: PointKind::Minor });
        }
    }
    for &m in majors {
        if m > interval_start && m < interval_end {
            pts.push(EffectPoint { local_t: m - baseline, kind: PointKind::Major });
        }
    }
    for &a in &v_seg.actpoints {
        if a >= v_lo && a <= v_hi {
            pts.push(EffectPoint { local_t: video_to_local(a), kind: PointKind::Act });
        }
    }
    for &p in &v_seg.peakpoints {
        if p >= v_lo && p <= v_hi {
            pts.push(EffectPoint { local_t: video_to_local(p), kind: PointKind::Peak });
        }
    }
    pts
}

/// Mirrors `generate_edit_plan(args)` from `utils/auto_editor.py`.
pub fn generate_edit_plan(
    audio_meta: &AudioMeta,
    videos: &[VideoData],
    args: &GenArgs,
) -> Result<EditPlan> {
    let cfg = default_config();
    let mut rng = match args.seed {
        Some(s) => StdRng::seed_from_u64(s),
        None => StdRng::seed_from_u64(rand::random()),
    };

    let detected_beats = detect_beats(&args.audio_path).unwrap_or_else(|_| Vec::new());

    let mut major_beats: Vec<f32> = Vec::new();
    let mut minor_beats: Vec<f32> = Vec::new();
    for seg in &audio_meta.segments {
        major_beats.extend(seg.major.iter().copied());
        minor_beats.extend(seg.minor.iter().copied());
    }
    major_beats.sort_by(|a, b| a.partial_cmp(b).unwrap());
    major_beats.dedup();
    minor_beats.sort_by(|a, b| a.partial_cmp(b).unwrap());
    minor_beats.dedup();

    let audio_total_dur = audio_meta.duration.unwrap_or(0.0);
    if major_beats.is_empty() {
        let mut t = 2.0;
        while t < audio_total_dur - 1.0 {
            major_beats.push(t);
            t += 2.0;
        }
    }
    let mut all_beats = vec![0.0, audio_total_dur];
    all_beats.extend(major_beats.iter().copied());
    all_beats.sort_by(|a, b| a.partial_cmp(b).unwrap());
    all_beats.dedup();
    let mut max_clips = all_beats.len() - 1;
    if let Some(d) = args.duration {
        for (i, b) in all_beats.iter().enumerate() {
            if *b >= d {
                max_clips = (i).max(1);
                break;
            }
        }
    }

    if videos.is_empty() {
        anyhow::bail!("no video segments provided");
    }
    let videos_with_acts: Vec<&VideoData> = videos.iter().filter(|v| v.actpoints.len() >= 2).collect();
    let act_pool: Vec<&VideoData> = if videos_with_acts.is_empty() {
        videos.iter().collect()
    } else {
        videos_with_acts
    };

    let mut plan = EditPlan {
        scenes: Vec::new(),
        global_effects: Vec::new(),
        metadata: None,
        audio_path: Some(args.audio_path.clone()),
    };

    // lyrics -> global text effects
    if let Ok(lyrics_text) = std::fs::read_to_string(&cfg.lyrics.file) {
        let lyrics = parse_lrc(&lyrics_text);
        for (i, lyr) in lyrics.iter().enumerate() {
            let lyr_dur = if i + 1 < lyrics.len() {
                (lyrics[i + 1].time - lyr.time).min(cfg.lyrics.max_duration)
            } else {
                cfg.lyrics.max_duration
            }
            .max(0.3);
            plan.global_effects.push(eff(
                "YoloTextEffect",
                lyr.time,
                lyr_dur,
                json!({
                    "text": lyr.text,
                    "font_path": cfg.lyrics.font_path,
                    "font_size": cfg.lyrics.font_size,
                    "position": cfg.lyrics.position,
                    "color": cfg.lyrics.color,
                    "opacity": cfg.lyrics.opacity,
                    "stroke_width": cfg.lyrics.stroke_width,
                    "stroke_color": cfg.lyrics.stroke_color,
                    "depth_composite": cfg.lyrics.depth_composite,
                    "transition_in": cfg.lyrics.transition_in,
                    "transition_out": cfg.lyrics.transition_out,
                    "animate_in": cfg.lyrics.animate_in,
                    "animate_out": cfg.lyrics.animate_out,
                }),
            ));
        }
    }

    let mut idx = 0usize;
    let mut last_v_file: Option<String> = None;
    let mut last_transition_type: Option<String> = None;
    let mut last_is_grid = false;
    let mut last_action: Option<Vec<String>> = None;
    let mut last_camera: Option<Vec<String>> = None;

    // Videos tagged with `keep_audio_tag`. Every tagged video is forced into
    // the plan (deduplicated by file) so all of their original audio clips are
    // present in the render, and the plan is extended if the requested duration
    // is too short to fit them.
    let tagged_unique: Vec<&VideoData> = match args.keep_audio_tag.as_ref() {
        Some(tag) => {
            let mut seen: HashSet<&str> = HashSet::new();
            videos
                .iter()
                .filter(|v| v.tags.iter().any(|t| t == tag) && seen.insert(v.file.as_str()))
                .collect()
        }
        None => Vec::new(),
    };
    let needed = tagged_unique.len();
    let mut tagged_remaining: Vec<&VideoData> = tagged_unique.clone();
    tagged_remaining.shuffle(&mut rng);

    // Extend the plan to fit every tagged clip. With one forced scene per
    // tagged video (span=1 while `tagged_remaining` is non-empty), we need at
    // least `needed` scene slots, so raise the cap and the effective duration
    // when the requested duration can't hold them all.
    if needed > 0 && needed >= max_clips {
        max_clips = needed.min(all_beats.len() - 1);
    }
    let mut eff_duration = args.duration;
    if needed > 0 {
        if let Some(d) = eff_duration {
            if let Some(b) = all_beats.get(needed.min(all_beats.len() - 1)) {
                if d < *b {
                    eff_duration = Some(*b);
                }
            }
        }
    }

    while idx < max_clips {
        // One slot per tagged video while any remain, so every tagged clip is
        // guaranteed a scene; then resume weighted random span selection.
        let span = if !tagged_remaining.is_empty() {
            1
        } else {
            cfg
            .span_weights
            .spans
            .choose_weighted(&mut rng, |item| {
                let i = cfg.span_weights.spans.iter().position(|x| x == item).unwrap_or(0);
                cfg.span_weights.weights.get(i).copied().unwrap_or(1.0)
            })
            .copied()
            .unwrap_or(1)
        };
        let end_idx = (idx + span as usize).min(max_clips);
        let t_m1 = all_beats[idx];
        let t_m2 = all_beats[end_idx];
        let out_dur = if let Some(d) = eff_duration {
            (t_m2 - t_m1).min(d - t_m1)
        } else {
            t_m2 - t_m1
        };
        if out_dur < 0.1 {
            idx = end_idx;
            continue;
        }
        let minors: Vec<f32> = minor_beats.iter().copied().filter(|b| *b > t_m1 && *b < (t_m1 + out_dur)).collect();
        let mut filtered: Vec<f32> = Vec::new();
        let mut last_t = t_m1;
        for b in &minors {
            if b - last_t >= args.min_beat_gap {
                filtered.push(*b);
                last_t = *b;
            }
        }
        if let Some(last) = filtered.last() {
            if t_m2 - *last < args.min_beat_gap {
                filtered.pop();
            }
        }
        let audio_points = {
            let mut v = vec![t_m1];
            v.extend(filtered.iter().copied());
            v
        };
        let n_audio = audio_points.len();
        let scene_end = t_m1 + out_dur;
        let pre_dur = audio_points[0] - t_m1;
        let post_dur = scene_end - audio_points[n_audio - 1];

        let use_align = !args.no_align && n_audio >= 2;
        let majors_in: Vec<f32> = major_beats.iter().copied().filter(|b| *b > t_m1 && *b < (t_m1 + out_dur)).collect();
        let minor_density = if out_dur > 0.0 { minors.len() as f32 / out_dur } else { 0.0 };

        // candidate selection
        let mut candidates: Vec<&VideoData> = if use_align {
            act_pool.iter().filter(|v| v.actpoints.len() >= n_audio).copied().collect()
        } else {
            videos.iter().collect()
        };
        if candidates.is_empty() {
            candidates = act_pool.clone();
        }
        // Force each tagged video into the plan in turn: while any remain, the
        // candidate set is just the remaining tagged pool, so a tagged clip is
        // selected and consumed each iteration.
        if !tagged_remaining.is_empty() {
            candidates = tagged_remaining.clone();
        }
        if candidates.len() > 1 {
            if let Some(lv) = &last_v_file {
                let varied: Vec<&VideoData> = candidates.iter().copied().filter(|v| &v.file != lv).collect();
                if !varied.is_empty() {
                    candidates = varied;
                }
            }
        }
        let mut v_seg = *candidates.choose(&mut rng).unwrap();
        let mut v_file = v_seg.file.clone();
        // Consume the selected tagged video so it appears in the plan exactly once.
        if !tagged_remaining.is_empty() {
            tagged_remaining.retain(|v| v.file != v_file);
        }

        // --- smart grid decision (metadata-driven) ---
        let mut grid_panel_count = 3usize;
        let mut is_grid = if args.smart_grid {
            let side_candidates = count_side_candidates(videos, v_seg, args.grid_tag.as_deref());
            let gc = select_grid(
                &cfg.smart.grid,
                &GridCtx { minor_density, v_seg, side_candidates },
                &mut rng,
            );
            grid_panel_count = gc.panel_count.max(1);
            gc.is_grid
        } else {
            rng.gen::<f32>() < args.grid_chance
        };
        if is_grid {
            // When a grid tag is configured, the main panel must carry it.
            if let Some(gt) = &args.grid_tag {
                if !v_seg.tags.iter().any(|t| t == gt) {
                    let tagged_cands: Vec<&VideoData> =
                        videos.iter().filter(|v| v.tags.iter().any(|t| t == gt)).collect();
                    if tagged_cands.is_empty() {
                        is_grid = false;
                    } else {
                        v_seg = *tagged_cands.choose(&mut rng).unwrap();
                        v_file = v_seg.file.clone();
                    }
                }
            }
            if count_side_candidates(videos, v_seg, args.grid_tag.as_deref()) == 0 {
                is_grid = false;
            }
        }

        let v_acts = &v_seg.actpoints;
        // Keep original source audio only for videos tagged with the configured
        // keep-audio tag (e.g. "sex"). All other clips render silent — their
        // background music (audio_path) still plays if configured.
        let keep_audio = args
            .keep_audio_tag
            .as_ref()
            .map(|t| v_seg.tags.iter().any(|tag| tag == t))
            .unwrap_or(false);
        last_v_file = Some(v_file.clone());

        let alignment_mode = if use_align && v_acts.len() >= 2 && n_audio >= 2 {
            let choices = ["cc", "dtw"];
            *choices.choose(&mut rng).unwrap_or(&"cc")
        } else {
            "none"
        };

        let beat_gap = t_m2 - t_m1;
        let is_grid_transition = last_is_grid || is_grid;
        let cut_on_major = major_beats.iter().any(|b| (b - t_m2).abs() < 0.15);
        let cut_on_action_change = last_action.as_ref().is_some_and(|a| a != &v_seg.action)
            || last_camera.as_ref().is_some_and(|c| c != &v_seg.camera);
        let suggested = suggested_transitions_for(audio_meta, t_m1);
        let trans_data = if args.smart_transitions {
            select_transition(
                &cfg.transitions,
                &cfg.smart.transitions,
                &suggested,
                is_grid_transition,
                cut_on_major,
                cut_on_action_change,
                last_transition_type.as_deref(),
                args.transition_chance,
                beat_gap,
                &mut rng,
            )
        } else {
            make_transition(&cfg.transitions, args, &mut rng, last_transition_type.as_deref(), is_grid_transition, beat_gap)
        };
        let trans_dur = trans_data.as_ref().map(|t| t.duration).unwrap_or(0.0);
        if let Some(ref tr) = trans_data {
            last_transition_type = Some(tr.transition_type.clone());
        }
        last_is_grid = is_grid;
        last_action = Some(v_seg.action.clone());
        last_camera = Some(v_seg.camera.clone());

        let mut clips: Vec<ClipSpec> = Vec::new();
        let mut side_effects: Vec<EffectSpec> = Vec::new();
        let mut s_seg: Option<&VideoData> = None;
        let mut s_seg2: Option<&VideoData> = None;
        let mut s_start = 0.0f32;
        let mut s2_start = 0.0f32;
        // Randomised start time for the grid main video (when random_cursor is on).
        let mut grid_v_start = v_seg.interval[0];

        if is_grid {
            let c_iv = v_seg.interval;
            let c_max = (c_iv[1] - out_dur).max(c_iv[0]);
            grid_v_start = if args.random_cursor && c_max > c_iv[0] {
                rng.gen_range(c_iv[0]..c_max)
            } else {
                c_iv[0]
            };
            // side panel selection (avoid shared tags)
            let mut side_cands: Vec<&VideoData> = videos.iter().filter(|v| v.file != v_file).collect();
            if let Some(gt) = &args.grid_tag {
                side_cands.retain(|v| !v.tags.contains(gt));
            } else {
                side_cands.retain(|v| v.tags.iter().all(|t| !v_seg.tags.contains(t)));
            }
            if side_cands.is_empty() {
                side_cands = videos.iter().filter(|v| v.file != v_file).collect();
            }
            if side_cands.is_empty() {
                side_cands = videos.iter().collect();
            }
            side_cands.shuffle(&mut rng);
            s_seg = side_cands.first().copied();
            // A 4-panel layout needs two distinct side clips.
            if grid_panel_count >= 4 {
                s_seg2 = side_cands.get(1).copied().filter(|v| v.file != s_seg.unwrap().file);
            }
            if let Some(sg) = s_seg {
                let s_iv = sg.interval;
                let s_max = (s_iv[1] - out_dur).max(s_iv[0]);
                s_start = if args.random_cursor && s_max > s_iv[0] {
                    rng.gen_range(s_iv[0]..s_max)
                } else {
                    s_iv[0]
                };
            }
            if let Some(sg) = s_seg2 {
                let s_iv = sg.interval;
                let s_max = (s_iv[1] - out_dur).max(s_iv[0]);
                s2_start = if args.random_cursor && s_max > s_iv[0] {
                    rng.gen_range(s_iv[0]..s_max)
                } else {
                    s_iv[0]
                };
            }
            // color grade on side
            let roll = rng.gen::<f32>();
            let gc = &cfg.grid.color_grade_chances;
            let desat = *gc.get("desaturated").unwrap_or(&0.0);
            let warm = desat + *gc.get("warm").unwrap_or(&0.0);
            let cool = warm + *gc.get("cool").unwrap_or(&0.0);
            let params = if roll < desat {
                grade_params(&cfg.grid.desaturated_params)
            } else if roll < warm {
                grade_params(&cfg.grid.warm_params)
            } else if roll < cool {
                grade_params(&cfg.grid.cool_params)
            } else {
                json!({})
            };
            if params != json!({}) {
                side_effects.push(eff("ColorAdjustEffect", 0.0, out_dur + trans_dur, params));
            }
        }

        // Panel builder honoring layout variety (grid_panel_count): the main
        // video always sits at panel index 1, mirror panels reuse a side panel.
        let make_grid = |v_start: f32, v_spd: f32, vf: &str| -> Vec<PanelSpec> {
            let s_file = s_seg.map(|s| s.file.as_str()).unwrap_or(vf);
            let side = |file: &str, start: f32, flip: Option<i32>, ref_idx: Option<usize>| PanelSpec {
                frame: file.to_string(),
                span: 1,
                start_time: start,
                flip,
                speed: 1.0,
                loop_: false,
                effects: side_effects.clone(),
                blend: "normal".into(),
                shape: None,
                yolo: false,
                feature: false,
                beat_tracking: false,
                border_radius: 0.0,
                border_width: 0.0,
                border_color: None,
                mask_dir: None,
                ref_panel_idx: ref_idx,
            };
            let center = PanelSpec {
                frame: vf.to_string(),
                span: 1,
                start_time: v_start,
                flip: None,
                speed: v_spd,
                loop_: false,
                effects: Vec::new(),
                blend: "normal".into(),
                shape: None,
                yolo: false,
                feature: false,
                beat_tracking: false,
                border_radius: 0.0,
                border_width: 0.0,
                border_color: None,
                mask_dir: None,
                ref_panel_idx: None,
            };
            let mut panels = vec![side(s_file, s_start, None, None), center];
            match grid_panel_count {
                2 => {}
                3 => panels.push(side(s_file, s_start, Some(1), Some(0))),
                _ => {
                    let s2f = s_seg2.map(|s| s.file.as_str()).unwrap_or(s_file);
                    panels.push(side(s2f, s2_start, None, None));
                    panels.push(side(s_file, s_start, Some(1), Some(0)));
                }
            }
            panels
        };

        if alignment_mode == "cc" {
            let v_dur = v_acts[v_acts.len() - 1] - v_acts[0];
            let a_dur = audio_points[n_audio - 1] - audio_points[0];
            let speed = if a_dur > 0.0 {
                (v_dur / a_dur).clamp(args.min_speed, args.max_speed)
            } else {
                1.0
            };
            if pre_dur > 0.02 {
                let lo = if is_grid { grid_v_start } else { v_seg.interval[0] };
                let v_pre = (v_acts[0] - pre_dur).max(lo);
                let apd = v_acts[0] - v_pre;
                if apd > 0.02 {
                    let mut c = ClipSpec {
                        frame: v_file.clone(),
                        span: 1,
                        start_time: v_pre,
                        duration: Some(apd),
                        trans_dur: 0.0,
                        is_grid,
                        panels: Vec::new(),
                        effects: Vec::new(),
                        transition: None,
                        speed: 1.0,
                        keep_audio,
                        resize_mode: args.resize_mode.clone(),
                        mask_dir: None,
                    };
                    if is_grid {
                        c.panels = make_grid(v_pre, 1.0, &v_file);
                    }
                    ensure_base_effect(&mut c.effects, apd);
                    clips.push(c);
                }
            }
            let mut aligned = ClipSpec {
                frame: v_file.clone(),
                span: 1,
                start_time: v_acts[0],
                duration: Some(a_dur),
                trans_dur: if post_dur <= 0.02 { trans_dur } else { 0.0 },
                is_grid,
                panels: Vec::new(),
                effects: Vec::new(),
                transition: None,
                speed,
                keep_audio,
                resize_mode: args.resize_mode.clone(),
                mask_dir: None,
            };
            if is_grid {
                let v0 = if args.random_cursor { grid_v_start } else { v_acts[0] };
                aligned.panels = make_grid(v0, speed, &v_file);
                if args.smart_effects {
                    let pts = smart_effect_points(
                        &filtered, &majors_in,
                        audio_points[0], audio_points[0] + a_dur, audio_points[0],
                        v_seg, v_acts[0], v_acts[v_acts.len() - 1],
                        |vp| (vp - v_acts[0]) * a_dur / v_dur.max(0.001),
                    );
                    let ctx = EffectCtx { is_grid: true, action: &v_seg.action, camera: &v_seg.camera, focus: &v_seg.focus };
                    let sel = select_effects(&cfg.smart.effects, &ctx, &pts, &mut rng);
                    aligned.panels.get_mut(1).unwrap().effects.extend(sel.panel);
                    aligned.effects.extend(sel.frame);
                } else {
                    let beats: Vec<(f32, f32)> = filtered.iter().map(|mb| (*mb, *mb - audio_points[0])).collect();
                    let center = aligned.panels.get_mut(1).unwrap();
                    apply_common_beat_effects(&mut center.effects, &cfg.beat_effects.cc, &beats, &mut rng);
                    apply_panel_effects(&mut center.effects, &cfg.beat_effects.cc, &beats, &mut rng);
                    apply_grid_frame_effects(&mut aligned.effects, &cfg.beat_effects.cc, &beats, &mut rng);
                    add_pulse_effects(&mut aligned.effects, &cfg.beat_effects.cc, audio_points[0], audio_points[0] + a_dur, &detected_beats);
                }
            } else if args.smart_effects {
                let pts = smart_effect_points(
                    &filtered, &majors_in,
                    audio_points[0], audio_points[0] + a_dur, audio_points[0],
                    v_seg, v_acts[0], v_acts[v_acts.len() - 1],
                    |vp| (vp - v_acts[0]) * a_dur / v_dur.max(0.001),
                );
                let ctx = EffectCtx { is_grid: false, action: &v_seg.action, camera: &v_seg.camera, focus: &v_seg.focus };
                let sel = select_effects(&cfg.smart.effects, &ctx, &pts, &mut rng);
                aligned.effects.extend(sel.panel);
            } else {
                let beats: Vec<(f32, f32)> = filtered.iter().map(|mb| (*mb, *mb - audio_points[0])).collect();
                apply_common_beat_effects(&mut aligned.effects, &cfg.beat_effects.cc, &beats, &mut rng);
                add_pulse_effects(&mut aligned.effects, &cfg.beat_effects.cc, audio_points[0], audio_points[0] + a_dur, &detected_beats);
            }
            ensure_base_effect(&mut aligned.effects, a_dur);
            clips.push(aligned);
            if post_dur > 0.02 {
                let v_post = v_acts[v_acts.len() - 1];
                let v_post_end = (v_post + post_dur).min(v_seg.interval[1]);
                let apd = v_post_end - v_post;
                if apd > 0.02 {
                    let mut c = ClipSpec {
                        frame: v_file.clone(),
                        span: 1,
                        start_time: v_post,
                        duration: Some(apd),
                        trans_dur,
                        is_grid,
                        panels: Vec::new(),
                        effects: Vec::new(),
                        transition: trans_data.clone(),
                        speed: 1.0,
                        keep_audio,
                        resize_mode: args.resize_mode.clone(),
                        mask_dir: None,
                    };
                    if is_grid {
                        c.panels = make_grid(v_post, 1.0, &v_file);
                    }
                    ensure_base_effect(&mut c.effects, apd);
                    clips.push(c);
                }
            }
        } else {
            let v_start = if args.random_cursor {
                let (lo, hi) = (v_seg.interval[0], (v_seg.interval[1] - out_dur).max(v_seg.interval[0]));
                if hi > lo { rng.gen_range(lo..hi) } else { v_seg.interval[0] }
            } else {
                v_seg.interval[0]
            };
            let mut c = ClipSpec {
                frame: v_file.clone(),
                span: 1,
                start_time: v_start,
                duration: Some(out_dur),
                trans_dur,
                is_grid,
                panels: Vec::new(),
                effects: Vec::new(),
                transition: trans_data.clone(),
                speed: 1.0,
                keep_audio,
                resize_mode: args.resize_mode.clone(),
                mask_dir: None,
            };
            if is_grid {
                c.panels = make_grid(v_start, 1.0, &v_file);
                if args.smart_effects {
                    let pts = smart_effect_points(
                        &filtered, &majors_in,
                        t_m1, t_m1 + out_dur, t_m1,
                        v_seg, v_start, v_start + out_dur,
                        |vp| vp - v_start,
                    );
                    let ctx = EffectCtx { is_grid: true, action: &v_seg.action, camera: &v_seg.camera, focus: &v_seg.focus };
                    let sel = select_effects(&cfg.smart.effects, &ctx, &pts, &mut rng);
                    c.panels.get_mut(1).unwrap().effects.extend(sel.panel);
                    c.effects.extend(sel.frame);
                } else {
                    let beats: Vec<(f32, f32)> = filtered.iter().map(|mb| (*mb, *mb - t_m1)).collect();
                    let center = c.panels.get_mut(1).unwrap();
                    apply_common_beat_effects(&mut center.effects, &cfg.beat_effects.grid, &beats, &mut rng);
                    apply_panel_effects(&mut center.effects, &cfg.beat_effects.grid, &beats, &mut rng);
                    apply_grid_frame_effects(&mut c.effects, &cfg.beat_effects.grid, &beats, &mut rng);
                    add_pulse_effects(&mut c.effects, &cfg.beat_effects.grid, t_m1, t_m1 + out_dur, &detected_beats);
                }
            } else if args.smart_effects {
                let pts = smart_effect_points(
                    &filtered, &majors_in,
                    t_m1, t_m1 + out_dur, t_m1,
                    v_seg, v_start, v_start + out_dur,
                    |vp| vp - v_start,
                );
                let ctx = EffectCtx { is_grid: false, action: &v_seg.action, camera: &v_seg.camera, focus: &v_seg.focus };
                let sel = select_effects(&cfg.smart.effects, &ctx, &pts, &mut rng);
                c.effects.extend(sel.panel);
            } else {
                let beats: Vec<(f32, f32)> = filtered.iter().map(|mb| (*mb, *mb - t_m1)).collect();
                apply_common_beat_effects(&mut c.effects, &cfg.beat_effects.single, &beats, &mut rng);
                add_pulse_effects(&mut c.effects, &cfg.beat_effects.single, t_m1, t_m1 + out_dur, &detected_beats);
            }
            ensure_base_effect(&mut c.effects, out_dur);
            clips.push(c);
        }

        plan.scenes.push(SceneSpec {
            name: format!("scene_{idx}"),
            clips,
        });
        idx = end_idx;
    }

    Ok(plan)
}

fn grade_params(p: &crate::config::ColorParams) -> serde_json::Value {
    json!({"saturation": p.saturation, "brightness": p.brightness, "contrast": p.contrast, "gamma": 1.0})
}

struct Lyric {
    time: f32,
    text: String,
}

fn parse_lrc(text: &str) -> Vec<Lyric> {
    let mut out = Vec::new();
    for line in text.lines() {
        if let Some(pos) = line.find(']') {
            let tc = &line[1..pos];
            let t = parse_timecode_simple(tc);
            let txt = line[pos + 1..].trim().to_string();
            if !txt.is_empty() {
                out.push(Lyric { time: t, text: txt });
            }
        }
    }
    out
}

fn parse_timecode_simple(tc: &str) -> f32 {
    let parts: Vec<&str> = tc.split(':').collect();
    let mut s = 0.0f32;
    for p in &parts {
        s = s * 60.0 + p.parse::<f32>().unwrap_or(0.0);
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    use ocv_core::pipeline::VideoPipeline;
    use crate::apply::apply_edit_plan;
    use crate::plan::{ClipSpec, EditPlan, PanelSpec, SceneSpec};

    #[test]
    fn apply_handwritten_plan() {
        let plan = EditPlan {
            scenes: vec![SceneSpec {
                name: "s".into(),
                clips: vec![
                    ClipSpec {
                        frame: "a.mp4".into(),
                        span: 1,
                        start_time: 0.0,
                        duration: Some(2.0),
                        trans_dur: 0.2,
                        is_grid: false,
                        panels: vec![],
                        effects: vec![EffectSpec {
                            effect_type: "ZoomEffect".into(),
                            params: json!({"start_zoom":1.0,"end_zoom":1.1,"easing":"ease_out"}),
                            start_time: Some(0.0), duration: Some(2.0), easing: None,
                        }],
                        transition: None,
                        speed: 1.0, keep_audio: false, resize_mode: "fill".into(), mask_dir: None,
                    },
                    ClipSpec {
                        frame: "b.mp4".into(),
                        span: 1,
                        start_time: 2.0,
                        duration: Some(2.0),
                        trans_dur: 0.0,
                        is_grid: true,
                        panels: vec![
                            PanelSpec { frame: "b.mp4".into(), span:1, start_time:0.0, flip:None, speed:1.0, loop_:false, effects:vec![], blend:"normal".into(), shape:None, yolo:false, feature:false, beat_tracking:false, border_radius:0.0, border_width:0.0, border_color:None, mask_dir:None, ref_panel_idx: None },
                            PanelSpec { frame: "c.mp4".into(), span:1, start_time:0.0, flip:None, speed:1.0, loop_:false, effects:vec![], blend:"normal".into(), shape:None, yolo:false, feature:false, beat_tracking:false, border_radius:0.0, border_width:0.0, border_color:None, mask_dir:None, ref_panel_idx: None },
                        ],
                        effects: vec![EffectSpec {
                            effect_type: "GridFlashEffect".into(),
                            params: json!({"intensity":0.4}),
                            start_time: Some(0.0), duration: Some(0.2), easing: None,
                        }],
                        transition: Some(TransitionSpec {
                            transition_type: "zoom".into(),
                            params: json!({"mode":"in"}),
                            duration: 0.2, easing: None,
                        }), speed: 1.0, keep_audio: false, resize_mode: "fill".into(), mask_dir: None,
                    },
                ],
            }],
            global_effects: vec![],
            metadata: None,
            audio_path: None,
        };
        let mut pipe = VideoPipeline::new(60.0, (1920, 1080), "fill");
        apply_edit_plan(&mut pipe, &plan).unwrap();
        assert_eq!(pipe.clips.len(), 2);
        // first clip has an effect + transition; second is a grid scene
        match &pipe.clips[0] {
            ocv_core::pipeline::ClipItem::File { effects, .. } => assert_eq!(effects.len(), 1),
            _ => panic!("expected file clip"),
        }
        assert!(pipe.transitions[1].is_some());
        assert!(pipe.transitions[0].is_none());
        match &pipe.clips[1] {
            ocv_core::pipeline::ClipItem::Grid { .. } => {}
            _ => panic!("expected grid clip"),
        }
    }
}
