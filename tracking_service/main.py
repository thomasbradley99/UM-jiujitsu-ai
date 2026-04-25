"""FastAPI server for fighter detection + tracking.

Two endpoints:
  POST /detect_frame  -> per-frame YOLO person detections (the picker UI)
  POST /track         -> full-video BoT-SORT track of the chosen person

Run:
  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from detector import detect_people
from tracker import render_tracked_video, track_video

app = FastAPI(title="UM Jiujitsu AI — Tracking Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before deploying
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "tracking_service"}


@app.post("/detect_frame")
async def detect_frame(frame: UploadFile = File(...), t: float = Form(0.0)) -> dict:
    """Detect all people in a single frame.

    Frontend captures the current paused frame from <video>, sends it
    here, and renders the returned bboxes as clickable overlays so
    the user can pick which fighter to track.
    """
    image_bytes = await frame.read()
    if not image_bytes:
        raise HTTPException(400, "empty frame upload")

    detections = detect_people(image_bytes)
    return {"t": t, "people": detections}


@app.post("/track")
async def track(
    video: UploadFile = File(...),
    target_bbox: str = Form(..., description="JSON array [x, y, w, h] in pixels"),
    target_t: float = Form(...),
    sample_fps: float = Form(8.0),
) -> dict:
    """Run YOLO + BoT-SORT(+ReID) over the whole video and return
    the bbox track for the fighter the user picked.

    target_bbox / target_t identify which person the user clicked on
    in the picker frame; we resolve that to a single track_id and
    return only that ID's samples across the video.
    """
    try:
        bbox = json.loads(target_bbox)
        if not (isinstance(bbox, list) and len(bbox) == 4):
            raise ValueError
        bbox = [float(v) for v in bbox]
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(400, "target_bbox must be a JSON array [x, y, w, h]")

    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await video.read())
        tmp.flush()
        tmp.close()
        result = track_video(
            video_path=tmp.name,
            target_bbox=bbox,
            target_t=target_t,
            sample_fps=sample_fps,
        )
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return result


@app.post("/track_video")
async def track_video_endpoint(
    background: BackgroundTasks,
    video: UploadFile = File(...),
    target_bbox: str = Form(..., description="JSON array [x, y, w, h] in pixels"),
    target_t: float = Form(...),
    mode: str = Form("box", description="'box' or 'crop' (follow-cam)"),
    crop_w: int = Form(1280),
    crop_h: int = Form(720),
) -> FileResponse:
    """Render an annotated MP4 of just the chosen fighter and stream it back.

    Same target_bbox/target_t semantics as /track. The response body is
    the MP4 file itself (Content-Type: video/mp4).
    """
    if mode not in ("box", "crop"):
        raise HTTPException(400, "mode must be 'box' or 'crop'")

    try:
        bbox = json.loads(target_bbox)
        if not (isinstance(bbox, list) and len(bbox) == 4):
            raise ValueError
        bbox = [float(v) for v in bbox]
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(400, "target_bbox must be a JSON array [x, y, w, h]")

    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    in_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    in_tmp.write(await video.read())
    in_tmp.flush()
    in_tmp.close()
    out_tmp.close()

    try:
        render_tracked_video(
            video_in=in_tmp.name,
            video_out=out_tmp.name,
            target_bbox=bbox,
            target_t=target_t,
            mode=mode,  # type: ignore[arg-type]
            crop_size=(crop_w, crop_h),
        )
    except RuntimeError as e:
        try:
            os.unlink(in_tmp.name)
            os.unlink(out_tmp.name)
        except OSError:
            pass
        raise HTTPException(422, str(e))

    background.add_task(os.unlink, in_tmp.name)
    background.add_task(os.unlink, out_tmp.name)
    out_name = f"{Path(video.filename or 'video').stem}_tracked_{mode}.mp4"
    return FileResponse(out_tmp.name, media_type="video/mp4", filename=out_name)
