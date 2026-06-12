from typing import Any, Optional

from pydantic import BaseModel


class FrameRequest(BaseModel):
    plan: dict[str, Any]
    time: float


class SegmentRequest(BaseModel):
    plan: dict[str, Any]
    start_time: float
    duration: float


class RenderRequest(BaseModel):
    plan: dict[str, Any]
    output_path: str = "output.mp4"


class PlanValidateRequest(BaseModel):
    plan: dict[str, Any]


class PlanSaveRequest(BaseModel):
    name: str
    plan: dict[str, Any]


class PlanInfo(BaseModel):
    name: str
    path: str
    modified: float


class PlanMetadata(BaseModel):
    duration: float
    fps: float
    output_size: list[int]
    scene_count: int
    clip_count: int
    effect_count: int
    has_audio: bool


class FileEntry(BaseModel):
    name: str
    path: str
    size: int


class EffectSchema(BaseModel):
    type: str
    params: dict[str, Any]


class TransitionSchema(BaseModel):
    type: str
    params: dict[str, Any]


class ConfigResponse(BaseModel):
    effects: list[EffectSchema]
    transitions: list[TransitionSchema]
    config: dict[str, Any]


class ThumbnailRequest(BaseModel):
    filepath: str
    time: float = 0.0


class AutoEditRequest(BaseModel):
    audio_path: str = "audios/Only Fire - Up n Down (Audio) [se9ZcIEN_gk].m4a"
    duration: Optional[float] = None
    resize_mode: str = "fill"
    transition_chance: float = 0.5
    grid_chance: float = 0.0
    align_mode: str = "cc"


class ErrorResponse(BaseModel):
    error: str
