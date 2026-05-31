#!/usr/bin/env python3
"""Phase B4 — Export Verified Ground Truth.
Reads labels.json (human-verified) and emits ground_truth.csv for algorithm evaluation.
Run after human review is complete (status.json stage == 'done' or 'reviewing').
"""

import json, sys, csv
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from gt_config import SESSION_UUID, EXPORT_DIR

LABEL_ORDER = ["OBSTACLE_NEAR", "OBSTACLE_FAR", "DEGRADED", "CLEAR"]


def frame_ground_truth(frame_labels: dict) -> str:
    """Collapse region-level labels to a single per-frame class."""
    status = frame_labels.get("status", "unreviewed")
    if status == "unreviewed":
        return None  # skip unreviewed frames

    obstacles = frame_labels.get("obstacles", [])
    if obstacles:
        types = [o.get("type", "") for o in obstacles]
        if "OBSTACLE_NEAR" in types:
            return "OBSTACLE_NEAR"
        if "OBSTACLE_FAR" in types:
            return "OBSTACLE_FAR"

    if frame_labels.get("degraded"):
        return "DEGRADED"

    if frame_labels.get("clear"):
        return "CLEAR"

    return "DEGRADED"  # reviewed but indeterminate → conservative


def main():
    labels_path = EXPORT_DIR / "labels.json"
    if not labels_path.exists():
        print("ERROR: labels.json not found — complete human review (Phase B3) first.")
        sys.exit(1)

    labels = json.loads(labels_path.read_text())
    frames = labels.get("frames", {})

    out_path = EXPORT_DIR / "ground_truth.csv"
    rows = []
    skipped = 0

    for frame_num_str, frame_labels in sorted(frames.items(), key=lambda x: int(x[0])):
        gt = frame_ground_truth(frame_labels)
        if gt is None:
            skipped += 1
            continue
        rows.append({"frame_idx": int(frame_num_str), "ground_truth": gt})

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["frame_idx", "ground_truth"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}  (skipped {skipped} unreviewed)")

    counts = {}
    for r in rows:
        counts[r["ground_truth"]] = counts.get(r["ground_truth"], 0) + 1
    for label in LABEL_ORDER:
        if label in counts:
            print(f"  {label:15s}: {counts[label]}")

    # Update status.json
    status_path = EXPORT_DIR / "status.json"
    if status_path.exists():
        st = json.loads(status_path.read_text())
        st["stage"] = "done"
        st["updated_at"] = datetime.now(timezone.utc).isoformat()
        status_path.write_text(json.dumps(st, indent=1))
        print("Updated status.json → stage=done")


if __name__ == "__main__":
    main()
