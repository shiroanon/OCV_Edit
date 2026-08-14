use crate::effect::{BoxedEffect, BoxedTransition};
use crate::frame::*;
use crate::scene::{GridScene, LayeredScene, SceneSources};
use anyhow::{Context, Result};
use serde::Serialize;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Mutex;

pub const CLIP_END: &str = "clip_end";
pub const CLIP_END_INT: f64 = -1.0;

/// Deterministic FNV-1a hash — used to pick a stable pseudo-random binaural
/// placement per source file so repeated renders don't jump around the room.
fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

/// Per-clip audio descriptor passed to the Python audio bridge. Mirroring
/// `utils/audio.py`, segment extraction (ffmpeg seek + pydub pad/trim) and the
/// crossfade merge happen in Python so the Rust port's audio matches the Python
/// reference exactly.
#[derive(Serialize)]
pub struct AudioSegSpec {
    pub filepath: String,
    pub start_time: f32,
    pub clip_dur: f32,
    pub clip_speed: f32,
    pub keep_audio: bool,
    pub crossfade_ms: u32,
    /// Horizontal placement of this clip's original audio in the binaural room
    /// (degrees; 0 = front-center, +30 = right, -30 = left). Mirrors
    /// `audioProcessing.py`'s azimuth placement.
    pub azimuth_deg: f64,
    /// When true the source orbits the listener (moving source, as in
    /// `audioProcessing.py`'s `ch_moving` segment).
    pub moving: bool,
}

pub struct EffectEntry {
    pub effect: BoxedEffect,
    pub start_time: f32,
    pub duration: f64, // <0 => until clip end
}

/// A background decode worker for one `ClipItem::File` clip.
///
/// ffmpeg decode + resize run on a dedicated thread, overlapping with the main
/// thread's effect processing + encode. The worker emits the clip's frames in
/// display order through a bounded channel (capacity 2 → at most a couple of
/// frames buffered, so memory stays bounded):
///
///   1. **head**  — local time `[0, incoming_dur)`, shown during the incoming
///      transition
///   2. **body**  — local time `[incoming_dur, incoming_dur + clip_dur - trans_out)`,
///      the bulk of the clip's frames
///   3. **tail**  — local time `[incoming_dur + clip_dur - trans_out, …)`, shown
///      during the outgoing transition
///
/// The tail start mirrors the Python-port bookkeeping in `render()` (persistent
/// `clip_local_times`), so frame order/duration is identical to the synchronous
/// path. `read_at` advances monotonically through the clip, so it never triggers
/// an ffmpeg re-seek.
struct DecodeWorker {
    rx: std::sync::mpsc::Receiver<Result<Option<Frame>, String>>,
}

impl DecodeWorker {
    fn spawn(
        filepath: String,
        start_time: f32,
        speed: f32,
        resize_mode: String,
        incoming_dur: f32,
        clip_dur: f32,
        trans_out: f32,
        ow: u32,
        oh: u32,
        fps: f64,
    ) -> DecodeWorker {
        let (tx, rx) = std::sync::mpsc::sync_channel::<Result<Option<Frame>, String>>(2);
        std::thread::spawn(move || {
            let mut src = match VideoSource::open(&filepath) {
                Ok(s) => s,
                Err(e) => {
                    let _ = tx.send(Err(e.to_string()));
                    return;
                }
            };
            let fpsf = fps as f32;
            let head = (incoming_dur * fpsf).max(0.0) as usize;
            let body = ((clip_dur - trans_out) * fpsf).max(0.0) as usize;
            let tail = (trans_out * fpsf).max(0.0) as usize;

            let emit = |src: &mut VideoSource,
                        tx: &std::sync::mpsc::SyncSender<Result<Option<Frame>, String>>,
                        local: f32|
             -> bool {
                let st = start_time as f64 + local as f64 * speed as f64;
                match src.read_at(st) {
                    Ok(Some(f)) => {
                        let f = resize_frame(&f, ow, oh, &resize_mode);
                        tx.send(Ok(Some(f))).is_ok()
                    }
                    Ok(None) => {
                        let _ = tx.send(Ok(None));
                        false
                    }
                    Err(e) => {
                        let _ = tx.send(Err(e.to_string()));
                        false
                    }
                }
            };

            let mut ok = true;
            for tf in 0..head {
                if !ok {
                    break;
                }
                ok = emit(&mut src, &tx, tf as f32 / fpsf);
            }
            for i in 0..body {
                if !ok {
                    break;
                }
                ok = emit(&mut src, &tx, incoming_dur + i as f32 / fpsf);
            }
            for tf in 0..tail {
                if !ok {
                    break;
                }
                ok = emit(&mut src, &tx, incoming_dur + clip_dur - trans_out + tf as f32 / fpsf);
            }
            // Dropping `tx` here (and any in `emit`) signals EOF to the consumer.
        });
        DecodeWorker { rx }
    }

