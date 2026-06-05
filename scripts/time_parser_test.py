import json
from mutagen.mp4 import MP4
import glob

# Test audio
audio_file = "audios/Roll 'n Rock (Bali Bandits).m4a"
try:
    a = MP4(audio_file)
    meta = a.get("----:com.shiro.audio:metadata")
    if meta:
        print("Audio meta:", json.loads(meta[0].decode("utf-8")))
    else:
        print("No audio meta")
except Exception as e:
    print(e)

# Test one video
vids = glob.glob("videos/*.mp4")
if vids:
    v = MP4(vids[0])
    meta = v.get("----:com.shiro.video:metadata")
    if meta:
        print("Video meta:", json.loads(meta[0].decode("utf-8")))
    else:
        print("No video meta")
