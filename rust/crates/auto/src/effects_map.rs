use anyhow::{anyhow, Result};
use ocv_core::easing::{resolve_easing, easing_from_spec, Easing};
use ocv_core::effect::{BoxedEffect, BoxedTransition, NoMask};
use ocv_core::effects::MaskSpec;
use ocv_core::effects::{
    BlurEffect, BounceEffect, ColorAdjustEffect, ColorParams, EmissionEffect, FlipEffect, GlowEffect,
    MaskedEffect, RGBShiftEffect, SegMaskedEffect, TextEffect, ZoomEffect, ZoomToPoint,
};
use ocv_core::effects_grid::{
    GridChromaticEffect, GridFlashEffect, GridGlitchEffect, GridPixelateEffect, GridScanEffect,
    GridWaveWarpEffect, KenBurnsEffect, PanelBounceEffect, PanelPulseEffect, PanelSlideEffect,
    PanelSpinEffect, TextOverlayEffect,
};
use ocv_core::text::TextPosition;
use ocv_core::transitions::{
    FlashTransition, GridWipeTransition, RadialWipeTransition, SlideTransition, ZoomInTransition,
    ZoomTransition,
};
use serde_json::Value;

use crate::plan::{EffectSpec, TransitionSpec};

fn f(v: &Value, k: &str, d: f32) -> f32 {
    v.get(k).and_then(|x| x.as_f64()).map(|x| x as f32).unwrap_or(d)
}
fn s(v: &Value, k: &str, d: &str) -> String {
    v.get(k).and_then(|x| x.as_str()).unwrap_or(d).to_string()
}
fn arr2(v: &Value, k: &str, d: (f32, f32)) -> (f32, f32) {
    match v.get(k).and_then(|x| x.as_array()) {
        Some(a) if a.len() >= 2 => (
            a[0].as_f64().unwrap_or(d.0 as f64) as f32,
            a[1].as_f64().unwrap_or(d.1 as f64) as f32,
        ),
        _ => d,
    }
}
fn col(v: &Value, k: &str, d: [u8; 3]) -> [u8; 3] {
    match v.get(k).and_then(|x| x.as_array()) {
        Some(a) if a.len() >= 3 => [
            a[0].as_f64().unwrap_or(0.0) as u8,
            a[1].as_f64().unwrap_or(0.0) as u8,
            a[2].as_f64().unwrap_or(0.0) as u8,
        ],
        _ => d,
    }
}

fn resolve_easing_spec(spec: &EffectSpec) -> Easing {
    if let Some(e) = &spec.easing {
        return easing_from_spec(e);
    }
    match spec.params.get("easing").and_then(|x| x.as_str()) {
        Some(n) => resolve_easing(n),
        None => Easing::Linear,
    }
}

fn mask_spec_from_params(p: &Value) -> MaskSpec {
    if let Some(r) = p.get("rect") {
        MaskSpec::Rect {
            x: f(r, "x", 0.0),
            y: f(r, "y", 0.0),
            w: f(r, "w", 1.0),
            h: f(r, "h", 1.0),
            norm: true,
        }
    } else if let Some(e) = p.get("ellipse") {
        MaskSpec::Ellipse {
            cx: f(e, "cx", 0.5),
            cy: f(e, "cy", 0.5),
            rx: f(e, "rx", 0.5),
            ry: f(e, "ry", 0.5),
            norm: true,
        }
    } else {
        MaskSpec::Rect {
            x: 0.0,
            y: 0.0,
            w: 1.0,
            h: 1.0,
            norm: true,
        }
    }
}

