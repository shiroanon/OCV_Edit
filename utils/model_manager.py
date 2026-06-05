from typing import Optional
from ultralytics import YOLO

_yolo_model_cache = {}


def get_yolo_model(model_path: Optional[str]):
    if not model_path:
        return None
    if model_path not in _yolo_model_cache:
        _yolo_model_cache[model_path] = YOLO(model_path)
    return _yolo_model_cache[model_path]
