import os
import tempfile
from typing import Optional

import cv2
import numpy as np

from utils.effects import (
    BlurEffect, ColorAdjustEffect, RGBShiftEffect, ZoomEffect, ZoomToPoint,
    KenBurnsEffect, PanelSlideEffect, PanelPulseEffect, GridScanEffect,
    GridFlashEffect, GridGlitchEffect, GridWaveWarpEffect, GridPixelateEffect,
    GridChromaticEffect, PanelBounceEffect, PanelSpinEffect,
    YoloEmissionEffect, YoloTextEffect,
)
from utils.grid import GridPanel, GridScene
from utils.pipeline import VideoPipeline
from utils.serialization import deserialize_effect, deserialize_transition

PREVIEW_TARGET_HEIGHT = 360


def _preview_size(output_size: tuple[int, int]) -> tuple[int, int]:
    w, h = output_size
    if h <= 0:
        return (640, 360)
    scale = PREVIEW_TARGET_HEIGHT / h
    return (int(round(w * scale)), PREVIEW_TARGET_HEIGHT)


def build_pipeline_from_plan(plan: dict) -> VideoPipeline:
    pipeline = VideoPipeline(
        fps=plan.get("fps", 30.0),
        output_size=tuple(plan.get("output_size", (854, 480))),
        resize_mode=plan.get("resize_mode", "fill"),
    )

    for ge in plan.get("global_effects", []):
        eff = deserialize_effect(ge)
        if eff:
            pipeline.add_effect(eff, ge.get("start_time", 0.0), ge.get("duration", -1.0))

    for scene in plan.get("scenes", []):
        is_grid = scene.get("is_grid", False)
        video_file = scene.get("video_file", "")
        trans_data = scene.get("transition")

        if is_grid:
            _add_grid_scene_to_pipeline(pipeline, scene)
        else:
            for clip in scene.get("clips", []):
                pipeline.add_clip(
                    filepath=clip.get("filepath", video_file),
                    start_time=clip.get("start_time", 0.0),
                    duration=clip.get("duration", 1.0),
                    speed=clip.get("speed", 1.0),
                    keep_audio=False,
                )
                clip_idx = len(pipeline.clips) - 1
                for eff_data in clip.get("effects", []):
                    eff = deserialize_effect(eff_data)
                    if eff:
                        pipeline.add_clip_effect(
                            clip_idx,
                            eff,
                            eff_data.get("start_time", 0.0),
                            eff_data.get("duration", -1.0),
                        )

        if trans_data:
            trans = deserialize_transition(trans_data)
            pipeline.transitions.append(trans if trans else None)
        else:
            pipeline.transitions.append(None)

    return pipeline


def _add_grid_scene_to_pipeline(pipeline: VideoPipeline, scene: dict):
    panels_data = scene.get("clips", [])
    video_file = scene.get("video_file", "")

    if not panels_data:
        pipeline.add_clip(filepath=video_file, start_time=0.0, duration=scene.get("out_dur", 1.0), keep_audio=False)
        return

    grid_panels = []
    for pd in panels_data:
        panels_list = pd.get("panels", [])
        if panels_list:
            for pp in panels_list:
                ref_idx = pp.get("ref_panel_idx")
                if ref_idx is not None and ref_idx < len(grid_panels):
                    p = GridPanel(ref_panel=grid_panels[ref_idx], flip=pp.get("flip"))
                elif pp.get("file"):
                    p = GridPanel(
                        pp["file"],
                        start_time=pp.get("start_time", 0.0),
                        speed=pp.get("speed", 1.0),
                        flip=pp.get("flip"),
                    )
                else:
                    continue
                for eff_data in pp.get("effects", []):
                    eff = deserialize_effect(eff_data)
                    if eff:
                        p.add_effect(eff, eff_data.get("start_time", 0.0), eff_data.get("duration", -1.0))
                grid_panels.append(p)
            break

    if not grid_panels:
        pipeline.add_clip(filepath=video_file, start_time=0.0, duration=scene.get("out_dur", 1.0), keep_audio=False)
        return

    gs = GridScene(
        panels=grid_panels,
        layout=(1, len(grid_panels)),
        duration=scene.get("out_dur", 1.0),
        col_weights=[1] * len(grid_panels),
        gap=0.003,
    )
    pipeline.add_grid_scene(gs)


