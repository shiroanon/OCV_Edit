import os, numpy as np
import pyroomacoustics as pra
from scipy.io import wavfile
from scipy.signal import resample
from pyroomacoustics.directivities.measured import MeasuredDirectivityFile
from pyroomacoustics.directivities import Rotation3D

ROOM_DIM = [15, 12, 5]
RT60_TGT = 1.2
FS = 16000
CENTER = [7.5, 6.0, 1.7]
HEAD_RADIUS = 0.09
SILENCE_GAP = 0.5
MOVE_SEGMENTS = 24

# 8 channel directions — each gets 3 distances: close, medium, far
CHANNELS = [
    ("L",    30,   0.0),
    ("C",    0,    0.0),
    ("R",    -30,  0.0),
    ("RS",   -110, 0.0),
    ("RR",   -150, 0.0),
    ("LR",   150,  0.0),
    ("LS",   110,  0.0),
    ("LFE",  0,    -1.4),
]

DISTANCES = {"close": 1.0, "medium": 2.5, "far": 5.0}
DIST_ORDER = ["close", "medium", "far"]

LABELS = {
    "L":"Left Front", "C":"Center", "R":"Right Front",
    "RS":"Right Surround", "RR":"Right Rear", "LR":"Left Rear",
    "LS":"Left Surround", "LFE":"Subwoofer",
}

def load_audio(path):
    fs_in, audio = wavfile.read(path)
    audio = audio.astype(np.float64) / np.iinfo(np.int16).max
    if fs_in != FS:
        audio = resample(audio, int(len(audio) * FS / fs_in))
    return audio

# Load all 24 audio clips
audio_cache = {}
for name, *_ in CHANNELS:
    for dist in DIST_ORDER:
        path = f"ch_{name}_{dist}.wav"
        audio_cache[(name, dist)] = load_audio(path)

# Max clip length for spacing
max_len = max(len(a) for a in audio_cache.values())
clip_len = max_len + int(SILENCE_GAP * FS)

# Moving audio
moving_audio = load_audio("ch_moving.wav")
seg_len = len(moving_audio) // MOVE_SEGMENTS

# === BUILD ROOM ===
e_absorption, max_order = pra.inverse_sabine(RT60_TGT, ROOM_DIM)
max_order = max(1, min(12, max_order))
room = pra.ShoeBox(
    ROOM_DIM,
    fs=FS,
    materials=pra.Material(e_absorption),
    max_order=max_order,
    air_absorption=True,
)

# === PLACE 24 STATIC SOURCES (8 channels × 3 distances) ===
# Order: all 3 distances for L, then all 3 for C, then R, etc.
src_idx = 0
for name, angle_deg, z_off in CHANNELS:
    rad = np.deg2rad(angle_deg)
    print(f"\n  [{name:>3s}] {LABELS[name]}:")
    for dist_key in DIST_ORDER:
        radius = DISTANCES[dist_key]
        pos = [
            CENTER[0] - radius * np.sin(rad),
            CENTER[1] + radius * np.cos(rad),
            CENTER[2] + z_off,
        ]
        delay = src_idx * clip_len / FS
        audio = audio_cache[(name, dist_key)]
        room.add_source(pos, signal=audio.copy(), delay=delay)
        print(f"    {dist_key:>6s}  dist={radius:.1f}m  "
              f"pos=({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})  "
              f"delay={delay:.2f}s")
        src_idx += 1

# === PLACE MOVING SOURCE ===
move_start_delay = src_idx * clip_len / FS
move_radius = 3.0
print(f"\n  [MOVE] Moving source: circle radius={move_radius}m, "
      f"{MOVE_SEGMENTS} segs, starts at {move_start_delay:.2f}s")

for seg in range(MOVE_SEGMENTS):
    frac = seg / MOVE_SEGMENTS
    angle_deg = frac * 360.0
    rad = np.deg2rad(angle_deg)
    pos = [
        CENTER[0] - move_radius * np.sin(rad),
        CENTER[1] + move_radius * np.cos(rad),
        CENTER[2],
    ]
    seg_audio = moving_audio[seg * seg_len : (seg + 1) * seg_len].copy()
    seg_delay = move_start_delay + seg * seg_len / FS
    room.add_source(pos, signal=seg_audio, delay=seg_delay)

# === BINAURAL MICROPHONES ===
sofa_path = os.path.join(os.path.dirname(pra.__file__), 'data', 'sofa', 'mit_kemar_normal_pinna.sofa')
if os.path.exists(sofa_path):
    print("Loading KEMAR HRTF...")
    hrtf_db = MeasuredDirectivityFile(sofa_path, fs=FS, interp_order=None)
    head_rot = Rotation3D(angles=[-90, 0, 0])
    left_dir = hrtf_db.get_mic_directivity('right', orientation=head_rot)
    right_dir = hrtf_db.get_mic_directivity('left', orientation=head_rot)
    hrtf_ok = True
    print("HRTF loaded")
else:
    print("WARNING: HRTF file not found, falling back to omnidirectional")
    hrtf_ok = False
mic_locs = np.array([
    [CENTER[0] - HEAD_RADIUS, CENTER[1], CENTER[2]],
    [CENTER[0] + HEAD_RADIUS, CENTER[1], CENTER[2]],
]).T
if hrtf_ok:
    room.add_microphone_array(mic_locs, directivity=[left_dir, right_dir])
else:
    room.add_microphone_array(mic_locs)

# === SIMULATE ===
n_total = src_idx + MOVE_SEGMENTS
print(f"\nTotal sources: {n_total}")
print("Computing RIRs...")
room.compute_rir()
print("Simulating...")
room.simulate()

# === EXPORT ===
binaural = room.mic_array.signals
peak = np.max(np.abs(binaural))
if peak > 0:
    binaural /= peak

output_path = "71_binaural_hall.wav"
binaural_int = (binaural * 32767).astype(np.int16)
wavfile.write(output_path, FS, binaural_int.T)
print(f"\nSaved: {output_path} ({binaural.shape[1]/FS:.1f}s, 2ch, {FS} Hz)")

print(f"\nTimeline:")
src_idx = 0
for name, *rest in CHANNELS:
    for dist_key in DIST_ORDER:
        d = src_idx * clip_len / FS
        radius = DISTANCES[dist_key]
        print(f"  {d:5.1f}s  — {LABELS[name]} ({name})  {dist_key}  @ {radius:.1f}m")
        src_idx += 1
print(f"  {move_start_delay:5.1f}s  — Moving source (circle, {move_radius}m radius)")
