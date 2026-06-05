"""
grid_edit.py
------------
An example edit script showcasing the GridScene layout system,
per-panel effects, full-scene effects, and YOLO segmentation.
"""

from utils.pipeline import CLIP_END, VideoPipeline
from utils.effects import (
    BlurEffect,
    ColorAdjustEffect,
    FlipEffect,
    RGBShiftEffect,
    YoloGlowSegEffect,
    YoloSegMaskedEffect,
    YoloTextEffect,
    ZoomEffect,
)
from utils.grid import GridPanel, GridScene
from utils.transitions import SlideTransition, ZoomTransition

MODEL = "models/yolo26n-seg_int8_openvino_model/"


def main():
    print("Setting up pipeline...")
    # Pipeline configuration
    pipeline = VideoPipeline(fps=30.0, output_size=(1920, 1080))

    # =========================================================================
    # Scene 1: Opening Shot (Fullscreen)
    # =========================================================================
    pipeline.add_clip("city1.mkv", duration=4.0)

    # Simple color grade and Ken-Burns zoom on the first clip
    pipeline.to(clip_idx=0, duration=CLIP_END, zoom=1.1, easing="linear")
    pipeline.add_clip_effect(
        0,
        ColorAdjustEffect(
            start_params={"saturation": 0.5, "contrast": 1.1},
            end_params={"saturation": 1.2, "contrast": 1.1},
        ),
        duration=CLIP_END,
    )

    opening_title = YoloTextEffect(
        text="THE GRID",
        font_path="Audiowide-Regular.ttf",
        font_size=0.148,
        position="center",
        color=(255, 255, 255),
        opacity=1.0,
        transition_in=0.5,
        transition_out=0.5,
        animate_in="slide_up",
        animate_out="fade",
        stroke_width=0.0,
        model_path=None,
    )
    pipeline.add_clip_effect(0, opening_title, start_time=0.5, duration=3.0)

    # Transition to Grid
    pipeline.add_transition(ZoomTransition(duration=0.5, mode="inout"))

    # =========================================================================
    # Scene 2: 1x3 Grid Layout
    # =========================================================================
    print("Configuring Grid Scene...")

    # Left Panel: city2 (slowed down, desaturated)
    p_left = GridPanel("person_reel_vertical_test.mp4", speed=1, loop=True)
    p_left.add_effect(
        ColorAdjustEffect(
            start_params={"saturation": 0.2, "brightness": -20},
            end_params={"saturation": 0.2, "brightness": -20},
        )
    )

    # Center Panel: boy1 (normal speed, with YOLO glow and masked color grade)
    p_center = GridPanel("person_reel_vertical_test.mp4", speed=1.0, loop=True)

    # We can add YOLO effects to individual panels!
    # Background goes dark, subject stays bright
    p_center.add_effect(
        YoloSegMaskedEffect(
            ColorAdjustEffect(
                start_params={"saturation": 0.1, "brightness": -30},
                end_params={"saturation": 0.1, "brightness": -30},
            ),
            model_path=MODEL,
            target="background",
            feather=0.019,
        )
    )

    # Glow around the subject
    p_center.add_effect(
        YoloGlowSegEffect(
            model_path=MODEL,
            glow_color=(0, 200, 255),  # Cyan glow
            blur_amount=0.029,
            intensity=1.8,
        )
    )

    # Right Panel: mirror of Left Panel
    # By using ref_panel, it shares the exact same video decoder and frames as p_left!
    # flip="h" mirrors it horizontally so it faces inward.
    p_right = GridPanel(ref_panel=p_left, flip="h")
    # Even though it shares frames, it can have its own separate effects if we wanted.

    # Build the scene
    grid_scene = GridScene(
        panels=[p_left, p_center, p_right],
        layout=(1, 3),  # 1 row, 3 columns
        duration=6.0,  # Total duration of this grid scene
        col_weights=[1, 2, 1],  # Center panel is 2x wider than the sides
        gap=0.003,
        keep_audio=1,  # Keep audio from the center panel (boy1.mkv)
    )

    # We can add an effect over the ENTIRE composited grid
    # Let's add a chromatic aberration (RGB shift) hit at the end before transitioning
    grid_scene.add_effect(
        RGBShiftEffect(start_shift=0.0, end_shift=0.037, angle=90),
        start_time=4.5,
        duration=1.5,
    )
    # And a slow zoom on the whole grid
    grid_scene.add_effect(ZoomEffect(start_zoom=1.0, end_zoom=1.15), duration=CLIP_END)

    # Add the grid scene to the timeline
    pipeline.add_grid_scene(grid_scene)

    # Transition out of Grid
    pipeline.add_transition(SlideTransition(duration=0.5, direction="up"))

    # =========================================================================
    # Scene 3: Closing Shot (Fullscreen)
    # =========================================================================
    pipeline.add_clip("boy2.webm", duration=4.0, speed=1.5)  # Fast forward

    pipeline.to(clip_idx=2, duration=CLIP_END, zoom=1.2, easing="linear")

    # Fade to blur at the end
    pipeline.to(
        clip_idx=2,
        duration=1.5,
        start_time=2.5,
        blur=0.019,
        brightness=-100,  # Fade to blackish
        easing="ease_in",
    )

    # =========================================================================
    # Render
    # =========================================================================
    print("Rendering grid_edit.mp4 ...")
    pipeline.render("grid_edit.mp4")
    print("Done!")


if __name__ == "__main__":
    main()
