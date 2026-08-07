//! Integration tests for every transition in ocv-core.
//!
//! Each test renders a short transition between two clips and saves the output.
//! Tests are ignored by default — run with:
//!
//!     cargo test --package ocv-core --test transitions -- --ignored
//!
//! Requires ffmpeg/ffprobe and the test clips at the project root:
//!   test1.mp4, test2.mp4
//!
//! Output videos are written to /tmp/ocv_test_outputs/<test_name>.mp4.

mod common;

use ocv_core::easing::Easing;
use ocv_core::transitions::{
    FlashTransition, GridWipeTransition, RadialWipeTransition, SlideTransition, ZoomInTransition,
    ZoomTransition,
};

const FPS: f64 = 30.0;
const NUM_FRAMES: usize = 30;
const SIZE: (u32, u32) = (640, 360);
const CLIP_A: &str = "test1.mp4";
const CLIP_B: &str = "test2.mp4";

macro_rules! transition_test {
    ($name:ident, $transition:expr) => {
        #[test]
        #[ignore]
        fn $name() {
            common::render_transition(
                &$transition, CLIP_A, CLIP_B, stringify!($name), NUM_FRAMES, FPS, SIZE,
            );
        }
    };
}

// ── Slide transitions ─────────────────────────────────────────────────────────

transition_test!(test_slide_transition_left, {
    SlideTransition::new("left", Easing::EaseOutQuad)
});

transition_test!(test_slide_transition_right, {
    SlideTransition::new("right", Easing::EaseOutQuad)
});

transition_test!(test_slide_transition_up, {
    SlideTransition::new("up", Easing::EaseOutQuad)
});

transition_test!(test_slide_transition_down, {
    SlideTransition::new("down", Easing::EaseOutQuad)
});

// ── Zoom transitions ─────────────────────────────────────────────────────────

transition_test!(test_zoom_transition_in, {
    ZoomTransition::new("in", Easing::EaseOutQuad)
});

transition_test!(test_zoom_transition_out, {
    ZoomTransition::new("out", Easing::EaseOutQuad)
});

transition_test!(test_zoom_transition_inout, {
    ZoomTransition::new("inout", Easing::EaseInOutQuad)
});

transition_test!(test_zoom_transition_outin, {
    ZoomTransition::new("outin", Easing::EaseInOutQuad)
});

// ── Grid wipe ────────────────────────────────────────────────────────────────

transition_test!(test_grid_wipe_transition, {
    GridWipeTransition::new(6, 4, "forward", Easing::Linear)
});

// ── Flash transition ─────────────────────────────────────────────────────────

transition_test!(test_flash_transition_white, {
    FlashTransition::new([255, 255, 255], 0.4, Easing::Linear)
});

transition_test!(test_flash_transition_red, {
    FlashTransition::new([50, 50, 255], 0.4, Easing::Linear)
});

// ── Radial wipe ──────────────────────────────────────────────────────────────

transition_test!(test_radial_wipe_center, {
    RadialWipeTransition::new((0.5, 0.5), Easing::EaseOutQuad)
});

transition_test!(test_radial_wipe_top_left, {
    RadialWipeTransition::new((0.1, 0.1), Easing::EaseOutQuad)
});

// ── Zoom in (aggressive) ────────────────────────────────────────────────────

transition_test!(test_zoom_in_transition, {
    ZoomInTransition::new(1.5, 8.0, Easing::EaseInOutQuad)
});
