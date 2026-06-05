import json
import os
import random
import re
import subprocess

import numpy as np
from mutagen.mp4 import MP4

from utils.pipeline import CLIP_END, VideoPipeline
from utils.effects import (
    BlurEffect, ColorAdjustEffect, GridChromaticEffect, GridFlashEffect,
    GridGlitchEffect, GridPixelateEffect, GridScanEffect, GridWaveWarpEffect,
    KenBurnsEffect, PanelBounceEffect, PanelPulseEffect, PanelSlideEffect,
    PanelSpinEffect, RGBShiftEffect, YoloEmissionEffect, YoloTextEffect,
    ZoomEffect, ZoomToPoint,
)
from utils.grid import GridPanel, GridScene
from utils.transitions import (
    FlashTransition, GridWipeTransition, RadialWipeTransition,
    SlideTransition, ZoomTransition,
)
from typing import Any, cast

from utils.grid import GridPanel, GridScene
from utils.config import CONFIG
from utils.serialization import deserialize_effect, deserialize_transition


def parse_timecode(tc):
    parts = tc.split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def parse_lrc(filepath):
    lyrics = []
    if not os.path.exists(filepath):
        return lyrics
    pattern = re.compile(r"\[(\d+):(\d+[\.\:]\d+)\](.*)")
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            match = pattern.match(line.strip())
            if match:
                m, s, text = match.groups()
                s = s.replace(":", ".")
                time = int(m) * 60 + float(s)
                if text.strip():
                    lyrics.append({"time": time, "text": text.strip()})
    return lyrics


def load_audio_metadata(path):
    a = MP4(path)
    meta = a.get("----:com.shiro.audio:metadata")
    if not meta:
        return None
    return json.loads(meta[0].decode("utf-8"))


def load_video_metadata(path):
    try:
        v = MP4(path)
        meta = v.get("----:com.shiro.video:metadata")
        if not meta:
            return None
        return json.loads(meta[0].decode("utf-8"))
    except Exception:
        return None


def cross_correlation_alignment(audio_points, video_points, search_range=2.0, bin_size=0.01):
    if not audio_points or not video_points:
        return 0.0
    diffs = [a - v for a in audio_points for v in video_points]
    diffs = [d for d in diffs if abs(d) <= search_range]
    if not diffs:
        return 0.0
    counts, bins = np.histogram(diffs, bins=np.arange(-search_range, search_range + bin_size, bin_size))
    best_bin = np.argmax(counts)
    return (bins[best_bin] + bins[best_bin + 1]) / 2


def dtw_alignment(audio_points, video_points):
    n, m = len(audio_points), len(video_points)
    if n == 0 or m == 0:
        return []
    dtw = np.full((n + 1, m + 1), float("inf"))
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(audio_points[i - 1] - video_points[j - 1])
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    path, i, j = [], n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        prev_cells = [(i - 1, j), (i, j - 1), (i - 1, j - 1)]
        i, j = prev_cells[int(np.argmin([dtw[c] for c in prev_cells]))]
    return path[::-1]


def add_clip(pipeline, file, start_time, duration, speed=1.0, is_grid=False,
             trans_dur=0.0, resize_mode="fill", grid_side=None, panels=None):
    total_dur = duration + trans_dur
    if total_dur <= 0:
        return
    if not is_grid:
        pipeline.add_clip(file, start_time=max(0.0, start_time), duration=total_dur,
                          speed=speed, keep_audio=False, resize_mode=resize_mode)
    elif panels:
        grid_panels: list[GridPanel] = []
        for p_data in panels:
            ref_idx = p_data.get("ref_panel_idx")
            if ref_idx is not None:
                p = GridPanel(ref_panel=grid_panels[ref_idx], flip=p_data.get("flip"), resize_mode=resize_mode)
            else:
                p = GridPanel(p_data["file"], start_time=max(0.0, p_data["start_time"]),
                              speed=p_data.get("speed", 1.0), flip=p_data.get("flip"), resize_mode=resize_mode)
            for eff_data in p_data.get("effects", []):
                eff_obj = deserialize_effect(eff_data)
                if eff_obj:
                    p.add_effect(eff_obj, start_time=eff_data.get("start_time", 0.0), duration=eff_data.get("duration", -1.0))
            grid_panels.append(p)
        gs = GridScene(panels=grid_panels, layout=(1, 3), duration=total_dur, col_weights=[1, 2, 1], gap=0.003)
        pipeline.add_grid_scene(gs)
    elif grid_side:
        p_side = GridPanel(grid_side["file"], start_time=max(0.0, grid_side["start_time"]),
                           speed=grid_side.get("speed", 1.0), resize_mode=resize_mode)
        p_center = GridPanel(file, start_time=max(0.0, start_time), speed=speed, resize_mode=resize_mode)
        p_mirror = GridPanel(ref_panel=p_side, flip="h", resize_mode=resize_mode)
        gs = GridScene(panels=[p_side, p_center, p_mirror], layout=(1, 3), duration=total_dur,
                       col_weights=[1, 2, 1], gap=0.003)
        pipeline.add_grid_scene(gs)
    else:
        p_center = GridPanel(file, start_time=max(0.0, start_time), speed=speed, resize_mode=resize_mode)
        p_left = GridPanel(ref_panel=p_center, flip="h", resize_mode=resize_mode)
        p_right = GridPanel(ref_panel=p_center, flip="h", resize_mode=resize_mode)
        gs = GridScene(panels=[p_left, p_center, p_right], layout=(1, 3), duration=total_dur,
                       col_weights=[1, 2, 1], gap=0.003)
        pipeline.add_grid_scene(gs)


def patch_plan(plan_data, patches):
    import copy
    plan_data = copy.deepcopy(plan_data)
    scenes = plan_data.get("scenes", [])
    for patch in patches:
        s_idx = patch.get("scene_idx")
        c_idx = patch.get("clip_idx")
        params = patch.get("params", {})
        if s_idx is None:
            print(f"[patch_plan] Warning: patch missing 'scene_idx', skipping: {patch}")
            continue
        if s_idx < 0 or s_idx >= len(scenes):
            print(f"[patch_plan] Warning: scene_idx {s_idx} out of range (0\u2013{len(scenes) - 1}), skipping.")
            continue
        scene = scenes[s_idx]
        if c_idx is None:
            for k, v in params.items():
                if k == "add_scene_effect":
                    plan_data.setdefault("global_effects", []).append(v)
                elif k == "clear_global_effects":
                    if v:
                        plan_data["global_effects"] = []
                else:
                    scene[k] = v
        else:
            clips = scene.get("clips", [])
            if c_idx < 0 or c_idx >= len(clips):
                print(f"[patch_plan] Warning: clip_idx {c_idx} out of range in scene {s_idx}, skipping.")
                continue
            clip = clips[c_idx]
            for k, v in params.items():
                if k == "add_effect":
                    clip.setdefault("effects", []).append(v)
                elif k == "clear_effects":
                    if v:
                        clip["effects"] = []
                elif k == "replace_effect":
                    e_idx, e_dict = v
                    effs = clip.setdefault("effects", [])
                    if 0 <= e_idx < len(effs):
                        effs[e_idx] = e_dict
                    else:
                        print(f"[patch_plan] Warning: effect_idx {e_idx} out of range in scene {s_idx} clip {c_idx}.")
                else:
                    clip[k] = v
    return plan_data


