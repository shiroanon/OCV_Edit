"""
grid_overlap.py
---------------
Demonstrates custom grid shapes and overlapping panels:
  1. A 1x3 grid where the middle panel's YOLO subject overlaps adjacent panels
  2. Shape-masked panels (circle, diamond)
  3. Blend modes and z-ordering
"""

import math
from utils.pipeline import VideoPipeline
from utils.effects import ColorAdjustEffect, ZoomEffect, RGBShiftEffect, YoloGlowSegEffect
from utils.grid import GridPanel, GridScene
from utils.transitions import SlideTransition

MODEL = "models/yolo26s-seg_int8_openvino_model/"


def main():
    print("Setting up pipeline...")
    pipeline = VideoPipeline(fps=30.0, output_size=(1920, 1080))

    # =========================================================================
    # Scene 1: Opening fullscreen clip
    # =========================================================================
    pipeline.add_clip("city1.mkv", duration=3.0)

    # =========================================================================
    # Scene 2: 1x3 Grid with Overlapping YOLO Subject
    # =========================================================================
    print("Configuring overlapping grid scene...")

    # Left panel — desaturated, z_index=0 (bottom)
    p_left = GridPanel(
        "person_reel_vertical_test.mp4",
        speed=1.0, loop=True,
        resize_mode="fill",
        z_index=0,
    )
    p_left.add_effect(
        ColorAdjustEffect(
            start_params={"saturation": 0.1, "brightness": -25},
            end_params={"saturation": 0.1, "brightness": -25},
        )
    )

    # Middle panel — YOLO subject mask, z_index=1 (on top of sides)
    # The subject will render over the left/right panels
    p_center = GridPanel(
        "person_reel_vertical_test.mp4",
        speed=1.0, loop=True,
        resize_mode="fill",
        z_index=1,                          # on top of left and right
        mask_type="subject",                # YOLO subject extraction
        feather=0.015,
        yolo_model_path=MODEL,
    )
    p_center.add_effect(
        YoloGlowSegEffect(
            model_path=MODEL,
            glow_color=(0, 200, 255),
            blur_amount=0.025,
            intensity=1.5,
        )
    )

    # Right panel — mirror of left, same z_index=0
    p_right = GridPanel(
        ref_panel=p_left, flip="h",
        z_index=0,
    )

    # Build the grid scene
    grid_scene = GridScene(
        panels=[p_left, p_center, p_right],
        layout=(1, 3),
        duration=6.0,
        col_weights=[1, 2, 1],
        gap=0.003,
        keep_audio=1,
    )
    grid_scene.add_effect(
        ZoomEffect(start_zoom=1.0, end_zoom=1.1),
        duration="clip_end",
    )

    pipeline.add_grid_scene(grid_scene)
    pipeline.add_transition(SlideTransition(duration=0.5, direction="up"))

    # =========================================================================
    # Scene 3: Shape-masked panels — circle + diamond
    # =========================================================================
    print("Configuring shape-masked grid scene...")

    # Circle panel
    p_circle = GridPanel(
        "city1.mkv",
        loop=True,
        shape="circle",
        resize_mode="fill",
    )

    # Diamond panel (shared frame with circle but flipped)
    p_diamond = GridPanel(
        ref_panel=p_circle, flip="h",
        shape="diamond",
    )

    # A small freeform overlay panel with animated position and screen blend
    p_overlay = GridPanel(
        "boy2.webm",
        loop=True,
        shape="ellipse",
        resize_mode="fill",
        z_index=1,
        blend_mode="screen",
        opacity=0.7,
        position=lambda t: (0.5 + 0.35 * math.sin(t * 0.8), 0.5 + 0.2 * math.cos(t * 0.6)),
        size=(0.25, 0.25),
        anchor="center",
    )

    shape_scene = GridScene(
        panels=[p_circle, p_diamond, p_overlay],
        layout=(1, 2),          # 2 grid panels (circle + diamond), overlay is freeform
        duration=5.0,
        gap=0.005,
    )

    pipeline.add_grid_scene(shape_scene)

    # =========================================================================
    # Render
    # =========================================================================
    print("Rendering grid_overlap.mp4 ...")
    pipeline.render("grid_overlap.mp4")
    print("Done!")


if __name__ == "__main__":
    main()
