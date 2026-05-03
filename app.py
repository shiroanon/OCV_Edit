import cv2
import numpy as np
from typing import List, Optional
from utils.base import BaseTransition, BaseEffect
from utils.transitions import SlideTransition, ZoomTransition
from utils.effects import YoloGlowSegEffect

class VideoPipeline:
    def __init__(self, fps: float = 30.0, output_size: tuple = (1980, 1080)):
        self.fps = fps
        self.output_size = output_size
        self.clips = []
        self.transitions = []
        self.effects = [] # Format: [(effect_instance, start_time, end_time), ...]

    def add_clip(self, filepath: str, start_time: float = 0, duration: float = -1):
        """Adds a video clip to the pipeline."""
        self.clips.append({
            "filepath": filepath,
            "start_time": start_time,
            "duration": duration,
            "effects": []
        })

    def add_transition(self, transition: BaseTransition):
        """Adds a transition between the latest clip and the next one."""
        self.transitions.append(transition)

    def add_effect(self, effect: BaseEffect, start_time: float = 0.0, duration: float = -1.0):
        """Adds an effect to the global timeline. Set duration > 0 for animated effects."""
        self.effects.append({
            "effect": effect,
            "start_time": start_time,
            "duration": duration
        })

    def add_clip_effect(self, clip_idx: int, effect: BaseEffect, start_time: float = 0.0, duration: float = -1.0):
        """Adds an effect to a specific clip's local timeline."""
        self.clips[clip_idx]["effects"].append({
            "effect": effect,
            "start_time": start_time,
            "duration": duration
        })

    # ------------------------------------------------------------------
    # GSAP-style shorthand API
    # Supported properties:
    #   blur            – Gaussian blur kernel size (int, 0 = off)
    #   rgb_shift       – Chromatic aberration pixel offset (float)
    #   rgb_shift_angle – Direction of the RGB shift in degrees (float, default 0)
    #   zoom            – Scale factor (float, 1.0 = original size)
    #   saturation      – Saturation multiplier (float, 1.0 = unchanged)
    #   brightness      – Additive brightness offset (float, 0 = unchanged)
    #   contrast        – Contrast multiplier (float, 1.0 = unchanged)
    #   gamma           – Gamma correction (float, 1.0 = unchanged)
    # ------------------------------------------------------------------

    def _build_effects_from_props(self, from_props: dict, to_props: dict, easing) -> list:
        """Internal: converts property dicts into concrete effect instances."""
        from utils.effects import BlurEffect, RGBShiftEffect, ZoomEffect, ColorAdjustEffect

        effects = []

        # --- Blur ---
        blur_keys = {"blur"}
        if blur_keys & (from_props.keys() | to_props.keys()):
            start_blur = from_props.get("blur", 0)
            end_blur   = to_props.get("blur", 0)
            effects.append(BlurEffect(start_blur=start_blur, end_blur=end_blur, easing=easing))

        # --- RGB Shift ---
        shift_keys = {"rgb_shift", "rgb_shift_angle"}
        if shift_keys & (from_props.keys() | to_props.keys()):
            start_shift = from_props.get("rgb_shift", 0.0)
            end_shift   = to_props.get("rgb_shift", 0.0)
            # Angle doesn't animate between from/to; use whichever is defined (to takes priority)
            angle = to_props.get("rgb_shift_angle", from_props.get("rgb_shift_angle", 0.0))
            effects.append(RGBShiftEffect(start_shift=start_shift, end_shift=end_shift, angle=angle, easing=easing))

        # --- Zoom ---
        if "zoom" in (from_props.keys() | to_props.keys()):
            start_zoom = from_props.get("zoom", 1.0)
            end_zoom   = to_props.get("zoom", 1.0)
            effects.append(ZoomEffect(start_zoom=start_zoom, end_zoom=end_zoom, easing=easing))

        # --- Color (saturation, brightness, contrast, gamma) ---
        color_keys = {"saturation", "brightness", "contrast", "gamma"}
        if color_keys & (from_props.keys() | to_props.keys()):
            effects.append(ColorAdjustEffect(
                start_params={k: from_props[k] for k in color_keys if k in from_props},
                end_params  ={k: to_props[k]   for k in color_keys if k in to_props},
                easing=easing
            ))

        return effects

    def to(self, clip_idx: int, duration: float, start_time: float = 0.0,
           easing="linear", **props):
        """
        GSAP-style .to() — animates FROM the neutral/default value TO the given props.

        Example:
            pipeline.to(clip_idx=0, duration=1.5, blur=25, zoom=1.3, easing="ease_out")
        """
        # Neutral starting values
        neutral = {
            "blur": 0, "rgb_shift": 0.0, "zoom": 1.0,
            "saturation": 1.0, "brightness": 0.0, "contrast": 1.0, "gamma": 1.0
        }
        from_props = {k: neutral[k] for k in props if k in neutral}
        for eff in self._build_effects_from_props(from_props, props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def from_(self, clip_idx: int, duration: float, start_time: float = 0.0,
              easing="linear", **props):
        """
        GSAP-style .from_() — animates FROM the given props BACK TO the neutral/default value.

        Example:
            pipeline.from_(clip_idx=1, duration=1.0, blur=31, zoom=1.5, easing="ease_in")
        """
        neutral = {
            "blur": 0, "rgb_shift": 0.0, "zoom": 1.0,
            "saturation": 1.0, "brightness": 0.0, "contrast": 1.0, "gamma": 1.0
        }
        to_props = {k: neutral[k] for k in props if k in neutral}
        for eff in self._build_effects_from_props(props, to_props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def fromTo(self, clip_idx: int, duration: float, from_props: dict, to_props: dict,
               start_time: float = 0.0, easing="linear"):
        """
        GSAP-style .fromTo() — explicit control over both start and end values.

        Example:
            pipeline.fromTo(
                clip_idx=1, duration=2.0,
                from_props={"saturation": 0.0, "blur": 15},
                to_props  ={"saturation": 1.5, "blur": 0},
                easing=(0.42, 0, 0.58, 1)
            )
        """
        for eff in self._build_effects_from_props(from_props, to_props, easing):
            self.add_clip_effect(clip_idx, eff, start_time=start_time, duration=duration)

    def render(self, output_path: str):
        if not self.clips:
            print("No clips added.")
            return

        import os
        import subprocess
        try:
            from pydub import AudioSegment
        except ImportError:
            print("pydub not installed. Running without audio.")
            AudioSegment = None

        temp_video_path = "temp_video_output.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, self.output_size)
        
        final_audio = None
        
        # Open all captures
        caps = [cv2.VideoCapture(c["filepath"]) for c in self.clips]
        
        # Verify captures and pre-calculate durations
        for i, cap in enumerate(caps):
            if not cap.isOpened():
                print(f"Failed to open video: {self.clips[i]['filepath']}")
                return
            if self.clips[i]["duration"] <= 0:
                total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps > 0 and total_frames > 0:
                    self.clips[i]["duration"] = total_frames / fps
                else:
                    self.clips[i]["duration"] = 1.0
        
        def get_frame(cap, target_size):
            ret, frame = cap.read()
            if not ret:
                return False, None
            
            # Aspect ratio (Scale to fit and pad with black bars)
            h, w = frame.shape[:2]
            tw, th = target_size
            
            # Scale to fit
            scale = min(tw / w, th / h)
            nw, nh = int(w * scale), int(h * scale)
            
            if nw == 0 or nh == 0:
                 return False, None
                 
            resized = cv2.resize(frame, (nw, nh))
            
            # Create black background canvas
            out_frame = np.zeros((th, tw, 3), dtype=np.uint8)
            
            # Paste the resized frame in the center
            y1 = (th - nh) // 2
            x1 = (tw - nw) // 2
            out_frame[y1:y1+nh, x1:x1+nw] = resized
            
            return True, out_frame

        current_clip_idx = 0
        current_time = 0.0
        clip_local_times = [0.0] * len(self.clips)
        
        while current_clip_idx < len(self.clips):
            cap1 = caps[current_clip_idx]
            clip_dur = self.clips[current_clip_idx]["duration"]
            
            if clip_dur <= 0:
                total_frames = cap1.get(cv2.CAP_PROP_FRAME_COUNT)
                fps = cap1.get(cv2.CAP_PROP_FPS)
                if fps > 0 and total_frames > 0:
                    clip_dur = total_frames / fps
                else:
                    clip_dur = 1.0 # fallback
            
            # Process Audio
            if AudioSegment is not None:
                try:
                    audio_clip = AudioSegment.from_file(self.clips[current_clip_idx]["filepath"])
                    # Match exact video frame duration
                    audio_clip = audio_clip[:int(clip_dur * 1000)]
                except Exception:
                    # Fallback to silence if no audio track exists
                    audio_clip = AudioSegment.silent(duration=int(clip_dur * 1000))
                
                if final_audio is None:
                    final_audio = audio_clip
                else:
                    # Apply crossfade using the PREVIOUS transition's duration
                    prev_trans = self.transitions[current_clip_idx - 1] if current_clip_idx - 1 < len(self.transitions) else None
                    prev_trans_dur = prev_trans.duration if prev_trans else 0.0
                    
                    if prev_trans_dur > 0:
                        fade_ms = int(prev_trans_dur * 1000)
                        # pydub crossfade must be strictly less than the length of either clip
                        fade_ms = min(fade_ms, len(final_audio) - 1, len(audio_clip) - 1)
                        if fade_ms > 0:
                            final_audio = final_audio.append(audio_clip, crossfade=fade_ms)
                        else:
                            final_audio += audio_clip
                    else:
                        final_audio += audio_clip

            has_transition = current_clip_idx < len(self.transitions) and current_clip_idx + 1 < len(self.clips)
            transition = self.transitions[current_clip_idx] if has_transition else None
            trans_duration = transition.duration if transition else 0.0
            
            frames_to_read = int((clip_dur - trans_duration) * self.fps)
            trans_frames = int(trans_duration * self.fps)
            
            def apply_local_effects(frame, clip_dict, local_time):
                c_dur = clip_dict["duration"]
                for eff in clip_dict["effects"]:
                    eff_start = eff["start_time"]
                    eff_dur = eff["duration"] if eff["duration"] > 0 else max(0.001, c_dur - eff_start)
                    eff_end = eff_start + eff_dur

                    if eff_start <= local_time <= eff_end:
                        progress       = (local_time - eff_start) / eff_dur
                        progress       = min(1.0, max(0.0, progress))
                        effect_time    = local_time - eff_start   # seconds since THIS effect started
                        frame = eff["effect"].process(frame, effect_time, progress)
                return frame

            def apply_global_effects(frame, time_val):
                for eff in self.effects:
                    eff_start = eff["start_time"]
                    eff_dur   = eff["duration"]
                    eff_end   = eff_start + eff_dur if eff_dur > 0 else 999999.0

                    if eff_start <= time_val <= eff_end:
                        if eff_dur > 0:
                            progress    = (time_val - eff_start) / eff_dur
                            effect_time = time_val - eff_start
                        else:
                            progress    = 1.0
                            effect_time = time_val - eff_start
                        progress = min(1.0, max(0.0, progress))
                        frame = eff["effect"].process(frame, effect_time, progress)
                return frame

            # Read solo frames
            for _ in range(frames_to_read):
                ret, frame = get_frame(cap1, self.output_size)
                if not ret:
                    break
                
                # Apply Local Effects -> Global Effects
                frame = apply_local_effects(frame, self.clips[current_clip_idx], clip_local_times[current_clip_idx])
                frame = apply_global_effects(frame, current_time)
                
                out.write(frame)
                current_time += 1.0 / self.fps
                clip_local_times[current_clip_idx] += 1.0 / self.fps
            
            # Apply transition
            if has_transition and trans_frames > 0:
                cap2 = caps[current_clip_idx + 1]
                for t_f in range(trans_frames):
                    ret1, frame1 = get_frame(cap1, self.output_size)
                    ret2, frame2 = get_frame(cap2, self.output_size)
                    
                    if not ret1 or not ret2:
                        break # One of the videos ended early
                    
                    # Apply Local Effects BEFORE Transition blending!
                    frame1 = apply_local_effects(frame1, self.clips[current_clip_idx], clip_local_times[current_clip_idx])
                    frame2 = apply_local_effects(frame2, self.clips[current_clip_idx + 1], clip_local_times[current_clip_idx + 1])
                    
                    # Blend
                    progress = t_f / float(trans_frames)
                    blended = transition.process(frame1, frame2, progress)
                    
                    # Apply Global Effects AFTER Transition
                    blended = apply_global_effects(blended, current_time)
                    
                    out.write(blended)
                    current_time += 1.0 / self.fps
                    clip_local_times[current_clip_idx] += 1.0 / self.fps
                    clip_local_times[current_clip_idx + 1] += 1.0 / self.fps

            current_clip_idx += 1

        for cap in caps:
            cap.release()
        out.release()
        
        if final_audio is not None and len(final_audio) > 0:
            print("Exporting audio and muxing...")
            temp_audio_path = "temp_audio.wav"
            final_audio.export(temp_audio_path, format="wav")
            
            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_video_path,
                "-i", temp_audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(temp_video_path): os.remove(temp_video_path)
            if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
            print(f"Render complete with audio: {output_path}")
        else:
            if os.path.exists(output_path): os.remove(output_path)
            os.rename(temp_video_path, output_path)
            print(f"Render complete: {output_path}")

if __name__ == "__main__":
    pipeline = VideoPipeline(fps=30.0, output_size=(1920, 1080))

    print("Setting up pipeline...")
    pipeline.add_clip("person_reel_vertical_test.mp4", duration=5.0)

    pipeline.add_transition(ZoomTransition(duration=0.3, easing=(0.75, 0, 0.25, 1), mode="inout"))

    pipeline.add_clip("test2.mp4", duration=3.0)

    from utils.effects import YoloTextEffect

    # --- Low-level API: glow + depth-composite text on clip 0 ---
    print("Loading YOLO Effects...")
    glow_effect = YoloGlowSegEffect(
        model_path="utils/yolo26n-seg_int8_openvino_model/",
        glow_color=(255, 100, 100),
        intensity=3
    )
    pipeline.add_clip_effect(clip_idx=0, effect=glow_effect)

    # Text slides up and fades in. Person is composited on top via YOLO seg,
    # so the subject appears to stand IN FRONT of the text.
    #
    # Total on-screen time = transition_in + hold + transition_out
    #   start_time=1.0, duration=4.0  →  on screen from 1s to 5s
    #   transition_in=0.6             →  slides up for 0.6s
    #   transition_out=0.4            →  fades out for the last 0.4s
    #   hold = 4.0 - 0.6 - 0.4 = 3.0s at full visibility
    title_text = YoloTextEffect(
        text="HIGHLIGHT REEL",
        font_path="Audiowide-Regular.ttf",
        font_size=96,
        position="center",
        color=(255, 255, 255),
        opacity=1.0,
        transition_in=0.6,
        transition_out=0.4,
        animate_in="slide_up",
        animate_out="fade",
        stroke_width=4,
        stroke_color=(0, 0, 0),
        model_path="utils/yolo26n-seg_int8_openvino_model/",
        easing="ease_out"
    )
    pipeline.add_clip_effect(clip_idx=0, effect=title_text, start_time=1.0, duration=4.0)

    # --- Clip 1: caption — 0.4s fade in, hold, 0.3s fade out; no YOLO for speed ---
    caption = YoloTextEffect(
        text="ft. @username",
        font_size=48,
        position="top_right",
        color=(200, 200, 200),
        opacity=0.9,
        transition_in=0.4,
        transition_out=0.3,
        animate_in="fade",
        animate_out="fade",
        model_path=None,
    )
    pipeline.add_clip_effect(clip_idx=1, effect=caption, start_time=0.0, duration=2.0)


    # --- GSAP-style API ---
    pipeline.to(clip_idx=0, duration=5.0, zoom=1.2, easing="ease_out")
    pipeline.fromTo(
        clip_idx=0, duration=5.0,
        from_props={"saturation": 0.5},
        to_props  ={"saturation": 1.8},
        easing="ease_in_out"
    )
    pipeline.from_(clip_idx=1, duration=0.8, brightness=-120, saturation=0.0, easing="ease_out")
    pipeline.to(clip_idx=1, duration=1.5, start_time=1.5,
                blur=31, rgb_shift=30, rgb_shift_angle=45, easing="ease_in")

    print("Rendering video...")
    pipeline.render("output.mp4")
