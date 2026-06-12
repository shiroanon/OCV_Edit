import os
import math
import numpy as np
from utils.pipeline import VideoPipeline, CLIP_END
from utils.grid import Layer, LayeredScene
from utils.effects import GLSLEffect, BlurEffect

# Check if model path exists
yolo_model = "models/yolo26s-seg_int8_openvino_model/"
if not os.path.exists(yolo_model):
    print(f"Warning: model path {yolo_model} not found, YOLO masking will be bypassed or fail.")

def main():
    print("Setting up pipeline...")
    # 30 fps, 1280x720 output size for faster test rendering
    pipeline = VideoPipeline(fps=30.0, output_size=(1280, 720))

    # Background layer (covers full screen, loops)
    bg_video = "person_reel_vertical_test.mp4"
    bg_layer = Layer(
        filepath=bg_video,
        loop=True,
        resize_mode="fill",
        opacity=0.4, # desaturated and semi-transparent
    )
    
    # Subject layer (isolated person using YOLO, positioned in the center, scaled to 0.7)
    # We will use the person_reel_vertical_test.mp4 video which contains a person.
    # YOLO "subject" mask will extract the person.
    subject_layer = Layer(
        filepath="person_reel_vertical_test.mp4",
        loop=True,
        resize_mode="fit",
        size=(0.8, 0.8),
        position=(0.5, 0.5),
        anchor="center",
        mask_type="subject",
        feather=0.021,
        yolo_model_path=yolo_model,
        opacity=1.0,
    )
    
    # Let's add a GLSL shader effect to the subject layer to give it a futuristic chromatic aberration glow!
    chromatic_shader = """
    #version 330
    in vec2 v_uv;
    out vec4 fragColor;
    uniform sampler2D tex;
    uniform float time;
    uniform float progress;
    void main() {
        float amount = 0.015 * sin(time * 5.0);
        vec3 col;
        col.r = texture(tex, vec2(v_uv.x + amount, v_uv.y)).r;
        col.g = texture(tex, v_uv).g;
        col.b = texture(tex, vec2(v_uv.x - amount, v_uv.y)).b;
        
        // Add a subtle scanline grid pattern
        float scanline = sin(v_uv.y * 300.0) * 0.08;
        col -= scanline;
        
        fragColor = vec4(col, 1.0);
    }
    """
    gl_effect = GLSLEffect(fragment_shader_code=chromatic_shader)
    subject_layer.add_effect(gl_effect)
    
    # Overlay layer: A dynamic geometric mask showing another view
    # Let's make it drift horizontally over time
    overlay_layer = Layer(
        filepath="person_reel_vertical_test.mp4",
        loop=True,
        resize_mode="fill",
        size=(0.3, 0.3),
        position=lambda t: (0.15 + 0.7 * abs(math.sin(t * 0.5)), 0.2),
        anchor="center",
        mask_type="ellipse",
        mask_params={"cx": 0.5, "cy": 0.5, "rx": 0.4, "ry": 0.4},
        blend_mode="screen",
        opacity=0.8,
    )

    # Let's build the LayeredScene
    scene = LayeredScene(
        layers=[bg_layer, subject_layer, overlay_layer],
        duration=5.0, # 5 seconds rendering is fast and enough to test
    )

    pipeline.add_layered_scene(scene)

    print("Rendering test_layered_output.mp4...")
    pipeline.render("test_layered_output.mp4")
    print("Done!")

if __name__ == "__main__":
    main()
