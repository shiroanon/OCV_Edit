import numpy as np

from utils.transitions import (
    SlideTransition, ZoomTransition, GridWipeTransition,
    FlashTransition, RadialWipeTransition,
)
from utils.effects import (
    BlurEffect, ColorAdjustEffect, RGBShiftEffect, ZoomEffect, ZoomToPoint,
    KenBurnsEffect, PanelSlideEffect, PanelPulseEffect, PanelBounceEffect,
    PanelSpinEffect, GridScanEffect, GridFlashEffect, GridGlitchEffect,
    GridWaveWarpEffect, GridPixelateEffect, GridChromaticEffect,
    YoloEmissionEffect, YoloTextEffect,
)


def serialize_transition(transition):
    if not transition:
        return None
    if isinstance(transition, SlideTransition):
        return {
            "type": "slide",
            "duration": transition.duration,
            "params": {"direction": transition.direction, "easing": transition.easing},
        }
    elif isinstance(transition, ZoomTransition):
        return {
            "type": "zoom",
            "duration": transition.duration,
            "params": {"mode": transition.mode, "easing": transition.easing},
        }
    elif isinstance(transition, GridWipeTransition):
        return {
            "type": "grid_wipe",
            "duration": transition.duration,
            "params": {
                "cols": transition.cols, "rows": transition.rows,
                "stagger": transition.stagger, "easing": transition.easing,
            },
        }
    elif isinstance(transition, FlashTransition):
        return {
            "type": "flash",
            "duration": transition.duration,
            "params": {
                "color": tuple(int(v) for v in transition.color.flatten()),
                "flash_point": transition.flash_point,
                "easing": transition.easing,
            },
        }
    elif isinstance(transition, RadialWipeTransition):
        return {
            "type": "radial_wipe",
            "duration": transition.duration,
            "params": {"origin": transition.origin, "easing": transition.easing},
        }
    return None


def deserialize_transition(data):
    if not data:
        return None
    t_type = data.get("type")
    dur = data.get("duration", 0.2)
    params = data.get("params", {})
    if t_type == "slide":
        return SlideTransition(duration=dur, direction=params.get("direction", "left"), easing=params.get("easing", "ease_in_out"))
    elif t_type == "zoom":
        return ZoomTransition(duration=dur, mode=params.get("mode", "in"), easing=params.get("easing", "ease_in_out"))
    elif t_type == "grid_wipe":
        return GridWipeTransition(duration=dur, cols=params.get("cols", 6), rows=params.get("rows", 4), stagger=params.get("stagger", "row"), easing=params.get("easing", "ease_in_out"))
    elif t_type == "flash":
        return FlashTransition(duration=dur, color=tuple(params.get("color", [255, 255, 255])), flash_point=params.get("flash_point", 0.35), easing=params.get("easing", "ease_in_out"))
    elif t_type == "radial_wipe":
        return RadialWipeTransition(duration=dur, origin=tuple(params.get("origin", (0.5, 0.5))), easing=params.get("easing", "ease_in_out"))
    return None


