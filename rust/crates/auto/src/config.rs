//! Rust mirror of `utils/config.py` (subset needed by the plan generator).

#[derive(Debug, Clone)]
pub struct BeatEffectCfg {
    pub zoom: BEffect,
    pub beat_bounce: BounceCfg,
    pub zoom_to_point: Option<ChanceEffect>,
    pub ken_burns: Option<ChanceEffect>,
    pub panel_slide: Option<ChanceEffect>,
    pub panel_pulse: Option<ChanceEffect>,
    pub panel_bounce: Option<ChanceEffect>,
    pub panel_spin: Option<ChanceEffect>,
    pub grid_scan: Option<ChanceEffect>,
    pub grid_flash: Option<ChanceEffect>,
    pub grid_glitch: Option<ChanceEffect>,
    pub grid_wave: Option<ChanceEffect>,
    pub grid_pixelate: Option<ChanceEffect>,
    pub grid_chromatic: Option<ChanceEffect>,
    pub rgb_shift: Option<ChanceEffect>,
    pub yolo_emission: Option<ChanceEffect>,
    pub max_common_panel: u32,
    pub max_grid_frame: u32,
}

#[derive(Debug, Clone)]
pub struct BEffect {
    pub start_zoom: f32,
    pub end_zoom: f32,
    pub duration: f32,
}

#[derive(Debug, Clone)]
pub struct BounceCfg {
    pub amplitude: f32,
    pub duration: f32,
}

#[derive(Debug, Clone)]
pub struct ChanceEffect {
    pub chance: f32,
    pub duration: f32,
    pub params: std::collections::HashMap<String, f64>,
}

pub struct Config {
    pub lyrics: LyricsCfg,
    pub transitions: TransitionsCfg,
    pub grid: GridCfg,
    pub span_weights: SpanWeights,
    pub beat_effects: BeatEffectsCfg,
    /// Metadata-driven smart selector weights (see `select.rs`).
    pub smart: SmartCfg,
}

/// Weights for the metadata-aware grid selector. Grid affinity is computed in
/// `[-1, 1]` from audio beat density + video metadata, then mapped to a
/// probability around `base_chance`.
pub struct GridSelectorCfg {
    pub base_chance: f32,
    /// `clamp(base_chance + affinity * affinity_scale, lo, hi)`.
    pub affinity_scale: f32,
    pub chance_lo: f32,
    pub chance_hi: f32,
    /// Minor beats/second at which density contributes full grid affinity.
    pub density_hi: f32,
    /// Multipliers applied to each normalized signal component.
    pub density_w: f32,
    pub camera_w: f32,
    pub action_w: f32,
    pub focus_w: f32,
    /// Affinity penalty (0..1) applied when the selected video has a peakpoint.
    pub peak_penalty: f32,
    /// Layout variety: panel count bounds, plus the density threshold that adds
    /// an extra side panel.
    pub min_panels: usize,
    pub max_panels: usize,
    pub min_density_panels: f32,
    pub panels_per_density: usize,
}

/// Extra weights for the smart transition selector layered on top of the
/// baseline `TransitionsCfg` types/weights.
pub struct TransitionSmartCfg {
    /// Probability of honoring the audio segment's `suggestedtrans` when set.
    pub suggested_priority: f32,
    /// Weight multipliers applied when the cut lands on a major beat.
    pub major_beat_boost: Vec<(String, f32)>,
    /// Weight multipliers applied when the cut is an action/camera change.
    pub action_change_boost: Vec<(String, f32)>,
}

/// Per-effect base weights for the smart effect selector, split by context.
pub struct EffectSelectorCfg {
    /// Max effects fired on a single point (per clip context).
    pub max_per_point: usize,
    /// Minimum seconds between scheduled effect start times. Points landing
    /// closer than this to the previously scheduled effect are skipped, so
    /// dense minor beats (2-3/sec) don't become a rapid-fire wall of effects.
    pub min_gap: f32,
    /// Intensity multiplier per point kind, order: major, minor, act, peak.
    pub strengths: [f32; 4],
    /// (effect type, base weight) tables.
    pub single: Vec<(String, f32)>,
    pub grid_panel: Vec<(String, f32)>,
    pub grid_frame: Vec<(String, f32)>,
}

