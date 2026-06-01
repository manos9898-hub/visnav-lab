# Lab Project

This is a separate project from visnav5. Do not mix concerns between the two.
visnav5 lives at `/home/ubuntu/visnav5/` — Android app code only.
Lab lives at `/home/ubuntu/lab/` — ground-truth pipeline, review tooling, and session data.

## Preparing a Session for Review

One script does everything — always use it:

```bash
python3 /home/ubuntu/lab/scripts/prepare_session.py --camera-height 116
```

This handles in order: S3 download, extraction, frame orientation fix, B1 clip
selection, B2 overlay generation. The session will appear in the review app when
it completes.

To target a specific session instead of the latest:

```bash
python3 /home/ubuntu/lab/scripts/prepare_session.py --camera-height 116 --session <uuid>
```

Never run `gt_select_clips.py`, `gt_overlay.py`, or `fix_a36_frame_orientation.py`
individually for a new session. Use `prepare_session.py`.

## Review App

```bash
# Start the server (if not already running)
nohup uvicorn app:app --host 127.0.0.1 --port 8050 \
  --app-dir /home/ubuntu/lab/gttool >> /home/ubuntu/lab/gttool/app.log 2>&1 &

# SSH tunnel (run on your local machine)
ssh -L 8050:localhost:8050 ubuntu@52.55.79.247

# Then open http://localhost:8050
```

Check if the server is already running before starting it:

```bash
ss -tlnp | grep 8050
```

## Layout

- `scripts/prepare_session.py` — single entry point for session preparation
- `scripts/gt_config.py` — session UUID and thresholds, updated by prepare_session.py
- `scripts/gt_select_clips.py` — Phase B1 (called by prepare_session.py)
- `scripts/gt_overlay.py` — Phase B2 (called by prepare_session.py)
- `scripts/gt_export.py` — Phase B4, run manually after human review is complete
- `scripts/fix_a36_frame_orientation.py` — called by prepare_session.py
- `gttool/app.py` — FastAPI review app
- `exports/<uuid>/` — per-session outputs (gitignored)
- `workspaces/<uuid>/` — extracted session data (gitignored)
- `sessions/` — pipeline documentation and execution reports (gitignored)

## After Human Review (Phase B4)

```bash
python3 /home/ubuntu/lab/scripts/gt_export.py
```

Writes `exports/<uuid>/ground_truth.csv`. Then version-track:

```bash
cd /home/ubuntu/lab
dvc add exports/$SESSION_UUID
git add exports/$SESSION_UUID.dvc .gitignore
git commit -m "Ground truth: session $SESSION_UUID"
git push
```
