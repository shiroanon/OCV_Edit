use std::collections::HashMap;

use anyhow::Result;
use ocv_core::effect::NoMask;
use ocv_core::pipeline::VideoPipeline;
use ocv_core::scene::{GridScene, PanelDef, ShapeSpec, SceneSources};

use crate::effects_map::{deserialize_effect, deserialize_transition};
use crate::plan::{ClipSpec, EditPlan, PanelSpec};

fn grid_dims(n: usize) -> (u32, u32) {
    if n == 0 {
        return (1, 1);
    }
    let n32 = n as u32;
    let sqrt_n = (n32 as f64).sqrt() as u32;
    let mut best = (1u32, n32);
    for cols in sqrt_n.max(1)..=n32 {
        let rows = (n32 + cols - 1) / cols;
        if rows <= cols {
            let waste = rows * cols - n32;
            let (_, best_waste) = best;
            if waste < best_waste || (waste == best_waste && rows < best.0) {
                best = (rows, cols);
            }
        }
    }
    best
}

fn shape_of(s: &str) -> ShapeSpec {
    match s {
        "ellipse" => ShapeSpec::Ellipse,
        "circle" => ShapeSpec::Circle,
        "diamond" => ShapeSpec::Diamond,
        _ => ShapeSpec::Rect,
    }
}

fn wave_shape(direction: &str) -> ShapeSpec {
    ShapeSpec::Wave {
        num_waves: 1.0,
        amplitude: 0.02,
        direction: direction.into(),
    }
}

fn build_panel(panel: &PanelSpec, source_index: usize) -> Result<PanelDef> {
    let mut pd = PanelDef::new(source_index);
    pd.effects = panel
        .effects
        .iter()
        .map(|e| {
            let eff = deserialize_effect(e)?;
            let st = e.start_time.unwrap_or(0.0);
            let dur = e.duration.unwrap_or(-1.0);
            Ok((eff, st, dur))
        })
        .collect::<Result<Vec<_>>>()?;
    pd.blend = panel.blend.clone();
    pd.shape = match panel.shape.as_deref() {
        Some(s) => shape_of(s),
        None => ShapeSpec::Rect,
    };
    pd.loop_ = panel.loop_;
    pd.speed = panel.speed;
    pd.opacity = 1.0;
    pd.start_time = panel.start_time;
    pd.flip = panel.flip;
    pd.loader = Box::new(NoMask);
    Ok(pd)
}

fn apply_wave_grid(panels: &mut [PanelDef]) {
    if panels.len() != 3 {
        return;
    }
    // Match Python auto_editor._apply_wave_grid:
    //   left panel  — wave clip on right edge, peeks into center from left
    //   right panel — wave clip on left edge, peeks into center from right
    //   center panel — behind side panels, fills gap
    panels[0].shape = wave_shape("right");
    panels[0].position = Some((0.15, 0.5));
    panels[0].size = Some((0.55, 1.0));
    panels[0].anchor = "center".into();
    panels[0].resize_mode = "fit".into();
    panels[2].shape = wave_shape("left");
    panels[2].position = Some((0.85, 0.5));
    panels[2].size = Some((0.55, 1.0));
    panels[2].anchor = "center".into();
    panels[2].resize_mode = "fit".into();
    panels[1].position = Some((0.5, 0.5));
    panels[1].size = Some((0.70, 1.0));
    panels[1].anchor = "center".into();
    panels[1].z_index = -1;
    panels[1].resize_mode = "fit".into();
}

fn clip_duration(clip: &ClipSpec) -> f32 {
    clip.duration
        .unwrap_or_else(|| clip.span as f32)
}

/// Resolve the original-audio source for a grid clip.
///
/// The auto-generated wave grids place the main video at panel index 1
/// (`[side, center, mirror]`); that is the panel whose audio should be kept.
/// `files` is the deduplicated source list built in panel order and
/// `si_for_panel[i]` maps panel `i` to its real source index (following
/// `ref_panel_idx`). Returns `None` (silent) when `keep_audio` is false or no
/// usable source exists.
fn grid_audio_source(
    clip: &ClipSpec,
    files: &[(String, f32, f32, bool)],
    si_for_panel: &[usize],
) -> Option<(String, f32, f32)> {
    if !clip.keep_audio || files.is_empty() || si_for_panel.is_empty() {
        return None;
    }
    let idx = if si_for_panel.len() >= 2 { 1 } else { 0 };
    let si = si_for_panel.get(idx).copied().unwrap_or(0);
    let (fp, st, sp, _) = files.get(si)?;
    if fp.is_empty() {
        return None;
    }
    Some((fp.clone(), *st, *sp))
}

