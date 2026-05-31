# ── Run Configuration ──────────────────────────────────────────────────────────
SESSION_UUID  = "16309e1d-ab4d-4179-8caa-2fa0656b21ec"
TARGET_PCT    = 0.05        # fraction of frames to select (as contiguous clips)

# Physical camera setup — set CAMERA_HEIGHT_M; CANE_BOUNDARY is derived below
CAMERA_HEIGHT_M   = 1.16    # measured camera height above ground (metres)

# Clip selection thresholds (Phase B1)
MIN_CLIP_LEN      = 15      # min consecutive good frames to count as a clip (~1 s at 15fps)
GYRO_TURN_GATE    = 40.0    # deg/s — converted to rad/s in scripts (÷57.2958); 15 was too strict for hand-held sway
ACCEL_MOVE_STD    = 0.15    # m/s² accel-magnitude std below which the wearer is standing still (z-axis alone at 1.0 was too strict)
SHARPNESS_MIN     = 80.0    # Laplacian variance below which a frame is too blurry
EXCLUDE_OBSCURED  = True    # drop frames with camera_obscured == True
TILT_MAX_DEG      = 30.0    # max camera pitch above horizontal (deg); above this the camera is pointing too far upward

# Overlay / future-traversal thresholds (Phase B2)
# CANE_BOUNDARY is computed below from CAMERA_HEIGHT_M — do not hardcode it here.
FORWARD_HORIZON   = 45      # max frames to track a feature forward (~3 s at 15 fps)
GROUND_FLOW_TOL   = 0.60    # residual tolerance vs expected ground-plane flow (relaxed for low-texture sidewalk)

# Analysis and render sizes — portrait (images are 960×1280 after A36 rotation fix)
FRAME_W, FRAME_H  = 240, 320    # 1/4-scale portrait for optical flow analysis
RENDER_W, RENDER_H = 480, 640  # 1/2-scale portrait for review frames

# Derive CANE_BOUNDARY from camera geometry:
#   portrait VFoV = 69.67° (55.13° landscape VFoV rotated to portrait at 960×1280)
#   f_pix = FRAME_H / (2 * tan(vfov/2))
#   CANE_BOUNDARY = (f_pix / FRAME_H) * (CAMERA_HEIGHT_M / D_CANE_M) + 0.5
#   D_CANE_M = 4.0 m (OBSTACLE_FAR outer edge)
import math as _math
_f_pix = FRAME_H / (2 * _math.tan(_math.radians(69.67 / 2)))
_D_CANE_M = 4.0
CANE_BOUNDARY = round((_f_pix / FRAME_H) * (CAMERA_HEIGHT_M / _D_CANE_M) + 0.5, 4)

# ── Derived paths (do not edit per run) ────────────────────────────────────────
import pathlib, hashlib, json

LAB         = pathlib.Path("/home/ubuntu/lab")
SESSION_DIR = LAB / "workspaces" / SESSION_UUID / f"session_{SESSION_UUID}"
EXPORT_DIR  = LAB / "exports" / SESSION_UUID
NDJSON      = SESSION_DIR / "frames.ndjson"

# params_hash identifies the threshold set used — changes when thresholds change
_hash_src = json.dumps({
    "TARGET_PCT": TARGET_PCT, "MIN_CLIP_LEN": MIN_CLIP_LEN,
    "GYRO_TURN_GATE": GYRO_TURN_GATE, "ACCEL_MOVE_STD": ACCEL_MOVE_STD,
    "SHARPNESS_MIN": SHARPNESS_MIN, "EXCLUDE_OBSCURED": EXCLUDE_OBSCURED,
    "TILT_MAX_DEG": TILT_MAX_DEG,
    "CANE_BOUNDARY": CANE_BOUNDARY, "FORWARD_HORIZON": FORWARD_HORIZON,
    "GROUND_FLOW_TOL": GROUND_FLOW_TOL, "FRAME_W": FRAME_W, "FRAME_H": FRAME_H,
}, sort_keys=True)
PARAMS_HASH = hashlib.sha256(_hash_src.encode()).hexdigest()[:8]
