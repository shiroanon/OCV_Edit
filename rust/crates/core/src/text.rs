use crate::frame::{Frame, Mask, RawMut};
use ab_glyph::{Font, FontVec, PxScale, ScaleFont};
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

// ───────────────────────── cached font / layout ─────────────────────────

/// Parsed fonts, keyed by the file path they were loaded from. Loading a TTF
/// (`fs::read` + `FontVec::try_from_vec`) on every `render_text` call was a
/// significant per-frame cost for text-heavy edits; fonts are immutable for the
/// process lifetime, so parse once and share.
static FONT_CACHE: OnceLock<Mutex<HashMap<String, Arc<FontVec>>>> = OnceLock::new();

fn font_cache() -> &'static Mutex<HashMap<String, Arc<FontVec>>> {
    FONT_CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Pre-computed text layout: wrapped lines plus their measured widths.
struct TextLayout {
    lines: Vec<String>,
    line_widths: Vec<f32>,
    total_w: f32,
}

static LAYOUT_CACHE: OnceLock<Mutex<HashMap<(String, u32), Arc<TextLayout>>>> = OnceLock::new();

fn layout_cache() -> &'static Mutex<HashMap<(String, u32), Arc<TextLayout>>> {
    LAYOUT_CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Wrapped layout (lines + per-line widths) cached per `(text, px_size)`.
fn cached_layout(font: &FontVec, text: &str, px_size: f32, max_width: f32) -> Arc<TextLayout> {
    let key = (text.to_string(), px_size.to_bits());
    let mut cache = layout_cache().lock().unwrap();
    if let Some(l) = cache.get(&key) {
        return Arc::clone(l);
    }
    let scale = PxScale::from(px_size);
    let lines = wrap_text(font, &scale, text, max_width);
    let line_widths: Vec<f32> = lines.iter().map(|l| measure_line(font, &scale, l)).collect();
    let total_w = line_widths.iter().copied().fold(0.0f32, f32::max);
    let layout = Arc::new(TextLayout { lines, line_widths, total_w });
    cache.insert(key, Arc::clone(&layout));
    layout
}

pub struct TextOptions<'a> {
    pub size: (u32, u32),
    pub text: &'a str,
    pub font_path: Option<&'a str>,
    pub font_size_frac: f32,
    pub position: TextPosition,
    pub color_bgr: [u8; 3],
    pub opacity: f32,
    pub stroke_width_frac: f32,
    pub stroke_color_bgr: [u8; 3],
    pub animate: &'a str,
    pub phase_p: f32,
    pub line_spacing: f32,
}

#[derive(Clone, Copy, Debug)]
pub enum TextPosition {
    Center,
    TopCenter,
    BottomCenter,
    TopLeft,
    BottomLeft,
    TopRight,
    BottomRight,
    Pixel(f32, f32),
    Norm(f32, f32),
}

impl TextPosition {
    pub fn from_str_or_tuple(s: &str) -> TextPosition {
        match s {
            "center" => TextPosition::Center,
            "top_center" => TextPosition::TopCenter,
            "bottom_center" => TextPosition::BottomCenter,
            "top_left" => TextPosition::TopLeft,
            "bottom_left" => TextPosition::BottomLeft,
            "top_right" => TextPosition::TopRight,
            "bottom_right" => TextPosition::BottomRight,
            _ => TextPosition::BottomCenter,
        }
    }
}

fn load_font(path: Option<&str>) -> Option<Arc<FontVec>> {
    let candidates = [
        path.map(|p| p.to_string()),
        Some("assets/fonts/Audiowide-Regular.ttf".to_string()),
        Some("/home/shiro/Projects/OCV_Edit/assets/fonts/Audiowide-Regular.ttf".to_string()),
        Some("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf".to_string()),
    ];
    let mut cache = font_cache().lock().unwrap();
    for c in candidates.into_iter().flatten() {
        if let Some(f) = cache.get(&c) {
            return Some(Arc::clone(f));
        }
        if let Ok(bytes) = std::fs::read(&c) {
            if let Ok(f) = FontVec::try_from_vec(bytes) {
                let f = Arc::new(f);
                cache.insert(c, Arc::clone(&f));
                return Some(f);
            }
        }
    }
    None
}

