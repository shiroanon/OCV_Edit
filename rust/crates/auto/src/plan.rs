use ocv_core::easing::EasingSpec;
use serde::{Deserialize, Serialize};

/// Mirrors the JSON edit plan emitted by `utils/auto_editor.py`.
#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct EditPlan {
    #[serde(default)]
    pub scenes: Vec<SceneSpec>,
    #[serde(default)]
    pub global_effects: Vec<EffectSpec>,
    #[serde(default)]
    pub metadata: Option<serde_json::Value>,
    /// Full background audio track (e.g. the music file) to mux into the
    /// rendered output. Mirrors `plan_data["audio_path"]` in the Python tool.
    #[serde(default, rename = "audio_path")]
    pub audio_path: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SceneSpec {
    pub name: String,
    #[serde(default)]
    pub clips: Vec<ClipSpec>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClipSpec {
    #[serde(rename = "filepath", alias = "frame")]
    pub frame: String,
    #[serde(default = "one_u32")]
    pub span: u32,
    #[serde(default)]
    pub start_time: f32,
    #[serde(default)]
    pub duration: Option<f32>,
    #[serde(default)]
    pub trans_dur: f32,
    #[serde(default)]
    pub is_grid: bool,
    #[serde(default)]
    pub panels: Vec<PanelSpec>,
    #[serde(default)]
    pub effects: Vec<EffectSpec>,
    #[serde(default)]
    pub transition: Option<TransitionSpec>,
    #[serde(default = "one_f32")]
    pub speed: f32,
    #[serde(default)]
    pub keep_audio: bool,
    #[serde(default)]
    pub resize_mode: String,
    #[serde(default)]
    pub mask_dir: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PanelSpec {
    #[serde(rename = "filepath", alias = "frame")]
    pub frame: String,
    #[serde(default = "one_u32")]
    pub span: u32,
    #[serde(default)]
    pub start_time: f32,
    #[serde(default)]
    pub flip: Option<i32>,
    #[serde(default)]
    pub effects: Vec<EffectSpec>,
    #[serde(default)]
    pub blend: String,
    #[serde(default)]
    pub shape: Option<String>,
    #[serde(default)]
    pub yolo: bool,
    #[serde(default)]
    pub feature: bool,
    #[serde(default)]
    pub beat_tracking: bool,
    #[serde(default)]
    pub border_radius: f32,
    #[serde(default)]
    pub border_width: f32,
    #[serde(default)]
    pub border_color: Option<[u8; 3]>,
    #[serde(default = "one_f32")]
    pub speed: f32,
    #[serde(default)]
    pub loop_: bool,
    #[serde(default)]
    pub mask_dir: Option<String>,
    #[serde(default)]
    pub ref_panel_idx: Option<usize>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EffectSpec {
    #[serde(rename = "type")]
    pub effect_type: String,
    #[serde(default)]
    pub params: serde_json::Value,
    #[serde(default)]
    pub start_time: Option<f32>,
    #[serde(default)]
    pub duration: Option<f64>,
    #[serde(default)]
    pub easing: Option<EasingSpec>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TransitionSpec {
    #[serde(rename = "type")]
    pub transition_type: String,
    #[serde(default)]
    pub params: serde_json::Value,
    #[serde(default)]
    pub duration: f32,
    #[serde(default)]
    pub easing: Option<EasingSpec>,
}

fn one_u32() -> u32 {
    1
}
fn one_f32() -> f32 {
    1.0
}