def generate_edit_plan(args):
    audio_path = "audios/Only Fire - Up n Down (Audio) [se9ZcIEN_gk].m4a"
    audio_meta = load_audio_metadata(audio_path)
    if not audio_meta:
        print("No audio metadata found!")
        return None
    major_beats, minor_beats = [], []
    for seg in audio_meta.get("segments", []):
        major_beats.extend(seg.get("major", []))
        minor_beats.extend(seg.get("minor", []))
    major_beats = sorted(set(major_beats))
    minor_beats = sorted(set(minor_beats))
    mp4_audio = MP4(audio_path)
    audio_total_dur = mp4_audio.info.length if mp4_audio.info is not None else 0.0
    if not major_beats:
        print("Warning: No major beats found. Using 2s periodic cuts.")
        t = 2.0
        while t < audio_total_dur - 1.0:
            major_beats.append(t)
            t += 2.0
    all_beats = sorted(set([0.0, audio_total_dur] + major_beats))
    max_clips = len(all_beats) - 1
    print(f"Audio: {audio_total_dur:.2f}s  |  {len(major_beats)} major beats  ->  {max_clips} intervals")
    if args.duration is not None:
        for i, b in enumerate(all_beats):
            if b >= args.duration:
                max_clips = max(1, i)
                break
    videos_data = []
    if not os.path.exists("videos"):
        print("No 'videos' directory found!")
        return None
    for fname in os.listdir("videos"):
        if not fname.endswith(".mp4"):
            continue
        vf = os.path.join("videos", fname)
        v_meta = load_video_metadata(vf)
        if not v_meta:
            continue
        try:
            mp4_v = MP4(vf)
            v_full_dur = mp4_v.info.length if mp4_v.info is not None else 0.0
        except Exception:
            v_full_dur = 0.0
        for seg in v_meta.get("segments", []):
            raw_acts = seg.get("meta", {}).get("actpoints", [])
            act_secs = sorted(parse_timecode(tp) for tp in raw_acts)
            interval = seg.get("interval", [0, v_full_dur])
            if interval[1] <= interval[0]:
                interval[1] = v_full_dur
            seg_tags = list(seg.get("tags", []))
            videos_data.append({
                "file": vf, "interval": interval, "actpoints": act_secs,
                "full_dur": v_full_dur, "tags": seg_tags,
            })
    if not videos_data:
        print("No video segments found in videos/!")
        return None
    videos_with_acts = [v for v in videos_data if len(v["actpoints"]) >= 2]
    if not videos_with_acts:
        print("Warning: No videos with \u22652 actpoints. Falling back to all videos (CC only).")
        videos_with_acts = videos_data
    print(f"Loaded {len(videos_data)} video segments ({len(videos_with_acts)} with actpoints)")
    plan_data = {
        "output_size": [640, 360], "fps": 30.0, "resize_mode": args.resize_mode,
        "audio_path": audio_path, "audio_total_dur": audio_total_dur,
        "global_effects": [], "scenes": [],
    }
    lyr_cfg = CONFIG["lyrics"]
    lyrics_file = lyr_cfg["file"]
    if os.path.exists(lyrics_file):
        lyrics = parse_lrc(lyrics_file)
        print(f"Loaded {len(lyrics)} lyric lines from {lyrics_file}")
        for i, lyr in enumerate(lyrics):
            lyr_start = lyr["time"]
            if i + 1 < len(lyrics):
                lyr_dur = min(lyrics[i + 1]["time"] - lyr_start, lyr_cfg["max_duration"])
            else:
                lyr_dur = lyr_cfg["max_duration"]
            lyr_dur = max(0.3, lyr_dur)
            plan_data["global_effects"].append({
                "type": "YoloTextEffect", "start_time": lyr_start, "duration": lyr_dur,
                "params": {
                    "text": lyr["text"], "font_path": lyr_cfg["font_path"],
                    "font_size": lyr_cfg["font_size"], "position": lyr_cfg["position"],
                    "color": lyr_cfg["color"], "opacity": lyr_cfg["opacity"],
                    "stroke_width": lyr_cfg["stroke_width"], "stroke_color": lyr_cfg["stroke_color"],
                    "depth_composite": lyr_cfg["depth_composite"],
                    "transition_in": lyr_cfg["transition_in"], "transition_out": lyr_cfg["transition_out"],
                    "animate_in": lyr_cfg["animate_in"], "animate_out": lyr_cfg["animate_out"],
                },
            })
    else:
        print(f"[lyrics] '{lyrics_file}' not found \u2014 skipping lyrics.")
    idx = 0
    last_v_file = None
    _span_cfg = CONFIG["span_weights"]
    while idx < max_clips:
        span = random.choices(_span_cfg["spans"], weights=_span_cfg["weights"])[0]
        end_idx = min(max_clips, idx + span)
        t_m1 = all_beats[idx]
        t_m2 = all_beats[end_idx]
        out_dur = t_m2 - t_m1
        if out_dur < 0.1:
            idx = end_idx
            continue
        minors_in_interval = [b for b in minor_beats if t_m1 < b < t_m2]
        filtered_minors = []
        last_t = t_m1
        for b in minors_in_interval:
            if b - last_t >= args.min_beat_gap:
                filtered_minors.append(b)
                last_t = b
        if filtered_minors and (t_m2 - filtered_minors[-1] < args.min_beat_gap):
            filtered_minors.pop()
        audio_points = [t_m1] + filtered_minors
        n_audio = len(audio_points)
        pre_dur = audio_points[0] - t_m1
        post_dur = t_m2 - audio_points[-1]
        use_align = not args.no_align
        grid_tag = getattr(args, "grid_tag", None)
        is_grid = random.random() < args.grid_chance
        candidates = []
        if use_align:
            for v in videos_with_acts:
                if len(v["actpoints"]) < n_audio:
                    continue
                v_start_act = v["actpoints"][0]
                v_end_act = v["actpoints"][-1]
                if (v_start_act - v["interval"][0] >= pre_dur) and (v["interval"][1] - v_end_act >= post_dur):
                    if is_grid and grid_tag:
                        if grid_tag in v.get("tags", []):
                            candidates.append(v)
                    else:
                        candidates.append(v)
            if not candidates:
                if is_grid and grid_tag:
                    candidates = [v for v in videos_with_acts if len(v["actpoints"]) >= n_audio and grid_tag in v.get("tags", [])]
                else:
                    candidates = [v for v in videos_with_acts if len(v["actpoints"]) >= n_audio]
        if not candidates:
            if is_grid and grid_tag:
                candidates = [v for v in videos_data if grid_tag in v.get("tags", [])]
                if not candidates:
                    is_grid = False
                    candidates = videos_with_acts if use_align else videos_data
            else:
                candidates = videos_with_acts if use_align else videos_data
        if len(candidates) > 1 and last_v_file:
            varied = [v for v in candidates if v["file"] != last_v_file]
            if varied:
                candidates = varied
        v_seg = random.choice(candidates)
        v_file = v_seg["file"]
        v_acts = v_seg["actpoints"]
        v_full_dur = v_seg.get("full_dur", 0.0)
        last_v_file = v_file
        if use_align and len(v_acts) >= 2 and n_audio >= 2:
            alignment_mode = random.choice(["cc", "dtw"])
        else:
            alignment_mode = "none"
        trans_data = None
        _trans_cfg = CONFIG["transitions"]
        if end_idx < max_clips:
            if random.random() < args.transition_chance:
                t_type = random.choices(_trans_cfg["types"], weights=_trans_cfg["types_weights"])[0]
                if t_type == "zoom":
                    trans_data = {"type": "zoom", "duration": _trans_cfg["duration"],
                                  "params": {"mode": random.choice(_trans_cfg["zoom_modes"]), "easing": "ease_in_out"}}
                elif t_type == "slide":
                    trans_data = {"type": "slide", "duration": _trans_cfg["duration"],
                                  "params": {"direction": random.choice(_trans_cfg["slide_directions"]), "easing": "ease_in_out"}}
                elif t_type == "grid_wipe":
                    trans_data = {"type": "grid_wipe", "duration": _trans_cfg["duration"],
                                  "params": {"cols": _trans_cfg.get("grid_wipe_cols", 6), "rows": _trans_cfg.get("grid_wipe_rows", 4),
                                             "stagger": random.choice(["row", "col"]), "easing": "ease_in_out"}}
                elif t_type == "flash":
                    trans_data = {"type": "flash", "duration": _trans_cfg["duration"],
                                  "params": {"color": _trans_cfg.get("flash_color", [255, 255, 255]), "flash_point": 0.35, "easing": "ease_in_out"}}
                elif t_type == "radial_wipe":
                    trans_data = {"type": "radial_wipe", "duration": _trans_cfg["duration"],
                                  "params": {"origin": (0.5, 0.5), "easing": "ease_in_out"}}
        grid_side = None
        panels_data = None
        s_seg = None
        s_start = 0.0
        side_effects = []
        c_start = 0.0

        def get_grid_panels_for_clip(clip_start, clip_spd, clip_dur, clip_t_dur, elapsed, _s_seg=None, _s_start=0.0, _side_effects=None, _v_file=""):
            adjusted_side_effects = []
            clip_total_dur = clip_dur + clip_t_dur
            for eff in _side_effects or []:
                eff_copy = dict(eff)
                eff_copy["duration"] = clip_total_dur
                adjusted_side_effects.append(eff_copy)
            return [
                {"file": _s_seg["file"] if _s_seg else "", "start_time": max(0.0, _s_start + elapsed),
                 "speed": 1.0, "flip": None, "effects": adjusted_side_effects},
                {"file": _v_file, "start_time": max(0.0, clip_start), "speed": clip_spd,
                 "flip": None, "effects": []},
                {"ref_panel_idx": 0, "flip": "h", "effects": adjusted_side_effects},
            ]

        if is_grid:
            c_iv = v_seg.get("interval", [0.0, v_full_dur])
            c_max = max(c_iv[0], c_iv[1] - out_dur)
            c_start = random.uniform(c_iv[0], c_max) if args.random_cursor and c_max > c_iv[0] else c_iv[0]
            trans_for_grade = trans_data.get("duration", 0.0) if trans_data else 0.0
            if not isinstance(trans_for_grade, (int, float)):
                trans_for_grade = 0.0
            side_cands = [v for v in videos_data if v["file"] != v_file]
            tags_to_exclude = set()
            if grid_tag:
                tags_to_exclude.add(grid_tag)
            else:
                tags_to_exclude.update(v_seg.get("tags", []))
            if tags_to_exclude:
                filtered = [v for v in side_cands if not (set(v.get("tags", [])) & tags_to_exclude)]
                if filtered:
                    side_cands = filtered
                else:
                    all_cands = [v for v in videos_data if v is not v_seg]
                    filtered = [v for v in all_cands if not (set(v.get("tags", [])) & tags_to_exclude)]
                    if filtered:
                        side_cands = filtered
            if not side_cands:
                side_cands = [v for v in videos_data if v is not v_seg]
            if not side_cands:
                side_cands = videos_data
            s_seg = random.choice(side_cands)
            s_iv = s_seg.get("interval", [0.0, s_seg.get("full_dur", 0.0)])
            s_max = max(s_iv[0], s_iv[1] - out_dur)
            s_start = random.uniform(s_iv[0], s_max) if args.random_cursor and s_max > s_iv[0] else s_iv[0]
            color_roll = random.random()
            grade_dur = out_dur + trans_for_grade
            _gcfg = CONFIG["grid"]
            _grade_chances = _gcfg["color_grade_chances"]
            desat_thresh = _grade_chances["desaturated"]
            warm_thresh = desat_thresh + _grade_chances["warm"]
            cool_thresh = warm_thresh + _grade_chances["cool"]
            if color_roll < desat_thresh:
                _p = _gcfg["desaturated_params"]
                side_effects.append({"type": "ColorAdjustEffect", "start_time": 0.0, "duration": grade_dur,
                                     "params": {"start_params": dict(_p), "end_params": dict(_p), "easing": "linear"}})
            elif color_roll < warm_thresh:
                _p = _gcfg["warm_params"]
                side_effects.append({"type": "ColorAdjustEffect", "start_time": 0.0, "duration": grade_dur,
                                     "params": {"start_params": dict(_p), "end_params": dict(_p), "easing": "linear"}})
            elif color_roll < cool_thresh:
                _p = _gcfg["cool_params"]
                side_effects.append({"type": "ColorAdjustEffect", "start_time": 0.0, "duration": grade_dur,
                                     "params": {"start_params": dict(_p), "end_params": dict(_p), "easing": "linear"}})

        clips_list = []
        scene = {
            "start_beat_idx": idx, "end_beat_idx": end_idx, "t_start": t_m1, "t_end": t_m2,
            "out_dur": out_dur, "alignment_mode": alignment_mode, "video_file": v_file,
            "is_grid": is_grid, "grid_side": grid_side, "clips": clips_list, "transition": trans_data,
        }
        trans_dur = trans_data["duration"] if trans_data else 0.0
        if not isinstance(trans_dur, (int, float)):
            trans_dur = 0.0

        if alignment_mode == "cc":
            v_dur = v_acts[-1] - v_acts[0]
            a_dur = audio_points[-1] - audio_points[0]
            speed = max(args.min_speed, min(args.max_speed, v_dur / a_dur if a_dur > 0 else 1.0))
            running_elapsed = 0.0
            if pre_dur > 0.02:
                v_pre_start = max(v_seg["interval"][0], v_acts[0] - pre_dur)
                actual_pre_dur = v_acts[0] - v_pre_start
                if actual_pre_dur > 0.02:
                    pre_clip = {"filepath": v_file, "start_time": v_pre_start, "duration": actual_pre_dur,
                                "speed": 1.0, "is_grid": is_grid, "trans_dur": 0.0, "effects": []}
                    if is_grid:
                        pre_clip["panels"] = get_grid_panels_for_clip(v_pre_start, 1.0, actual_pre_dur, 0.0, running_elapsed, s_seg, s_start, side_effects, v_file)
                    clips_list.append(pre_clip)
                    running_elapsed += actual_pre_dur
            if post_dur > 0.02:
                aligned_clip = {"filepath": v_file, "start_time": v_acts[0], "duration": a_dur,
                                "speed": speed, "is_grid": is_grid, "trans_dur": 0.0, "effects": []}
                if is_grid:
                    aligned_clip["panels"] = get_grid_panels_for_clip(v_acts[0], speed, a_dur, 0.0, running_elapsed, s_seg, s_start, side_effects, v_file)
                clips_list.append(aligned_clip)
                running_elapsed += a_dur
                v_post_start = v_acts[-1]
                v_post_end = min(v_seg["interval"][1], v_post_start + post_dur)
                actual_post_dur = v_post_end - v_post_start
                if actual_post_dur > 0.02:
                    post_clip = {"filepath": v_file, "start_time": v_post_start, "duration": actual_post_dur,
                                 "speed": 1.0, "is_grid": is_grid, "trans_dur": trans_dur, "effects": []}
                    if is_grid:
                        post_clip["panels"] = get_grid_panels_for_clip(v_post_start, 1.0, actual_post_dur, trans_dur, running_elapsed, s_seg, s_start, side_effects, v_file)
                    clips_list.append(post_clip)
                    running_elapsed += actual_post_dur + trans_dur
            else:
                aligned_clip = {"filepath": v_file, "start_time": v_acts[0], "duration": a_dur,
                                "speed": speed, "is_grid": is_grid, "trans_dur": trans_dur, "effects": []}
                if is_grid:
                    aligned_clip["panels"] = get_grid_panels_for_clip(v_acts[0], speed, a_dur, trans_dur, running_elapsed, s_seg, s_start, side_effects, v_file)
                clips_list.append(aligned_clip)
                running_elapsed += a_dur + trans_dur
            be_cc = CONFIG["beat_effects"]["cc"]
            if aligned_clip:
                clip: dict[str, Any] = aligned_clip
                clip_effects = clip["panels"][1]["effects"] if is_grid and "panels" in clip else clip["effects"]
                if not isinstance(clip_effects, list):
                    clip_effects = []
                for mb in minors_in_interval:
                    local_t = mb - audio_points[0]
                    clip_effects.append({"type": "ZoomEffect", "start_time": local_t, "duration": be_cc["zoom"]["duration"],
                                         "params": {"start_zoom": be_cc["zoom"]["start_zoom"], "end_zoom": be_cc["zoom"]["end_zoom"], "easing": "ease_out"}})
                    if "zoom_to_point" in be_cc and random.random() < be_cc["zoom_to_point"]["chance"]:
                        ztp = be_cc["zoom_to_point"]
                        clip_effects.append({"type": "ZoomToPoint", "start_time": local_t, "duration": ztp["duration"],
                                             "params": {"center": ztp["center"], "start_zoom": ztp["start_zoom"], "end_zoom": ztp["end_zoom"], "easing": ztp.get("easing", "ease_in_out")}})
                    if "ken_burns" in be_cc and random.random() < be_cc["ken_burns"]["chance"]:
                        kb = be_cc["ken_burns"]
                        clip_effects.append({"type": "KenBurnsEffect", "start_time": local_t, "duration": kb["duration"], "params": dict(kb)})
                    if "yolo_emission" in be_cc and random.random() < be_cc["yolo_emission"]["chance"]:
                        ye = be_cc["yolo_emission"]
                        clip_effects.append({"type": "YoloEmissionEffect", "start_time": local_t, "duration": ye["duration"],
                                             "params": {"inner_color": ye["inner_color"], "outer_color": ye["outer_color"],
                                                        "inner_radius": ye["inner_radius"], "outer_radius": ye["outer_radius"],
                                                        "intensity": ye["intensity"], "pulse_speed": ye["pulse_speed"],
                                                        "pulse_amplitude": ye["pulse_amplitude"], "easing": ye.get("easing", "ease_in_out")}})
                    if random.random() < be_cc["rgb_shift"]["chance"]:
                        clip_effects.append({"type": "RGBShiftEffect", "start_time": local_t, "duration": be_cc["rgb_shift"]["duration"],
                                             "params": {"start_shift": be_cc["rgb_shift"]["start_shift"], "end_shift": be_cc["rgb_shift"]["end_shift"], "angle": 0.0, "easing": "linear"}})

        elif alignment_mode == "dtw":
            path = dtw_alignment(audio_points, v_acts)
            running_elapsed = 0.0
            if pre_dur > 0.02:
                v_first = v_acts[path[0][1]]
                v_pre_start = max(v_seg["interval"][0], v_first - pre_dur)
                actual_pre_dur = v_first - v_pre_start
                if actual_pre_dur > 0.02:
                    pre_clip = {"filepath": v_file, "start_time": v_pre_start, "duration": actual_pre_dur,
                                "speed": 1.0, "is_grid": is_grid, "trans_dur": 0.0, "effects": []}
                    if is_grid:
                        pre_clip["panels"] = get_grid_panels_for_clip(v_pre_start, 1.0, actual_pre_dur, 0.0, running_elapsed, s_seg, s_start, side_effects, v_file)
                    clips_list.append(pre_clip)
                    running_elapsed += actual_pre_dur
            deduped_path = [path[0]]
            for step in path[1:]:
                if step[1] != deduped_path[-1][1]:
                    deduped_path.append(step)
            p_idx = 0
            clip_info = []
            while p_idx < len(deduped_path) - 1:
                a_i1, v_i1 = deduped_path[p_idx]
                best_next = p_idx + 1
                for jump in range(3, 0, -1):
                    if p_idx + jump >= len(deduped_path):
                        continue
                    a_it, v_it = deduped_path[p_idx + jump]
                    seg_a_dur = audio_points[a_it] - audio_points[a_i1]
                    seg_v_dur = v_acts[v_it] - v_acts[v_i1]
                    if seg_a_dur <= 0:
                        continue
                    s_test = seg_v_dur / seg_a_dur
                    if 0.8 <= s_test <= 1.25:
                        best_next = p_idx + jump
                        break
                a_i1, v_i1 = deduped_path[p_idx]
                a_i2, v_i2 = deduped_path[best_next]
                seg_a_dur = audio_points[a_i2] - audio_points[a_i1]
                seg_v_dur = v_acts[v_i2] - v_acts[v_i1]
                is_last = best_next == len(deduped_path) - 1
                post_dur_check = t_m2 - audio_points[-1]
                seg_trans = trans_dur if (is_last and post_dur_check <= 0.02) else 0.0
                if seg_a_dur <= 0:
                    p_idx = best_next
                    continue
                seg_speed = max(args.min_speed, min(args.max_speed, seg_v_dur / seg_a_dur))
                clip_info.append((audio_points[a_i1], audio_points[a_i2], len(clips_list)))
                clip_obj = {"filepath": v_file, "start_time": v_acts[v_i1], "duration": seg_a_dur,
                            "speed": seg_speed, "is_grid": is_grid, "trans_dur": seg_trans, "effects": []}
                if is_grid:
                    clip_obj["panels"] = get_grid_panels_for_clip(v_acts[v_i1], seg_speed, seg_a_dur, seg_trans, running_elapsed, s_seg, s_start, side_effects, v_file)
                clips_list.append(clip_obj)
                running_elapsed += seg_a_dur + seg_trans
                p_idx = best_next
            if post_dur > 0.02:
                v_last = v_acts[path[-1][1]]
                v_post_end = min(v_seg["interval"][1], v_last + post_dur)
                actual_post_dur = v_post_end - v_last
                if actual_post_dur > 0.02:
                    post_clip = {"filepath": v_file, "start_time": v_last, "duration": actual_post_dur,
                                 "speed": 1.0, "is_grid": is_grid, "trans_dur": trans_dur, "effects": []}
                    if is_grid:
                        post_clip["panels"] = get_grid_panels_for_clip(v_last, 1.0, actual_post_dur, trans_dur, running_elapsed, s_seg, s_start, side_effects, v_file)
                    clips_list.append(post_clip)
                    running_elapsed += actual_post_dur + trans_dur
            be_dtw = CONFIG["beat_effects"]["dtw"]
            for mb in minors_in_interval:
                target_clip = None
                local_t = 0.0
                for s_a, e_a, c_idx in clip_info:
                    if s_a <= mb < e_a:
                        target_clip = clips_list[c_idx]
                        local_t = mb - s_a
                        break
                if target_clip is None:
                    continue
                tc: dict[str, Any] = cast(dict[str, Any], target_clip)
                tc_effects = tc["panels"][1]["effects"] if is_grid and "panels" in tc else tc["effects"]
                if not isinstance(tc_effects, list):
                    tc_effects = []
                tc_effects.append({"type": "ZoomEffect", "start_time": local_t, "duration": be_dtw["zoom"]["duration"],
                                    "params": {"start_zoom": be_dtw["zoom"]["start_zoom"], "end_zoom": be_dtw["zoom"]["end_zoom"], "easing": "ease_out"}})
                if "zoom_to_point" in be_dtw and random.random() < be_dtw["zoom_to_point"]["chance"]:
                    ztp = be_dtw["zoom_to_point"]
                    tc_effects.append({"type": "ZoomToPoint", "start_time": local_t, "duration": ztp["duration"],
                                       "params": {"center": ztp["center"], "start_zoom": ztp["start_zoom"], "end_zoom": ztp["end_zoom"], "easing": ztp.get("easing", "ease_in_out")}})
                if "ken_burns" in be_dtw and random.random() < be_dtw["ken_burns"]["chance"]:
                    kb = be_dtw["ken_burns"]
                    tc_effects.append({"type": "KenBurnsEffect", "start_time": local_t, "duration": kb["duration"], "params": dict(kb)})
                if "yolo_emission" in be_dtw and random.random() < be_dtw["yolo_emission"]["chance"]:
                    ye = be_dtw["yolo_emission"]
                    tc_effects.append({"type": "YoloEmissionEffect", "start_time": local_t, "duration": ye["duration"],
                                       "params": {"inner_color": ye["inner_color"], "outer_color": ye["outer_color"],
                                                  "inner_radius": ye["inner_radius"], "outer_radius": ye["outer_radius"],
                                                  "intensity": ye["intensity"], "pulse_speed": ye["pulse_speed"],
                                                  "pulse_amplitude": ye["pulse_amplitude"], "easing": ye.get("easing", "ease_in_out")}})
                if random.random() < be_dtw["rgb_shift"]["chance"]:
                    tc_effects.append({"type": "RGBShiftEffect", "start_time": local_t, "duration": be_dtw["rgb_shift"]["duration"],
                                       "params": {"start_shift": be_dtw["rgb_shift"]["start_shift"], "end_shift": be_dtw["rgb_shift"]["end_shift"], "angle": 0.0, "easing": "linear"}})

        elif use_align and n_audio == 1 and len(v_acts) >= 1:
            if args.random_cursor:
                v_first = random.choice(v_acts)
                v_avail_start = v_seg["interval"][0]
                v_avail_end = v_seg["interval"][1] if len(v_seg["interval"]) > 1 else v_full_dur
                pre_dur_req = audio_points[0] - t_m1
                post_dur_req = t_m2 - audio_points[0]
                v_min = v_avail_start + pre_dur_req
                v_max = v_avail_end - post_dur_req
                if v_max > v_min:
                    v_first = random.uniform(v_min, v_max)
            else:
                v_first = min(v_acts, key=lambda v: abs(v - audio_points[0]))
            running_elapsed = 0.0
            pre_dur = audio_points[0] - t_m1
            if pre_dur > 0.02:
                pre_clip_start = max(0.0, v_first - pre_dur)
                pre_clip = {"filepath": v_file, "start_time": pre_clip_start, "duration": pre_dur,
                            "speed": 1.0, "is_grid": is_grid, "trans_dur": 0.0, "effects": []}
                if is_grid:
                    pre_clip["panels"] = get_grid_panels_for_clip(pre_clip_start, 1.0, pre_dur, 0.0, running_elapsed, s_seg, s_start, side_effects, v_file)
                clips_list.append(pre_clip)
                running_elapsed += pre_dur
            post_dur = t_m2 - audio_points[0]
            if post_dur > 0.02:
                post_clip = {"filepath": v_file, "start_time": v_first, "duration": post_dur,
                             "speed": 1.0, "is_grid": is_grid, "trans_dur": trans_dur, "effects": []}
                if is_grid:
                    post_clip["panels"] = get_grid_panels_for_clip(v_first, 1.0, post_dur, trans_dur, running_elapsed, s_seg, s_start, side_effects, v_file)
                clips_list.append(post_clip)
                running_elapsed += post_dur + trans_dur
                be_single = CONFIG["beat_effects"]["single"]
                post_clip["effects"].append({"type": "ZoomEffect", "start_time": 0.0, "duration": be_single["zoom"]["duration"],
                                             "params": {"start_zoom": be_single["zoom"]["start_zoom"], "end_zoom": be_single["zoom"]["end_zoom"], "easing": "ease_out"}})
                if "zoom_to_point" in be_single and random.random() < be_single["zoom_to_point"]["chance"]:
                    ztp = be_single["zoom_to_point"]
                    post_clip["effects"].append({"type": "ZoomToPoint", "start_time": 0.0, "duration": ztp["duration"],
                                                 "params": {"center": ztp["center"], "start_zoom": ztp["start_zoom"], "end_zoom": ztp["end_zoom"], "easing": ztp.get("easing", "ease_in_out")}})
                if "ken_burns" in be_single and random.random() < be_single["ken_burns"]["chance"]:
                    kb = be_single["ken_burns"]
                    post_clip["effects"].append({"type": "KenBurnsEffect", "start_time": 0.0, "duration": kb["duration"], "params": dict(kb)})
                if "yolo_emission" in be_single and random.random() < be_single["yolo_emission"]["chance"]:
                    ye = be_single["yolo_emission"]
                    post_clip["effects"].append({"type": "YoloEmissionEffect", "start_time": 0.0, "duration": ye["duration"],
                                                 "params": {"inner_color": ye["inner_color"], "outer_color": ye["outer_color"],
                                                            "inner_radius": ye["inner_radius"], "outer_radius": ye["outer_radius"],
                                                            "intensity": ye["intensity"], "pulse_speed": ye["pulse_speed"],
                                                            "pulse_amplitude": ye["pulse_amplitude"], "easing": ye.get("easing", "ease_in_out")}})

        else:
            if args.random_cursor:
                v_start_limit = v_seg["interval"][0] if v_seg["interval"] else 0.0
                v_end_limit = v_seg["interval"][1] if (v_seg["interval"] and len(v_seg["interval"]) > 1) else v_full_dur
                if v_end_limit <= v_start_limit:
                    v_end_limit = v_full_dur
                src_dur = out_dur
                v_start = random.uniform(v_start_limit, v_end_limit - src_dur) if v_end_limit - v_start_limit > src_dur else v_start_limit
            else:
                v_start = v_seg["interval"][0] if v_seg["interval"] else 0.0
            running_elapsed = 0.0
            clip_obj = {"filepath": v_file, "start_time": v_start, "duration": out_dur,
                        "speed": 1.0, "is_grid": is_grid, "trans_dur": trans_dur, "effects": []}
            if is_grid:
                clip_obj["panels"] = get_grid_panels_for_clip(v_start, 1.0, out_dur, trans_dur, running_elapsed, s_seg, s_start, side_effects, v_file)
            clips_list.append(clip_obj)
            if is_grid:
                be_grid = CONFIG["beat_effects"]["grid"]
                obj: dict[str, Any] = cast(dict[str, Any], clip_obj)
                panel_effects: list[Any] = obj["panels"][1]["effects"]
                for mb in minors_in_interval:
                    local_t = mb - t_m1
                    panel_effects.append({"type": "ZoomEffect", "start_time": local_t, "duration": be_grid["zoom"]["duration"],
                                          "params": {"start_zoom": be_grid["zoom"]["start_zoom"], "end_zoom": be_grid["zoom"]["end_zoom"], "easing": "ease_out"}})
                    if "zoom_to_point" in be_grid and random.random() < be_grid["zoom_to_point"]["chance"]:
                        ztp = be_grid["zoom_to_point"]
                        panel_effects.append({"type": "ZoomToPoint", "start_time": local_t, "duration": ztp["duration"],
                                              "params": {"center": ztp["center"], "start_zoom": ztp["start_zoom"], "end_zoom": ztp["end_zoom"], "easing": ztp.get("easing", "ease_in_out")}})
                    if "ken_burns" in be_grid and random.random() < be_grid["ken_burns"]["chance"]:
                        kb = be_grid["ken_burns"]
                        panel_effects.append({"type": "KenBurnsEffect", "start_time": local_t, "duration": kb["duration"], "params": dict(kb)})
                    if "panel_slide" in be_grid and random.random() < be_grid["panel_slide"]["chance"]:
                        ps = be_grid["panel_slide"]
                        panel_effects.append({"type": "PanelSlideEffect", "start_time": local_t, "duration": ps["duration"],
                                              "params": {"direction": ps.get("direction", "left"), "start_offset": ps.get("start_offset", 1.0),
                                                         "end_offset": ps.get("end_offset", 0.0), "easing": ps.get("easing", "ease_out")}})
                    if "panel_pulse" in be_grid and random.random() < be_grid["panel_pulse"]["chance"]:
                        pp = be_grid["panel_pulse"]
                        panel_effects.append({"type": "PanelPulseEffect", "start_time": local_t, "duration": pp["duration"],
                                              "params": {"start_scale": pp.get("start_scale", 1.0), "pulse_scale": pp.get("pulse_scale", 1.12),
                                                         "end_scale": pp.get("end_scale", 1.0), "easing": pp.get("easing", "ease_out")}})
                    if "grid_scan" in be_grid and random.random() < be_grid["grid_scan"]["chance"]:
                        gs = be_grid["grid_scan"]
                        clip_obj["effects"].append({"type": "GridScanEffect", "start_time": local_t, "duration": gs["duration"],
                                                    "params": {"num_bars": gs.get("num_bars", 240.0), "bar_speed": gs.get("bar_speed", 0.8),
                                                               "bar_width": gs.get("bar_width", 0.05), "easing": gs.get("easing", "linear")}})
                    if "grid_flash" in be_grid and random.random() < be_grid["grid_flash"]["chance"]:
                        gf = be_grid["grid_flash"]
                        clip_obj["effects"].append({"type": "GridFlashEffect", "start_time": local_t, "duration": gf["duration"],
                                                    "params": {"intensity": gf.get("intensity", 0.5), "easing": gf.get("easing", "linear")}})
                    if "grid_glitch" in be_grid and random.random() < be_grid["grid_glitch"]["chance"]:
                        gg = be_grid["grid_glitch"]
                        clip_obj["effects"].append({"type": "GridGlitchEffect", "start_time": local_t, "duration": gg["duration"],
                                                    "params": {"intensity": gg.get("intensity", 1.0), "easing": gg.get("easing", "linear")}})
                    if "grid_wave" in be_grid and random.random() < be_grid["grid_wave"]["chance"]:
                        gw = be_grid["grid_wave"]
                        clip_obj["effects"].append({"type": "GridWaveWarpEffect", "start_time": local_t, "duration": gw["duration"],
                                                    "params": {"frequency": gw.get("frequency", 20.0), "amplitude": gw.get("amplitude", 0.03),
                                                               "speed": gw.get("speed", 5.0), "easing": gw.get("easing", "linear")}})
                    if "grid_pixelate" in be_grid and random.random() < be_grid["grid_pixelate"]["chance"]:
                        gp = be_grid["grid_pixelate"]
                        clip_obj["effects"].append({"type": "GridPixelateEffect", "start_time": local_t, "duration": gp["duration"],
                                                    "params": {"max_pixels": gp.get("max_pixels", 400.0), "min_pixels": gp.get("min_pixels", 25.0),
                                                               "easing": gp.get("easing", "linear")}})
                    if "grid_chromatic" in be_grid and random.random() < be_grid["grid_chromatic"]["chance"]:
                        gc = be_grid["grid_chromatic"]
                        clip_obj["effects"].append({"type": "GridChromaticEffect", "start_time": local_t, "duration": gc["duration"],
                                                    "params": {"intensity": gc.get("intensity", 1.0), "angle": gc.get("angle", 0.0),
                                                               "easing": gc.get("easing", "linear")}})
                    if "yolo_emission" in be_grid and random.random() < be_grid["yolo_emission"]["chance"]:
                        ye = be_grid["yolo_emission"]
                        clip_obj["effects"].append({"type": "YoloEmissionEffect", "start_time": local_t, "duration": ye["duration"],
                                                    "params": {"inner_color": ye["inner_color"], "outer_color": ye["outer_color"],
                                                               "inner_radius": ye["inner_radius"], "outer_radius": ye["outer_radius"],
                                                               "intensity": ye["intensity"], "pulse_speed": ye["pulse_speed"],
                                                               "pulse_amplitude": ye["pulse_amplitude"], "easing": ye.get("easing", "ease_in_out")}})
                    if "panel_bounce" in be_grid and random.random() < be_grid["panel_bounce"]["chance"]:
                        pb = be_grid["panel_bounce"]
                        panel_effects.append({"type": "PanelBounceEffect", "start_time": local_t, "duration": pb["duration"],
                                              "params": {"direction": pb.get("direction", "up"), "amplitude": pb.get("amplitude", 0.06),
                                                         "easing": pb.get("easing", "ease_out")}})
                    if "panel_spin" in be_grid and random.random() < be_grid["panel_spin"]["chance"]:
                        pn = be_grid["panel_spin"]
                        panel_effects.append({"type": "PanelSpinEffect", "start_time": local_t, "duration": pn["duration"],
                                              "params": {"max_angle": pn.get("max_angle", 3.0), "easing": pn.get("easing", "ease_out")}})
                    if random.random() < be_grid["rgb_shift"]["chance"]:
                        panel_effects.append({"type": "RGBShiftEffect", "start_time": local_t, "duration": be_grid["rgb_shift"]["duration"],
                                              "params": {"start_shift": be_grid["rgb_shift"]["start_shift"], "end_shift": be_grid["rgb_shift"]["end_shift"],
                                                         "angle": 0.0, "easing": "linear"}})

        plan_data["scenes"].append(scene)
        idx = end_idx
    return plan_data