/// Fallback: render text via Python (PIL) when Rust font loading fails.
fn render_text_py(opts: &TextOptions) -> (Frame, Mask) {
    let mut child = match std::process::Command::new("python3")
        .arg("render_text_py.py")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::inherit())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[text] python3 not found: {e}");
            return (Frame::new(opts.size.0, opts.size.1), Mask::new(opts.size.0, opts.size.1));
        }
    };

    let json_input = serde_json::json!({
        "text": opts.text,
        "font_path": opts.font_path.unwrap_or("Audiowide-Regular.ttf"),
        "font_size": opts.font_size_frac * opts.size.1 as f32,
        "width": opts.size.0,
        "height": opts.size.1,
        "color_r": opts.color_bgr[2],
        "color_g": opts.color_bgr[1],
        "color_b": opts.color_bgr[0],
        "stroke_width": (opts.stroke_width_frac * opts.size.1 as f32) as u32,
        "stroke_color_r": opts.stroke_color_bgr[2],
        "stroke_color_g": opts.stroke_color_bgr[1],
        "stroke_color_b": opts.stroke_color_bgr[0],
        "opacity": opts.opacity,
        "position": match opts.position {
            TextPosition::Center => "center",
            TextPosition::TopCenter => "top_center",
            TextPosition::BottomCenter => "bottom_center",
            TextPosition::TopLeft => "top_left",
            TextPosition::BottomLeft => "bottom_left",
            TextPosition::TopRight => "top_right",
            TextPosition::BottomRight => "bottom_right",
            TextPosition::Pixel(..) => "top_center",
            TextPosition::Norm(..) => "top_center",
        },
        "animate": opts.animate,
        "phase_p": opts.phase_p,
        "line_spacing": opts.line_spacing,
    });

    use std::io::Write;
    if let Err(e) = child.stdin.as_mut().unwrap().write_all(json_input.to_string().as_bytes()) {
        eprintln!("[text] failed to write to python stdin: {e}");
        return (Frame::new(opts.size.0, opts.size.1), Mask::new(opts.size.0, opts.size.1));
    }
    let output = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => {
            eprintln!("[text] python process failed: {e}");
            return (Frame::new(opts.size.0, opts.size.1), Mask::new(opts.size.0, opts.size.1));
        }
    };

    let (w, h) = opts.size;
    let expected = (w * h * 4) as usize;
    let raw = output.stdout;
    if raw.len() < expected {
        eprintln!("[text] python output too short: {} < {}", raw.len(), expected);
        return (Frame::new(w, h), Mask::new(w, h));
    }

    let mut bgr = Frame::new(w, h);
    let mut alpha = Mask::new(w, h);
    let bd = bgr.raw_mut();
    let ad = alpha.raw_mut();
    for y in 0..h {
        for x in 0..w {
            let i = (y * w + x) as usize;
            let pi = i * 4;
            let r = raw[pi];
            let g = raw[pi + 1];
            let b = raw[pi + 2];
            let a = raw[pi + 3] as f32 / 255.0;
            let bi = i * 3;
            bd[bi] = b;
            bd[bi + 1] = g;
            bd[bi + 2] = r;
            ad[i] = a;
        }
    }
    (bgr, alpha)
}