pub struct SmartCfg {
    pub grid: GridSelectorCfg,
    pub transitions: TransitionSmartCfg,
    pub effects: EffectSelectorCfg,
}

pub struct LyricsCfg {
    pub file: String,
    pub font_path: String,
    pub font_size: f32,
    pub position: String,
    pub color: [u8; 3],
    pub opacity: f32,
    pub stroke_width: f32,
    pub stroke_color: [u8; 3],
    pub depth_composite: bool,
    pub transition_in: f32,
    pub transition_out: f32,
    pub animate_in: String,
    pub animate_out: String,
    pub max_duration: f32,
}

pub struct TransitionsCfg {
    pub types: Vec<String>,
    pub types_weights: Vec<f32>,
    pub zoom_modes: Vec<String>,
    pub slide_directions: Vec<String>,
    pub stagger_choices: Vec<String>,
    pub duration: f32,
    pub min_duration: f32,
    pub max_duration: f32,
    pub grid_wipe_cols: u32,
    pub grid_wipe_rows: u32,
    pub flash_color: [u8; 3],
}

pub struct GridCfg {
    pub color_grade_chances: std::collections::HashMap<String, f32>,
    pub desaturated_params: ColorParams,
    pub warm_params: ColorParams,
    pub cool_params: ColorParams,
}

#[derive(Clone)]
pub struct ColorParams {
    pub saturation: f32,
    pub brightness: f32,
    pub contrast: f32,
}

pub struct SpanWeights {
    pub spans: Vec<u32>,
    pub weights: Vec<f32>,
}

pub struct BeatEffectsCfg {
    pub grid: BeatEffectCfg,
    pub cc: BeatEffectCfg,
    pub dtw: BeatEffectCfg,
    pub single: BeatEffectCfg,
}

