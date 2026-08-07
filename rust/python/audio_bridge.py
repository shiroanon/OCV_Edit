#!/usr/bin/env python3
"""Audio bridge for the Rust port.

Reads a JSON spec from stdin and produces the final video-with-audio file:

    {
      "video": "<rendered video-only file>",
      "output": "<final output path>",
      "bgm": "<background music path or null>",
      "clip_volume": 2.0,   # gain applied to the merged clip audio
      "bgm_volume": 0.3,    # gain applied to the background music
      "segments": [
        {"filepath", "start_time", "clip_dur", "clip_speed",
         "keep_audio", "crossfade_ms"},
        ...
      ]
    }

Segment extraction + merging mirror `utils/audio.py` exactly (pydub), so the
Rust port's audio matches the Python reference sample-for-sample.
"""

import json
import os
import subprocess
import sys

import numpy as np
from pydub import AudioSegment

# ── Binaural room spatialization (optional) ────────────────────────────────
# Mirrors `audioProcessing.py`: KEMAR HRTF binaural render of a point source in
# a reverberant ShoeBox. Only the ORIGINAL clip audio is spatialized; the
# background music is left dry. Falls back to unprocessed audio if
# pyroomacoustics/HRTF are unavailable.
try:
    import pyroomacoustics as pra
    from pyroomacoustics.directivities import Rotation3D
    from pyroomacoustics.directivities.measured import MeasuredDirectivityFile
    from scipy.io import wavfile
    PRA_OK = True
except Exception:  # noqa: BLE001
    PRA_OK = False

BIN_FS = 44100
ROOM_DIM = [15, 12, 5]
RT60_TGT = 1.2
CENTER = [7.5, 6.0, 1.7]
HEAD_RADIUS = 0.09
MOVE_SEGMENTS = 24
MOVE_RADIUS = 3.0
DISTANCE = 2.5

_hrtf_dirs = None


def _get_hrtf_dirs():
    """Load the KEMAR binaural mic directivities once and cache them."""
    global _hrtf_dirs
    if _hrtf_dirs is not None:
        return _hrtf_dirs
    if not PRA_OK:
        return None
    sofa = os.path.join(
        os.path.dirname(pra.__file__), "data", "sofa", "mit_kemar_normal_pinna.sofa"
    )
    if not os.path.exists(sofa):
        return None
    hrtf_db = MeasuredDirectivityFile(sofa, fs=BIN_FS, interp_order=None)
    head_rot = Rotation3D(angles=[-90, 0, 0])
    _hrtf_dirs = [
        hrtf_db.get_mic_directivity("right", orientation=head_rot),
        hrtf_db.get_mic_directivity("left", orientation=head_rot),
    ]
    return _hrtf_dirs


def _position(azimuth_deg, radius, z_off=0.0):
    rad = np.deg2rad(azimuth_deg)
    return [
        CENTER[0] - radius * np.sin(rad),
        CENTER[1] + radius * np.cos(rad),
        CENTER[2] + z_off,
    ]


def binaural_render(sig_mono, azimuth_deg, moving):
    """Place `sig_mono` (float64 mono @ BIN_FS) in the room and return the
    binaural stereo mix (2, N). Static sources sit at `azimuth_deg`; moving
    sources orbit the listener over MOVE_SEGMENTS steps."""
    e_abs, max_order = pra.inverse_sabine(RT60_TGT, ROOM_DIM)
    max_order = max(1, min(12, max_order))
    room = pra.ShoeBox(
        ROOM_DIM, fs=BIN_FS, materials=pra.Material(e_abs),
        max_order=max_order, air_absorption=True,
    )
    dirs = _get_hrtf_dirs()
    mic_locs = np.array([
        [CENTER[0] - HEAD_RADIUS, CENTER[1], CENTER[2]],
        [CENTER[0] + HEAD_RADIUS, CENTER[1], CENTER[2]],
    ]).T
    if dirs is not None:
        room.add_microphone_array(mic_locs, directivity=dirs)
    else:
        room.add_microphone_array(mic_locs)
    if moving:
        seg_len = max(1, len(sig_mono) // MOVE_SEGMENTS)
        for seg in range(MOVE_SEGMENTS):
            frac = seg / MOVE_SEGMENTS
            pos = _position(frac * 360.0, MOVE_RADIUS)
            seg_audio = sig_mono[seg * seg_len:(seg + 1) * seg_len].copy()
            room.add_source(pos, signal=seg_audio, delay=seg * seg_len / BIN_FS)
    else:
        room.add_source(_position(azimuth_deg, DISTANCE), signal=sig_mono.copy(), delay=0)
    room.compute_rir()
    room.simulate()
    return room.mic_array.signals


def binauralize(seg_path, spec):
    """In-place: rewrite `seg_path` with the binaural-rendered version of its
    audio, preserving the original peak loudness and exact duration. No-op when
    unavailable. The reverb tail is trimmed to the clip duration so segments
    stay sample-aligned with the video timeline during the crossfade merge."""
    if not PRA_OK:
        return
    seg = AudioSegment.from_wav(seg_path)
    mono = seg.set_channels(1)
    samples = np.frombuffer(mono.raw_data, dtype=np.int16).astype(np.float64) / 32768.0
    if len(samples) == 0 or np.max(np.abs(samples)) == 0:
        return
    azimuth = float(spec.get("azimuth_deg", 0.0))
    moving = bool(spec.get("moving", False))
    try:
        binaural = binaural_render(samples, azimuth, moving)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"  binaural warning: {e}\n")
        return
    binaural = binaural[:, :len(samples)]
    peak_in = np.max(np.abs(samples))
    peak_out = np.max(np.abs(binaural))
    if peak_out > 0:
        binaural = binaural * (peak_in / peak_out)
    out = np.clip(binaural * 32767, -32768, 32767).astype(np.int16)
    wavfile.write(seg_path, BIN_FS, out.T)