/// Renders text to a (bgr layer, alpha mask) pair at the frame size. `opacity`
/// and slide offsets (from `animate`/`phase_p`) are already applied.
///
/// Uses the Rust-native `ab_glyph` path first; falls back to Python PIL if the
/// font cannot be loaded.
pub fn render_text(opts: &TextOptions) -> (Frame, Mask) {
    let (w, h) = opts.size;
    let font = match load_font(opts.font_path) {
        Some(f) => f,
        None => return render_text_py(opts),
    };
    let mut bgr = Frame::new(w, h);

    let px_size = (opts.font_size_frac * h as f32).max(8.0);
    let scale = PxScale::from(px_size);
    let scaled = font.as_scaled(scale);
    let line_height = (px_size * opts.line_spacing).max(1.0);

    let max_width = (w as f32 * 0.92) as f32;
    let layout = cached_layout(&font, opts.text, px_size, max_width);
    let lines = &layout.lines;
    let total_w = layout.total_w;
    let total_h = lines.len() as f32 * line_height;

    let margin = (0.031 * w as f32).max(10.0);
    let (start_x, mut start_y) = match opts.position {
        TextPosition::Center => ((w as f32 - total_w) / 2.0, (h as f32 - total_h) / 2.0),
        TextPosition::TopCenter => ((w as f32 - total_w) / 2.0, margin),
        TextPosition::BottomCenter => ((w as f32 - total_w) / 2.0, h as f32 - total_h - margin),
        TextPosition::TopLeft => (margin, margin),
        TextPosition::BottomLeft => (margin, h as f32 - total_h - margin),
        TextPosition::TopRight => (w as f32 - total_w - margin, margin),
        TextPosition::BottomRight => (w as f32 - total_w - margin, h as f32 - total_h - margin),
        TextPosition::Pixel(x, y) => (x, y),
        TextPosition::Norm(x, y) => (x * w as f32, y * h as f32),
    };

    // slide animation
    if opts.animate == "slide_up" {
        start_y += (1.0 - opts.phase_p) * h as f32 * 0.25;
    } else if opts.animate == "slide_down" {
        start_y -= (1.0 - opts.phase_p) * h as f32 * 0.25;
    }

    let mut fill: Mask = Mask::new(w, h);
    let scaled = font.as_scaled(scale);
    for (i, line) in lines.iter().enumerate() {
        let ly = start_y + i as f32 * line_height;
        let lx = if matches!(
            opts.position,
            TextPosition::Center | TextPosition::TopCenter | TextPosition::BottomCenter
        ) {
            (w as f32 - layout.line_widths[i]) / 2.0
        } else {
            start_x
        };
        let mut pen_x = lx;
        for ch in line.chars() {
            if ch == ' ' {
                pen_x += scaled.h_advance(font.glyph_id(ch));
                continue;
            }
            let glyph = font.glyph_id(ch).with_scale(scale);
            let outlined = match font.outline_glyph(glyph) {
                Some(o) => o,
                None => {
                    pen_x += scaled.h_advance(font.glyph_id(ch));
                    continue;
                }
            };
            let bb = outlined.px_bounds();
            outlined.draw(|gx, gy, gv| {
                let x = bb.min.x as i32 + gx as i32;
                let y = bb.min.y as i32 + gy as i32;
                if x >= 0 && y >= 0 && x < w as i32 && y < h as i32 {
                    let idx = (y as u32 * w + x as u32) as usize;
                    let raw = fill.raw_mut();
                    raw[idx] = raw[idx].max(gv);
                }
            });
            pen_x += scaled.h_advance(font.glyph_id(ch));
        }
    }

    let fill_alpha = match opts.animate {
        "fade" => opts.phase_p,
        _ => 1.0,
    } * opts.opacity;

    // Stroke pass (dilated fill behind)
    if opts.stroke_width_frac > 0.0 {
        let sw = (opts.stroke_width_frac * h as f32).max(1.0) as i32;
        let mut stroke_alpha = fill.clone();
        dilate_alpha(&mut stroke_alpha, sw);
        composite_mask_color(&mut bgr, &stroke_alpha, opts.stroke_color_bgr, 1.0);
        let fa = fill.raw_mut();
        let sa = stroke_alpha.as_raw();
        for i in 0..fa.len() {
            fa[i] = fa[i].max(sa[i]);
        }
    }
    composite_mask_color(&mut bgr, &fill, opts.color_bgr, fill_alpha);

    (bgr, fill.clone())
}

fn composite_mask_color(bgr: &mut Frame, mask: &Mask, color: [u8; 3], strength: f32) {
    let (w, h) = (bgr.width() as usize, bgr.height() as usize);
    let bd = bgr.raw_mut();
    let md = mask.as_raw();
    for y in 0..h {
        for x in 0..w {
            let cov = md[y * w + x] * strength;
            if cov <= 0.0 {
                continue;
            }
            let i = (y * w + x) * 3;
            for c in 0..3 {
                let b = bd[i + c] as f32;
                bd[i + c] = (b * (1.0 - cov) + color[c] as f32 * cov) as u8;
            }
        }
    }
}

fn dilate_alpha(alpha: &mut Mask, radius: i32) {
    if radius <= 0 {
        return;
    }
    let (w, h) = (alpha.width() as usize, alpha.height() as usize);
    let s = alpha.as_raw().to_vec();
    let d = alpha.raw_mut();
    for y in 0..h {
        for x in 0..w {
            let mut m = 0.0f32;
            for dy in -radius..=radius {
                for dx in -radius..=radius {
                    let nx = (x as i32 + dx).clamp(0, w as i32 - 1) as usize;
                    let ny = (y as i32 + dy).clamp(0, h as i32 - 1) as usize;
                    m = m.max(s[ny * w + nx]);
                }
            }
            d[y * w + x] = m;
        }
    }
}

fn measure_line(font: &FontVec, scale: &PxScale, line: &str) -> f32 {
    let scaled = font.as_scaled(*scale);
    let mut w = 0.0f32;
    for ch in line.chars() {
        w += scaled.h_advance(font.glyph_id(ch));
    }
    w
}

fn wrap_text(font: &FontVec, scale: &PxScale, text: &str, max_width: f32) -> Vec<String> {
    let scaled = font.as_scaled(*scale);
    let mut lines = Vec::new();
    for raw_line in text.split('\n') {
        let words: Vec<&str> = raw_line.split(' ').collect();
        let mut current = String::new();
        for word in words {
            let trial = if current.is_empty() {
                word.to_string()
            } else {
                format!("{current} {word}")
            };
            if measure_line(font, scale, &trial) <= max_width || current.is_empty() {
                current = trial;
            } else {
                lines.push(current.clone());
                current = word.to_string();
            }
        }
        lines.push(current);
    }
    lines
}