pub fn deserialize_effect(spec: &EffectSpec) -> Result<BoxedEffect> {
    let p = &spec.params;
    let ease = resolve_easing_spec(spec);
    let out: BoxedEffect = match spec.effect_type.as_str() {
        "ZoomEffect" => Box::new(ZoomEffect::new(f(p, "start_zoom", 1.0), f(p, "end_zoom", 1.0), ease)),
        "ZoomToPoint" => Box::new(ZoomToPoint::new(
            arr2(p, "center", (0.5, 0.5)),
            f(p, "start_zoom", 1.0),
            f(p, "end_zoom", 1.0),
            ease,
        )),
        "ColorAdjustEffect" => {
            let end = ColorParams {
                saturation: f(p, "saturation", 1.0),
                contrast: f(p, "contrast", 1.0),
                brightness: f(p, "brightness", 0.0),
                gamma: f(p, "gamma", 1.0),
            };
            let start = ColorParams { saturation: 1.0, contrast: 1.0, brightness: 0.0, gamma: 1.0 };
            Box::new(ColorAdjustEffect::new(start, end, ease))
        }
        "BlurEffect" => Box::new(BlurEffect::new(f(p, "start_sigma", 0.0), f(p, "end_sigma", 0.0), ease)),
        "RGBShiftEffect" => Box::new(RGBShiftEffect::new(
            f(p, "start_shift", 0.0),
            f(p, "end_shift", 0.0),
            f(p, "angle", 0.0),
            ease,
        )),
        "FlipEffect" => Box::new(FlipEffect::new(&s(p, "mode", "h"))),
        "MaskedEffect" => {
            let inner = if let Some(inner_spec) = p.get("effect") {
                let es: EffectSpec = serde_json::from_value(inner_spec.clone())
                    .map_err(|e| anyhow!("invalid inner effect: {e}"))?;
                deserialize_effect(&es)?
            } else {
                let id = ColorParams { saturation: 1.0, contrast: 1.0, brightness: 0.0, gamma: 1.0 };
                Box::new(ColorAdjustEffect::new(id.clone(), id, Easing::Linear))
            };
            Box::new(MaskedEffect::new(
                inner,
                mask_spec_from_params(p),
                f(p, "feather", 0.0),
                p.get("invert").and_then(|x| x.as_bool()).unwrap_or(false),
            ))
        }
        "YoloGlowSegEffect" => Box::new(GlowEffect::new(
            col(p, "outer_color", [30, 80, 255]),
            f(p, "outer_radius", 0.14),
            f(p, "intensity", 0.8),
            Box::new(NoMask),
        )),
        "YoloEmissionEffect" => Box::new(EmissionEffect::new(
            col(p, "inner_color", [180, 220, 255]),
            col(p, "outer_color", [30, 80, 255]),
            f(p, "inner_radius", 0.042),
            f(p, "outer_radius", 0.142),
            f(p, "intensity", 0.8),
            f(p, "pulse_speed", 2.5),
            f(p, "pulse_amplitude", 0.15),
            Box::new(NoMask),
        )),
        "YoloSegMaskedEffect" => {
            let inner = if let Some(inner_spec) = p.get("effect") {
                let es: EffectSpec = serde_json::from_value(inner_spec.clone())
                    .map_err(|e| anyhow!("invalid inner effect: {e}"))?;
                deserialize_effect(&es)?
            } else {
                let id = ColorParams { saturation: 1.0, contrast: 1.0, brightness: 0.0, gamma: 1.0 };
                Box::new(ColorAdjustEffect::new(id.clone(), id, Easing::Linear))
            };
            Box::new(SegMaskedEffect::new(
                inner,
                &s(p, "target", "person"),
                f(p, "feather", 0.0),
                Box::new(NoMask),
            ))
        }
        "YoloTextEffect" => Box::new(TextEffect::new(
            &s(p, "text", ""),
            p.get("font_path").and_then(|x| x.as_str()),
            f(p, "font_size", 0.1),
            TextPosition::from_str_or_tuple(&s(p, "position", "bottom_center")),
            col(p, "color", [255, 255, 255]),
            f(p, "opacity", 1.0),
            f(p, "transition_in", 0.0),
            f(p, "transition_out", 0.0),
            &s(p, "animate_in", "fade"),
            &s(p, "animate_out", "fade"),
            f(p, "stroke_width", 0.0),
            col(p, "stroke_color", [0, 0, 0]),
            f(p, "line_spacing", 1.1),
            p.get("depth_composite").and_then(|x| x.as_bool()).unwrap_or(false),
            Box::new(ocv_core::yolo::YoloSegMaskLoader::new(
                std::env::var("OCV_YOLO_MODEL")
                    .unwrap_or_else(|_| "models/yolo26s-seg.onnx".to_string()),
            )),
        )),
        "KenBurnsEffect" => Box::new(KenBurnsEffect {
            easing: ease,
            center: arr2(p, "center", (0.5, 0.5)),
            zoom_out: f(p, "zoom_out", 1.06),
            zoom_in: f(p, "zoom_in", 1.18),
            drift_x: f(p, "drift_x", 0.0),
            drift_y: f(p, "drift_y", 0.0),
        }),
        "PanelSlideEffect" => Box::new(PanelSlideEffect {
            easing: ease,
            direction: s(p, "direction", "left"),
            start_offset: f(p, "start_offset", 1.0),
            end_offset: f(p, "end_offset", 0.0),
        }),
        "PanelPulseEffect" => Box::new(PanelPulseEffect {
            easing: ease,
            start_scale: f(p, "start_scale", 1.0),
            pulse_scale: f(p, "pulse_scale", 1.12),
            end_scale: f(p, "end_scale", 1.0),
        }),
        "PanelBounceEffect" => Box::new(PanelBounceEffect {
            easing: ease,
            direction: s(p, "direction", "up"),
            amplitude: f(p, "amplitude", 0.06),
        }),
        "PanelSpinEffect" => Box::new(PanelSpinEffect {
            easing: ease,
            max_angle: f(p, "max_angle", 3.0),
        }),
        "GridScanEffect" => Box::new(GridScanEffect {
            easing: ease,
            num_bars: f(p, "num_bars", 240.0),
            bar_speed: f(p, "bar_speed", 0.8),
            bar_width: f(p, "bar_width", 0.05),
        }),
        "GridFlashEffect" => Box::new(GridFlashEffect {
            easing: ease,
            intensity: f(p, "intensity", 0.4),
        }),
        "GridGlitchEffect" => Box::new(GridGlitchEffect {
            easing: ease,
            intensity: f(p, "intensity", 0.8),
        }),
        "GridWaveWarpEffect" => Box::new(GridWaveWarpEffect {
            easing: ease,
            frequency: f(p, "frequency", 20.0),
            amplitude: f(p, "amplitude", 0.03),
            speed: f(p, "speed", 5.0),
        }),
        "GridPixelateEffect" => Box::new(GridPixelateEffect {
            easing: ease,
            max_pixels: f(p, "max_pixels", 400.0),
            min_pixels: f(p, "min_pixels", 25.0),
        }),
        "GridChromaticEffect" => Box::new(GridChromaticEffect {
            easing: ease,
            intensity: f(p, "intensity", 1.0),
            angle: f(p, "angle", 0.0),
        }),
        "TextOverlayEffect" => Box::new(TextOverlayEffect {
            easing: ease,
            text: s(p, "text", ""),
            font_path: s(p, "font_path", ""),
            font_size: f(p, "font_size", 0.1),
            position: s(p, "position", "bottom_center"),
            color: col(p, "color", [255, 255, 255]),
            opacity: f(p, "opacity", 1.0),
            stroke_width: f(p, "stroke_width", 0.0),
            stroke_color: col(p, "stroke_color", [0, 0, 0]),
        }),
        "BounceEffect" => Box::new(BounceEffect::new(
            f(p, "amplitude", 1.08),
            ease,
        )),
        other => return Err(anyhow!("unknown effect type: {other}")),
    };
    Ok(out)
}

