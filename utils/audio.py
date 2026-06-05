import os
import subprocess
from typing import Any, List


def change_audio_speed_file(src_path: str, dst_path: str, speed: float):
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
        ["ffmpeg", "-y", "-i", src_path,
         "-filter:a", ",".join(filters), dst_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def extract_clip_audio(
    filepath: str,
    start_time: float,
    clip_dur: float,
    clip_speed: float,
    clip_keep_audio: bool,
    out_dur_ms: int,
    seg_counter: List[int],
    AudioSegment: Any,
) -> str:
    seg_path = f"_audio_seg_{seg_counter[0]}.wav"
    seg_counter[0] += 1

    if clip_keep_audio and filepath:
        try:
            raw_path = seg_path + "_raw.wav"
            subprocess.run(
                ["ffmpeg", "-y",
                 "-ss", str(start_time),
                 "-t",  str(clip_dur * clip_speed),
                 "-i",  filepath,
                 "-ar", "44100", "-ac", "2",
                 raw_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if abs(clip_speed - 1.0) > 0.01:
                change_audio_speed_file(raw_path, seg_path, clip_speed)
                os.remove(raw_path)
            else:
                os.rename(raw_path, seg_path)
            if AudioSegment is not None:
                seg = AudioSegment.from_wav(seg_path)
                if len(seg) != out_dur_ms:
                    seg = seg[:out_dur_ms]
                    if len(seg) < out_dur_ms:
                        seg += AudioSegment.silent(out_dur_ms - len(seg))
                    seg.export(seg_path, format="wav")
        except Exception as e:
            print(f"  Audio warning: {e}")
            for _p in (seg_path, seg_path + "_raw.wav"):
                if os.path.exists(_p):
                    os.remove(_p)
            if AudioSegment is not None:
                AudioSegment.silent(duration=out_dur_ms).export(seg_path, format="wav")
    else:
        if AudioSegment is not None:
            AudioSegment.silent(duration=out_dur_ms).export(seg_path, format="wav")

    return seg_path


def merge_audio_segments(audio_segments: List[dict], AudioSegment: Any) -> str:
    temp_audio_path = "temp_audio.wav"
    if len(audio_segments) == 1:
        os.rename(audio_segments[0]["path"], temp_audio_path)
    else:
        if AudioSegment is not None:
            merged = AudioSegment.from_wav(audio_segments[0]["path"])
            os.remove(audio_segments[0]["path"])
            for seg_info in audio_segments[1:]:
                nxt = AudioSegment.from_wav(seg_info["path"])
                os.remove(seg_info["path"])
                fade_ms = seg_info["crossfade_ms"]
                if fade_ms > 0:
                    fade_ms = min(fade_ms, len(merged) - 1, len(nxt) - 1)
                if fade_ms > 0:
                    merged = merged.append(nxt, crossfade=fade_ms)
                else:
                    merged = merged + nxt
            merged.export(temp_audio_path, format="wav")
    return temp_audio_path


def mux_video_audio(video_path: str, audio_path: str, output_path: str):
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            output_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
