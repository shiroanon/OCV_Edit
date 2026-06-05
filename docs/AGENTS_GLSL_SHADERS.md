# GLSL Shader Effects — Agent Guide

`GLSLEffect` in `utils/effects.py` (line 1097) applies custom fragment shaders to video frames using `moderngl` (OpenGL).

## Basic Usage

```python
from utils.effects import GLSLEffect

shader_code = """
#version 330
in vec2 v_uv;
out vec4 fragColor;
uniform sampler2D tex;
uniform float time;
uniform float progress;

void main() {
    vec3 col = texture(tex, v_uv).rgb;
    // Apply a simple RGB tint that evolves over time
    float r = sin(time * 2.0) * 0.5 + 0.5;
    col *= vec3(1.0, r, 1.0 - r);
    fragColor = vec4(col, 1.0);
}
"""

effect = GLSLEffect(fragment_shader_code=shader_code)
pipeline.add_clip_effect(0, effect, duration=3.0)
```

## Available (Default) Uniforms

| Uniform | Type | Description |
|---|---|---|
| `tex` | `sampler2D` | The input video frame (RGB) |
| `resolution` | `vec2` | Frame width and height in pixels |
| `time` | `float` | Seconds since this effect started |
| `progress` | `float` | Eased 0→1 progress over effect duration |

These are set automatically if the shader declares them.

## Custom Uniforms

Pass extra uniforms via the `uniforms` dict:

```python
effect = GLSLEffect(
    fragment_shader_code=shader_code,
    uniforms={
        "strength": 0.5,
        "color": (1.0, 0.0, 0.0),    # vec3
    }
)
```

Supported uniform types: `float`, `int`, `tuple`/`list` (converted to vec), `np.ndarray`.

## Default Vertex Shader

```glsl
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
```

Override by passing `vertex_shader_code` to the constructor.

## Complete Example (from `test_layered.py`)

Chromatic aberration + scanlines:

```python
shader = """
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
    float scanline = sin(v_uv.y * 300.0) * 0.08;
    col -= scanline;
    fragColor = vec4(col, 1.0);
}
"""
```

## Important Details

- **BGR ↔ RGB**: `GLSLEffect.apply()` converts frame from BGR (OpenCV) to RGB before uploading to the GPU, then converts RGB back to BGR when reading the result. Your shader operates on RGB.
- **Context**: Uses a shared global `moderngl` context (created once, cached in `_gl_context`). Standalone context — no window required.
- **Lazy init**: GL resources are allocated on first `apply()` call. If resolution changes, resources are recreated.
- **Texture unit 0**: The input texture is bound to unit 0.
- **Requires `moderngl`**: Import errors are caught at runtime, so the pipeline works without GPU support.
- **Performance**: Each frame does: CPU→GPU upload → shader render → GPU→CPU readback. Expect ~1-5ms on dedicated GPU, more on integrated.

## Writing Efficient Shaders

- Use `v_uv` for texture coordinates (0,0 = bottom-left, 1,1 = top-right)
- Avoid branching on per-pixel conditions when possible
- Precompute values in `main()` before the texture fetch
- Use `textureSize(tex, 0)` to get resolution inside the shader if needed
