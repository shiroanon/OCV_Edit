#!/usr/bin/env python3
"""Render text to RGBA raw pixels (stdout). Called by Rust text.rs fallback.

Input:  JSON on stdin with keys: text, font_path, font_size, width, height,
        color_r, color_g, color_b, stroke_width, stroke_color_r, stroke_color_g,
        stroke_color_b, position ("top_center"|"center"|"bottom_center"|...),
        opacity, animate, phase_p
Output: raw RGBA 32-bit float pixels (W*H*4 bytes) to stdout.
"""
import json, sys, struct
from PIL import Image, ImageDraw, ImageFont

def main():
    opts = json.load(sys.stdin)
    import os
    with open("/tmp/render_text_debug.log", "a") as log:
        log.write(f"font_path={opts.get('font_path')}, cwd={os.getcwd()}\n")
    w, h = opts["width"], opts["height"]
    txt = opts["text"]
    font_path = opts["font_path"]
    font_size = opts["font_size"]
    color = (opts["color_r"], opts["color_g"], opts["color_b"])
    sw = opts.get("stroke_width", 0.0)
    sc = (opts.get("stroke_color_r", 0), opts.get("stroke_color_g", 0), opts.get("stroke_color_b", 0))
    opacity = opts.get("opacity", 1.0)
    position = opts.get("position", "top_center")
    animate = opts.get("animate", "none")
    phase_p = opts.get("phase_p", 1.0)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_path, int(font_size))
    except (OSError, IOError) as e:
        with open("/tmp/render_text_debug.log", "a") as log:
            log.write(f"  FONT LOAD FAILED: {e}\n")
        sys.stdout.buffer.write(b"\x00" * w * h * 4)
        return

    # wrap text
    max_w = int(w * 0.92)
    lines = _wrap_text(txt, font, max_w, draw)

    # measure
    line_h = font_size * opts.get("line_spacing", 1.1)
    total_w = max(draw.textbbox((0, 0), l, font=font)[2] for l in lines) if lines else 0
    total_h = len(lines) * line_h

    margin = max(10, int(0.031 * w))
    if position == "center":
        sx = (w - total_w) / 2.0
        sy = (h - total_h) / 2.0
    elif position == "top_center":
        sx = (w - total_w) / 2.0
        sy = margin
    elif position == "bottom_center":
        sx = (w - total_w) / 2.0
        sy = h - total_h - margin
    elif position == "top_left":
        sx = margin
        sy = margin
    elif position == "bottom_left":
        sx = margin
        sy = h - total_h - margin
    elif position == "top_right":
        sx = w - total_w - margin
        sy = margin
    elif position == "bottom_right":
        sx = w - total_w - margin
        sy = h - total_h - margin
    else:
        sx = (w - total_w) / 2.0
        sy = (h - total_h) / 2.0

    # slide animation
    if animate == "slide_up":
        sy += (1.0 - phase_p) * h * 0.25
    elif animate == "slide_down":
        sy -= (1.0 - phase_p) * h * 0.25

    fill_alpha = phase_p if animate == "fade" else 1.0
    fill_alpha *= opacity

    if fill_alpha <= 0.0:
        sys.stdout.buffer.write(b"\x00" * w * h * 4)
        return

    # stroke
    if sw > 0.0:
        stroke_rgba = (sc[0], sc[1], sc[2], int(255 * fill_alpha))
        for dy in (-sw, sw):
            for dx in (-sw, sw):
                for i, line in enumerate(lines):
                    ly = sy + i * line_h
                    draw.text((sx + dx, ly + dy), line, font=font, fill=stroke_rgba)

    # fill
    fill_rgba = (color[0], color[1], color[2], int(255 * fill_alpha))
    for i, line in enumerate(lines):
        ly = sy + i * line_h
        draw.text((sx, ly), line, font=font, fill=fill_rgba)

    # output RGBA raw
    raw = img.tobytes()
    sys.stdout.buffer.write(raw)

def _wrap_text(text, font, max_w, draw):
    lines = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            tw = draw.textbbox((0, 0), trial, font=font)[2]
            if tw <= max_w or current == "":
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines

if __name__ == "__main__":
    main()
