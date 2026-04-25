"""Bridge from cluster_pipeline output to a follow-cam cropped video.

Glue between the partner's appearance-clustering pipeline and the
single-fighter crop renderer:

    cluster_pipeline.run(...)                 # detect → embed → cluster
        ↓ produces (detections, kept_ids, labels)
    build_smoothed_path(target_cluster=...)   # sparse → dense → EMA-smoothed
        ↓ produces dict[frame_idx -> bbox]
    render_cropped_for_cluster(...)           # write follow-cam MP4

Plus a helper for the "click a bbox on the picker frame" UX:
    find_cluster_for_bbox(...)                # embed crop, nearest centroid
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


def build_smoothed_path(
    detections: List[dict],
    kept_ids: List[int],
    labels: np.ndarray,
    target_cluster: int,
    max_gap_frames: int = 60,
    smooth_alpha: float = 0.18,
) -> Dict[int, List[float]]:
    """Per-cluster smoothed bbox path.

    Walks the cluster pipeline's detection-level labels, picks the
    detections assigned to ``target_cluster``, fills small gaps via
    linear interpolation, and EMA-smooths centre + size over time.

    Returns a dict ``frame_idx -> [x, y, w, h]`` covering every frame
    between the cluster's first and last detection (interpolated where
    needed). Frames where the cluster was absent for longer than
    ``max_gap_frames`` are simply absent from the output.

    The renderer is responsible for what to do with frames not in the
    dict (typically: hold the last known centre).
    """
    label_for_det = {kept_ids[m]: int(labels[m]) for m in range(len(kept_ids))}

    # 1. Sparse: frame_idx -> (bbox, conf), best detection per frame.
    sparse: Dict[int, Tuple[List[float], float]] = {}
    for det_idx, det in enumerate(detections):
        cid = label_for_det.get(det_idx)
        if cid != target_cluster:
            continue
        f = det["frame"]
        prev = sparse.get(f)
        if prev is None or det["conf"] > prev[1]:
            sparse[f] = (list(det["bbox"]), float(det["conf"]))

    if not sparse:
        return {}

    sorted_frames = sorted(sparse.keys())
    first_f, last_f = sorted_frames[0], sorted_frames[-1]

    # 2. Densify with linear interpolation, but only across small gaps.
    dense: Dict[int, List[float]] = {}
    for f in range(first_f, last_f + 1):
        if f in sparse:
            dense[f] = list(sparse[f][0])
            continue
        pos = bisect.bisect_left(sorted_frames, f)
        if pos == 0 or pos == len(sorted_frames):
            continue
        f0 = sorted_frames[pos - 1]
        f1 = sorted_frames[pos]
        gap = f1 - f0
        # Don't interpolate across a long disappearance — better to
        # render a dropout (caller will hold last centre).
        if gap > max_gap_frames * 2:
            continue
        if (f - f0) > max_gap_frames or (f1 - f) > max_gap_frames:
            continue
        t = (f - f0) / gap if gap else 0.0
        b0 = sparse[f0][0]
        b1 = sparse[f1][0]
        dense[f] = [b0[i] + t * (b1[i] - b0[i]) for i in range(4)]

    # 3. EMA smooth centre + size, forward pass over densified frames.
    smoothed: Dict[int, List[float]] = {}
    ema_cx: Optional[float] = None
    ema_cy: Optional[float] = None
    ema_w: Optional[float] = None
    ema_h: Optional[float] = None
    for f in sorted(dense.keys()):
        x, y, w, h = dense[f]
        cx, cy = x + w / 2, y + h / 2
        if ema_cx is None:
            ema_cx, ema_cy, ema_w, ema_h = cx, cy, w, h
        else:
            ema_cx = smooth_alpha * cx + (1 - smooth_alpha) * ema_cx
            ema_cy = smooth_alpha * cy + (1 - smooth_alpha) * ema_cy
            ema_w = smooth_alpha * w + (1 - smooth_alpha) * ema_w
            ema_h = smooth_alpha * h + (1 - smooth_alpha) * ema_h
        smoothed[f] = [ema_cx - ema_w / 2, ema_cy - ema_h / 2, ema_w, ema_h]

    return smoothed


def render_cropped_for_cluster(
    video_in: str,
    video_out: str,
    smoothed_path: Dict[int, List[float]],
    crop_size: Tuple[int, int] = (1280, 720),
    min_crop_w: int = 480,
    min_crop_h: int = 270,
    deadzone_ratio: float = 0.25,
) -> dict:
    """Write a follow-cam MP4 centred on the smoothed cluster path.

    The crop window has fixed size ``crop_size`` (clamped to the source
    video size) and follows the smoothed bbox centre with a dead-zone
    of ``deadzone_ratio`` of the crop dimensions — so the camera only
    pans when the subject actually moves out of the centre region,
    avoiding micro-jitter.

    Frames outside ``smoothed_path``'s coverage hold the last seen
    centre. Output video has the same length and FPS as the source.
    """
    cap = cv2.VideoCapture(video_in)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_in}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    out_w, out_h = crop_size
    out_w = max(min_crop_w, min(out_w, src_w))
    out_h = max(min_crop_h, min(out_h, src_h))

    Path(video_out).parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_out, fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open VideoWriter for {video_out}")

    # Initial centre: first known bbox if we have one, else frame centre.
    sorted_frames = sorted(smoothed_path.keys())
    if sorted_frames:
        b0 = smoothed_path[sorted_frames[0]]
        cam_cx = b0[0] + b0[2] / 2
        cam_cy = b0[1] + b0[3] / 2
    else:
        cam_cx, cam_cy = src_w / 2, src_h / 2

    dz_x = out_w * deadzone_ratio / 2
    dz_y = out_h * deadzone_ratio / 2

    frame_idx = 0
    frames_with_bbox = 0
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        bbox = smoothed_path.get(frame_idx)
        if bbox is not None:
            target_cx = bbox[0] + bbox[2] / 2
            target_cy = bbox[1] + bbox[3] / 2
            # Dead-zone: only move the camera if the subject left the
            # centre rectangle of the current crop window.
            if target_cx - cam_cx > dz_x:
                cam_cx = target_cx - dz_x
            elif cam_cx - target_cx > dz_x:
                cam_cx = target_cx + dz_x
            if target_cy - cam_cy > dz_y:
                cam_cy = target_cy - dz_y
            elif cam_cy - target_cy > dz_y:
                cam_cy = target_cy + dz_y
            frames_with_bbox += 1

        x1 = int(round(cam_cx - out_w / 2))
        y1 = int(round(cam_cy - out_h / 2))
        x1 = max(0, min(x1, src_w - out_w))
        y1 = max(0, min(y1, src_h - out_h))
        cropped = frame[y1:y1 + out_h, x1:x1 + out_w]
        if cropped.shape[:2] != (out_h, out_w):
            cropped = cv2.resize(cropped, (out_w, out_h))
        writer.write(cropped)
        frame_idx += 1

    cap.release()
    writer.release()

    return {
        "output_path": video_out,
        "frames_total": frame_idx,
        "frames_with_bbox": frames_with_bbox,
        "fps": fps,
        "out_w": out_w,
        "out_h": out_h,
    }


def find_cluster_for_bbox(
    video_path: str,
    target_t: float,
    target_bbox: List[float],
    centroids: np.ndarray,
) -> Tuple[int, float]:
    """Embed a user-clicked bbox crop and return (best_cluster_id, similarity).

    For the "click a bbox on the picker frame" selection flow:
      1. Frontend captures a frame and a clicked bbox.
      2. We embed that single crop with the same OSNet used for clustering.
      3. Return the cluster whose centroid has the highest cosine
         similarity to the embedding.
    """
    from embedder import _crop_bbox, embed_crops

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    target_frame = int(round(target_t * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame at t={target_t}")

    crop = _crop_bbox(frame, target_bbox)
    if crop is None:
        raise RuntimeError("bbox too small or off-frame")

    feats = embed_crops([crop])  # (1, 512), L2-normalized
    sims = feats @ centroids.T   # (1, K)
    best_cid = int(sims.argmax(axis=1)[0])
    best_sim = float(sims[0, best_cid])
    return best_cid, best_sim
