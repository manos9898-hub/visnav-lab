import json, pathlib
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

EXPORTS = pathlib.Path("/home/ubuntu/lab/exports")
HERE    = pathlib.Path(__file__).parent

app = FastAPI()

@app.get("/api/sessions")
def list_sessions():
    out = []
    for d in sorted(EXPORTS.glob("*")):
        sf = d / "status.json"
        if not sf.exists():
            continue
        st = json.loads(sf.read_text())
        if st.get("ready_to_review"):
            out.append(st)
    return out

@app.get("/api/session/{uuid}/manifest")
def manifest(uuid: str):
    f = EXPORTS / uuid / "gt_manifest.json"
    if not f.exists():
        raise HTTPException(404, "manifest not found")
    return JSONResponse(json.loads(f.read_text()))

@app.get("/api/session/{uuid}/frame/{n}")
def frame(uuid: str, n: int):
    f = EXPORTS / uuid / "review_frames" / f"frame_{n:06d}.jpg"
    if not f.exists():
        raise HTTPException(404, "frame not found")
    return FileResponse(f)

@app.get("/api/session/{uuid}/labels")
def get_labels(uuid: str):
    f = EXPORTS / uuid / "labels.json"
    if f.exists():
        return JSONResponse(json.loads(f.read_text()))
    # fall back to auto polygons from the manifest
    m = EXPORTS / uuid / "gt_manifest.json"
    return JSONResponse(json.loads(m.read_text()) if m.exists() else {})

class Labels(BaseModel):
    frames: dict   # frame_number -> {clear: [poly...], obstacles: [{type, poly}...], status}

@app.post("/api/session/{uuid}/labels")
def save_labels(uuid: str, labels: Labels):
    d = EXPORTS / uuid
    (d / "labels.json").write_text(json.dumps(labels.model_dump(), indent=1))
    sf = d / "status.json"
    st = json.loads(sf.read_text())
    st["n_reviewed"] = sum(1 for v in labels.frames.values()
                           if v.get("status") != "unreviewed")
    st["stage"] = "done" if st["n_reviewed"] >= st["n_frames_selected"] else "reviewing"
    sf.write_text(json.dumps(st, indent=1))
    return {"saved": True, "n_reviewed": st["n_reviewed"]}

# Front end served from ./static
app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")
