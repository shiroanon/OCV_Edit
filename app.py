from utils.pipeline import VideoPipeline, CLIP_END
from utils.effects import (
    BlurEffect, ColorAdjustEffect, RGBShiftEffect, ZoomEffect, ZoomToPoint,
    YoloGlowSegEffect, YoloSegMaskedEffect, YoloTextEffect, GLSLEffect,
)
from utils.transitions import SlideTransition, ZoomTransition

if __name__ == "__main__":
    pipeline = VideoPipeline(fps=30.0, output_size=(1920, 1080))
    print("Setting up pipeline...")
    pipeline.add_clip("person.mp4", duration=10.0)
    pipeline.add_transition(ZoomTransition(duration=0.3, easing=(0.75, 0, 0.25, 1), mode="inout"))
    pipeline.add_clip("test2.mp4", duration=3.0)

    print("Loading YOLO Effects...")
    glow_effect = YoloGlowSegEffect(
        model_path="models/yolo26n-seg_int8_openvino_model/",
        glow_color=(255, 100, 100), intensity=3,
    )
    title_text = YoloTextEffect(
        text="HIGHLIGHT REEL",
        font_path="Audiowide-Regular.ttf",
        font_size=0.139, position="center", color=(255, 255, 255),
        opacity=1.0, transition_in=0.2, transition_out=0.4,
        animate_in="slide_up", animate_out="fade",
        stroke_width=0.0, stroke_color=(0, 0, 0),
        model_path="models/yolo26n-seg_int8_openvino_model/",
        easing="ease_out",
    )
    pipeline.add_clip_effect(clip_idx=0, effect=title_text, start_time=1.0, duration=CLIP_END)

    caption = YoloTextEffect(
        text="ft. @username",
        font_size=0.044, position="top_right", color=(200, 200, 200),
        opacity=0.9, transition_in=0.4, transition_out=0.3,
        animate_in="fade", animate_out="fade", model_path=None,
    )
    pipeline.add_clip_effect(clip_idx=1, effect=caption, start_time=0.0, duration=2.0)

    MODEL = "models/yolo26n-seg_int8_openvino_model/"
    print("Setting up YoloSeg masked effects...")
    bg_desat = YoloSegMaskedEffect(
        ColorAdjustEffect(start_params={"saturation": 0.0, "brightness": -15},
                          end_params={"saturation": 0.0, "brightness": -15}),
        model_path=MODEL, target="background", feather=0.019,
    )
    pipeline.add_clip_effect(clip_idx=0, effect=bg_desat)

    bg_dof = YoloSegMaskedEffect(
        BlurEffect(start_blur=0.0, end_blur=0.019),
        model_path=MODEL, target="background", feather=0.014,
    )
    pipeline.add_clip_effect(clip_idx=0, effect=bg_dof, duration=5.0)

    subject_grade = YoloSegMaskedEffect(
        ColorAdjustEffect(start_params={"saturation": 1.4, "contrast": 1.15, "brightness": 10},
                          end_params={"saturation": 1.4, "contrast": 1.15, "brightness": 10}),
        model_path=MODEL, target="subject", feather=0.017,
    )
    pipeline.add_clip_effect(clip_idx=1, effect=subject_grade)

    pipeline.to(clip_idx=0, duration=5.0, zoom=1.2, easing="ease_out")
    pipeline.fromTo(clip_idx=0, duration=5.0,
                    from_props={"saturation": 0.5}, to_props={"saturation": 1.8},
                    easing="ease_in_out")
    pipeline.from_(clip_idx=1, duration=0.8, brightness=-120, saturation=0.0, easing="ease_out")
    pipeline.to(clip_idx=1, duration=1.5, start_time=1.5,
                blur=0.019, rgb_shift=0.019, rgb_shift_angle=45, easing="ease_in")

    print("Rendering video...")
    pipeline.render("output.mp4")