def serialize_effect(effect):
    if not effect:
        return None
    if isinstance(effect, ZoomEffect):
        return {
            "type": "ZoomEffect",
            "params": {"start_zoom": effect.start_zoom, "end_zoom": effect.end_zoom, "easing": effect.easing},
        }
    elif isinstance(effect, RGBShiftEffect):
        return {
            "type": "RGBShiftEffect",
            "params": {
                "start_shift": effect.start_shift, "end_shift": effect.end_shift,
                "angle": float(np.rad2deg(effect.angle_rad)), "easing": effect.easing,
            },
        }
    elif isinstance(effect, ColorAdjustEffect):
        return {
            "type": "ColorAdjustEffect",
            "params": {"start_params": effect.start_params, "end_params": effect.end_params, "easing": effect.easing},
        }
    elif isinstance(effect, BlurEffect):
        return {
            "type": "BlurEffect",
            "params": {"start_blur": effect.start_blur, "end_blur": effect.end_blur, "easing": effect.easing},
        }
    elif isinstance(effect, ZoomToPoint):
        if callable(effect.center):
            return None
        return {
            "type": "ZoomToPoint",
            "params": {
                "center": tuple(float(v) for v in effect.center),
                "start_zoom": effect.start_zoom, "end_zoom": effect.end_zoom,
                "easing": effect.easing,
            },
        }
    elif isinstance(effect, KenBurnsEffect):
        u = effect.uniforms
        return {
            "type": "KenBurnsEffect",
            "params": {
                "center": tuple(float(v) for v in u.get("center", (0.5, 0.5))),
                "zoom_out": u.get("zoom_out", 1.06), "zoom_in": u.get("zoom_in", 1.18),
                "drift_x": u.get("drift_x", 0.02), "drift_y": u.get("drift_y", 0.01),
                "easing": effect.easing,
            },
        }
    elif isinstance(effect, PanelSlideEffect):
        return {
            "type": "PanelSlideEffect",
            "params": {
                "direction": effect.direction, "start_offset": effect.start_offset,
                "end_offset": effect.end_offset, "easing": effect.easing,
            },
        }
    elif isinstance(effect, PanelPulseEffect):
        return {
            "type": "PanelPulseEffect",
            "params": {
                "start_scale": effect.start_scale, "pulse_scale": effect.pulse_scale,
                "end_scale": effect.end_scale, "easing": effect.easing,
            },
        }
    elif isinstance(effect, GridScanEffect):
        u = effect.uniforms
        return {
            "type": "GridScanEffect",
            "params": {
                "num_bars": u.get("num_bars", 240.0), "bar_speed": u.get("bar_speed", 0.8),
                "bar_width": u.get("bar_width", 0.05), "easing": effect.easing,
            },
        }
    elif isinstance(effect, GridFlashEffect):
        return {
            "type": "GridFlashEffect",
            "params": {"intensity": effect.uniforms.get("intensity", 0.5), "easing": effect.easing},
        }
    elif isinstance(effect, GridGlitchEffect):
        return {
            "type": "GridGlitchEffect",
            "params": {"intensity": effect.uniforms.get("intensity", 1.0), "easing": effect.easing},
        }
    elif isinstance(effect, GridWaveWarpEffect):
        u = effect.uniforms
        return {
            "type": "GridWaveWarpEffect",
            "params": {
                "frequency": u.get("frequency", 20.0), "amplitude": u.get("amplitude", 0.03),
                "speed": u.get("speed", 5.0), "easing": effect.easing,
            },
        }
    elif isinstance(effect, GridPixelateEffect):
        u = effect.uniforms
        return {
            "type": "GridPixelateEffect",
            "params": {
                "max_pixels": u.get("max_pixels", 400.0), "min_pixels": u.get("min_pixels", 25.0),
                "easing": effect.easing,
            },
        }
    elif isinstance(effect, GridChromaticEffect):
        u = effect.uniforms
        return {
            "type": "GridChromaticEffect",
            "params": {
                "intensity": u.get("intensity", 1.0), "angle": u.get("angle", 0.0),
                "easing": effect.easing,
            },
        }
    elif isinstance(effect, PanelBounceEffect):
        return {
            "type": "PanelBounceEffect",
            "params": {"direction": effect.direction, "amplitude": effect.amplitude, "easing": effect.easing},
        }
    elif isinstance(effect, PanelSpinEffect):
        return {
            "type": "PanelSpinEffect",
            "params": {"max_angle": effect.max_angle, "easing": effect.easing},
        }
    elif isinstance(effect, YoloEmissionEffect):
        return {
            "type": "YoloEmissionEffect",
            "params": {
                "inner_color": list(effect.inner_color), "outer_color": list(effect.outer_color),
                "inner_radius": effect.inner_radius, "outer_radius": effect.outer_radius,
                "intensity": effect.intensity, "pulse_speed": effect.pulse_speed,
                "pulse_amplitude": effect.pulse_amplitude, "easing": effect.easing,
            },
        }
    elif isinstance(effect, YoloTextEffect):
        color = effect.color_rgba[:3][::-1] if hasattr(effect, "color_rgba") else (255, 255, 255)
        stroke_color = effect.stroke_color_rgba[:3][::-1] if hasattr(effect, "stroke_color_rgba") else (0, 0, 0)
        return {
            "type": "YoloTextEffect",
            "params": {
                "text": effect.text, "font_path": getattr(effect, "font_path", None),
                "font_size": effect.font_size, "position": effect.position,
                "color": list(color), "opacity": effect.opacity,
                "transition_in": effect.transition_in, "transition_out": effect.transition_out,
                "animate_in": effect.animate_in, "animate_out": effect.animate_out,
                "stroke_width": effect.stroke_width, "stroke_color": list(stroke_color),
                "depth_composite": effect.depth_composite, "line_spacing": effect.line_spacing,
                "easing": effect.easing,
            },
        }
    return None


