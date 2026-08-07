//! Integration tests for every effect in ocv-core.
//!
//! Each test renders a short video through one effect using real test clips.
//! Tests are ignored by default — run with:
//!
//!     cargo test --package ocv-core --test effects -- --ignored
//!
//! Requires ffmpeg/ffprobe and the test clips at the project root:
//!   test1.mp4, test2.mp4, test_potrait_human.mp4
//!
//! Output videos are written to /tmp/ocv_test_outputs/<test_name>.mp4.

mod common;

use ocv_core::easing::Easing;
use ocv_core::effect::NoMask;
use ocv_core::effects::{
    BlurEffect, ColorAdjustEffect, ColorParams, EmissionEffect, FlipEffect, GlowEffect,
    MaskSpec, MaskedEffect, RGBShiftEffect, SegMaskedEffect, TextEffect, ZoomEffect, ZoomToPoint,
};
use ocv_core::effects_grid::{
    GridChromaticEffect, GridFlashEffect, GridGlitchEffect, GridPixelateEffect, GridScanEffect,
    GridWaveWarpEffect, KenBurnsEffect, PanelBounceEffect, PanelPulseEffect, PanelSlideEffect,
    PanelSpinEffect, TextOverlayEffect,
};
use ocv_core::text::TextPosition;

const FPS: f64 = 30.0;
const NUM_FRAMES: usize = 30;
const SIZE: (u32, u32) = (640, 360);
const CLIP: &str = "test1.mp4";
const CLIP_PORTRAIT: &str = "test_potrait_human.mp4";

// ── Helpers ───────────────────────────────────────────────────────────────────

macro_rules! effect_test {
    ($name:ident, $effect:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_effect(&$effect, CLIP, stringify!($name), NUM_FRAMES, FPS, SIZE, true);
        }
    };
    ($name:ident, $effect:expr, $clip:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_effect(&$effect, $clip, stringify!($name), NUM_FRAMES, FPS, SIZE, true);
        }
    };
}

macro_rules! effect_test_noop {
    ($name:ident, $effect:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_effect(
                &$effect, CLIP, stringify!($name), NUM_FRAMES, FPS, SIZE, false,
            );
        }
    };
}

// ── 1. Effects from effects.rs ────────────────────────────────────────────────

effect_test!(test_zoom_effect, ZoomEffect::new(1.0, 1.3, Easing::Linear));

effect_test!(test_zoom_to_point, {
    ZoomToPoint::new((0.3, 0.3), 1.0, 1.5, Easing::EaseOutQuad)
});

effect_test!(test_color_adjust_effect, {
    let start = ColorParams { saturation: 1.0, contrast: 1.0, brightness: 0.0, gamma: 1.0 };
    let end = ColorParams { saturation: 1.4, contrast: 1.15, brightness: 8.0, gamma: 1.1 };
    ColorAdjustEffect::new(start, end, Easing::Linear)
});

effect_test!(test_blur_effect, {
    BlurEffect::new(0.0, 0.04, Easing::Linear)
});

effect_test!(test_rgb_shift_effect, {
    RGBShiftEffect::new(0.0, 0.025, 45.0, Easing::EaseOutQuad)
});

effect_test!(test_flip_horizontal, {
    FlipEffect::new("h")
});

effect_test!(test_flip_vertical, {
    FlipEffect::new("v")
});

effect_test!(test_flip_both, {
    FlipEffect::new("both")
});

effect_test!(test_masked_ellipse, {
    let inner = Box::new(ColorAdjustEffect::new(
        ColorParams { saturation: 1.0, contrast: 1.0, brightness: 0.0, gamma: 1.0 },
        ColorParams { saturation: 1.0, contrast: 1.4, brightness: 15.0, gamma: 1.0 },
        Easing::Linear,
    ));
    MaskedEffect::new(
        inner,
        MaskSpec::Ellipse { cx: 0.5, cy: 0.5, rx: 0.4, ry: 0.4, norm: true },
        0.02,
        false,
    )
});

effect_test_noop!(test_glow_effect_noop, {
    GlowEffect::new([30, 80, 255], 0.14, 0.8, Box::new(NoMask))
});

effect_test_noop!(test_emission_effect_noop, {
    EmissionEffect::new(
        [180, 220, 255], [30, 80, 255], 0.042, 0.142, 0.8, 2.5, 0.15, Box::new(NoMask),
    )
});

effect_test_noop!(test_seg_masked_effect_noop, {
    let inner = Box::new(ZoomEffect::new(1.0, 1.2, Easing::Linear));
    SegMaskedEffect::new(inner, "person", 0.01, Box::new(NoMask))
});

// Text effects depend on Python PIL (render_text_py.py). If unavailable,
// the effect renders empty text (no pixel change) — we still check dimensions
// and produce an output video for visual inspection.
macro_rules! effect_test_text {
    ($name:ident, $effect:expr, $clip:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_effect(
                &$effect, $clip, stringify!($name), NUM_FRAMES, FPS, SIZE, false,
            );
        }
    };
}