pub fn deserialize_transition(spec: &TransitionSpec) -> Result<BoxedTransition> {
    let p = &spec.params;
    let ease = match &spec.easing {
        Some(e) => easing_from_spec(e),
        None => resolve_easing(p.get("easing").and_then(|x| x.as_str()).unwrap_or("linear")),
    };
    let out: BoxedTransition = match spec.transition_type.as_str() {
        "slide" => Box::new(SlideTransition::new(&s(p, "direction", "up"), ease)),
        "zoom" => Box::new(ZoomTransition::new(&s(p, "mode", "in"), ease)),
        "grid_wipe" => Box::new(GridWipeTransition::new(
            f(p, "cols", 6.0) as u32,
            f(p, "rows", 4.0) as u32,
            &s(p, "stagger", "row"),
            ease,
        )),
        "flash" => Box::new(FlashTransition::new(col(p, "color", [255, 255, 255]), 0.5, ease)),
        "radial_wipe" => Box::new(RadialWipeTransition::new(arr2(p, "origin", (0.5, 0.5)), ease)),
        "zoom_in" => Box::new(ZoomInTransition::new(f(p, "max_zoom", 1.5), f(p, "blur_peak", 8.0), ease)),
        other => return Err(anyhow!("unknown transition type: {other}")),
    };
    Ok(out)
}