def deserialize_effect(data):
    if not data:
        return None
    eff_type = data.get("type")
    params = data.get("params", {})
    if eff_type == "ZoomEffect":
        return ZoomEffect(start_zoom=params.get("start_zoom", 1.0), end_zoom=params.get("end_zoom", 1.0), easing=params.get("easing", "linear"))
    elif eff_type == "RGBShiftEffect":
        return RGBShiftEffect(start_shift=params.get("start_shift", 0.0), end_shift=params.get("end_shift", 0.0), angle=params.get("angle", 0.0), easing=params.get("easing", "linear"))
    elif eff_type == "ColorAdjustEffect":
        return ColorAdjustEffect(start_params=params.get("start_params", {}), end_params=params.get("end_params", {}), easing=params.get("easing", "linear"))
    elif eff_type == "BlurEffect":
        return BlurEffect(start_blur=params.get("start_blur", 0), end_blur=params.get("end_blur", 0), easing=params.get("easing", "linear"))
    elif eff_type == "ZoomToPoint":
        return ZoomToPoint(center=tuple(params.get("center", (0.5, 0.5))), start_zoom=params.get("start_zoom", 1.0), end_zoom=params.get("end_zoom", 1.0), easing=params.get("easing", "ease_in_out"))
    elif eff_type == "KenBurnsEffect":
        return KenBurnsEffect(center=tuple(params.get("center", (0.5, 0.5))), zoom_out=params.get("zoom_out", 1.06), zoom_in=params.get("zoom_in", 1.18), drift_x=params.get("drift_x", 0.02), drift_y=params.get("drift_y", 0.01), easing=params.get("easing", "linear"))
    elif eff_type == "PanelSlideEffect":
        return PanelSlideEffect(direction=params.get("direction", "left"), start_offset=params.get("start_offset", 1.0), end_offset=params.get("end_offset", 0.0), easing=params.get("easing", "ease_out"))
    elif eff_type == "PanelPulseEffect":
        return PanelPulseEffect(start_scale=params.get("start_scale", 1.0), pulse_scale=params.get("pulse_scale", 1.12), end_scale=params.get("end_scale", 1.0), easing=params.get("easing", "ease_out"))
    elif eff_type == "GridScanEffect":
        return GridScanEffect(num_bars=params.get("num_bars", 240.0), bar_speed=params.get("bar_speed", 0.8), bar_width=params.get("bar_width", 0.05), easing=params.get("easing", "linear"))
    elif eff_type == "GridFlashEffect":
        return GridFlashEffect(intensity=params.get("intensity", 0.5), easing=params.get("easing", "linear"))
    elif eff_type == "GridGlitchEffect":
        return GridGlitchEffect(intensity=params.get("intensity", 1.0), easing=params.get("easing", "linear"))
    elif eff_type == "GridWaveWarpEffect":
        return GridWaveWarpEffect(frequency=params.get("frequency", 20.0), amplitude=params.get("amplitude", 0.03), speed=params.get("speed", 5.0), easing=params.get("easing", "linear"))
    elif eff_type == "GridPixelateEffect":
        return GridPixelateEffect(max_pixels=params.get("max_pixels", 400.0), min_pixels=params.get("min_pixels", 25.0), easing=params.get("easing", "linear"))
    elif eff_type == "GridChromaticEffect":
        return GridChromaticEffect(intensity=params.get("intensity", 1.0), angle=params.get("angle", 0.0), easing=params.get("easing", "linear"))
    elif eff_type == "PanelBounceEffect":
        return PanelBounceEffect(direction=params.get("direction", "up"), amplitude=params.get("amplitude", 0.06), easing=params.get("easing", "ease_out"))
    elif eff_type == "PanelSpinEffect":
        return PanelSpinEffect(max_angle=params.get("max_angle", 3.0), easing=params.get("easing", "ease_out"))
    elif eff_type == "YoloEmissionEffect":
        return YoloEmissionEffect(inner_color=tuple(params.get("inner_color", [180, 220, 255])), outer_color=tuple(params.get("outer_color", [30, 80, 255])), inner_radius=params.get("inner_radius", 15), outer_radius=params.get("outer_radius", 51), intensity=params.get("intensity", 1.0), pulse_speed=params.get("pulse_speed", 2.5), pulse_amplitude=params.get("pulse_amplitude", 0.15), easing=params.get("easing", "ease_in_out"))
    elif eff_type == "YoloTextEffect":
        return YoloTextEffect(text=params.get("text", ""), font_path=params.get("font_path"), font_size=params.get("font_size", 80), position=params.get("position", "bottom_center"), color=tuple(params.get("color", [255, 255, 255])), opacity=params.get("opacity", 1.0), transition_in=params.get("transition_in", 0.5), transition_out=params.get("transition_out", 0.5), animate_in=params.get("animate_in", "slide_up"), animate_out=params.get("animate_out", "fade"), stroke_width=params.get("stroke_width", 0), stroke_color=tuple(params.get("stroke_color", [0, 0, 0])), model_path="models/yolo26n-seg_int8_openvino_model/", depth_composite=params.get("depth_composite", True), line_spacing=params.get("line_spacing", 1.1), easing=params.get("easing", "linear"))
    return None
