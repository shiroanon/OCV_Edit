//! Metadata-driven selectors for the auto-editor.
//!
//! The three selectors here replace the flat random rolls in `generate.rs`:
//!
//! * `select_grid` — decides **whether** a scene is a grid and **how many
//!   panels** it has, from audio beat density + the chosen video's metadata
//!   (`camera`/`action`/`focus`/`peakpoints`) and side-candidate availability.
//! * `select_transition` — prefers the audio segment's `suggestedtrans`, then
//!   weights the transition palette by grid context, major-beat cuts and
//!   action/camera changes.
//! * `select_effects` — picks from the full core palette per metadata *point*
//!   (major/minor audio beats, video actpoints/peakpoints), weighted by the
//!   point kind, its strength, and the clip's video metadata.
//!
//! All selection is weight-adjusted randomness: the metadata steers the
//! seeded RNG, so output stays reproducible per `--seed` while varying run to
//! run.

use rand::seq::SliceRandom;
use rand::Rng;
use rand::rngs::StdRng;
use serde_json::json;

use crate::config::{EffectSelectorCfg, GridSelectorCfg, TransitionsCfg, TransitionSmartCfg};
use crate::metadata::VideoData;
use crate::plan::{EffectSpec, TransitionSpec};

// ─────────────────────────── grid selector ───────────────────────────

pub struct GridCtx<'a> {
    /// Minor beats/second within the scene interval (audio rhythm density).
    pub minor_density: f32,
    pub v_seg: &'a VideoData,
    /// Number of distinct clips usable as side panels (excludes the main clip
    /// and, when `grid_tag` is set, the tagged videos used for the main panel).
    pub side_candidates: usize,
}

pub struct GridChoice {
    pub is_grid: bool,
    pub panel_count: usize,
}

/// Camera metadata → grid affinity. Full/static framing reads well in a grid;
/// nothing is strongly penalized.
fn camera_affinity(cam: &[String]) -> f32 {
    if cam.is_empty() {
        0.0
    } else {
        0.2
    }
}

/// Action metadata → grid affinity. Rhythmic/energetic actions suit a grid;
/// intimate/static ones are better highlighted full-screen.
fn action_affinity(act: &[String]) -> f32 {
    let mut a = 0.0f32;
    for x in act {
        match x.as_str() {
            "dance" | "twerk" | "jump" | "posing" | "walking" => a = a.max(0.6),
            "sex" | "blowjob" | "vaginal" | "licking" | "assjob" => a = a.max(-0.5),
            _ => {}
        }
    }
    a
}

/// Focus metadata → grid affinity. "full" body suits a grid; close focus
/// (face/ass/boobs/legs) is a subject highlight best shown full-screen.
fn focus_affinity(foc: &[String]) -> f32 {
    let mut a = 0.0f32;
    for x in foc {
        match x.as_str() {
            "full" => a = a.max(0.4),
            "ass" | "boobs" | "face" | "booty" | "legs" => a = a.max(-0.5),
            _ => {}
        }
    }
    a
}

pub fn select_grid(cfg: &GridSelectorCfg, ctx: &GridCtx, rng: &mut StdRng) -> GridChoice {
    // A grid needs at least one distinct side clip.
    if ctx.side_candidates == 0 {
        return GridChoice { is_grid: false, panel_count: 0 };
    }

    let dnorm = (ctx.minor_density / cfg.density_hi).clamp(0.0, 1.0);
    let affinity = dnorm * cfg.density_w
        + camera_affinity(&ctx.v_seg.camera) * cfg.camera_w
        + action_affinity(&ctx.v_seg.action) * cfg.action_w
        + focus_affinity(&ctx.v_seg.focus) * cfg.focus_w
        - if ctx.v_seg.peakpoints.is_empty() { 0.0 } else { cfg.peak_penalty };
    let chance =
        (cfg.base_chance + affinity * cfg.affinity_scale).clamp(cfg.chance_lo, cfg.chance_hi);
    if rng.gen::<f32>() >= chance {
        return GridChoice { is_grid: false, panel_count: 0 };
    }

    // Layout variety: denser beats -> more side panels. Main video stays at
    // panel index 1 (the auto-render keeps panel 1's audio by convention).
    let extra = (ctx.minor_density / cfg.min_density_panels).floor() as usize
        * cfg.panels_per_density;
    let mut panels = cfg.min_panels + extra.min(cfg.max_panels - cfg.min_panels);
    // Mirror reuses a side panel, so we need (panels - 2) distinct side clips.
    let sides_needed = panels.saturating_sub(2);
    if ctx.side_candidates < sides_needed {
        panels = (ctx.side_candidates + 2).clamp(cfg.min_panels, cfg.max_panels);
    }
    GridChoice { is_grid: true, panel_count: panels.max(cfg.min_panels) }
}