def apply_edit_plan(pipeline, plan_data):
    resize_mode = plan_data.get("resize_mode", "fill")
    for eff_data in plan_data.get("global_effects", []):
        eff_obj = deserialize_effect(eff_data)
        if eff_obj:
            pipeline.add_effect(eff_obj, start_time=eff_data["start_time"], duration=eff_data["duration"])
    global_clip_idx = 0
    scenes = plan_data.get("scenes", [])
    for s_idx, scene in enumerate(scenes):
        clips_in_scene = scene.get("clips", [])
        grid_side = scene.get("grid_side")
        scene_elapsed_out_dur = 0.0
        for c_idx, clip in enumerate(clips_in_scene):
            filepath = clip["filepath"]
            start_time = clip["start_time"]
            duration = clip["duration"]
            speed = clip["speed"]
            is_grid = clip["is_grid"]
            trans_dur = clip.get("trans_dur", 0.0)
            clip_grid_side = None
            if grid_side:
                side_speed = grid_side.get("speed", 1.0)
                clip_grid_side = {
                    "file": grid_side["file"],
                    "start_time": grid_side["start_time"] + scene_elapsed_out_dur * side_speed,
                    "speed": side_speed,
                }
            add_clip(pipeline, filepath, start_time, duration, speed=speed, is_grid=is_grid,
                     trans_dur=trans_dur, resize_mode=resize_mode, grid_side=clip_grid_side,
                     panels=clip.get("panels"))
            scene_elapsed_out_dur += duration + trans_dur
            for eff_data in clip.get("effects", []):
                eff_obj = deserialize_effect(eff_data)
                if eff_obj:
                    pipeline.add_clip_effect(global_clip_idx, eff_obj, start_time=eff_data["start_time"], duration=eff_data["duration"])
            is_last_clip_of_pipeline = (s_idx == len(scenes) - 1) and (c_idx == len(clips_in_scene) - 1)
            if not is_last_clip_of_pipeline:
                if c_idx == len(clips_in_scene) - 1:
                    trans_data = scene.get("transition")
                    pipeline.add_transition(deserialize_transition(trans_data) if trans_data else None)
                else:
                    pipeline.add_transition(None)
            global_clip_idx += 1