    /// Next decoded frame in emission order. Returns `Ok(None)` at end of
    /// stream (worker sent its terminal `None` or exited).
    fn recv(&self) -> anyhow::Result<Option<Frame>> {
        match self.rx.recv() {
            Ok(Ok(f)) => Ok(f),
            Ok(Err(e)) => anyhow::bail!("decode worker error: {e}"),
            Err(_) => Ok(None),
        }
    }
}

pub enum ClipItem {
    File {
        filepath: String,
        start_time: f32,
        duration: f32,
        speed: f32,
        keep_audio: bool,
        resize_mode: String,
        effects: Vec<EffectEntry>,
    },
    Grid {
        scene: GridScene,
        sources: Mutex<SceneSources>,
        duration: f32,
        effects: Vec<EffectEntry>,
        audio_filepath: Option<String>,
        audio_start: f32,
        audio_speed: f32,
    },
    Layered {
        scene: LayeredScene,
        sources: Mutex<SceneSources>,
        duration: f32,
        effects: Vec<EffectEntry>,
        audio_filepath: Option<String>,
        audio_start: f32,
        audio_speed: f32,
    },
}

impl ClipItem {
    fn duration(&self) -> f32 {
        match self {
            ClipItem::File { duration, .. } => *duration,
            ClipItem::Grid { duration, .. } => *duration,
            ClipItem::Layered { duration, .. } => *duration,
        }
    }
    fn keep_audio_filepath(&self) -> Option<String> {
        match self {
            ClipItem::File { filepath, keep_audio, .. } => {
                if *keep_audio {
                    Some(filepath.clone())
                } else {
                    None
                }
            }
            ClipItem::Grid { audio_filepath, .. }
            | ClipItem::Layered { audio_filepath, .. } => audio_filepath.clone(),
        }
    }
    fn audio_start_speed(&self) -> (f32, f32) {
        match self {
            ClipItem::File { start_time, speed, .. } => (*start_time, *speed),
            ClipItem::Grid { audio_start, audio_speed, .. }
            | ClipItem::Layered { audio_start, audio_speed, .. } => (*audio_start, *audio_speed),
        }
    }
    /// Binaural-room placement for this clip's original audio. Grid clips pan
    /// with their audio panel's on-screen position; plain file clips pick a
    /// deterministic pseudo-random spot among {left, center, right, moving}.
    fn audio_position(&self) -> (f64, bool) {
        match self {
            ClipItem::File { filepath, .. } => match fnv1a(filepath.as_bytes()) % 4 {
                0 => (-30.0, false),
                1 => (0.0, false),
                2 => (30.0, false),
                _ => (0.0, true),
            },
            ClipItem::Grid { scene, .. } => {
                // Audio comes from the center panel (see `grid_audio_source`).
                let idx = if scene.panels.len() >= 2 { 1 } else { 0 };
                let px = scene
                    .panels
                    .get(idx)
                    .and_then(|p| p.position)
                    .map(|(x, _)| x)
                    .unwrap_or(0.5);
                (((px - 0.5) * 2.0 * 30.0) as f64, false)
            }
            ClipItem::Layered { .. } => (0.0, false),
        }
    }
    fn effects(&self) -> &[EffectEntry] {
        match self {
            ClipItem::File { effects, .. } => effects,
            ClipItem::Grid { effects, .. } => effects,
            ClipItem::Layered { effects, .. } => effects,
        }
    }
}