effect_test_text!(test_text_effect, {
    TextEffect::new(
        "Hello OCV",
        None, 0.08, TextPosition::BottomCenter,
        [255, 255, 255], 1.0, 0.3, 0.3, "fade", "fade",
        0.005, [0, 0, 0], 1.1, false, Box::new(NoMask),
    )
}, CLIP_PORTRAIT);

effect_test_text!(test_text_effect_depth, {
    TextEffect::new(
        "Depth Text",
        None, 0.08, TextPosition::Center,
        [255, 220, 50], 0.95, 0.3, 0.3, "fade", "fade",
        0.005, [0, 0, 0], 1.1, true, Box::new(NoMask),
    )
}, CLIP_PORTRAIT);

// ── 2. Grid effects from effects_grid.rs ──────────────────────────────────────

effect_test!(test_ken_burns_effect, {
    KenBurnsEffect {
        easing: Easing::EaseInOutQuad,
        center: (0.5, 0.5),
        zoom_out: 1.0,
        zoom_in: 1.25,
        drift_x: 0.02,
        drift_y: 0.01,
    }
});

effect_test!(test_panel_slide_left, {
    PanelSlideEffect { easing: Easing::EaseOutQuad, direction: "left".into(), start_offset: 1.0, end_offset: 0.0 }
});

effect_test!(test_panel_slide_right, {
    PanelSlideEffect { easing: Easing::EaseOutQuad, direction: "right".into(), start_offset: -1.0, end_offset: 0.0 }
});

effect_test!(test_panel_slide_up, {
    PanelSlideEffect { easing: Easing::EaseOutQuad, direction: "up".into(), start_offset: 1.0, end_offset: 0.0 }
});

effect_test!(test_panel_slide_down, {
    PanelSlideEffect { easing: Easing::EaseOutQuad, direction: "down".into(), start_offset: -1.0, end_offset: 0.0 }
});

effect_test!(test_panel_pulse_effect, {
    PanelPulseEffect { easing: Easing::EaseOutQuad, start_scale: 1.0, pulse_scale: 1.15, end_scale: 1.0 }
});

effect_test!(test_panel_bounce_effect, {
    PanelBounceEffect { easing: Easing::Linear, direction: "up".into(), amplitude: 0.08 }
});

effect_test!(test_panel_spin_effect, {
    PanelSpinEffect { easing: Easing::EaseOutQuad, max_angle: 5.0 }
});

effect_test!(test_grid_scan_effect, {
    GridScanEffect { easing: Easing::Linear, num_bars: 180.0, bar_speed: 0.6, bar_width: 0.08 }
});

effect_test!(test_grid_flash_effect, {
    GridFlashEffect { easing: Easing::EaseOutQuad, intensity: 0.6 }
});

effect_test!(test_grid_glitch_effect, {
    GridGlitchEffect { easing: Easing::Linear, intensity: 0.6 }
});

effect_test!(test_grid_wave_warp_effect, {
    // amplitude must yield non-zero dx at mid-progress: 6.0 * 0.5 * sin ≈ 3 → non-zero
    GridWaveWarpEffect { easing: Easing::Linear, frequency: 24.0, amplitude: 6.0, speed: 4.0 }
});

effect_test!(test_grid_pixelate_effect, {
    GridPixelateEffect { easing: Easing::EaseOutQuad, max_pixels: 320.0, min_pixels: 8.0 }
});

effect_test!(test_grid_chromatic_effect, {
    // intensity must yield shift >= 1 at mid-progress: 250 * 0.02 * 0.5 = 2.5 → 2 pixels
    GridChromaticEffect { easing: Easing::EaseOutQuad, intensity: 250.0, angle: 0.0 }
});

macro_rules! effect_test_text_overlay {
    ($name:ident, $effect:expr, $clip:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_effect(
                &$effect, $clip, stringify!($name), NUM_FRAMES, FPS, SIZE, false,
            );
        }
    };
}

effect_test_text_overlay!(test_text_overlay_effect, {
    TextOverlayEffect {
        easing: Easing::Linear,
        text: "Overlay".into(),
        font_path: "/home/shiro/Projects/OCV_Edit/assets/fonts/Audiowide-Regular.ttf".into(),
        font_size: 0.1,
        position: "center".into(),
        color: [255, 200, 50],
        opacity: 0.9,
        stroke_width: 0.003,
        stroke_color: [0, 0, 0],
    }
}, CLIP_PORTRAIT);

effect_test_text_overlay!(test_text_overlay_bottom, {
    TextOverlayEffect {
        easing: Easing::Linear,
        text: "Bottom Text".into(),
        font_path: "/home/shiro/Projects/OCV_Edit/assets/fonts/Audiowide-Regular.ttf".into(),
        font_size: 0.07,
        position: "bottom_center".into(),
        color: [255, 255, 255],
        opacity: 0.85,
        stroke_width: 0.003,
        stroke_color: [0, 0, 0],
    }
}, CLIP_PORTRAIT);
