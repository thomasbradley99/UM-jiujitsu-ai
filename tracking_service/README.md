# Tracking Service

YOLO + BoT-SORT (with ReID) fighter-tracking API for the UM Jiujitsu AI app.

Runs as its own FastAPI process on port **8000**, separate from the Vite
frontend (`:5173`) and the Express Anam-token proxy (`:3001`).

## Endpoints

### `GET /health`
```json
{ "ok": true, "service": "tracking_service" }
```

### `POST /detect_frame`
Multipart form:
- `frame` — JPEG/PNG image of the current paused video frame
- `t` — float, timestamp (seconds) of that frame

Returns:
```json
{
  "t": 12.4,
  "people": [
    { "id": 0, "bbox": [x, y, w, h], "conf": 0.91 },
    { "id": 1, "bbox": [x, y, w, h], "conf": 0.88 }
  ]
}
```
Frontend renders these bboxes over the paused frame so the user can pick
which fighter to track.

### `POST /track`
Multipart form:
- `video` — the source video file (mp4)
- `target_bbox` — JSON string `[x, y, w, h]` (pixels) — the bbox the user clicked
- `target_t` — float, the timestamp of the picker frame
- `sample_fps` — float, output samples per second (default 8)

Returns:
```json
{
  "track_id": 3,
  "video_duration": 370.4,
  "fps": 30.0,
  "samples": [
    { "t": 0.0,  "bbox": [x, y, w, h], "conf": 0.88 },
    { "t": 0.125,"bbox": [x, y, w, h], "conf": 0.86 }
  ]
}
```

## Two CLIs — pick the right one for your video

Both run end-to-end on a single video file with no server or frontend.

### `cluster_cli.py` — recommended for fights / grappling / busy footage

Appearance-based identity (OSNet embeddings → K-means clustering). Survives
heavy occlusion and tangles because it doesn't rely on temporal coherence —
two fighters rolling on the ground stay correctly identified.

```bash
cd tracking_service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python cluster_cli.py /path/to/fight.mp4 --k 2
```

Pipeline:
1. YOLO every frame → person bboxes (no tracker IDs).
2. OSNet embeds every crop → 512-d appearance vector.
3. Spherical K-means → K identity clusters.
4. Hungarian per-frame to enforce one cluster per person per frame.
5. Saves `fight_clusters.jpg` — a thumbnail strip showing one representative
   crop per cluster, colour-coded.
6. Saves `fight_clusters.mp4` — original video with all detections boxed
   in their cluster's colour (preview).
7. Prompts: *"Which cluster to crop? choices=[0, 1]"*. Open the thumbnail
   strip, see who is who, type the number.
8. Builds an EMA-smoothed bbox path for that cluster (gap-filled) and
   writes `fight_cluster1_crop.mp4` — a 1280×720 follow-cam of just that
   person for the full duration.

Slow steps (1–4) are cached to `.cache_<name>_k<K>.pkl`, so re-running with
a different `--pick` skips straight to rendering.

Useful flags:
```bash
python cluster_cli.py fight.mp4 --k 2 --pick 1    # skip the prompt
python cluster_cli.py gym.mov --k 8               # gym video with 8 people
python cluster_cli.py fight.mp4 --k 2 --no-clustered    # skip the all-IDs preview mp4
python cluster_cli.py fight.mp4 --k 2 --no-cache        # force re-run (e.g. after tweaking K)
python cluster_cli.py fight.mp4 --k 2 --crop-w 960 --crop-h 540
```

### `cli.py` — single-tracker version (BoT-SORT + ReID)

Faster but unreliable on grappling because it depends on temporal continuity
and silently swaps fighter IDs in tangles. Use this only for clean stand-up
footage.

```bash
python cli.py /path/to/fight.mp4
```

Flow: grabs the midpoint frame, draws YOLO boxes numbered 0..N, you type a
number, BoT-SORT renders the chosen fighter with a green box on every frame.

Useful flags:
```bash
python cli.py fight.mp4 --at 30          # use the frame at 30s as the picker
python cli.py fight.mp4 --mode crop      # follow-cam crop instead of bbox overlay
python cli.py fight.mp4 --pick 1         # skip prompt, auto-pick person index 1
python cli.py fight.mp4 --out only_him.mp4
```

## Setup

```bash
cd tracking_service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

First run will auto-download YOLO weights (`yolov8x.pt`, ~130MB) into
`./models/` (or wherever Ultralytics caches; you can move them in).

## Run

```bash
uvicorn main:app --reload --port 8000
# or, no autoreload:
uvicorn main:app --host 0.0.0.0 --port 8000
```

Health check:
```bash
curl -s localhost:8000/health
```

## Sample requests

Detect on a frame:
```bash
curl -s -F "frame=@frame.jpg" -F "t=12.4" \
  http://localhost:8000/detect_frame | jq
```

Run a full track (uses the bbox returned by `/detect_frame`):
```bash
curl -s \
  -F "video=@fight.mp4" \
  -F 'target_bbox=[420.5, 180.2, 220.0, 510.0]' \
  -F "target_t=12.4" \
  -F "sample_fps=8" \
  http://localhost:8000/track | jq '.track_id, (.samples|length)'
```

Render an annotated MP4 directly (saves to disk):
```bash
curl -s \
  -F "video=@fight.mp4" \
  -F 'target_bbox=[420.5, 180.2, 220.0, 510.0]' \
  -F "target_t=12.4" \
  -F "mode=box" \
  -o fight_tracked.mp4 \
  http://localhost:8000/track_video
```

## Performance notes

- **Model size**: `yolov8x.pt` is the default for quality. For CPU-only
  dev, swap to `yolov8n.pt` in `detector.py` (`DEFAULT_WEIGHTS`).
- **Mac (MPS)**: BoT-SORT's ReID embedding extraction can be flaky on
  MPS. If you hit dtype errors, force CPU: `CUDA_VISIBLE_DEVICES="" PYTORCH_ENABLE_MPS_FALLBACK=1 uvicorn ...`
- **Frame sampling**: source videos are usually 30fps. Output is
  resampled to `sample_fps` (default 8), giving ~3000 entries for a
  6-min fight. Increase if the overlay looks jumpy, decrease for speed.
- **track_buffer**: tuned to 150 frames in `botsort_reid.yaml`. Lower
  this if you see new track IDs being created during normal scrambles;
  raise it for very long occlusions.

## Wiring into the React frontend

`services/trackingService.ts` (in the parent project) wraps these two
endpoints. Frontend calls:

1. User clicks **TRACK** → app pauses video, captures current frame
   to canvas, posts to `/detect_frame`.
2. Bboxes render in `PersonPicker` modal. User clicks one.
3. App posts the *original video file* + the chosen bbox + timestamp
   to `/track`. Spinner.
4. Response comes back. App stores `samples[]` and shows
   `TrackingOverlay` over the player.