pub struct VideoPipeline {
    fps: f64,
    output_size: (u32, u32),
    resize_mode: String,
    pub clips: Vec<ClipItem>,
    pub transitions: Vec<Option<(BoxedTransition, f32)>>,
    pub global_effects: Vec<EffectEntry>,
    /// Full background audio track (e.g. the music file) muxed into the
    /// final output, mirroring the Python tool's post-render audio mux.
    pub background_audio: Option<String>,
}

impl VideoPipeline {
    pub fn new(fps: f64, output_size: (u32, u32), resize_mode: &str) -> Self {
        VideoPipeline {
            fps,
            output_size,
            resize_mode: resize_mode.to_string(),
            clips: Vec::new(),
            transitions: Vec::new(),
            global_effects: Vec::new(),
            background_audio: None,
        }
    }

    pub fn set_background_audio(&mut self, path: Option<String>) {
        self.background_audio = path;
    }

    pub fn add_clip(&mut self, filepath: &str, start_time: f32, duration: f32, speed: f32, keep_audio: bool, resize_mode: &str) {
        self.clips.push(ClipItem::File {
            filepath: filepath.to_string(),
            start_time,
            duration,
            speed,
            keep_audio,
            resize_mode: if resize_mode.is_empty() { self.resize_mode.clone() } else { resize_mode.to_string() },
            effects: Vec::new(),
        });
        self.transitions.push(None);
    }

    pub fn add_clip_effect(&mut self, clip_idx: usize, effect: BoxedEffect, start_time: f32, duration: f64) {
        if let Some(ClipItem::File { effects, .. }) = self.clips.get_mut(clip_idx) {
            effects.push(EffectEntry { effect, start_time, duration });
        }
    }

    /// `audio` is the optional original-audio source for the scene:
    /// `(filepath, source_start_time, speed)`. It must be the panel whose
    /// audio the user wants kept (e.g. the center/main panel of a wave grid),
    /// not the scene's first source. `None` renders the scene silent.
    pub fn add_grid_scene(&mut self, scene: GridScene, sources: SceneSources, duration: f32, audio: Option<(String, f32, f32)>) {
        let (audio_filepath, audio_start, audio_speed) = match audio {
            Some((fp, st, sp)) => (Some(fp), st, sp),
            None => (None, 0.0, 1.0),
        };
        self.clips.push(ClipItem::Grid { scene, sources: Mutex::new(sources), duration, effects: Vec::new(), audio_filepath, audio_start, audio_speed });
        self.transitions.push(None);
    }

    pub fn add_layered_scene(&mut self, scene: LayeredScene, sources: SceneSources, duration: f32, audio: Option<(String, f32, f32)>) {
        let (audio_filepath, audio_start, audio_speed) = match audio {
            Some((fp, st, sp)) => (Some(fp), st, sp),
            None => (None, 0.0, 1.0),
        };
        self.clips.push(ClipItem::Layered { scene, sources: Mutex::new(sources), duration, effects: Vec::new(), audio_filepath, audio_start, audio_speed });
        self.transitions.push(None);
    }

    pub fn add_transition(&mut self, transition: BoxedTransition, duration: f32) {
        if let Some(slot) = self.transitions.last_mut() {
            *slot = Some((transition, duration));
        }
    }

    pub fn add_global_effect(&mut self, effect: BoxedEffect, start_time: f32, duration: f64) {
        self.global_effects.push(EffectEntry { effect, start_time, duration });
    }

    fn apply_effects(frame: Frame, effects: &[EffectEntry], local_time: f32, clip_dur: f32, fi: u64) -> Frame {
        let mut f = frame;
        for e in effects {
            let ed = if e.duration < 0.0 { (clip_dur - e.start_time).max(0.001) } else { e.duration as f32 };
            if local_time >= e.start_time && local_time <= e.start_time + ed {
                let p = ((local_time - e.start_time) / ed).clamp(0.0, 1.0);
                f = e.effect.process(&f, local_time - e.start_time, p, fi);
            }
        }
        f
    }

