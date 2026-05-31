#!/usr/bin/env python3
"""Phase B1 — Clip Selection. Reads frames.ndjson + frame JPEGs, writes clips.json."""

import json, math, sys
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from gt_config import (
    SESSION_UUID, SESSION_DIR, EXPORT_DIR, NDJSON,
    TARGET_PCT, MIN_CLIP_LEN,
    GYRO_TURN_GATE, ACCEL_MOVE_STD, SHARPNESS_MIN, EXCLUDE_OBSCURED,
    TILT_MAX_DEG, FRAME_W, FRAME_H,
)

GYRO_TURN_GATE_RAD = GYRO_TURN_GATE / 57.2958  # deg/s → rad/s


def laplacian_variance(img_path: Path) -> float:
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    small = cv2.resize(img, (FRAME_W, FRAME_H))
    return float(cv2.Laplacian(small, cv2.CV_64F).var())


def classify_frame(record: dict) -> tuple[bool, str]:
    """Return (good, drop_reason). drop_reason is non-empty when frame is rejected."""
    if EXCLUDE_OBSCURED and record.get("camera_obscured", False):
        return False, "obscured"

    accel = record.get("accelerometer", [])
    if len(accel) < 2:
        # too few samples to compute std — treat as not moving
        return False, "not_moving"
    mags = np.sqrt(np.array([[s["x"], s["y"], s["z"]] for s in accel])**2).sum(axis=1)
    if mags.std() < ACCEL_MOVE_STD:
        return False, "not_moving"

    gyro = record.get("gyroscope", [])
    if gyro:
        mags = [math.sqrt(s["x"]**2 + s["y"]**2 + s["z"]**2) for s in gyro]
        if np.mean(mags) >= GYRO_TURN_GATE_RAD:
            return False, "turning"

    # Tilt filter: estimate camera pitch from gravity direction.
    # The phone's Z axis points toward the user (away from camera). When the
    # camera tilts upward, gz becomes increasingly negative.
    # pitch_up = arcsin(-gz / |g|); positive = camera above horizontal.
    xs = np.array([s["x"] for s in accel])
    ys = np.array([s["y"] for s in accel])
    zs = np.array([s["z"] for s in accel])
    g_mag = math.sqrt(float(xs.mean())**2 + float(ys.mean())**2 + float(zs.mean())**2)
    if g_mag > 0:
        pitch_deg = math.degrees(math.asin(max(-1.0, min(1.0, -float(zs.mean()) / g_mag))))
        if pitch_deg > TILT_MAX_DEG:
            return False, "tilted"

    return True, ""  # sharpness checked separately (needs disk read)


def main():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Session : {SESSION_UUID}")
    print(f"Loading : {NDJSON}")

    records = []
    with open(NDJSON) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    records.sort(key=lambda r: r["frame_number"])
    n_total = len(records)
    print(f"Frames  : {n_total}")

    target_n = max(MIN_CLIP_LEN, int(n_total * TARGET_PCT))
    print(f"Target  : {target_n} frames ({TARGET_PCT*100:.1f}%)")
    print("Classifying frames …")

    good = []
    dropped = {"not_moving": 0, "turning": 0, "tilted": 0, "blurry": 0, "obscured": 0}

    for i, rec in enumerate(records):
        ok, reason = classify_frame(rec)
        if not ok:
            dropped[reason] += 1
            good.append(False)
            continue

        lap = laplacian_variance(SESSION_DIR / rec["frame_filename"])
        if lap < SHARPNESS_MIN:
            dropped["blurry"] += 1
            good.append(False)
        else:
            good.append(True)

        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{n_total}")

    print(f"  {n_total}/{n_total}")

    # Find maximal runs of good frames >= MIN_CLIP_LEN
    runs = []
    i = 0
    while i < n_total:
        if good[i]:
            j = i
            while j < n_total and good[j]:
                j += 1
            if j - i >= MIN_CLIP_LEN:
                runs.append((i, j - 1))  # inclusive end
            i = j
        else:
            i += 1

    print(f"Good runs >= {MIN_CLIP_LEN} frames: {len(runs)}")

    # Select longest-first until target reached
    runs_sorted = sorted(runs, key=lambda r: r[1] - r[0] + 1, reverse=True)
    selected_clips = []
    n_selected = 0
    for start, end in runs_sorted:
        clip_len = end - start + 1
        selected_clips.append({"start": start, "end": end})
        n_selected += clip_len
        if n_selected >= target_n:
            break

    selected_clips.sort(key=lambda c: c["start"])

    print(f"\nSelected {len(selected_clips)} clips, {n_selected} frames")
    print(f"Drop breakdown: {dropped}")

    out = {
        "uuid": SESSION_UUID,
        "n_frames_total": n_total,
        "n_frames_selected": n_selected,
        "n_clips": len(selected_clips),
        "clips": selected_clips,
        "dropped": dropped,
    }
    out_path = EXPORT_DIR / "clips.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
