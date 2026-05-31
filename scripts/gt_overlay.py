#!/usr/bin/env python3
"""Phase B2 — Ground-Truth Overlay Generation.
Tracks GFTT features forward with Lucas-Kanade; points that reach the cane line
with ground-plane-consistent flow mark their origin as confirmed clear.
Writes gt_manifest.json, review_frames/, and status.json.
"""

import json, sys, math, hashlib
from pathlib import Path
from datetime import datetime, timezone

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from gt_config import (
    SESSION_UUID, SESSION_DIR, EXPORT_DIR, NDJSON, PARAMS_HASH,
    CANE_BOUNDARY, FORWARD_HORIZON, GROUND_FLOW_TOL,
    FRAME_W, FRAME_H, RENDER_W, RENDER_H,
)

CANE_Y = int(CANE_BOUNDARY * FRAME_H)   # y-pixel of cane line in analysis frame

LK_PARAMS = dict(
    winSize=(15, 15),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
)
GFTT_PARAMS = dict(maxCorners=200, qualityLevel=0.01, minDistance=7, blockSize=7)


def load_gray(frame_filename: str) -> np.ndarray:
    img = cv2.imread(str(SESSION_DIR / frame_filename), cv2.IMREAD_GRAYSCALE)
    return cv2.resize(img, (FRAME_W, FRAME_H))


def load_color(frame_filename: str) -> np.ndarray:
    img = cv2.imread(str(SESSION_DIR / frame_filename))
    return cv2.resize(img, (RENDER_W, RENDER_H))


def estimate_foe(flows: np.ndarray, pts: np.ndarray) -> tuple[float, float]:
    """Rough FOE from the intersection of radial flow lines (median vote)."""
    # For each flow vector, FOE lies along the line pt - flow*t.
    # Simple approximation: use centroid of points that have low magnitude flow.
    mags = np.linalg.norm(flows, axis=1)
    if mags.max() < 1e-3:
        return FRAME_W / 2, FRAME_H * 0.3
    low = mags < np.percentile(mags, 30)
    if low.sum() == 0:
        return FRAME_W / 2, FRAME_H * 0.3
    return float(pts[low, 0].mean()), float(pts[low, 1].mean())


def expected_flow(pt: np.ndarray, foe: tuple, scale: float) -> np.ndarray:
    """Expected radial flow of a ground-plane point under forward motion."""
    dx, dy = pt[0] - foe[0], pt[1] - foe[1]
    return np.array([dx, dy]) * scale