pub fn default_config() -> Config {
    let ce = |chance: f32, duration: f32| ChanceEffect {
        chance,
        duration,
        params: std::collections::HashMap::new(),
    };
    Config {
        lyrics: LyricsCfg {
            file: "lyrics.txt".into(),
            font_path: "Audiowide-Regular.ttf".into(),
            font_size: 0.472,
            position: "top_center".into(),
            color: [255, 255, 255],
            opacity: 1.0,
            stroke_width: 0.0,
            stroke_color: [0, 0, 0],
            depth_composite: true,
            transition_in: 0.0,
            transition_out: 0.0,
            animate_in: "fade".into(),
            animate_out: "fade".into(),
            max_duration: 4.0,
        },
        transitions: TransitionsCfg {
            types: vec![
                "zoom".into(),
                "slide".into(),
                "grid_wipe".into(),
                "flash".into(),
                "radial_wipe".into(),
                "zoom_in".into(),
            ],
            types_weights: vec![0.25, 0.25, 0.15, 0.15, 0.1, 0.1],
            zoom_modes: vec!["in".into(), "out".into()],
            slide_directions: vec!["up".into(), "down".into(), "left".into(), "right".into()],
            duration: 0.2,
            min_duration: 0.15,
            max_duration: 0.35,
            grid_wipe_cols: 6,
            grid_wipe_rows: 4,
            stagger_choices: vec!["row".into(), "col".into()],
            flash_color: [255, 255, 255],
        },
        grid: GridCfg {
            color_grade_chances: {
                let mut m = std::collections::HashMap::new();
                m.insert("desaturated".into(), 0.0);
                m.insert("warm".into(), 0.15);
                m.insert("cool".into(), 0.15);
                m
            },
            desaturated_params: ColorParams {
                saturation: 0.0,
                brightness: -10.0,
                contrast: 1.0,
            },
            warm_params: ColorParams {
                saturation: 1.2,
                brightness: 8.0,
                contrast: 1.05,
            },
            cool_params: ColorParams {
                saturation: 0.8,
                brightness: -8.0,
                contrast: 1.1,
            },
        },
        span_weights: SpanWeights {
            spans: vec![1, 2, 3],
            weights: vec![0.5, 0.4, 0.1],
        },
        smart: SmartCfg {
            grid: GridSelectorCfg {
                base_chance: 0.35,
                affinity_scale: 0.55,
                chance_lo: 0.05,
                chance_hi: 0.9,
                density_hi: 1.5,
                density_w: 1.0,
                camera_w: 0.3,
                action_w: 0.4,
                focus_w: 0.2,
                peak_penalty: 0.8,
                min_panels: 2,
                max_panels: 3,
                min_density_panels: 0.7,
                panels_per_density: 1,
            },
            transitions: TransitionSmartCfg {
                suggested_priority: 0.9,
                major_beat_boost: vec![
                    ("zoom_in".into(), 2.5),
                    ("flash".into(), 2.0),
                    ("radial_wipe".into(), 1.6),
                ],
                action_change_boost: vec![("slide".into(), 2.0), ("zoom".into(), 1.5)],
            },
            effects: EffectSelectorCfg {
                max_per_point: 1,
                min_gap: 0.4,
                strengths: [1.0, 0.6, 0.9, 1.25],
                single: vec![
                    ("ZoomToPoint".into(), 0.5),
                    ("KenBurnsEffect".into(), 0.25),
                    ("BounceEffect".into(), 0.7),
                    ("RGBShiftEffect".into(), 0.8),
                    ("BlurEffect".into(), 0.25),
                    ("FlipEffect".into(), 0.15),
                    ("GlowEffect".into(), 0.15),
                ],
                grid_panel: vec![
                    ("ZoomToPoint".into(), 0.4),
                    ("PanelSlideEffect".into(), 0.6),
                    ("PanelPulseEffect".into(), 0.5),
                    ("PanelBounceEffect".into(), 0.5),
                    ("PanelSpinEffect".into(), 0.3),
                    ("BounceEffect".into(), 0.6),
                    ("RGBShiftEffect".into(), 0.7),
                ],
                grid_frame: vec![
                    ("GridFlashEffect".into(), 0.9),
                    ("GridGlitchEffect".into(), 0.8),
                    ("GridScanEffect".into(), 0.5),
                    ("GridWaveWarpEffect".into(), 0.4),
                    ("GridPixelateEffect".into(), 0.4),
                    ("GridChromaticEffect".into(), 0.5),
                ],
            },
        },
        beat_effects: BeatEffectsCfg {
            grid: BeatEffectCfg {
                zoom: BEffect {
                    start_zoom: 1.03,
                    end_zoom: 1.0,
                    duration: 0.25,
                },
                beat_bounce: BounceCfg {
                    amplitude: 1.15,
                    duration: 0.25,
                },
                zoom_to_point: Some(ChanceEffect {
                    chance: 0.3,
                    duration: 0.35,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_zoom".into(), 1.05);
                        m.insert("end_zoom".into(), 1.15);
                        m.insert("center_x".into(), 0.5);
                        m.insert("center_y".into(), 0.5);
                        m
                    },
                }),
                ken_burns: Some(ce(0.0, 0.8)),
                panel_slide: Some(ChanceEffect {
                    chance: 0.4,
                    duration: 0.3,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("direction".into(), 0.0);
                        m
                    },
                }),
                panel_pulse: Some(ce(0.1, 0.35)),
                panel_bounce: Some(ce(0.35, 0.2)),
                panel_spin: Some(ce(0.25, 0.25)),
                grid_scan: Some(ce(0.2, 0.3)),
                grid_flash: Some(ce(0.3, 0.2)),
                grid_glitch: Some(ce(0.4, 0.25)),
                grid_wave: Some(ce(0.2, 0.35)),
                grid_pixelate: Some(ce(0.2, 0.3)),
                grid_chromatic: Some(ce(0.2, 0.3)),
                rgb_shift: Some(ChanceEffect {
                    chance: 0.7,
                    duration: 0.2,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_shift".into(), 0.083);
                        m.insert("end_shift".into(), 0.0);
                        m
                    },
                }),
                yolo_emission: Some(ChanceEffect {
                    chance: 0.15,
                    duration: 0.6,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("inner_color_r".into(), 180.0);
                        m.insert("inner_color_g".into(), 220.0);
                        m.insert("inner_color_b".into(), 255.0);
                        m.insert("outer_color_r".into(), 30.0);
                        m.insert("outer_color_g".into(), 80.0);
                        m.insert("outer_color_b".into(), 255.0);
                        m.insert("inner_radius".into(), 0.042);
                        m.insert("outer_radius".into(), 0.142);
                        m.insert("intensity".into(), 0.8);
                        m.insert("pulse_speed".into(), 2.5);
                        m.insert("pulse_amplitude".into(), 0.15);
                        m
                    },
                }),
                max_common_panel: 2,
                max_grid_frame: 2,
            },
            cc: BeatEffectCfg {
                zoom: BEffect {
                    start_zoom: 1.03,
                    end_zoom: 1.0,
                    duration: 0.25,
                },
                beat_bounce: BounceCfg {
                    amplitude: 1.15,
                    duration: 0.25,
                },
                zoom_to_point: Some(ChanceEffect {
                    chance: 0.0,
                    duration: 0.4,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_zoom".into(), 1.0);
                        m.insert("end_zoom".into(), 1.6);
                        m
                    },
                }),
                ken_burns: Some(ce(0.0, 0.7)),
                panel_slide: Some(ce(0.4, 0.3)),
                panel_pulse: Some(ce(0.1, 0.35)),
                panel_bounce: Some(ce(0.35, 0.2)),
                panel_spin: Some(ce(0.25, 0.25)),
                grid_scan: Some(ce(0.2, 0.3)),
                grid_flash: Some(ce(0.3, 0.2)),
                grid_glitch: Some(ce(0.4, 0.25)),
                grid_wave: Some(ce(0.2, 0.35)),
                grid_pixelate: Some(ce(0.2, 0.3)),
                grid_chromatic: Some(ce(0.2, 0.3)),
                rgb_shift: Some(ChanceEffect {
                    chance: 0.7,
                    duration: 0.2,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_shift".into(), 0.083);
                        m.insert("end_shift".into(), 0.0);
                        m
                    },
                }),
                yolo_emission: None,
                max_common_panel: 2,
                max_grid_frame: 2,
            },
            dtw: BeatEffectCfg {
                zoom: BEffect {
                    start_zoom: 1.03,
                    end_zoom: 1.0,
                    duration: 0.25,
                },
                beat_bounce: BounceCfg {
                    amplitude: 1.15,
                    duration: 0.25,
                },
                zoom_to_point: Some(ChanceEffect {
                    chance: 0.3,
                    duration: 0.35,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_zoom".into(), 1.05);
                        m.insert("end_zoom".into(), 1.15);
                        m
                    },
                }),
                ken_burns: Some(ce(0.0, 0.8)),
                panel_slide: Some(ce(0.4, 0.3)),
                panel_pulse: Some(ce(0.1, 0.35)),
                panel_bounce: Some(ce(0.35, 0.2)),
                panel_spin: Some(ce(0.25, 0.25)),
                grid_scan: Some(ce(0.2, 0.3)),
                grid_flash: Some(ce(0.3, 0.2)),
                grid_glitch: Some(ce(0.4, 0.25)),
                grid_wave: Some(ce(0.2, 0.35)),
                grid_pixelate: Some(ce(0.2, 0.3)),
                grid_chromatic: Some(ce(0.2, 0.3)),
                rgb_shift: Some(ChanceEffect {
                    chance: 0.7,
                    duration: 0.2,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_shift".into(), 0.083);
                        m.insert("end_shift".into(), 0.0);
                        m
                    },
                }),
                yolo_emission: Some(ce(0.15, 0.6)),
                max_common_panel: 2,
                max_grid_frame: 2,
            },
            single: BeatEffectCfg {
                zoom: BEffect {
                    start_zoom: 1.03,
                    end_zoom: 1.0,
                    duration: 0.25,
                },
                beat_bounce: BounceCfg {
                    amplitude: 1.15,
                    duration: 0.25,
                },
                zoom_to_point: None,
                ken_burns: Some(ce(0.0, 0.7)),
                panel_slide: None,
                panel_pulse: None,
                panel_bounce: None,
                panel_spin: None,
                grid_scan: None,
                grid_flash: None,
                grid_glitch: None,
                grid_wave: None,
                grid_pixelate: None,
                grid_chromatic: None,
                rgb_shift: Some(ChanceEffect {
                    chance: 0.7,
                    duration: 0.2,
                    params: {
                        let mut m = std::collections::HashMap::new();
                        m.insert("start_shift".into(), 0.083);
                        m.insert("end_shift".into(), 0.0);
                        m
                    },
                }),
                yolo_emission: None,
                max_common_panel: 2,
                max_grid_frame: 0,
            },
        },
    }
}
