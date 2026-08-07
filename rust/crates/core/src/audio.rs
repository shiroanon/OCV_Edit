use anyhow::{bail, Context, Result};
use std::process::Command;

/// Energy-based onset detection. Decodes audio to mono 22050 Hz, computes
/// short-time RMS energy, detects positive-going peaks (onsets), and returns
/// beat timestamps in seconds.
pub fn detect_beats(audio_path: &str) -> Result<Vec<f32>> {
    let raw_path = format!("{audio_path}.detect_beats.raw");
    let status = Command::new("ffmpeg")
        .args([
            "-y", "-i", audio_path,
            "-ac", "1",
            "-ar", "22050",
            "-f", "f32le",
            "-c:a", "pcm_f32le",
            &raw_path,
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .context("ffmpeg decode for beat detection")?;
    if !status.success() {
        bail!("ffmpeg failed to decode audio for beat detection");
    }
    let raw_data = std::fs::read(&raw_path)?;
    let _ = std::fs::remove_file(&raw_path);
    if raw_data.len() < 4 {
        return Ok(vec![0.0]);
    }
    let samples: Vec<f32> = raw_data
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    let sr = 22050.0;
    let frame_size = 1024usize;
    let hop_size = 512usize;
    let num_frames = if samples.len() <= frame_size {
        0
    } else {
        (samples.len() - frame_size) / hop_size + 1
    };
    if num_frames == 0 {
        return Ok(vec![0.0]);
    }
    // Frame RMS energy
    let mut energy: Vec<f32> = Vec::with_capacity(num_frames);
    for i in 0..num_frames {
        let start = i * hop_size;
        let end = (start + frame_size).min(samples.len());
        let sum_sq: f32 = samples[start..end].iter().map(|s| s * s).sum();
        let rms = (sum_sq / (end - start) as f32).sqrt();
        energy.push(rms);
    }
    // Half-wave rectified energy derivative (onset strength)
    let mut flux: Vec<f32> = Vec::with_capacity(energy.len());
    flux.push(0.0);
    for i in 1..energy.len() {
        flux.push((energy[i] - energy[i - 1]).max(0.0));
    }
    // Smooth with 5-frame moving average (~115ms window)
    let w = 5usize;
    let mut smooth: Vec<f32> = Vec::with_capacity(flux.len());
    for i in 0..flux.len() {
        let lo = i.saturating_sub(w / 2);
        let hi = (i + w / 2 + 1).min(flux.len());
        let m: f32 = flux[lo..hi].iter().sum::<f32>() / (hi - lo) as f32;
        smooth.push(m);
    }
    // Adaptive threshold: fraction of mean of top 20%
    let mut sorted = smooth.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let top_n = (smooth.len() / 5).max(5);
    let top_mean: f32 = sorted.iter().rev().take(top_n).sum::<f32>() / top_n as f32;
    let threshold = top_mean * 0.35;
    // Local-maximum peak picking with 150ms min interval
    let min_interval = 0.15f32;
    let mut beats: Vec<f32> = Vec::new();
    let mut last_beat = -min_interval;
    for i in 2..smooth.len().saturating_sub(2) {
        if smooth[i] > threshold
            && smooth[i] > smooth[i - 1]
            && smooth[i] > smooth[i - 2]
            && smooth[i] >= smooth[i + 1]
            && smooth[i] >= smooth[i + 2]
        {
            let t = i as f32 * hop_size as f32 / sr;
            if t - last_beat >= min_interval {
                beats.push(t);
                last_beat = t;
            }
        }
    }
    // Fallback: regular 0.5s intervals if no onsets found
    if beats.is_empty() {
        let total = samples.len() as f32 / sr;
        let mut t = 0.25;
        while t < total {
            beats.push(t);
            t += 0.5;
        }
    }
    Ok(beats)
}
