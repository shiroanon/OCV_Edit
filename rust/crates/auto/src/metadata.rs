use anyhow::Result;
use mp4ameta::{FreeformIdent, Tag};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize, Default)]
pub struct AudioMeta {
    #[serde(default)]
    pub segments: Vec<BeatSegment>,
    #[serde(default)]
    pub duration: Option<f32>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct BeatSegment {
    #[serde(default)]
    pub major: Vec<f32>,
    #[serde(default)]
    pub minor: Vec<f32>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct VideoMeta {
    #[serde(default)]
    pub segments: Vec<VideoSegment>,
    #[serde(default)]
    pub duration: Option<f32>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct VideoSegment {
    #[serde(default)]
    pub meta: VideoSegMeta,
    #[serde(default)]
    pub interval: Option<[f32; 2]>,
    #[serde(default)]
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct VideoSegMeta {
    #[serde(default)]
    pub actpoints: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct VideoData {
    pub file: String,
    pub interval: [f32; 2],
    pub actpoints: Vec<f32>,
    pub tags: Vec<String>,
}

/// Parse "mm:ss.mmm" / "hh:mm:ss" / plain seconds.
pub fn parse_timecode(tc: &str) -> f32 {
    let tc = tc.trim();
    if let Ok(s) = tc.parse::<f32>() {
        return s;
    }
    let parts: Vec<&str> = tc.split(':').collect();
    let mut secs = 0.0f32;
    for p in &parts {
        secs = secs * 60.0 + p.parse::<f32>().unwrap_or(0.0);
    }
    secs
}

fn read_atom(path: &str, mean: &'static str, name: &'static str) -> Option<String> {
    let tag = Tag::read_from_path(path).ok()?;
    let ident = FreeformIdent::new_static(mean, name);
    let vals: Vec<String> = tag.strings_of(&ident).map(|s| s.to_string()).collect();
    vals.into_iter().next()
}

/// Reads the `com.shiro.audio:metadata` atom (JSON) from an MP4.
pub fn load_audio_metadata(path: &str) -> Result<AudioMeta> {
    let json = read_atom(path, "com.shiro.audio", "metadata")
        .ok_or_else(|| anyhow::anyhow!("no audio metadata atom in {path}"))?;
    let meta: AudioMeta = serde_json::from_str(&json)?;
    Ok(meta)
}

/// Reads the `com.shiro.video:metadata` atom (JSON) from an MP4.
pub fn load_video_metadata(path: &str) -> Result<VideoMeta> {
    let json = read_atom(path, "com.shiro.video", "metadata")
        .ok_or_else(|| anyhow::anyhow!("no video metadata atom in {path}"))?;
    let meta: VideoMeta = serde_json::from_str(&json)?;
    Ok(meta)
}

/// Scan a directory for `.mp4` files and read their per-segment metadata.
pub fn scan_videos(dir: &str) -> Vec<VideoData> {
    let mut out = Vec::new();
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return out,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("mp4") {
            continue;
        }
        let vf = path.to_string_lossy().to_string();
        let v_meta = match load_video_metadata(&vf) {
            Ok(m) => m,
            Err(_) => continue,
        };
        let full_dur = v_meta.duration.unwrap_or(0.0);
        for seg in &v_meta.segments {
            let raw = &seg.meta.actpoints;
            let act_secs: Vec<f32> = raw.iter().map(|s| parse_timecode(s)).collect();
            let interval = seg.interval.unwrap_or([0.0, full_dur]);
            out.push(VideoData {
                file: vf.clone(),
                interval,
                actpoints: act_secs,
                tags: seg.tags.clone(),
            });
        }
    }
    out
}
