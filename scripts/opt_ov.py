#!/usr/bin/env python3
"""Optimize all YOLO .pt checkpoints in the current working directory to OpenVINO IR."""

from pathlib import Path
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
IMGSZ = 640
HALF = True  # FP16; set False if you want FP32 (INT8 needs calibration data)


def optimize(model_path: Path) -> Path | None:
    out_dir = model_path.parent / "openvino_models"
    stem = model_path.stem
    expected_ir = out_dir / f"{stem}.xml"
    expected_weights = out_dir / f"{stem}.bin"

    if expected_ir.exists() and expected_weights.exists():
        print(f"[SKIP] {expected_ir} already exists")
        return None

    print(f"[OPT]  {model_path.name} -> {out_dir / stem}")
    model = YOLO(str(model_path))
    exported = model.export(format="openvino", imgsz=IMGSZ, half=HALF)
    return expected_ir


def main():
    pts = sorted(ROOT.glob("*.pt"))
    print(f"Found {len(pts)} .pt model(s) in {ROOT}")
    done = []
    skipped = []
    failed = []
    for pt in pts:
        if "_seg" in pt.stem or "seg" in pt.stem:
            print(f"[SKIP] {pt.name} — segmentation export requires special handling")
            skipped.append(pt.name)
            continue
        try:
            result = optimize(pt)
            if result is None:
                skipped.append(pt.name)
            else:
                done.append(pt.name)
        except Exception as e:
            print(f"[ERR]  {pt.name}: {e}")
            failed.append((pt.name, str(e)))

    print()
    print("=== Summary ===")
    print(f"  Optimized : {len(done)}")
    for n in done:
        print(f"    {n}")
    print(f"  Skipped   : {len(skipped)}")
    for n in skipped:
        print(f"    {n}")
    print(f"  Failed    : {len(failed)}")
    for n, e in failed:
        print(f"    {n}: {e}")


if __name__ == "__main__":
    main()
