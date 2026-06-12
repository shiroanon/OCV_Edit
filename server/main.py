import json
import os
import time
from glob import glob
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from server.models import (
    AutoEditRequest, ConfigResponse, EffectSchema, ErrorResponse, FileEntry,
    FrameRequest, PlanInfo, PlanMetadata, PlanSaveRequest,
    PlanValidateRequest, RenderRequest, SegmentRequest, ThumbnailRequest,
    TransitionSchema,
)
from server.preview import (
    build_pipeline_from_plan, get_plan_metadata, render_frame_at_time, render_segment,
)
from utils.config import CONFIG
from utils.pipeline import VideoPipeline

app = FastAPI(title="OCV Edit Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PLANS_DIR = "plans"
os.makedirs(PLANS_DIR, exist_ok=True)

_pipeline_cache: dict[str, tuple[float, VideoPipeline]] = {}


def _get_pipeline(plan: dict, cache_key: Optional[str] = None) -> VideoPipeline:
    if cache_key and cache_key in _pipeline_cache:
        ts, pipe = _pipeline_cache[cache_key]
        if time.time() - ts < 30:
            return pipe
    pipe = build_pipeline_from_plan(plan)
    if cache_key:
        _pipeline_cache[cache_key] = (time.time(), pipe)
    return pipe


@app.get("/api/config", response_model=ConfigResponse)
def get_config():
    effect_types = [
        "BlurEffect", "ColorAdjustEffect", "RGBShiftEffect", "ZoomEffect",
        "ZoomToPoint", "KenBurnsEffect", "PanelSlideEffect", "PanelPulseEffect",
        "PanelBounceEffect", "PanelSpinEffect", "GridScanEffect", "GridFlashEffect",
        "GridGlitchEffect", "GridWaveWarpEffect", "GridPixelateEffect",
        "GridChromaticEffect", "YoloEmissionEffect", "YoloTextEffect",
    ]
    transition_types = ["slide", "zoom", "grid_wipe", "flash", "radial_wipe", "zoom_in"]

    return ConfigResponse(
        effects=[EffectSchema(type=t, params={}) for t in effect_types],
        transitions=[TransitionSchema(type=t, params={}) for t in transition_types],
        config=CONFIG,
    )


@app.get("/api/videos", response_model=list[FileEntry])
def list_videos():
    if not os.path.exists("videos"):
        return []
    entries = []
    for f in sorted(glob("videos/*.mp4")):
        size = os.path.getsize(f)
        entries.append(FileEntry(name=os.path.basename(f), path=f, size=size))
    return entries


@app.get("/api/audio", response_model=list[FileEntry])
def list_audio():
    if not os.path.exists("audios"):
        return []
    entries = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg"):
        for f in sorted(glob(f"audios/{ext}")):
            size = os.path.getsize(f)
            entries.append(FileEntry(name=os.path.basename(f), path=f, size=size))
    return entries


@app.post("/api/preview/frame")
def preview_frame(req: FrameRequest):
    try:
        pipeline = _get_pipeline(req.plan)
        jpeg_bytes = render_frame_at_time(pipeline, req.time)
        if jpeg_bytes is None:
            raise HTTPException(status_code=422, detail="Could not render frame")
        return Response(content=jpeg_bytes, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/preview/segment")
def preview_segment(req: SegmentRequest):
    try:
        pipeline = _get_pipeline(req.plan)
        mp4_bytes = render_segment(pipeline, req.start_time, req.duration)
        if mp4_bytes is None:
            raise HTTPException(status_code=422, detail="Could not render segment")
        return Response(content=mp4_bytes, media_type="video/mp4")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/preview/thumbnail")
def preview_thumbnail(req: ThumbnailRequest):
    try:
        import cv2
        import os
        if not os.path.exists(req.filepath):
            raise HTTPException(status_code=404, detail="File not found")
        cap = cv2.VideoCapture(req.filepath)
        if not cap.isOpened():
            raise HTTPException(status_code=422, detail="Could not open video")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_idx = int(req.time * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise HTTPException(status_code=422, detail="Could not read frame")
        h, w = frame.shape[:2]
        tw, th = (160, 90)
        scale = max(tw / w, th / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (nw, nh))
        y1 = (nh - th) // 2
        x1 = (nw - tw) // 2
        cropped = resized[y1:y1 + th, x1:x1 + tw]
        _, buf = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/render")
def render_video(req: RenderRequest):
    try:
        pipeline = build_pipeline_from_plan(req.plan)
        pipeline.render(req.output_path)
        if not os.path.exists(req.output_path):
            raise HTTPException(status_code=500, detail="Render failed - no output file")
        return FileResponse(req.output_path, media_type="video/mp4", filename=os.path.basename(req.output_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/plan/metadata", response_model=PlanMetadata)
def plan_metadata(req: PlanValidateRequest):
    try:
        meta = get_plan_metadata(req.plan)
        return PlanMetadata(**meta)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/plan/validate")
def validate_plan(req: PlanValidateRequest):
    errors = []
    plan = req.plan
    if not isinstance(plan, dict):
        return {"valid": False, "errors": ["Plan must be a JSON object"]}

    if "fps" not in plan:
        errors.append("Missing 'fps'")
    if "output_size" not in plan:
        errors.append("Missing 'output_size'")
    if "scenes" not in plan or not isinstance(plan["scenes"], list):
        errors.append("Missing or invalid 'scenes' array")

    for i, scene in enumerate(plan.get("scenes", [])):
        if "out_dur" not in scene:
            errors.append(f"Scene {i}: missing 'out_dur'")
        if "clips" not in scene or not isinstance(scene["clips"], list):
            errors.append(f"Scene {i}: missing 'clips' array")
        else:
            for j, clip in enumerate(scene["clips"]):
                if "filepath" not in clip:
                    errors.append(f"Scene {i} clip {j}: missing 'filepath'")

    return {"valid": len(errors) == 0, "errors": errors}


@app.get("/api/plans", response_model=list[PlanInfo])
def list_plans():
    plans = []
    for f in sorted(glob(os.path.join(PLANS_DIR, "*.json"))):
        mtime = os.path.getmtime(f)
        name = os.path.splitext(os.path.basename(f))[0]
        plans.append(PlanInfo(name=name, path=f, modified=mtime))
    return plans


@app.post("/api/plans", response_model=PlanInfo)
def save_plan(req: PlanSaveRequest):
    safe_name = req.name.replace(" ", "_").replace("/", "_")
    path = os.path.join(PLANS_DIR, f"{safe_name}.json")
    with open(path, "w") as f:
        json.dump(req.plan, f, indent=2)
    return PlanInfo(name=safe_name, path=path, modified=os.path.getmtime(path))


@app.get("/api/plans/{name}")
def load_plan(name: str):
    safe_name = name.replace(" ", "_").replace("/", "_")
    path = os.path.join(PLANS_DIR, f"{safe_name}.json")
    if not os.path.exists(path):
        path = os.path.join("plans", f"{name}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Plan '{name}' not found")
    with open(path) as f:
        return json.load(f)


@app.delete("/api/plans/{name}")
def delete_plan(name: str):
    safe_name = name.replace(" ", "_").replace("/", "_")
    path = os.path.join(PLANS_DIR, f"{safe_name}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"deleted": safe_name}


@app.post("/api/autoedit/plan")
def autoedit_plan(req: AutoEditRequest):
    try:
        from types import SimpleNamespace
        from utils.auto_editor import generate_edit_plan

        args = SimpleNamespace(
            audio=req.audio_path,
            duration=req.duration,
            resize_mode=req.resize_mode,
            transition_chance=req.transition_chance,
            grid_chance=req.grid_chance,
            random_cursor=False,
            no_align=False,
            min_speed=0.8,
            max_speed=1.4,
            min_beat_gap=0.2,
            grid_tag=None,
            load_plan=None,
            patch_plan=None,
        )
        plan = generate_edit_plan(args)
        if plan is None:
            raise HTTPException(status_code=422, detail="AutoEdit could not generate a plan")
        return plan
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/video/metadata")
def video_metadata(req: ThumbnailRequest):
    try:
        import cv2
        if not os.path.exists(req.filepath):
            raise HTTPException(status_code=404, detail="File not found")
        cap = cv2.VideoCapture(req.filepath)
        if not cap.isOpened():
            raise HTTPException(status_code=422, detail="Could not open video")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return {"filepath": req.filepath, "fps": fps, "duration": duration, "width": w, "height": h, "frames": total_frames}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": time.time()}