def get_plan_metadata(plan: dict) -> dict:
    total_dur = 0.0
    for scene in plan.get("scenes", []):
        total_dur += scene.get("out_dur", 0.0)

    clip_count = sum(len(scene.get("clips", [])) for scene in plan.get("scenes", []))
    effect_count = 0
    for scene in plan.get("scenes", []):
        for clip in scene.get("clips", []):
            effect_count += len(clip.get("effects", []))
    effect_count += len(plan.get("global_effects", []))

    return {
        "duration": total_dur,
        "fps": plan.get("fps", 30.0),
        "output_size": plan.get("output_size", [854, 480]),
        "scene_count": len(plan.get("scenes", [])),
        "clip_count": clip_count,
        "effect_count": effect_count,
        "has_audio": bool(plan.get("audio_path")),
    }


def render_frame_at_time(pipeline: VideoPipeline, time_sec: float) -> Optional[bytes]:
    if not pipeline.clips:
        return None

    target_size = _preview_size(pipeline.output_size)

    clip_durations = []
    total_clips = len(pipeline.clips)
    for i, c in enumerate(pipeline.clips):
        cd = c["duration"]
        has_trans = i < len(pipeline.transitions) and i + 1 < total_clips and pipeline.transitions[i] is not None
        td = pipeline.transitions[i].duration if has_trans else 0.0
        clip_durations.append((cd, td))

    cumulative = 0.0
    target_clip = -1
    target_is_transition = False
    trans_progress = 0.0
    local_time = 0.0

    for i, (cd, td) in enumerate(clip_durations):
        clip_end = cumulative + cd
        if time_sec < clip_end:
            target_clip = i
            target_is_transition = False
            local_time = time_sec - cumulative
            break
        cumulative = clip_end

        if td > 0:
            trans_end = cumulative + td
            if time_sec < trans_end:
                target_clip = i
                target_is_transition = True
                trans_progress = (time_sec - cumulative) / td
                local_time = cd
                break
            cumulative = trans_end

    if target_clip < 0:
        target_clip = len(pipeline.clips) - 1
        target_is_transition = False
        cd, td = clip_durations[target_clip]
        local_time = min(time_sec - cumulative + cd, cd)

    c = pipeline.clips[target_clip]
    resize_mode = c.get("resize_mode", pipeline.resize_mode)

    if target_is_transition and target_clip + 1 < total_clips and pipeline.transitions[target_clip]:
        transition = pipeline.transitions[target_clip]
        next_c = pipeline.clips[target_clip + 1]
        next_resize = next_c.get("resize_mode", pipeline.resize_mode)

        frame1 = _seek_frame_in_clip(c, local_time, target_size, resize_mode)
        frame2 = _seek_frame_in_clip(next_c, 0.0, target_size, next_resize)

        if frame1 is None or frame2 is None:
            return None

        frame1 = _apply_local_effects(frame1, c, local_time)
        frame2 = _apply_local_effects(frame2, next_c, 0.0)
        blended = transition.process(frame1, frame2, trans_progress)
        blended = _apply_global_effects(blended, pipeline.effects, time_sec)
        _, buf = cv2.imencode(".jpg", blended, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()
    else:
        frame = _seek_frame_in_clip(c, local_time, target_size, resize_mode)
        if frame is None:
            return None
        frame = _apply_local_effects(frame, c, local_time)
        frame = _apply_global_effects(frame, pipeline.effects, time_sec)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()


def _seek_frame_in_clip(clip: dict, local_time: float, target_size: tuple, resize_mode: str = "fill") -> Optional[np.ndarray]:
    ctype = clip.get("type", "clip")
    if ctype == "grid" or ctype == "layered":
        return clip.get("scene", clip).render_frame(local_time, target_size)

    filepath = clip.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        return None

    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    source_start = clip.get("start_time", 0.0)
    speed = clip.get("speed", 1.0)

    source_time = (source_start + local_time * speed) % max(0.001, total_frames / fps) if total_frames > 0 else source_start + local_time * speed
    src_frame_idx = max(0, min(int(source_time * fps), total_frames - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return None

    return _resize_frame(frame, target_size, resize_mode)


def _resize_frame(frame: np.ndarray, target_size: tuple, mode: str = "fill") -> np.ndarray:
    h, w = frame.shape[:2]
    tw, th = target_size
    if tw <= 0 or th <= 0:
        return np.zeros((max(1, th), max(1, tw), 3), dtype=np.uint8)

    if mode == "stretch":
        return cv2.resize(frame, (tw, th))

    if mode == "fill":
        scale = max(tw / w, th / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        if nw < tw: nw = tw
        if nh < th: nh = th
        resized = cv2.resize(frame, (nw, nh))
        y1 = (nh - th) // 2
        x1 = (nw - tw) // 2
        out_frame = resized[y1: y1 + th, x1: x1 + tw]
    else:  # fit
        scale = min(tw / w, th / h)
        nw, nh = int(w * scale), int(h * scale)
        if nw == 0 or nh == 0:
            return np.zeros((th, tw, 3), dtype=np.uint8)
        resized = cv2.resize(frame, (nw, nh))
        out_frame = np.zeros((th, tw, 3), dtype=np.uint8)
        y_offset = max(0, (th - nh) // 2)
        x_offset = max(0, (tw - nw) // 2)
        rh, rw = resized.shape[:2]
        out_frame[y_offset: y_offset + rh, x_offset: x_offset + rw] = resized

    if out_frame.shape[:2] != (th, tw):
        out_frame = cv2.resize(out_frame, (tw, th))
    return out_frame


def _apply_local_effects(frame: np.ndarray, clip: dict, local_time: float) -> np.ndarray:
    c_dur = clip["duration"]
    for eff_entry in clip.get("effects", []):
        eff = eff_entry.get("effect")
        if eff is None:
            continue
        eff_start = eff_entry["start_time"]
        eff_dur = eff_entry["duration"] if eff_entry["duration"] > 0 else max(0.001, c_dur - eff_start)
        eff_end = eff_start + eff_dur
        if eff_start <= local_time <= eff_end:
            progress = min(1.0, max(0.0, (local_time - eff_start) / eff_dur))
            effect_time = local_time - eff_start
            frame = eff.process(frame, effect_time, progress)
    return frame


def _apply_global_effects(frame: np.ndarray, effects: list, time_sec: float) -> np.ndarray:
    for eff_entry in sorted(effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
        eff = eff_entry["effect"]
        eff_start = eff_entry["start_time"]
        eff_dur = eff_entry["duration"]
        eff_end = eff_start + eff_dur if eff_dur > 0 else 999999.0
        if eff_start <= time_sec <= eff_end:
            if eff_dur > 0:
                progress = (time_sec - eff_start) / eff_dur
            else:
                progress = 1.0
            progress = min(1.0, max(0.0, progress))
            effect_time = time_sec - eff_start
            frame = eff.process(frame, effect_time, progress)
    return frame


def render_segment(pipeline: VideoPipeline, start_sec: float, duration_sec: float) -> Optional[bytes]:
    target_size = _preview_size(pipeline.output_size)

    frames: list[np.ndarray] = []
    max_frames = int(duration_sec * pipeline.fps)
    frame_dt = 1.0 / pipeline.fps

    for i in range(max_frames):
        t = start_sec + i * frame_dt
        frame_bytes = render_frame_at_time(pipeline, t)
        if frame_bytes is None:
            break
        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        frames.append(frame)

    if not frames:
        return None

    import subprocess
    w, h = target_size
    fps = pipeline.fps

    temp_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-crf", "23",
            temp_path
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        for f in frames:
            proc.stdin.write(f.tobytes())
        proc.stdin.close()
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr.read().decode()}")

        with open(temp_path, "rb") as f:
            data = f.read()
        return data
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