// ─────────────────────── transition selector ───────────────────────

/// Map an annotator transition name (e.g. "slideup") to a known transition
/// type plus an optional slide-direction override.
fn map_suggested(s: &str) -> Option<(&'static str, Option<&'static str>)> {
    let t = s.trim().to_ascii_lowercase().replace('-', "_");
    match t.as_str() {
        "slideup" => Some(("slide", Some("up"))),
        "slidedown" => Some(("slide", Some("down"))),
        "slideleft" => Some(("slide", Some("left"))),
        "slideright" => Some(("slide", Some("right"))),
        "slide" => Some(("slide", None)),
        "zoom" | "zoomin" | "zoomout" => Some(("zoom", None)),
        "grid_wipe" | "gridwipe" | "grid" => Some(("grid_wipe", None)),
        "flash" => Some(("flash", None)),
        "radial_wipe" | "radial" => Some(("radial_wipe", None)),
        "zoom_in" => Some(("zoom_in", None)),
        _ => None,
    }
}

fn build_transition_body(
    cfg: &TransitionsCfg,
    rng: &mut StdRng,
    t_type: &str,
    beat_gap: f32,
    dir: Option<&str>,
) -> TransitionSpec {
    let duration = (beat_gap * 0.3).clamp(cfg.min_duration, cfg.max_duration);
    let params = match t_type {
        "zoom" => json!({"mode": cfg.zoom_modes.choose(rng).cloned().unwrap_or("in".into()), "easing": "ease_in_out"}),
        "slide" => json!({
            "direction": dir.map(|d| d.to_string())
                .or_else(|| cfg.slide_directions.choose(rng).cloned())
                .unwrap_or("up".into()),
            "easing": "ease_in_out"
        }),
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

pub fn select_transition(
    trans_cfg: &TransitionsCfg,
    smart: &TransitionSmartCfg,
    suggested: &[String],
    is_grid_transition: bool,
    cut_on_major: bool,
    cut_on_action_change: bool,
    last_type: Option<&str>,
    chance: f32,
    beat_gap: f32,
    rng: &mut StdRng,
) -> Option<TransitionSpec> {
    if rng.gen::<f32>() >= chance {
        return None;
    }

    // 1) Honor the annotator's suggested transitions for this audio segment.
    if !suggested.is_empty() && rng.gen::<f32>() < smart.suggested_priority {
        let mut pool: Vec<String> = Vec::new();
        for s in suggested {
            if let Some((ty, _)) = map_suggested(s) {
                if last_type != Some(ty) && !pool.contains(&ty.to_string()) {
                    pool.push(ty.to_string());
                }
            }
        }
        if !pool.is_empty() {
            let ty = pool.choose(rng).unwrap();
            let dir = suggested
                .iter()
                .find_map(|s| {
                    let (mty, dir) = map_suggested(s)?;
                    if mty == ty {
                        Some(dir)
                    } else {
                        None
                    }
                })
                .flatten();
            return Some(build_transition_body(trans_cfg, rng, ty, beat_gap, dir));
        }
    }

    // 2) Weighted selection with metadata boosts.
    let weights: Vec<f32> = trans_cfg
        .types
        .iter()
        .enumerate()
        .map(|(i, t)| {
            let mut w = trans_cfg.types_weights.get(i).copied().unwrap_or(0.1);
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
            if cut_on_major {
                for (bty, b) in &smart.major_beat_boost {
                    if bty == t {
                        w *= *b;
                    }
                }
            }
            if cut_on_action_change {
                for (bty, b) in &smart.action_change_boost {
                    if bty == t {
                        w *= *b;
                    }
                }
            }
            w.max(0.0)
        })
        .collect();

    let total: f32 = weights.iter().sum();
    let chosen = if total <= 0.0 {
        // fallback when everything was zeroed (e.g. single-type repeated)
        trans_cfg
            .types
            .choose_weighted(rng, |item| {
                trans_cfg
                    .types
                    .iter()
                    .position(|x| x == item)
                    .and_then(|i| trans_cfg.types_weights.get(i))
                    .copied()
                    .unwrap_or(0.1)
            })
            .cloned()
            .unwrap_or_else(|_| "zoom".into())
    } else {
        let mut roll = rng.gen::<f32>() * total;
        let mut chosen = "zoom".to_string();
        for (i, t) in trans_cfg.types.iter().enumerate() {
            if roll < weights[i] {
                chosen = t.clone();
                break;
            }
            roll -= weights[i];
        }
        chosen
    };
    Some(build_transition_body(trans_cfg, rng, &chosen, beat_gap, None))
}

// ───────────────────────── effect selector ─────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PointKind {
    /// Major audio beat (strong).
    Major = 0,
    /// Minor audio beat (subtle).
    Minor = 1,
    /// Video action point.
    Act = 2,
    /// Video peak/climax point.
    Peak = 3,
}

#[derive(Debug, Clone)]
pub struct EffectPoint {
    /// Local time within the clip.
    pub local_t: f32,
    pub kind: PointKind,
}

pub struct EffectCtx<'a> {
    pub is_grid: bool,
    pub action: &'a [String],
    pub camera: &'a [String],
    pub focus: &'a [String],
}

