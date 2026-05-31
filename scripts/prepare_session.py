#!/usr/bin/env python3
"""
Prepare the latest uploaded session for ground-truth review.

Downloads the session zip from S3, extracts it, deletes the zip,
fixes frame orientation, then runs Phase B1 (clip selection) and
Phase B2 (overlay generation) so the session appears in the review app.

Usage:
    python3 prepare_session.py --camera-height 116
    python3 prepare_session.py --camera-height 116 --session <uuid>
    python3 prepare_session.py --camera-height 116 --session session_<uuid>.zip

All calculations (including CANE_BOUNDARY) flow automatically from
--camera-height. The only value you set per session is camera height.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
LAB = Path("/home/ubuntu/lab")
SESSIONS_DIR = LAB / "sessions"
WORKSPACES_DIR = LAB / "workspaces"
BUCKET = "visual-navigation-sessions"


# ── S3 helpers ────────────────────────────────────────────────────────────────

def list_s3_sessions() -> list[tuple[str, str]]:
    """Return [(datetime_str, filename), ...] sorted oldest-first."""
    result = subprocess.run(
        ["aws", "s3", "ls", f"s3://{BUCKET}/sessions/", "--recursive"],
        capture_output=True, text=True, check=True,
    )
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].endswith(".zip"):
            dt = f"{parts[0]} {parts[1]}"
            filename = Path(parts[3]).name
            entries.append((dt, filename))
    entries.sort()
    return entries


def find_latest_session() -> str:
    """Return the filename of the most recently uploaded session zip."""
    entries = list_s3_sessions()
    if not entries:
        raise RuntimeError("No session zips found in S3")
    _, filename = entries[-1]
    print(f"Latest S3 session: {filename}")
    return filename


# ── Download / extract ────────────────────────────────────────────────────────

def uuid_from_basename(basename: str) -> str:
    return basename.removeprefix("session_").removesuffix(".zip")


def download_and_extract(basename: str) -> str:
    """
    Download zip from S3 → lab/sessions/, extract to workspaces/<uuid>/, delete zip.
    Returns the session UUID. Skips download/extract if workspace already exists.
    """
    uuid = uuid_from_basename(basename)
    workspace = WORKSPACES_DIR / uuid

    if workspace.exists():
        print(f"Workspace already exists, skipping download: {workspace}")
        return uuid

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = SESSIONS_DIR / basename

    if not zip_path.exists():
        print(f"Downloading {basename} from S3 …")
        subprocess.run(
            ["aws", "s3", "cp", f"s3://{BUCKET}/sessions/{basename}", str(zip_path)],
            check=True,
        )
    else:
        print(f"Zip already in sessions/: {zip_path}")

    print(f"Extracting to {workspace} …")
    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(["unzip", "-q", str(zip_path), "-d", str(workspace)], check=True)

    zip_path.unlink()
    print(f"Deleted {zip_path.name}")

    return uuid


# ── Config patch ──────────────────────────────────────────────────────────────

def patch_config(uuid: str, camera_height_m: float):
    """Replace SESSION_UUID and CAMERA_HEIGHT_M in gt_config.py."""
    config_path = SCRIPTS_DIR / "gt_config.py"
    text = config_path.read_text()

    text = re.sub(
        r'^SESSION_UUID\s*=\s*"[^"]*"',
        f'SESSION_UUID  = "{uuid}"',
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r'^CAMERA_HEIGHT_M\s*=\s*[\d.]+',
        f'CAMERA_HEIGHT_M   = {camera_height_m:.4f}',
        text,
        flags=re.MULTILINE,
    )

    config_path.write_text(text)
    print(f"gt_config.py updated: SESSION_UUID={uuid}, CAMERA_HEIGHT_M={camera_height_m:.4f} m")


# ── Phase checks ──────────────────────────────────────────────────────────────

def b1_done(uuid: str) -> bool:
    return (LAB / "exports" / uuid / "clips.json").exists()


def b2_done(uuid: str) -> bool:
    status_path = LAB / "exports" / uuid / "status.json"
    if not status_path.exists():
        return False
    st = json.loads(status_path.read_text())
    return st.get("stage") in ("overlaid", "reviewing", "done")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Prepare a VisNav5 session for ground-truth review."
    )
    parser.add_argument(
        "--camera-height", type=float, required=True,
        metavar="CM",
        help="Camera height above ground in centimetres (e.g. 116)",
    )
    parser.add_argument(
        "--session", type=str, default=None,
        metavar="UUID_OR_FILENAME",
        help="Session UUID or zip filename. Default: latest from S3.",
    )
    args = parser.parse_args()

    camera_height_m = args.camera_height / 100.0
    print(f"Camera height: {args.camera_height} cm  ({camera_height_m:.4f} m)")

    # Resolve session filename
    if args.session:
        raw = args.session
        if raw.endswith(".zip"):
            basename = Path(raw).name
        else:
            basename = f"session_{raw}.zip"
    else:
        basename = find_latest_session()

    uuid = uuid_from_basename(basename)
    print(f"Session UUID : {uuid}")
    print()

    # Step 1 — Download & extract (deletes zip)
    print("── Step 1: Download & extract ──────────────────────────")
    download_and_extract(basename)
    print()

    # Step 2 — Fix frame orientation
    print("── Step 2: Fix frame orientation ───────────────────────")
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "fix_a36_frame_orientation.py"), uuid],
        check=True,
    )
    print()

    # Step 3 — Patch config
    print("── Step 3: Write config ─────────────────────────────────")
    patch_config(uuid, camera_height_m)
    print()

    # Step 4 — Phase B1: clip selection
    if b1_done(uuid):
        print("── Step 4: B1 clip selection — already done, skipping ──")
    else:
        print("── Step 4: B1 clip selection ────────────────────────────")
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "gt_select_clips.py")], check=True)
    print()

    # Step 5 — Phase B2: overlay generation
    if b2_done(uuid):
        print("── Step 5: B2 overlay generation — already done, skipping")
    else:
        print("── Step 5: B2 overlay generation ────────────────────────")
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "gt_overlay.py")], check=True)
    print()

    print("── Done ─────────────────────────────────────────────────")
    print(f"Session {uuid} is ready for review.")
    print("Open http://localhost:8050 (via SSH tunnel) to start reviewing.")


if __name__ == "__main__":
    main()
