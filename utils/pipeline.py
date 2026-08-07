from typing import Any, List, Optional, Union

import cv2
import numpy as np

from utils.base import BaseEffect, BaseTransition
from utils.grid import GridScene, LayeredScene

CLIP_END = "clip_end"
_CLIP_END_INT = -1.0


class VideoPipeline:
    def __init__(self, fps: float = 30.0, output_size: tuple = (1980, 1080), resize_mode: str = "fit"):
        self.fps = fps
        self.output_size = output_size
        self.resize_mode = resize_mode
        self.clips = []
        self.transitions = []
        self.effects = []

    def add_clip(self, filepath: str, start_time: float = 0, duration: float = -1,
                 keep_audio: bool = True, speed: float = 1.0, resize_mode: Optional[str] = None):
        self.clips.append({
            "type": "clip",
            "filepath": filepath,
            "start_time": start_time,
            "duration": duration,
            "keep_audio": keep_audio,
            "speed": speed,
            "resize_mode": resize_mode or self.resize_mode,
            "effects": [],
        })

    def add_grid_scene(self, scene: GridScene):
        self.clips.append({"type": "grid", "scene": scene, "duration": scene.duration, "effects": []})

    def add_layered_scene(self, scene: LayeredScene):
        self.clips.append({"type": "layered", "scene": scene, "duration": scene.duration, "effects": []})

    def add_transition(self, transition: BaseTransition):
        self.transitions.append(transition)

    def add_effect(self, effect: BaseEffect, start_time: float = 0.0, duration: Union[float, str] = CLIP_END):
        self.effects.append({"effect": effect, "start_time": start_time, "duration": self._resolve_dur(duration)})

    def add_clip_effect(self, clip_idx: int, effect: BaseEffect, start_time: float = 0.0,
                        duration: Union[float, str] = CLIP_END):
        self.clips[clip_idx]["effects"].append({
            "effect": effect, "start_time": start_time, "duration": self._resolve_dur(duration),
        })

    @staticmethod
    def _resolve_dur(duration) -> float:
        if duration is CLIP_END or (isinstance(duration, (int, float)) and duration < 0):
            return _CLIP_END_INT
        return float(duration)

    def _build_effects_from_props(self, from_props: dict, to_props: dict, easing) -> list:
        from utils.effects import BlurEffect, ColorAdjustEffect, RGBShiftEffect, ZoomEffect, ZoomToPoint
        effects: List[BaseEffect] = []

        blur_keys = {"blur"}
        if blur_keys & (from_props.keys() | to_props.keys()):
            effects.append(BlurEffect(start_blur=from_props.get("blur", 0), end_blur=to_props.get("blur", 0), easing=easing))

        shift_keys = {"rgb_shift", "rgb_shift_angle"}
        if shift_keys & (from_props.keys() | to_props.keys()):
            angle = to_props.get("rgb_shift_angle", from_props.get("rgb_shift_angle", 0.0))
            effects.append(RGBShiftEffect(
                start_shift=from_props.get("rgb_shift", 0.0), end_shift=to_props.get("rgb_shift", 0.0),
                angle=angle, easing=easing,
            ))

        if "zoom" in (from_props.keys() | to_props.keys()):
            effects.append(ZoomEffect(start_zoom=from_props.get("zoom", 1.0), end_zoom=to_props.get("zoom", 1.0), easing=easing))

        ztp_raw = to_props.get("zoom_to_point") or from_props.get("zoom_to_point")
        if ztp_raw:
            if isinstance(ztp_raw, dict):
                center = ztp_raw.get("center", (0.5, 0.5))
                start_z = ztp_raw.get("start_zoom", from_props.get("zoom", 1.0))
                end_z = ztp_raw.get("end_zoom", to_props.get("zoom", 1.0))
            else:
                center = ztp_raw
                start_z = from_props.get("zoom", 1.0)
                end_z = to_props.get("zoom", 1.0)
            effects.append(ZoomToPoint(center=center, start_zoom=start_z, end_zoom=end_z, easing=easing))

        color_keys = {"saturation", "brightness", "contrast", "gamma"}
        if color_keys & (from_props.keys() | to_props.keys()):
            effects.append(ColorAdjustEffect(
                start_params={k: from_props[k] for k in color_keys if k in from_props},
                end_params={k: to_props[k] for k in color_keys if k in to_props},
                easing=easing,
            ))

        return effects

    def to(self, clip_idx: int, duration: Union[float, str] = CLIP_END, start_time: float = 0.0,
           easing="linear", **props):
        neutral = {"blur": 0, "rgb_shift": 0.0, "zoom": 1.0, "saturation": 1.0,
                   "brightness": 0.0, "contrast": 1.0, "gamma": 1.0}
        from_props = {k: neutral[k] for k in props if k in neutral}
        for eff in self._build_effects_from_props(from_props, props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def from_(self, clip_idx: int, duration: Union[float, str] = CLIP_END, start_time: float = 0.0,
              easing="linear", **props):
        neutral = {"blur": 0, "rgb_shift": 0.0, "zoom": 1.0, "saturation": 1.0,
                   "brightness": 0.0, "contrast": 1.0, "gamma": 1.0}
        to_props = {k: neutral[k] for k in props if k in neutral}
        for eff in self._build_effects_from_props(props, to_props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def fromTo(self, clip_idx: int, duration: Union[float, str] = CLIP_END,
               from_props: Optional[dict] = None, to_props: Optional[dict] = None,
               start_time: float = 0.0, easing="linear"):
        from_props = from_props or {}
        to_props = to_props or {}
        for eff in self._build_effects_from_props(from_props, to_props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def render(self, output_path: str):
        if not self.clips:
            print("No clips added.")
            return

        import gc
        import os
        import subprocess
        import glob
        import sys
        import time

        from utils.audio import extract_clip_audio, merge_audio_segments, mux_video_audio

        try:
            from tqdm import tqdm as _tqdm
        except ImportError:
            def _tqdm(iterable, desc="", unit="", total=None, disable=False):
                if disable:
                    yield from iterable
                    return
                start = time.time()
                total = total or len(iterable) if hasattr(iterable, '__len__') else None
                for i, item in enumerate(iterable):
                    elapsed = time.time() - start
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    pct = f"{100.0 * (i + 1) / total:.0f}%" if total else f"{i + 1}"
                    bar_len = 30
                    if total:
                        filled = int(bar_len * (i + 1) / total)
                        bar = "█" * filled + "░" * (bar_len - filled)
                        sys.stdout.write(f"\r{desc}: |{bar}| {pct}  {i + 1}/{total}  [{rate:.0f}it/s]")
                    else:
                        sys.stdout.write(f"\r{desc}: {pct} items  [{rate:.0f}it/s]")
                    sys.stdout.flush()
                    yield item
                if not disable:
                    sys.stdout.write("\n")

        try:
            from pydub import AudioSegment
        except ImportError:
            print("pydub not installed. Running without audio.")
            AudioSegment = None

        temp_video_path = "temp_video_output.mp4"
        fourcc = getattr(cv2, "VideoWriter_fourcc")(*"mp4v")
        out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, self.output_size)

        audio_segments = []
        _audio_seg_counter = [0]

        any_audio = False
        for c in self.clips:
            if c.get("type", "clip") == "clip":
                if c.get("keep_audio", True):
                    any_audio = True
                    break
            else:
                if c["scene"].keep_audio is not None:
                    any_audio = True
                    break

        if AudioSegment is None:
            any_audio = False

        # ── Calculate total frame count for progress bar ──────────────
        total_frames = 0
        for i, c in enumerate(self.clips):
            if c.get("type", "clip") == "clip":
                if c["duration"] <= 0:
                    _probe = cv2.VideoCapture(c["filepath"])
                    if not _probe.isOpened():
                        print(f"Failed to open video: {c['filepath']}")
                        return
                    tf = _probe.get(cv2.CAP_PROP_FRAME_COUNT)
                    sfps = _probe.get(cv2.CAP_PROP_FPS)
                    sfps = sfps if sfps > 0 else 30.0
                    source_dur = tf / sfps if sfps > 0 and tf > 0 else 1.0
                    c["duration"] = source_dur / c.get("speed", 1.0)
                    _probe.release()
                else:
                    _probe = cv2.VideoCapture(c["filepath"])
                    _probe.release()
            cd = c["duration"]
            has_trans = i < len(self.transitions) and i + 1 < len(self.clips) and self.transitions[i] is not None
            td = self.transitions[i].duration if has_trans else 0.0
            clip_frames = int(max(0, cd - td) * self.fps)
            trans_frames = int(td * self.fps) if has_trans else 0
            total_frames += clip_frames + trans_frames

        pbar = _tqdm(total=total_frames, desc="Rendering", unit="frame", disable=total_frames == 0)

        try:
            caps: List[Any] = [None] * len(self.clips)
            clip_source_fps = [30.0] * len(self.clips)

            def _open_cap(i):
                c = self.clips[i]
                if c.get("type", "clip") in ("grid", "layered"):
                    if caps[i] is None:
                        c["scene"].open_panels()
                        caps[i] = "scene"
                    return
                if caps[i] is None:
                    cap = cv2.VideoCapture(c["filepath"])
                    caps[i] = cap
                    sfps = cap.get(cv2.CAP_PROP_FPS)
                    clip_source_fps[i] = sfps if sfps > 0 else 30.0

            def _release_cap(i):
                c = self.clips[i]
                if c.get("type", "clip") in ("grid", "layered"):
                    if caps[i] == "scene":
                        c["scene"].release_panels()
                        caps[i] = None
                elif caps[i] is not None:
                    caps[i].release()
                    caps[i] = None

            clip_pos = {i: 0 for i in range(len(self.clips))}

            for i, c in enumerate(self.clips):
                if c.get("type", "clip") == "clip" and c["duration"] <= 0:
                    _probe = cv2.VideoCapture(c["filepath"])
                    if not _probe.isOpened():
                        print(f"Failed to open video: {c['filepath']}")
                        _probe.release()
                        return
                    total_frames_probe = _probe.get(cv2.CAP_PROP_FRAME_COUNT)
                    sfps = _probe.get(cv2.CAP_PROP_FPS)
                    sfps = sfps if sfps > 0 else 30.0
                    clip_source_fps[i] = sfps
                    if sfps > 0 and total_frames_probe > 0:
                        source_dur = total_frames_probe / sfps
                        c["duration"] = source_dur / c.get("speed", 1.0)
                    else:
                        c["duration"] = 1.0
                    _probe.release()
                elif c.get("type", "clip") == "clip":
                    _probe = cv2.VideoCapture(c["filepath"])
                    sfps = _probe.get(cv2.CAP_PROP_FPS)
                    clip_source_fps[i] = sfps if sfps > 0 else 30.0
                    _probe.release()
                else:
                    c["duration"] = c["scene"].duration

                def _resize_frame(frame, target_size, mode="fit"):
                h, w = frame.shape[:2]
                tw, th = target_size
                if mode == "fill":
                    scale = max(tw / w, th / h)
                    nw, nh = int(round(w * scale)), int(round(h * scale))
                    if nw < tw: nw = tw
                    if nh < th: nh = th
                    resized = cv2.resize(frame, (nw, nh))
                    y1 = (nh - th) // 2
                    x1 = (nw - tw) // 2
                    out_frame = resized[y1: y1 + th, x1: x1 + tw]
                else:
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

            def seek_frame(clip_idx, local_output_time, target_size):
                c = self.clips[clip_idx]
                speed = c.get("speed", 1.0)
                _open_cap(clip_idx)
                cap = caps[clip_idx]
                fps = clip_source_fps[clip_idx]
                total_frames_seek = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                source_dur = total_frames_seek / fps
                if source_dur > 0:
                    source_time = (c.get("start_time", 0.0) + local_output_time * speed) % source_dur
                else:
                    source_time = c.get("start_time", 0.0) + local_output_time * speed
                src_frame_idx = int(source_time * fps)
                src_frame_idx = max(0, min(src_frame_idx, total_frames_seek - 1))
                if src_frame_idx == clip_pos[clip_idx]:
                    pass
                elif src_frame_idx > clip_pos[clip_idx] and src_frame_idx - clip_pos[clip_idx] < 5:
                    for _ in range(src_frame_idx - clip_pos[clip_idx]):
                        cap.grab()
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, src_frame_idx)
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames_seek - 1))
                    ret, frame = cap.read()
                    if not ret:
                        return False, None
                clip_pos[clip_idx] = src_frame_idx + 1
                out_frame = _resize_frame(frame, target_size, mode=c.get("resize_mode", "fit"))
                return (True, out_frame) if out_frame is not None else (False, None)

            def get_frame_for_timeline_item(clip_idx, local_output_time, target_size):
                c = self.clips[clip_idx]
                if c.get("type", "clip") == "clip":
                    return seek_frame(clip_idx, local_output_time, target_size)
                else:
                    frame = c["scene"].render_frame(local_output_time, target_size)
                    return True, frame

            current_clip_idx = 0
            current_time = 0.0
            clip_local_times = [0.0] * len(self.clips)

            while current_clip_idx < len(self.clips):
                clip_info = self.clips[current_clip_idx]
                clip_dur = clip_info["duration"]

                if any_audio:
                    if clip_info.get("type", "clip") == "clip":
                        clip_keep_audio = clip_info.get("keep_audio", True)
                        filepath = clip_info["filepath"]
                        start_time = clip_info.get("start_time", 0.0)
                        clip_speed = clip_info.get("speed", 1.0)
                    else:
                        scene = clip_info["scene"]
                        elements = getattr(scene, "panels", getattr(scene, "layers", []))
                        if scene.keep_audio is not None and scene.keep_audio < len(elements):
                            p = elements[scene.keep_audio]
                            ref = p
                            while getattr(ref, "ref_panel", getattr(ref, "ref_layer", None)) is not None:
                                ref = getattr(ref, "ref_panel", getattr(ref, "ref_layer", None))
                            if ref is None:
                                filepath = None
                                start_time = 0.0
                                clip_speed = 1.0
                                clip_keep_audio = False
                            else:
                                filepath = ref.filepath
                                clip_keep_audio = True
                                start_time = ref.start_time
                                clip_speed = ref.speed
                        else:
                            clip_keep_audio = False
                            filepath = None
                            start_time = 0.0
                            clip_speed = 1.0

                    out_dur_ms = int(clip_dur * 1000)
                    seg_path = extract_clip_audio(
                        filepath or "", start_time, clip_dur, clip_speed,
                        clip_keep_audio, out_dur_ms, _audio_seg_counter, AudioSegment,
                    )
                    prev_trans = (
                        self.transitions[current_clip_idx - 1]
                        if current_clip_idx > 0 and current_clip_idx - 1 < len(self.transitions)
                        else None
                    )
                    crossfade_ms = int(prev_trans.duration * 1000) if prev_trans else 0
                    audio_segments.append({"path": seg_path, "crossfade_ms": crossfade_ms})

                has_transition = current_clip_idx < len(self.transitions) and current_clip_idx + 1 < len(self.clips)
                transition = self.transitions[current_clip_idx] if has_transition else None
                trans_duration = transition.duration if transition else 0.0

                frames_to_read = int((clip_dur - trans_duration) * self.fps)
                trans_frames = int(trans_duration * self.fps)

                def apply_local_effects(frame, clip_dict, local_time):
                    c_dur = clip_dict["duration"]
                    for eff in sorted(clip_dict["effects"], key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
                        eff_start = eff["start_time"]
                        eff_dur = eff["duration"] if eff["duration"] > 0 else max(0.001, c_dur - eff_start)
                        eff_end = eff_start + eff_dur
                        if eff_start <= local_time <= eff_end:
                            progress = min(1.0, max(0.0, (local_time - eff_start) / eff_dur))
                            effect_time = local_time - eff_start
                            frame = eff["effect"].process(frame, effect_time, progress)
                    return frame

                def apply_global_effects(frame, time_val):
                    for eff in sorted(self.effects, key=lambda e: not hasattr(e["effect"], '_yolo_priority')):
                        eff_start = eff["start_time"]
                        eff_dur = eff["duration"]
                        eff_end = eff_start + eff_dur if eff_dur > 0 else 999999.0
                        if eff_start <= time_val <= eff_end:
                            if eff_dur > 0:
                                progress = (time_val - eff_start) / eff_dur
                                effect_time = time_val - eff_start
                            else:
                                progress = 1.0
                                effect_time = time_val - eff_start
                            progress = min(1.0, max(0.0, progress))
                            frame = eff["effect"].process(frame, effect_time, progress)
                    return frame

                _open_cap(current_clip_idx)
                if has_transition and current_clip_idx + 1 < len(self.clips):
                    _open_cap(current_clip_idx + 1)

                for _ in range(frames_to_read):
                    ret, frame = get_frame_for_timeline_item(current_clip_idx, clip_local_times[current_clip_idx], self.output_size)
                    if not ret:
                        break
                    frame = apply_local_effects(frame, self.clips[current_clip_idx], clip_local_times[current_clip_idx])
                    frame = apply_global_effects(frame, current_time)
                    out.write(frame)
                    pbar.update(1)
                    current_time += 1.0 / self.fps
                    clip_local_times[current_clip_idx] += 1.0 / self.fps

                if has_transition and trans_frames > 0:
                    next_clip_idx = current_clip_idx + 1
                    for t_f in range(trans_frames):
                        ret1, frame1 = get_frame_for_timeline_item(current_clip_idx, clip_local_times[current_clip_idx], self.output_size)
                        ret2, frame2 = get_frame_for_timeline_item(next_clip_idx, clip_local_times[next_clip_idx], self.output_size)
                        if not ret1 or not ret2:
                            break
                        frame1 = apply_local_effects(frame1, self.clips[current_clip_idx], clip_local_times[current_clip_idx])
                        frame2 = apply_local_effects(frame2, self.clips[next_clip_idx], clip_local_times[next_clip_idx])
                        progress = t_f / float(trans_frames)
                        blended = transition.process(frame1, frame2, progress) if transition else frame1
                        blended = apply_global_effects(blended, current_time)
                        out.write(blended)
                        pbar.update(1)
                        current_time += 1.0 / self.fps
                        clip_local_times[current_clip_idx] += 1.0 / self.fps
                        clip_local_times[next_clip_idx] += 1.0 / self.fps

                _release_cap(current_clip_idx)
                gc.collect()
                current_clip_idx += 1

            for i in range(len(self.clips)):
                _release_cap(i)
            gc.collect()
            out.release()
            pbar.close()

            if audio_segments:
                print("Merging audio segments and muxing...")
                temp_audio_path = merge_audio_segments(audio_segments, AudioSegment)
                mux_video_audio(temp_video_path, temp_audio_path, output_path)
                for p in (temp_video_path, temp_audio_path):
                    if os.path.exists(p):
                        os.remove(p)
                print(f"Render complete with audio: {output_path}")
            else:
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_video_path, output_path)
                print(f"Render complete: {output_path}")

        except Exception:
            raise
        finally:
            for i in range(len(self.clips)):
                try:
                    _release_cap(i)
                except Exception:
                    pass
            try:
                out.release()
            except Exception:
                pass
            for seg in audio_segments:
                p = seg.get("path", "")
                if p and os.path.exists(p):
                    os.remove(p)
            for p in glob.glob("_audio_seg_*.wav"):
                if os.path.exists(p):
                    os.remove(p)