fn apply_clip(pipeline: &mut VideoPipeline, clip: &ClipSpec, is_first: bool) -> Result<()> {
    if clip.is_grid && !clip.panels.is_empty() {
        let n = clip.panels.len();
        // Deduplicate file paths: map each unique file to a source index.
        let mut file_to_si: HashMap<&str, usize> = HashMap::new();
        let mut si_for_panel: Vec<usize> = Vec::with_capacity(n);
        let mut files: Vec<(String, f32, f32, bool)> = Vec::new();
        for (_i, panel) in clip.panels.iter().enumerate() {
                let si = match panel.ref_panel_idx {
                    Some(ri) => si_for_panel[ri],
                    None => {
                        let len = file_to_si.len();
                        let si = *file_to_si.entry(panel.frame.as_str()).or_insert(len);
                        if si == len {
                            files.push((panel.frame.clone(), panel.start_time, panel.speed, panel.loop_));
                        }
                        si
                    }
                };
            si_for_panel.push(si);
        }
        let sources = SceneSources::from_files(&files)?;
        eprintln!("  grid files: {:?}", files.iter().map(|f| &f.0).collect::<Vec<_>>());
        eprintln!("  si_for_panel: {:?}", si_for_panel);
        // Build panels with resolved source indices.
        let mut panels: Vec<PanelDef> = clip.panels.iter().zip(si_for_panel.iter())
            .map(|(p, si)| build_panel(p, *si))
            .collect::<Result<Vec<_>>>()?;
        for (i, pd) in panels.iter().enumerate() {
            eprintln!("  panel[{}]: si={} pos={:?} size={:?} z={} anchor={}", i, pd.source_index, pd.position, pd.size, pd.z_index, pd.anchor);
        }
        // Match Python: always 1xN wave grid for 3 panels with [1,2,1] weights, else use grid_dims.
        let (rows, cols, col_weights) = if n == 3 {
            apply_wave_grid(&mut panels);
            (1u32, 3u32, vec![1.0, 2.0, 1.0])
        } else {
            let (r, c) = grid_dims(n);
            (r, c, vec![1.0; c as usize])
        };
        for (i, pd) in panels.iter().enumerate() {
            eprintln!("  AFTER wave: panel[{}]: si={} pos={:?} size={:?} z={} anchor={}", i, pd.source_index, pd.position, pd.size, pd.z_index, pd.anchor);
        }
        let mut scene = GridScene::new(panels, rows, cols, clip_duration(clip));
        scene.col_weights = col_weights;
        for e in &clip.effects {
            let eff = deserialize_effect(e)?;
            scene
                .effects
                .push((eff, e.start_time.unwrap_or(0.0) as f32, e.duration.unwrap_or(-1.0)));
        }
        let audio = grid_audio_source(clip, &files, &si_for_panel);
        pipeline.add_grid_scene(scene, sources, clip_duration(clip), audio);
    } else {
        pipeline.add_clip(
            &clip.frame,
            clip.start_time,
            clip_duration(clip),
            if clip.speed <= 0.0 { 1.0 } else { clip.speed },
            clip.keep_audio,
            &clip.resize_mode,
        );
        let ci = pipeline.clips.len() - 1;
        for e in &clip.effects {
            let eff = deserialize_effect(e)?;
            pipeline.add_clip_effect(
                ci,
                eff,
                e.start_time.unwrap_or(0.0),
                e.duration.unwrap_or(-1.0),
            );
        }
    }
    if !is_first {
        if let Some(tr) = &clip.transition {
            let t = deserialize_transition(tr)?;
            pipeline.add_transition(t, tr.duration);
        }
    }
    Ok(())
}

/// Mirrors `apply_edit_plan(pipeline, plan_data)`.
pub fn apply_edit_plan(pipeline: &mut VideoPipeline, plan: &EditPlan) -> Result<()> {
    let mut first = true;
    for scene in &plan.scenes {
        for clip in &scene.clips {
            apply_clip(pipeline, clip, first)?;
            first = false;
        }
    }
    for ge in &plan.global_effects {
        let eff = deserialize_effect(ge)?;
        pipeline.add_global_effect(
            eff,
            ge.start_time.unwrap_or(0.0),
            ge.duration.unwrap_or(-1.0),
        );
    }
    pipeline.set_background_audio(plan.audio_path.clone());
    Ok(())
}

/// Deep-merge JSON patches into the plan (mirrors `patch_plan`).
pub fn patch_plan(plan: &mut EditPlan, patch: &serde_json::Value) -> Result<()> {
    let mut value = serde_json::to_value(&*plan)?;
    deep_merge(&mut value, patch);
    *plan = serde_json::from_value(value)?;
    Ok(())
}

fn deep_merge(base: &mut serde_json::Value, patch: &serde_json::Value) {
    if let serde_json::Value::Object(b) = base {
        if let serde_json::Value::Object(p) = patch {
            for (k, v) in p {
                deep_merge(b.entry(k.clone()).or_insert(serde_json::Value::Null), v);
            }
            return;
        }
    }
    *base = patch.clone();
}

/// Human-readable summary (mirrors `print_edit_plan`).
pub fn print_edit_plan(plan: &EditPlan) {
    println!("EditPlan: {} scenes", plan.scenes.len());
    for (si, scene) in plan.scenes.iter().enumerate() {
        println!("    [{}] {} ({} clips)", si, scene.name, scene.clips.len());
        for (ci, clip) in scene.clips.iter().enumerate() {
            let kind = if clip.is_grid { format!("grid[{}]", clip.panels.len()) } else { "file".into() };
            println!(
                "      clip#{} {} {} span={} dur={:.2} effects={}",
                ci,
                kind,
                clip.frame,
                clip.span,
                clip_duration(clip),
                clip.effects.len()
            );
        }
    }
    if !plan.global_effects.is_empty() {
        println!("  global_effects: {}", plan.global_effects.len());
    }
}
