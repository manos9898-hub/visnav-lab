#!/usr/bin/env python3
"""
Rotate frames captured by the Samsung Galaxy A36 (SM-A366U1) to correct orientation.

The A36 writes camera frames as 1280x960 landscape pixels when the device is held
in portrait. Each frame needs a 90° clockwise rotation to put ground down
and the scene right-side up.

Usage:
    python3 fix_a36_frame_orientation.py <session_id_or_path>

Examples:
    python3 fix_a36_frame_orientation.py a9995a5a-2a4f-4868-9e6d-08c7641cf448
    python3 fix_a36_frame_orientation.py /home/ubuntu/lab/workspaces/a9995a5a-2a4f-4868-9e6d-08c7641cf448/session_a9995a5a-2a4f-4868-9e6d-08c7641cf448
"""

import sys
import os
import json
from pathlib import Path
from PIL import Image, ImageFile

# Allow loading truncated JPEG files rather than crashing
ImageFile.LOAD_TRUNCATED_IMAGES = True

WORKSPACES_ROOT = Path("/home/ubuntu/lab/workspaces")


def resolve_session_path(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p

    # bare session ID — find it under workspaces
    for workspace in WORKSPACES_ROOT.iterdir():
        candidate = workspace / f"session_{workspace.name}"
        if workspace.name.startswith(arg) and candidate.is_dir():
            return candidate
        inner = workspace / arg
        if inner.is_dir():
            return inner

    raise FileNotFoundError(f"Could not find session directory for: {arg}")


def rotate_frames(session_path: Path):
    jpgs = sorted(session_path.glob("frame_*.jpg"))
    if not jpgs:
        print(f"No frame_*.jpg files found in {session_path}", file=sys.stderr)
        sys.exit(1)

    total = len(jpgs)
    print(f"Session: {session_path}")
    print(f"Rotating {total} frames 90° CW ...")

    skipped = 0
    errors = 0
    for i, jpg in enumerate(jpgs, 1):
        try:
            img = Image.open(jpg)
            img.load()
            w, h = img.size
            # already portrait — was rotated in a previous run, skip it
            if h > w:
                skipped += 1
                continue
            rotated = img.rotate(-90, expand=True)
            rotated.save(jpg, "JPEG", quality=80, subsampling=0)
        except Exception as e:
            print(f"  WARNING: skipping {jpg.name} — {e}")
            errors += 1
        if i % 500 == 0 or i == total:
            print(f"  {i}/{total}")

    print(f"Done. skipped={skipped} (already rotated), errors={errors}")
    update_meta_resolution(session_path)


def update_meta_resolution(session_path: Path):
    meta_path = session_path / "session_meta.json"
    if not meta_path.exists():
        print("WARNING: session_meta.json not found, skipping resolution update")
        return
    with open(meta_path) as f:
        meta = json.load(f)
    original = meta.get("capture_resolution", "")
    # flip WxH → HxW to reflect post-rotation portrait dimensions
    if "x" in original:
        w, h = original.split("x", 1)
        rotated = f"{h}x{w}"
    else:
        rotated = original
    if meta.get("capture_resolution") == rotated:
        print(f"session_meta.json capture_resolution already correct ({rotated})")
        return
    meta["capture_resolution"] = rotated
    with open(meta_path, "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    print(f"session_meta.json capture_resolution updated: {original} → {rotated}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    session_path = resolve_session_path(sys.argv[1])
    rotate_frames(session_path)
