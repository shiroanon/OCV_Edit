# Auto-Editing Engine — Agent Guide

The auto-editor (`auto_edit.py`, 1885 lines) generates and renders edit plans by aligning video "action points" to audio beats.

## How It Works

1. **Load audio metadata**: Reads beat timestamps from MP4 custom atoms (`com.shiro.audio`)
2. **Load video metadata**: Reads video segments with actpoints from MP4 atoms (`com.shiro.video`)
3. **Plan generation**: Iterates beat intervals, randomly picks video segments, determines alignment (CC/DTW/none)
4. **Render**: Converts the JSON plan to `VideoPipeline` commands and renders

## CLI Usage

```bash
python auto_edit.py \
  --duration 60 \
  --resize-mode fill \
  --random-cursor \
  --no-align \
  --min-speed 0.8 \
  --max-speed 1.2 \
  --min-beat-gap 2 \
  --transition-chance 0.3 \
  --grid-chance 0.3 \
  --grid-tag "grid" \
  --save-plan plan.json \
  --load-plan plan.json \
  --patch-plan patches.json \
  --print-only \
  --output final_auto_edit.mp4
```

### Arguments

| Argument | Default | Description |
|---|---|---|
| `--duration` | 30 | Target output duration in seconds |
| `--resize-mode` | fill | `fill` or `fit` |
| `--random-cursor` | False | Random source start offset |
| `--no-align` | False | Disable beat alignment |
| `--min-speed` | 0.8 | Minimum clip speed multiplier |
| `--max-speed` | 1.2 | Maximum clip speed multiplier |
| `--min-beat-gap` | 2 | Minimum beats between clips |
| `--transition-chance` | 0.5 | Probability of inserting a transition |
| `--grid-chance` | 0.3 | Probability of grid scene layout |
| `--grid-tag` | "grid" | Filename tag for grid videos |
| `--save-plan` | None | Save generated plan JSON |
| `--load-plan` | None | Load plan from JSON instead of generating |
| `--patch-plan` | None | Apply patches to a loaded plan |
| `--print-only` | False | Print plan without rendering |
| `--output` | final_auto_edit.mp4 | Output file path |

## Config Structure (`CONFIG` dict, line 25)

Key sections:
- **`lyrics`**: Text overlay settings (font, position, animations, max duration)
- **`transitions`**: Types/weights/durations for auto-chosen transitions
- **`grid`**: Layout weights, gap, color grade chances (desaturated/warm/cool)
- **`span_weights`**: How many beats each scene covers (1/2/3 with weights 0.6/0.3/0.1)
- **`beat_effects`**: Per-alignment-type beat-synced effects (zoom, RGB shift with chances/durations)

## Alignment Modes

| Mode | Method | When Used |
|---|---|---|
| `cc` | Cross-correlation (histogram-based) | Finds linear time-shift offset |
| `dtw` | Dynamic Time Warping | Optimal non-linear path |
| `none` | No alignment | Random offsets |

## Plan Format (see `plan.json`)

```json
{
  "version": 1,
  "duration": 60.0,
  "audio_file": "audios/...",
  "lyrics": [{"time": 1.5, "text": "hello"}, ...],
  "scenes": [
    {
      "type": "single",
      "alignment": "cc",
      "offset": 0.0,
      "speed": 1.0,
      "start_time": 0.0,
      "duration": 2.5,
      "video": "videos/clip.mp4",
      "beats": [...],
      "actpoints": [...],
      "transition": {"type": "zoom", "mode": "in", "duration": 0.3},
      "effects": [{"type": "zoom", "params": {...}}, ...]
    }
  ]
}
```

Scene types: `"single"` (single clip), `"grid"` (3-panel grid with per-panel sources).

## Key Functions

| Function | Line | Purpose |
|---|---|---|
| `parse_timecode(tc)` | 130 | `HH:MM:SS.ss` → seconds |
| `parse_lrc(filepath)` | 136 | LRC lyrics to `[{time, text}]` |
| `load_audio_metadata(path)` | ~150 | Reads beats from MP4 atoms |
| `load_video_metadata(path)` | ~150 | Reads actpoints from MP4 atoms |
| `cross_correlation_alignment(a, v)` | ~200 | Histogram-based time offset |
| `dtw_alignment(a, v)` | ~200 | Dynamic Time Warping path |
| `generate_edit_plan(args)` | 639 | Core plan generation logic |
| `apply_edit_plan(pipeline, plan)` | ~1500 | Plan → pipeline commands |
| `patch_plan(plan_data, patches)` | ~600 | Apply JSON patches |
| `main()` | ~1800 | CLI entry point |

## Metadata Format (MP4 Custom Atoms)

Audio file atoms (`com.shiro.audio`):
```json
{"beats": [0.5, 1.0, 1.5, ...], "bpm": 140, "duration": 180.0}
```

Video file atoms (`com.shiro.video`):
```json
{"segments": [{"file": "clip.mp4", "start": 0, "end": 10, "actpoints": [1.2, 3.5, ...]}, ...]}
```

See `METADATA_SPEC.md` for full schema details.

## Extending

- Add new alignment modes by implementing a new function and adding a case in `generate_edit_plan()`
- Add new scene types by extending the scene dispatch in `add_clip()` helper
- Beat effects are configured in `CONFIG["beat_effects"]` by alignment type