pub struct EffectSelection {
    /// Effects applied to the center panel of a grid (or the clip itself for
    /// single clips).
    pub panel: Vec<EffectSpec>,
    /// Grid-wide frame effects (grid scenes only).
    pub frame: Vec<EffectSpec>,
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

/// Metadata-aware multiplier applied to an effect's weight. Ties effect choice
/// to the point kind and to the video's action/camera/focus tags.
fn metadata_modifier(ctx: &EffectCtx, t: &str, kind: PointKind) -> f32 {
    let act_has = |k: &str| ctx.action.iter().any(|a| a == k);
    match t {
        "FlipEffect" => {
            if act_has("transition") && kind == PointKind::Act {
                6.0
            } else {
                0.0
            }
        }
        "BlurEffect" => match kind {
            PointKind::Peak => 4.0,
            PointKind::Major | PointKind::Act => 1.0,
            PointKind::Minor => 0.5,
        },
        "GlowEffect" => match kind {
            PointKind::Peak | PointKind::Major => 2.0,
            _ => 0.4,
        },
        "RGBShiftEffect" => match kind {
            PointKind::Major | PointKind::Act | PointKind::Peak => 1.6,
            PointKind::Minor => 0.5,
        },
        "ZoomToPoint" => match kind {
            PointKind::Act | PointKind::Major | PointKind::Peak => 1.6,
            PointKind::Minor => 0.7,
        },
        "GridGlitchEffect" | "GridChromaticEffect" | "GridWaveWarpEffect" => match kind {
            PointKind::Major | PointKind::Act | PointKind::Peak => 1.6,
            PointKind::Minor => 0.6,
        },
        "GridFlashEffect" => match kind {
            PointKind::Major | PointKind::Peak => 2.2,
            _ => 0.7,
        },
        "GridScanEffect" => 0.7,
        _ => 1.0,
    }
}

/// Map a focus tag to a normalized focal center (used by zoom/ken-burns).
fn focal_center(focus: &[String]) -> [f32; 2] {
    for x in focus {
        match x.as_str() {
            "ass" | "booty" | "legs" => return [0.5, 0.75],
            "face" => return [0.5, 0.3],
            "boobs" => return [0.5, 0.55],
            _ => {}
        }
    }
    [0.5, 0.5]
}

fn build_effect(
    t: &str,
    t0: f32,
    kind: PointKind,
    strength: f32,
    ctx: &EffectCtx,
    rng: &mut StdRng,
) -> Option<EffectSpec> {
    let base = match kind {
        PointKind::Peak => 0.4,
        PointKind::Major => 0.3,
        _ => 0.2,
    };
    let dur = base * (0.8 + 0.4 * strength);
    let center = focal_center(ctx.focus);
    match t {
        "ZoomToPoint" => Some(eff(
            "ZoomToPoint",
            t0,
            dur,
            json!({"center": center, "start_zoom": 1.0, "end_zoom": 1.15 + 0.1 * strength, "easing": "ease_out"}),
        )),
        "KenBurnsEffect" => Some(eff(
            "KenBurnsEffect",
            t0,
            0.8,
            json!({"center": center, "zoom_out": 1.06, "zoom_in": 1.18, "drift_x": 0.012, "drift_y": 0.008, "easing": "linear"}),
        )),
        "BounceEffect" => Some(eff(
            "BounceEffect",
            t0,
            0.12,
            json!({"amplitude": 1.06 + 0.1 * strength, "easing": "linear"}),
        )),
        "RGBShiftEffect" => Some(eff(
            "RGBShiftEffect",
            t0,
            dur,
            json!({"start_shift": 0.05 + 0.05 * strength, "end_shift": 0.0, "angle": 0.0, "easing": "linear"}),
        )),
        "BlurEffect" => Some(eff(
            "BlurEffect",
            t0,
            dur,
            json!({"start_sigma": 0.0, "end_sigma": 2.0 * strength, "easing": "ease_out"}),
        )),
        "FlipEffect" => {
            let mode = if rng.gen::<bool>() { "h" } else { "v" };
            Some(eff("FlipEffect", t0, dur, json!({"mode": mode})))
        }
        "GlowEffect" => Some(eff(
            "YoloGlowSegEffect",
            t0,
            dur,
            json!({"outer_color": [30, 80, 255], "outer_radius": 0.14, "intensity": 0.6 + 0.3 * strength}),
        )),
        "PanelSlideEffect" => {
            let dir = if rng.gen::<bool>() { "left" } else { "right" };
            Some(eff("PanelSlideEffect", t0, dur, json!({"direction": dir, "start_offset": 1.0, "end_offset": 0.0, "easing": "ease_out"})))
        }
        "PanelPulseEffect" => Some(eff(
            "PanelPulseEffect",
            t0,
            dur,
            json!({"start_scale": 1.0, "pulse_scale": 1.12, "end_scale": 1.0, "easing": "ease_out"}),
        )),
        "PanelBounceEffect" => {
            let dir = if rng.gen::<bool>() { "up" } else { "down" };
            Some(eff("PanelBounceEffect", t0, dur, json!({"direction": dir, "amplitude": 0.06, "easing": "ease_out"})))
        }
        "PanelSpinEffect" => Some(eff("PanelSpinEffect", t0, dur, json!({"max_angle": 3.0, "easing": "ease_out"}))),
        "GridScanEffect" => Some(eff("GridScanEffect", t0, dur, json!({"num_bars": 240.0, "bar_speed": 0.8, "bar_width": 0.05, "easing": "linear"}))),
        "GridFlashEffect" => Some(eff("GridFlashEffect", t0, dur, json!({"intensity": 0.3 + 0.2 * strength, "easing": "linear"}))),
        "GridGlitchEffect" => Some(eff("GridGlitchEffect", t0, dur, json!({"intensity": 0.6 + 0.3 * strength, "easing": "linear"}))),
        "GridWaveWarpEffect" => Some(eff("GridWaveWarpEffect", t0, dur, json!({"frequency": 20.0, "amplitude": 0.03, "speed": 5.0, "easing": "linear"}))),
        "GridPixelateEffect" => Some(eff("GridPixelateEffect", t0, dur, json!({"max_pixels": 400.0, "min_pixels": 25.0, "easing": "linear"}))),
        "GridChromaticEffect" => Some(eff("GridChromaticEffect", t0, dur, json!({"intensity": 1.0, "angle": 0.0, "easing": "linear"}))),
        _ => None,
    }
}

fn pick_up_to(
    pool: &mut Vec<(String, f32)>,
    max: usize,
    rng: &mut StdRng,
) -> Vec<(String, f32)> {
    let mut picked = Vec::new();
    for _ in 0..max {
        if pool.is_empty() {
            break;
        }
        let total: f32 = pool.iter().map(|(_, w)| w).sum();
        if total <= 0.0 {
            break;
        }
        let mut roll = rng.gen::<f32>() * total;
        let mut chosen = 0usize;
        for (i, (_, w)) in pool.iter().enumerate() {
            if roll < *w {
                chosen = i;
                break;
            }
            roll -= *w;
        }
        picked.push(pool.remove(chosen));
    }
    picked
}

pub fn select_effects(
    cfg: &EffectSelectorCfg,
    ctx: &EffectCtx,
    points: &[EffectPoint],
    rng: &mut StdRng,
) -> EffectSelection {
    let mut panel: Vec<EffectSpec> = Vec::new();
    let mut frame: Vec<EffectSpec> = Vec::new();
    let strength = |k: PointKind| -> f32 { cfg.strengths[k as usize] };

    // Fire effects in temporal order and never more often than `min_gap` apart.
    // Points arrive grouped by kind (all minors, then majors, then acts/peaks),
    // so sorting by local time is required for a meaningful cooldown.
    let mut sorted: Vec<&EffectPoint> = points.iter().collect();
    sorted.sort_by(|a, b| a.local_t.total_cmp(&b.local_t));
    let mut last_t = f32::NEG_INFINITY;

    for pt in sorted {
        if pt.local_t - last_t < cfg.min_gap {
            continue;
        }
        last_t = pt.local_t;
        let s = strength(pt.kind);
        let mut panel_pool: Vec<(String, f32)> = Vec::new();
        for (t, w) in &cfg.single {
            let w = w * s * metadata_modifier(ctx, t, pt.kind);
            if w > 0.01 {
                panel_pool.push((t.clone(), w));
            }
        }
        if ctx.is_grid {
            for (t, w) in &cfg.grid_panel {
                let w = w * s * metadata_modifier(ctx, t, pt.kind);
                if w > 0.01 {
                    panel_pool.push((t.clone(), w));
                }
            }
            let mut frame_pool: Vec<(String, f32)> = Vec::new();
            for (t, w) in &cfg.grid_frame {
                let w = w * s * metadata_modifier(ctx, t, pt.kind);
                if w > 0.01 {
                    frame_pool.push((t.clone(), w));
                }
            }
            for (t, _w) in pick_up_to(&mut frame_pool, cfg.max_per_point, rng) {
                if let Some(spec) = build_effect(&t, pt.local_t, pt.kind, s, ctx, rng) {
                    frame.push(spec);
                }
            }
        }
        for (t, _w) in pick_up_to(&mut panel_pool, cfg.max_per_point, rng) {
            if let Some(spec) = build_effect(&t, pt.local_t, pt.kind, s, ctx, rng) {
                panel.push(spec);
            }
        }
    }
    EffectSelection { panel, frame }
}