def process_clip(clip: dict, frames_index: dict) -> list[dict]:
    """
    Run optical flow over one clip. Returns a list of manifest frame entries,
    one per selected frame in the clip.
    """
    start, end = clip["start"], clip["end"]
    clip_frames = [frames_index[n] for n in range(start, end + 1) if n in frames_index]
    if not clip_frames:
        return []

    # Load all grayscale frames for this clip
    grays = [load_gray(r["frame_filename"]) for r in clip_frames]
    n = len(grays)

    # confirmed_clear[frame_idx_in_clip] = list of (x, y) origin pixels
    confirmed_clear = [[] for _ in range(n)]

    # Track features starting from each frame, forward up to FORWARD_HORIZON.
    # Restrict feature detection to the lower half of the frame — the region
    # where the ground is expected. This prevents GFTT from clustering on
    # high-contrast building walls and fire escapes in the upper frame.
    ground_mask = np.zeros((FRAME_H, FRAME_W), dtype=np.uint8)
    ground_mask[FRAME_H // 2:, :] = 255

    for origin_idx in range(n):
        pts = cv2.goodFeaturesToTrack(grays[origin_idx], mask=ground_mask, **GFTT_PARAMS)
        if pts is None or len(pts) == 0:
            continue
        pts = pts.reshape(-1, 2)

        # Estimate FOE and scale from the flow on the first step
        if origin_idx + 1 < n:
            next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                grays[origin_idx], grays[origin_idx + 1], pts.reshape(-1, 1, 2), None, **LK_PARAMS
            )
            if next_pts is not None:
                st = status.ravel().astype(bool)
                if st.sum() > 0:
                    flows_1 = next_pts.reshape(-1, 2)[st] - pts[st]
                    foe = estimate_foe(flows_1, pts[st])
                    mags = np.linalg.norm(flows_1, axis=1)
                    scale = float(np.median(mags[mags > 0.5])) / max(
                        float(np.median(np.linalg.norm(pts[st] - np.array(foe), axis=1))), 1.0
                    ) if (mags > 0.5).any() else 0.01
                else:
                    foe = (FRAME_W / 2, FRAME_H * 0.3)
                    scale = 0.01
            else:
                foe = (FRAME_W / 2, FRAME_H * 0.3)
                scale = 0.01
        else:
            foe = (FRAME_W / 2, FRAME_H * 0.3)
            scale = 0.01

        # Track each feature forward until it hits the cane line or FORWARD_HORIZON
        current_pts = pts.copy()
        active = np.ones(len(pts), dtype=bool)
        flow_residuals = np.zeros(len(pts))
        flow_steps = np.zeros(len(pts), dtype=int)

        for step in range(1, min(FORWARD_HORIZON, n - origin_idx)):
            if not active.any():
                break
            nxt, status, _ = cv2.calcOpticalFlowPyrLK(
                grays[origin_idx + step - 1],
                grays[origin_idx + step],
                current_pts[active].reshape(-1, 1, 2),
                None,
                **LK_PARAMS,
            )
            if nxt is None:
                active[:] = False
                break

            st = status.ravel().astype(bool)
            active_indices = np.where(active)[0]
            # Deactivate lost tracks
            for local_i, global_i in enumerate(active_indices):
                if not st[local_i]:
                    active[global_i] = False
                    continue
                new_pt = nxt[local_i, 0]
                act_flow = new_pt - current_pts[global_i]
                exp_flow = expected_flow(current_pts[global_i], foe, scale)
                mag_exp = np.linalg.norm(exp_flow)
                if mag_exp > 0.5:
                    residual = np.linalg.norm(act_flow - exp_flow) / mag_exp
                    flow_residuals[global_i] = max(flow_residuals[global_i], residual)
                current_pts[global_i] = new_pt
                flow_steps[global_i] = step

                # Check if this feature has crossed the cane line
                if new_pt[1] >= CANE_Y:
                    active[global_i] = False
                    # Accept if ground-plane flow was consistent throughout
                    if flow_residuals[global_i] <= GROUND_FLOW_TOL:
                        ox, oy = pts[global_i]
                        confirmed_clear[origin_idx].append((float(ox), float(oy)))

    # Build manifest entries for selected frames in this clip
    entries = []
    scale_x = RENDER_W / FRAME_W
    scale_y = RENDER_H / FRAME_H

    for local_idx, rec in enumerate(clip_frames):
        pts_clear = confirmed_clear[local_idx]
        if len(pts_clear) >= 3:
            hull_pts = cv2.convexHull(np.array(pts_clear, dtype=np.float32).reshape(-1, 1, 2))
            polygon = [(float(p[0][0] * scale_x), float(p[0][1] * scale_y))
                       for p in hull_pts]
            # Clip to frame bounds
            polygon = [
                (max(0.0, min(float(RENDER_W), x)), max(0.0, min(float(RENDER_H), y)))
                for x, y in polygon
            ]
        else:
            polygon = []

        entries.append({
            "frame_number": rec["frame_number"],
            "clear_polygon": polygon,
            "detector_state": "CLEAR",
            "obstacles": [],
        })

    # Render review frames
    render_dir = EXPORT_DIR / "review_frames"
    render_dir.mkdir(parents=True, exist_ok=True)

    for local_idx, rec in enumerate(clip_frames):
        entry = entries[local_idx]
        color_img = load_color(rec["frame_filename"])
        polygon = entry["clear_polygon"]
        if len(polygon) >= 3:
            pts_render = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
            overlay = color_img.copy()
            cv2.fillPoly(overlay, [pts_render], (0, 200, 0))
            color_img = cv2.addWeighted(color_img, 0.6, overlay, 0.4, 0)
            cv2.polylines(color_img, [pts_render], True, (0, 255, 0), 2)
        out_path = render_dir / f"frame_{rec['frame_number']:06d}.jpg"
        cv2.imwrite(str(out_path), color_img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    return entries


def main():
    clips_path = EXPORT_DIR / "clips.json"
    if not clips_path.exists():
        print("ERROR: clips.json not found — run gt_select_clips.py first")
        sys.exit(1)

    clips_data = json.loads(clips_path.read_text())

    # Guard: refuse to overwrite a different-params-hash manifest unless forced
    manifest_path = EXPORT_DIR / "gt_manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing.get("params_hash") != PARAMS_HASH:
            if "--force" not in sys.argv:
                print(f"ERROR: existing manifest has params_hash={existing['params_hash']}, "
                      f"current={PARAMS_HASH}. Use --force to overwrite.")
                sys.exit(1)
        else:
            print("Manifest already exists with matching params_hash — skipping (idempotent).")
            print("Use --force to regenerate anyway.")
            if "--force" not in sys.argv:
                return

    # Build frame index from NDJSON
    print("Loading frames.ndjson …")
    frames_index = {}
    with open(NDJSON) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                frames_index[r["frame_number"]] = r

    clips = clips_data["clips"]
    print(f"Processing {len(clips)} clips ({clips_data['n_frames_selected']} frames) …")

    all_entries = []
    for i, clip in enumerate(clips):
        print(f"  Clip {i+1}/{len(clips)}: frames {clip['start']}–{clip['end']}")
        entries = process_clip(clip, frames_index)
        all_entries.extend(entries)
        print(f"    → {len(entries)} frames rendered, "
              f"{sum(1 for e in entries if e['clear_polygon'])} with polygon")

    manifest = {
        "uuid": SESSION_UUID,
        "params_hash": PARAMS_HASH,
        "frames": all_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"\nWrote {manifest_path}")
    print(f"Wrote {len(all_entries)} review frames to {EXPORT_DIR / 'review_frames'}")

    status = {
        "uuid": SESSION_UUID,
        "stage": "overlaid",
        "ready_to_review": True,
        "n_frames_total": clips_data["n_frames_total"],
        "n_frames_selected": clips_data["n_frames_selected"],
        "n_clips": clips_data["n_clips"],
        "n_reviewed": 0,
        "params_hash": PARAMS_HASH,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (EXPORT_DIR / "status.json").write_text(json.dumps(status, indent=1))
    print(f"Wrote status.json  (stage=overlaid, ready_to_review=true)")


if __name__ == "__main__":
    main()