    fn apply_global(frame: Frame, globals: &[EffectEntry], time_val: f32, fps: f32) -> Frame {
        let mut f = frame;
        for e in globals {
            let ed = if e.duration < 0.0 { f32::MAX } else { e.duration as f32 };
            if time_val >= e.start_time && time_val <= e.start_time + ed {
                let p = if e.duration < 0.0 {
                    1.0
                } else {
                    ((time_val - e.start_time) / ed).clamp(0.0, 1.0)
                };
                f = e.effect.process(&f, time_val - e.start_time, p, (time_val * fps).round() as u64);
            }
        }
        f
    }

    fn get_clip_frame(
        &self,
        clip: &ClipItem,
        file_src: &mut Option<VideoSource>,
        local_time: f32,
    ) -> Result<Option<Frame>> {
        let (ow, oh) = self.output_size;
        match clip {
            ClipItem::File { start_time, speed, resize_mode, .. } => {
                let src = file_src.as_mut().unwrap();
                let src_time = *start_time as f64 + (local_time as f64) * (*speed as f64);
                let frame = src.read_at(src_time)?;
                match frame {
                    Some(f) => Ok(Some(resize_frame(&f, ow, oh, resize_mode))),
                    None => Ok(None),
                }
            }
            ClipItem::Grid { scene, sources, .. } => {
                let mut prov = sources.lock().unwrap();
                Ok(Some(scene.render_frame(local_time, (ow, oh), &mut *prov, self.fps as f32)))
            }
            ClipItem::Layered { scene, sources, .. } => {
                let mut prov = sources.lock().unwrap();
                Ok(Some(scene.render_frame(local_time, (ow, oh), &mut *prov, self.fps as f32)))
            }
        }
    }

    fn estimate_total_frames(&self) -> usize {
        let mut total = 0usize;
        for (i, c) in self.clips.iter().enumerate() {
            let cd = c.duration();
            let td = if i < self.transitions.len() {
                self.transitions[i].as_ref().map(|(_, d)| *d).unwrap_or(0.0)
            } else {
                0.0
            };
            total += ((cd - td) * self.fps as f32).max(0.0) as usize;
            total += (td * self.fps as f32).max(0.0) as usize;
        }
        total
    }

    /// Duration of clip `idx`'s outgoing transition (0 if none).
    fn trans_out_dur(&self, idx: usize) -> f32 {
        self.transitions.get(idx).and_then(|t| t.as_ref().map(|(_, d)| *d)).unwrap_or(0.0)
    }

    /// Spawn a background decode worker for `clip` when it is a
    /// `ClipItem::File`; returns `None` for scene clips (they render
    /// synchronously). `incoming_dur` is how far into the clip the head blend
    /// already played, `trans_out` is the duration of the outgoing transition
    /// whose tail frames this worker must produce.
    fn spawn_file_worker(&self, clip: &ClipItem, incoming_dur: f32, trans_out: f32) -> Option<DecodeWorker> {
        if let ClipItem::File { filepath, start_time, speed, resize_mode, .. } = clip {
            let clip_dur = clip.duration();
            let (ow, oh) = self.output_size;
            Some(DecodeWorker::spawn(
                filepath.clone(),
                *start_time,
                *speed,
                resize_mode.clone(),
                incoming_dur,
                clip_dur,
                trans_out,
                ow,
                oh,
                self.fps,
            ))
        } else {
            None
        }
    }