def _change_speed(src, dst, speed):
    filters = []
    s = speed
    while s > 2.0:
        filters.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        filters.append("atempo=0.5")
        s *= 2.0
    filters.append(f"atempo={s:.6f}")
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-filter:a", ",".join(filters), dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def extract_segment(spec, seg_path):
    filepath = spec.get("filepath") or ""
    start_time = float(spec.get("start_time", 0.0))
    clip_dur = float(spec.get("clip_dur", 1.0))
    clip_speed = float(spec.get("clip_speed", 1.0))
    keep_audio = bool(spec.get("keep_audio", False))
    out_dur_ms = max(1, int(round(clip_dur * 1000)))

    if keep_audio and filepath and os.path.exists(filepath):
        try:
            raw = seg_path + "_raw.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(start_time),
                 "-t", str(clip_dur * clip_speed),
                 "-i", filepath, "-ar", "44100", "-ac", "2", raw],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if abs(clip_speed - 1.0) > 0.01:
                _change_speed(raw, seg_path, clip_speed)
                os.remove(raw)
            else:
                os.rename(raw, seg_path)
            seg = AudioSegment.from_wav(seg_path)
            if len(seg) != out_dur_ms:
                seg = seg[:out_dur_ms]
                if len(seg) < out_dur_ms:
                    seg += AudioSegment.silent(out_dur_ms - len(seg))
                seg.export(seg_path, format="wav")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  audio warning: {e}\n")
            for p in (seg_path, seg_path + "_raw.wav"):
                if os.path.exists(p):
                    os.remove(p)
            AudioSegment.silent(duration=out_dur_ms).export(seg_path, format="wav")
    else:
        AudioSegment.silent(duration=out_dur_ms).export(seg_path, format="wav")
    return seg_path


def merge_segments(built):
    merged = AudioSegment.from_wav(built[0]["path"])
    os.remove(built[0]["path"])
    for seg_info in built[1:]:
        nxt = AudioSegment.from_wav(seg_info["path"])
        os.remove(seg_info["path"])
        fade_ms = int(seg_info["crossfade_ms"])
        if fade_ms > 0:
            fade_ms = min(fade_ms, len(merged) - 1, len(nxt) - 1)
        if fade_ms > 0:
            merged = merged.append(nxt, crossfade=fade_ms)
        else:
            merged = merged + nxt
    return merged


def _video_duration_ms(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return int(float(r.stdout.strip()) * 1000)
    except ValueError:
        return 0


def _gain_db(vol):
    return 20.0 * (vol and __import__("math").log10(vol) or 0.0)


def main():
    data = json.load(sys.stdin)
    video = data["video"]
    output = data["output"]
    bgm_path = data.get("bgm") or None
    clip_vol = float(data.get("clip_volume", 2.0))
    bgm_vol = float(data.get("bgm_volume", 0.3))
    out_dir = os.path.dirname(os.path.abspath(output))

    clip_track = None
    segments = data.get("segments") or []
    if segments:
        built = []
        for i, spec in enumerate(segments):
            seg_path = os.path.join(out_dir, f"_audio_seg_{i}.wav")
            extract_segment(spec, seg_path)
            if spec.get("keep_audio"):
                binauralize(seg_path, spec)
            built.append({"path": seg_path,
                          "crossfade_ms": int(spec.get("crossfade_ms", 0))})
        clip_track = merge_segments(built)

    dur_ms = _video_duration_ms(video)
    if dur_ms <= 0:
        sys.stderr.write("audio bridge: could not probe video duration\n")
        return 1

    bgm_track = None
    if bgm_path and os.path.exists(bgm_path):
        bgm_track = AudioSegment.from_file(bgm_path)
        if len(bgm_track) < dur_ms:
            bgm_track = bgm_track + AudioSegment.silent(dur_ms - len(bgm_track))
        bgm_track = bgm_track[:dur_ms]

    if clip_track is not None:
        if abs(clip_vol - 1.0) > 0.001:
            clip_track = clip_track.apply_gain(_gain_db(clip_vol))
        if len(clip_track) < dur_ms:
            clip_track = clip_track + AudioSegment.silent(dur_ms - len(clip_track))
        clip_track = clip_track[:dur_ms]
        if PRA_OK:
            clip_track = clip_track.fade_out(min(60, len(clip_track)))
        if bgm_track is not None:
            if abs(bgm_vol - 1.0) > 0.001:
                bgm_track = bgm_track.apply_gain(_gain_db(bgm_vol))
            mixed = clip_track.overlay(bgm_track, position=0)
        else:
            mixed = clip_track
    elif bgm_track is not None:
        if abs(bgm_vol - 1.0) > 0.001:
            bgm_track = bgm_track.apply_gain(_gain_db(bgm_vol))
        mixed = bgm_track
    else:
        mixed = AudioSegment.silent(duration=dur_ms)

    tmp_wav = os.path.join(out_dir, "_audio_bridge_mix.wav")
    mixed.export(tmp_wav, format="wav")
    tmp_out = os.path.join(out_dir, "_audio_bridge_out.mkv")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-i", tmp_wav,
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", tmp_out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        sys.stderr.write("audio bridge: ffmpeg mux failed\n")
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        return 1
    os.remove(tmp_wav)
    os.replace(tmp_out, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