def print_edit_plan(plan_data):
    print("=" * 80)
    print(" EDIT PLAN SUMMARY")
    print("=" * 80)
    print(f"Output Size : {plan_data.get('output_size')}")
    print(f"FPS         : {plan_data.get('fps')}")
    print(f"Resize Mode : {plan_data.get('resize_mode')}")
    print(f"Audio Path  : {plan_data.get('audio_path')}")
    print("-" * 80)
    scenes = plan_data.get("scenes", [])
    for idx, scene in enumerate(scenes):
        print(f"Scene {idx + 1:>2}: {scene['t_start']:.2f}s \u2192 {scene['t_end']:.2f}s ({scene['out_dur']:.2f}s)")
        print(f"  Alignment Mode: {scene['alignment_mode'].upper()}")
        print(f"  Video File    : {os.path.basename(scene['video_file'])}")
        if scene.get("is_grid"):
            print("  Layout        : GridScene (Independent Panels)")
        print("  Clips:")
        for c_idx, clip in enumerate(scene.get("clips", [])):
            print(f"    - Clip {c_idx}: {os.path.basename(clip['filepath'])} (Start: {clip['start_time']:.2f}s, Dur: {clip['duration']:.2f}s, Speed: {clip['speed']:.2f}x)")
            if clip.get("panels"):
                print("      Grid Panels:")
                for pi, p in enumerate(clip["panels"]):
                    p_label = ["Left", "Center", "Right"][pi] if pi < 3 else f"Panel {pi}"
                    p_effs = [e["type"] for e in p.get("effects", [])]
                    eff_str = f" [{', '.join(p_effs)}]" if p_effs else ""
                    flip_str = f" (flip={p['flip']})" if p.get("flip") else ""
                    if "file" in p:
                        file_info = f"{os.path.basename(p['file'])} @ {p['start_time']:.2f}s"
                    elif "ref_panel_idx" in p:
                        ref_lbl = ["Left", "Center", "Right"][p["ref_panel_idx"]] if p["ref_panel_idx"] < 3 else f"Panel {p['ref_panel_idx']}"
                        file_info = f"Ref({ref_lbl})"
                    else:
                        file_info = "Unknown"
                    print(f"        {p_label}: {file_info}{flip_str}{eff_str}")
            if clip.get("effects"):
                eff_names = [e["type"] for e in clip["effects"]]
                print(f"      Effects   : {', '.join(eff_names)}")
        if scene.get("transition"):
            t = scene["transition"]
            print(f"  Transition    : {t['type'].upper()} ({t['duration']:.2f}s)")
        print("-" * 80)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=None, help="Max duration of the edit in seconds")
    parser.add_argument("--resize-mode", choices=["fill", "fit"], default="fill",
                        help="How to handle resolution mismatch: 'fill' (zoom/crop) or 'fit' (black bars)")
    parser.add_argument("--random-cursor", action="store_true",
                        help="Allow video clips to start at a random cursor position when not aligned")
    parser.add_argument("--no-align", action="store_true",
                        help="Disable audio-video alignment (CC/DTW) and cut clips at beat boundaries")
    parser.add_argument("--min-speed", type=float, default=0.8,
                        help="Minimum playback speed multiplier for aligned clips")
    parser.add_argument("--max-speed", type=float, default=1.4,
                        help="Maximum playback speed multiplier for aligned clips")
    parser.add_argument("--min-beat-gap", type=float, default=0.2,
                        help="Minimum seconds between alignment points")
    parser.add_argument("--transition-chance", type=float, default=0.5,
                        help="Probability (0.0 to 1.0) of adding a transition between scenes")
    parser.add_argument("--grid-chance", type=float, default=0.0,
                        help="Probability (0.0 to 1.0) of rendering a scene as a grid layout")
    parser.add_argument("--grid-tag", type=str, default=None, metavar="TAG",
                        help="When set, grid scenes with this tag use 3-panel layout")
    parser.add_argument("--save-plan", type=str, default=None, help="Save edit plan to JSON")
    parser.add_argument("--load-plan", type=str, default=None, help="Load edit plan from JSON")
    parser.add_argument("--patch-plan", type=str, default=None,
                        help="JSON string/file containing list of patch dicts")
    parser.add_argument("--print-only", action="store_true",
                        help="Print plan summary and exit without rendering")
    parser.add_argument("--output", type=str, default="final_auto_edit.mp4",
                        help="Path to the output final video file")
    args = parser.parse_args()

    if args.load_plan:
        print(f"Loading edit plan from {args.load_plan}...")
        with open(args.load_plan, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
    else:
        plan_data = generate_edit_plan(args)
        if not plan_data:
            return
        if args.save_plan:
            print(f"Saving generated edit plan to {args.save_plan}...")
            with open(args.save_plan, "w", encoding="utf-8") as f:
                json.dump(plan_data, f, indent=2)

    if args.patch_plan:
        patch_source = args.patch_plan
        if os.path.exists(patch_source):
            with open(patch_source, "r", encoding="utf-8") as pf:
                patches = json.load(pf)
        else:
            try:
                patches = json.loads(patch_source)
            except json.JSONDecodeError as e:
                print(f"Error: --patch-plan is neither a valid file path nor valid JSON: {e}")
                return
        if not isinstance(patches, list):
            patches = [patches]
        print(f"Applying {len(patches)} patch(es) to plan...")
        if isinstance(plan_data, dict):
            plan_data = patch_plan(plan_data, patches)
        if not args.load_plan and args.save_plan:
            with open(args.save_plan, "w", encoding="utf-8") as f:
                json.dump(plan_data, f, indent=2)
            print(f"Updated saved plan: {args.save_plan}")

    print_edit_plan(plan_data)
    if args.print_only:
        print("[--print-only] Exiting without rendering.")
        return

    pipeline = VideoPipeline(
        fps=plan_data.get("fps", 30.0),
        output_size=tuple(plan_data.get("output_size", [854, 480])),
        resize_mode=plan_data.get("resize_mode", "fill"),
    )
    apply_edit_plan(pipeline, plan_data)

    raw_video = "temp_auto_edit_raw.mp4"
    final_video = args.output
    print(f"\nRendering raw video to {raw_video} ...")
    pipeline.render(raw_video)

    audio_path = plan_data.get("audio_path")
    if audio_path and os.path.exists(audio_path):
        total_dur = plan_data["scenes"][-1]["t_end"] if plan_data.get("scenes") else 0.0
        print(f"Muxing full audio (0 \u2192 {total_dur:.2f}s)...")
        subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-ss", "0", "-t", str(total_dur),
                        "-c:a", "aac", "temp_bgm.m4a"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["ffmpeg", "-y", "-i", raw_video, "-i", "temp_bgm.m4a",
                        "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                        "-t", f"{total_dur:.3f}", "-shortest", final_video],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in (raw_video, "temp_bgm.m4a"):
            if os.path.exists(f):
                os.remove(f)
    else:
        if os.path.exists(raw_video):
            if os.path.exists(final_video):
                os.remove(final_video)
            os.rename(raw_video, final_video)
    print(f"Done! Output: {final_video}")