    pub fn render(&self, output_path: &str) -> Result<()> {
        if self.clips.is_empty() {
            println!("No clips added.");
            return Ok(());
        }
        let (ow, oh) = self.output_size;
        let fps = self.fps;

        // Compute once, used in the log line and for background audio duration.
        let total_frames = self.estimate_total_frames();

        let mut sink = VideoSink::create(output_path, fps, ow, oh, "libx264")?;

        let mut audio_segs: Vec<AudioSegSpec> = Vec::new();
        let any_audio = self.clips.iter().any(|c| c.keep_audio_filepath().is_some());

        let mut current = 0usize;
        let mut frame_count: u64 = 0;
        eprintln!(
            "Rendering {} clips (~{:.1}s @ {:.0}fps) -> {output_path}",
            self.clips.len(),
            total_frames as f64 / fps,
            fps
        );
        // A decode worker spawned by a clip's outgoing transition, carried over
        // into the next clip. Its head frames were consumed during the blend;
        // body/tail remain for the next iteration.
        let mut pending_worker: Option<DecodeWorker> = None;
        while current < self.clips.len() {
            let clip = &self.clips[current];
            let clip_dur = clip.duration();
            let has_trans = current + 1 < self.clips.len()
                && current < self.transitions.len()
                && self.transitions[current].is_some();
            let (trans, trans_dur) = if has_trans {
                let (t, d) = self.transitions[current].as_ref().unwrap();
                (Some(t), *d)
            } else {
                (None, 0.0)
            };

            // How far the clip's head was already shown during the PREVIOUS
            // clip's transition blend (mirrors Python's persistent
            // `clip_local_times`, which advance for both clips during a
            // transition). The clip's audio segment spans the full clip_dur and
            // its head is crossfaded in during that same blend, so the visual
            // loop must continue from here — otherwise the head is re-shown
            // (double-render) and the audio runs ahead of the visuals.
            let incoming_dur = if current > 0 {
                self.transitions[current - 1].as_ref().map(|(_, d)| *d).unwrap_or(0.0)
            } else {
                0.0
            };

            // Pipelined decode: for `ClipItem::File` clips, reuse the worker
            // spawned by the previous clip's outgoing transition (its head
            // frames were already blended in), or spawn a fresh one. Scene
            // clips render synchronously via their own sources.
            let mut worker: Option<DecodeWorker> = pending_worker.take();
            if matches!(clip, ClipItem::File { .. }) && worker.is_none() {
                worker = self.spawn_file_worker(clip, incoming_dur, trans_dur);
            }

            if any_audio {
                let (az, mov) = clip.audio_position();
                if let Some(fp) = clip.keep_audio_filepath() {
                    let (st, sp) = clip.audio_start_speed();
                    let prev = if current > 0 { self.transitions[current - 1].as_ref().map(|(_, d)| *d) } else { None };
                    let crossfade = prev.map(|d| (d * 1000.0) as u32).unwrap_or(0);
                    audio_segs.push(AudioSegSpec {
                        filepath: fp,
                        start_time: st,
                        clip_dur,
                        clip_speed: sp,
                        keep_audio: true,
                        crossfade_ms: crossfade,
                        azimuth_deg: az,
                        moving: mov,
                    });
                } else {
                    let prev = if current > 0 { self.transitions[current - 1].as_ref().map(|(_, d)| *d) } else { None };
                    let crossfade = prev.map(|d| (d * 1000.0) as u32).unwrap_or(0);
                    audio_segs.push(AudioSegSpec {
                        filepath: String::new(),
                        start_time: 0.0,
                        clip_dur,
                        clip_speed: 1.0,
                        keep_audio: false,
                        crossfade_ms: crossfade,
                        azimuth_deg: az,
                        moving: mov,
                    });
                }
            }

            let frames_to_read = ((clip_dur - trans_dur) * fps as f32).max(0.0) as usize;
            // Continue from where the incoming transition left off (see
            // `incoming_dur` above). `global_time` is the monotonic output
            // timeline position (frame_index/fps), matching Python's
            // `current_time`.
            let mut local_time = incoming_dur;
            let mut global_time = frame_count as f32 / fps as f32;

            for _ in 0..frames_to_read {
                let base = match &worker {
                    Some(w) => w.recv()?,
                    None => self.get_clip_frame(clip, &mut None, local_time)?,
                };
                let f = match base {
                    Some(fr) => fr,
                    None => break,
                };
                let fi = (local_time * fps as f32).round() as u64;
                let f = Self::apply_effects(f, clip.effects(), local_time, clip_dur, fi);
                let f = Self::apply_global(f, &self.global_effects, global_time, self.fps as f32);
                sink.write_frame(&f)?;
                local_time += 1.0 / fps as f32;
                global_time += 1.0 / fps as f32;
                frame_count += 1;
                if frame_count % 30 == 0 {
                    eprintln!("  frame {frame_count} (clip {}/{})", current + 1, self.clips.len());
                }
            }

            if let Some(t) = trans {
                let td = (trans_dur * fps as f32).max(0.0) as usize;
                // Spawn the next clip's decode worker now: its head frames
                // (local 0..trans_dur) are exactly what this transition blends
                // in, and the worker carries over into the next clip's body so
                // decode keeps running ahead of the encode.
                let mut next_worker: Option<DecodeWorker> = None;
                if current + 1 < self.clips.len() {
                    next_worker = self.spawn_file_worker(&self.clips[current + 1], trans_dur, self.trans_out_dur(current + 1));
                }
                for tf in 0..td {
                    let p = if td == 0 { 1.0 } else { tf as f32 / td as f32 };
                    let f1 = match &worker {
                        Some(w) => w.recv()?,
                        None => self.get_clip_frame(clip, &mut None, local_time)?,
                    };
                    // The incoming clip plays from its OWN local time (0..trans_dur)
                    // during the transition, mirroring Python's
                    // `clip_local_times[next_clip_idx]`. Using the outgoing clip's
                    // local_time here made the transition show the next clip's
                    // mid/tail frames while its audio was only starting — A/V desync.
                    let next_local = tf as f32 / fps as f32;
                    let f2 = if current + 1 < self.clips.len() {
                        match &next_worker {
                            Some(w) => w.recv()?,
                            None => self.get_clip_frame(&self.clips[current + 1], &mut None, next_local)?,
                        }
                    } else {
                        None
                    };
                    if let (Some(a), Some(b)) = (f1, f2) {
                        let blended = t.process(&a, &b, p);
                        let blended = Self::apply_global(blended, &self.global_effects, global_time, self.fps as f32);
                        sink.write_frame(&blended)?;
                        frame_count += 1;
                        if frame_count % 30 == 0 {
                            eprintln!("  frame {frame_count} (clip {}/{})", current + 1, self.clips.len());
                        }
                    }
                    local_time += 1.0 / fps as f32;
                    global_time += 1.0 / fps as f32;
                }
                // Hand the next clip's worker (head already consumed) to the
                // next iteration so its body decode continues in the background.
                pending_worker = next_worker;
            }

            // Close grid/layered sources now that this clip is done rendering.
            // Without this, ALL sources for ALL grid/layered scenes stay open
            // for the entire pipeline lifetime — each ffmpeg decoder can use
            // 50-200+ MB, so 50 grid scenes × 2 sources = 100 concurrent
            // processes → easily 10+ GB.
            match clip {
                ClipItem::Grid { sources, .. } => sources.lock().unwrap().close_all(),
                ClipItem::Layered { sources, .. } => sources.lock().unwrap().close_all(),
                _ => {}
            }

            current += 1;
        }

        sink.finish()?;

        // Delegate all audio to the Python bridge (`python/audio_bridge.py`),
        // which mirrors `utils/audio.py`: per-clip extraction via ffmpeg seek +
        // pydub pad/trim, crossfade merge, background-music mix, and final mux.
        let bgm_path = self.background_audio.clone().unwrap_or_default();
        if !audio_segs.is_empty() || !bgm_path.is_empty() {
            eprintln!("Building audio track ({} clip segment(s))...", audio_segs.len());
            let spec = serde_json::json!({
                "video": output_path,
                "output": output_path,
                "bgm": if bgm_path.is_empty() { serde_json::Value::Null } else { serde_json::Value::String(bgm_path) },
                "clip_volume": 2.0,
                "bgm_volume": 0.3,
                "segments": audio_segs,
            });
            let bridge = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../python/audio_bridge.py");
            let mut child = Command::new("python3")
                .arg(&bridge)
                .stdin(Stdio::piped())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
                .context("spawn python audio bridge")?;
            if let Some(stdin) = child.stdin.as_mut() {
                stdin.write_all(spec.to_string().as_bytes())?;
            }
            let status = child.wait().context("wait python audio bridge")?;
            if !status.success() {
                anyhow::bail!("python audio bridge failed (exit {status})");
            }
        } else {
            eprintln!("No audio sources — output will be silent");
        }

        println!("Render complete: {output_path}");
        Ok(())
    }
}
