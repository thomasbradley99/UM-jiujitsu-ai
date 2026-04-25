"""Full-video tracking with YOLO + BoT-SORT + ReID.

Four entry points:
  - track_video()           -> JSON bbox samples for ONE chosen track
  - render_tracked_video()  -> annotated MP4 for ONE chosen track
  - track_all_video()       -> JSON summary + samples for EVERY track
  - render_all_tracks_video()-> annotated MP4 with every track in its own color

All share the same internal pipeline:
  1. Run model.track() once over the whole video, collect every
     (frame_idx, track_id, bbox, conf) tuple.
  2. (single-target only) Resolve the user's clicked bbox to one track_id.
  3. Either downsample to JSON or rasterise an annotated video.
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, TypedDict

import cv2
import numpy as np

from detector import DEFAULT_WEIGHTS, PERSON_CLASS_ID, get_model

TRACKER_CONFIG = str(Path(__file__).parent / "botsort_reid.yaml")

# (frame_idx, track_id, bbox=[x, y, w, h], conf)
PerFrame = Dict[int, List[Tuple[int, List[float], float]]]


class Sample(TypedDict):
    t: float
    bbox: List[float]
    conf: float


class TrackResult(TypedDict):
    track_id: int
    samples: List[Sample]
    video_duration: float
    fps: float


def _video_meta(video_path: str) -> Tuple[float, float, int, int]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration = frame_count / fps if fps else 0.0
    return fps, duration, width, height


def _iou_xywh(a: List[float], b: List[float]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _run_tracking(video_path: str, weights: str = DEFAULT_WEIGHTS) -> PerFrame:
    """Run YOLO + BoT-SORT(+ReID) over the entire video."""
    model = get_model(weights)
    results = model.track(
        source=video_path,
        tracker=TRACKER_CONFIG,
        classes=[PERSON_CLASS_ID],
        conf=0.4,
        persist=False,
        stream=True,
        verbose=False,
    )

    per_frame: PerFrame = {}
    for frame_idx, r in enumerate(results):
        if r.boxes is None or r.boxes.id is None:
            continue
        ids = r.boxes.id.int().tolist()
        xyxys = r.boxes.xyxy.tolist()
        confs = r.boxes.conf.tolist()
        rows: List[Tuple[int, List[float], float]] = []
        for tid, (x1, y1, x2, y2), c in zip(ids, xyxys, confs):
            rows.append(
                (int(tid), [float(x1), float(y1), float(x2 - x1), float(y2 - y1)], float(c))
            )
        per_frame[frame_idx] = rows

    if not per_frame:
        raise RuntimeError("No tracks produced — is the video readable / has people in it?")
    return per_frame


def _resolve_track_id(
    per_frame: PerFrame,
    target_bbox: List[float],
    target_t: float,
    fps: float,
) -> int:
    """Pick the track_id whose bbox at ~target_t overlaps best with target_bbox."""
    target_frame = int(round(target_t * fps))
    candidate_frames = sorted(per_frame.keys(), key=lambda f: abs(f - target_frame))

    chosen_id: Optional[int] = None
    best_iou = 0.0
    for f in candidate_frames[:5]:
        for tid, bbox, _ in per_frame[f]:
            iou = _iou_xywh(bbox, target_bbox)
            if iou > best_iou:
                best_iou = iou
                chosen_id = tid
        if chosen_id is not None and best_iou > 0.3:
            break

    if chosen_id is None:
        # Fallback: pick whichever track is closest by bbox center
        ref = per_frame.get(target_frame) or per_frame[candidate_frames[0]]
        tx = target_bbox[0] + target_bbox[2] / 2
        ty = target_bbox[1] + target_bbox[3] / 2

        def center_dist(row: Tuple[int, List[float], float]) -> float:
            _, b, _ = row
            cx = b[0] + b[2] / 2
            cy = b[1] + b[3] / 2
            return (cx - tx) ** 2 + (cy - ty) ** 2

        chosen_id = min(ref, key=center_dist)[0]

    return chosen_id


def _bbox_by_frame(per_frame: PerFrame, track_id: int) -> Dict[int, List[float]]:
    out: Dict[int, List[float]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, _ in rows:
            if tid == track_id:
                out[f] = bbox
                break
    return out


def _interpolate_bbox(
    bbox_by_frame: Dict[int, List[float]],
    sorted_frames: List[int],
    frame_idx: int,
    max_gap: int = 30,
) -> Optional[List[float]]:
    """Linear-interpolate bbox at frame_idx between nearest sampled frames.

    Returns None if the nearest sample is more than max_gap frames away
    (track was lost — better to draw nothing than a stale box).
    """
    if not sorted_frames:
        return None
    if frame_idx in bbox_by_frame:
        return bbox_by_frame[frame_idx]
    if frame_idx <= sorted_frames[0]:
        return bbox_by_frame[sorted_frames[0]] if sorted_frames[0] - frame_idx <= max_gap else None
    if frame_idx >= sorted_frames[-1]:
        return bbox_by_frame[sorted_frames[-1]] if frame_idx - sorted_frames[-1] <= max_gap else None
    pos = bisect.bisect_left(sorted_frames, frame_idx)
    f0 = sorted_frames[pos - 1]
    f1 = sorted_frames[pos]
    if min(frame_idx - f0, f1 - frame_idx) > max_gap:
        return None
    t = (frame_idx - f0) / (f1 - f0) if f1 != f0 else 0.0
    b0 = bbox_by_frame[f0]
    b1 = bbox_by_frame[f1]
    return [b0[i] + t * (b1[i] - b0[i]) for i in range(4)]


def track_video(
    video_path: str,
    target_bbox: List[float],
    target_t: float,
    sample_fps: float = 8.0,
    weights: str = DEFAULT_WEIGHTS,
) -> TrackResult:
    """Return downsampled bbox samples for the chosen fighter (JSON-friendly)."""
    fps, duration, _, _ = _video_meta(video_path)
    per_frame = _run_tracking(video_path, weights)
    chosen_id = _resolve_track_id(per_frame, target_bbox, target_t, fps)

    stride = max(1, int(round(fps / sample_fps)))
    samples: List[Sample] = []
    for f in sorted(per_frame.keys()):
        if f % stride != 0:
            continue
        for tid, bbox, conf in per_frame[f]:
            if tid == chosen_id:
                samples.append({"t": f / fps, "bbox": bbox, "conf": conf})
                break

    return {
        "track_id": chosen_id,
        "samples": samples,
        "video_duration": duration,
        "fps": fps,
    }


RenderMode = Literal["box", "crop"]


def render_tracked_video(
    video_in: str,
    video_out: str,
    target_bbox: List[float],
    target_t: float,
    mode: RenderMode = "box",
    crop_size: Tuple[int, int] = (1280, 720),
    smooth_alpha: float = 0.18,
    weights: str = DEFAULT_WEIGHTS,
) -> dict:
    """Render an annotated MP4 of the chosen fighter.

    mode='box':  original video, green bbox + label drawn on chosen fighter
                 every frame. Other people untouched.
    mode='crop': follow-cam — output is a fixed-size window centred on the
                 chosen fighter, EMA-smoothed so it doesn't jitter.
    """
    fps, duration, width, height = _video_meta(video_in)
    per_frame = _run_tracking(video_in, weights)
    chosen_id = _resolve_track_id(per_frame, target_bbox, target_t, fps)
    bbox_by_frame = _bbox_by_frame(per_frame, chosen_id)
    sorted_frames = sorted(bbox_by_frame.keys())

    cap = cv2.VideoCapture(video_in)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    if mode == "crop":
        out_w, out_h = crop_size
        # Clamp crop to source size
        out_w = min(out_w, width)
        out_h = min(out_h, height)
        writer = cv2.VideoWriter(video_out, fourcc, fps, (out_w, out_h))
    else:
        writer = cv2.VideoWriter(video_out, fourcc, fps, (width, height))

    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open VideoWriter for {video_out}")

    smoothed_cx: Optional[float] = None
    smoothed_cy: Optional[float] = None
    frames_written = 0
    frames_with_bbox = 0

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        bbox = _interpolate_bbox(bbox_by_frame, sorted_frames, frame_idx)

        if mode == "box":
            if bbox is not None:
                x, y, w, h = bbox
                p1 = (int(x), int(y))
                p2 = (int(x + w), int(y + h))
                cv2.rectangle(frame, p1, p2, (0, 255, 0), 3)
                label = f"Fighter {chosen_id}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(frame, (p1[0], p1[1] - th - 10),
                              (p1[0] + tw + 8, p1[1]), (0, 255, 0), -1)
                cv2.putText(frame, label, (p1[0] + 4, p1[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
                frames_with_bbox += 1
            writer.write(frame)
            frames_written += 1

        else:  # crop
            if bbox is not None:
                cx = bbox[0] + bbox[2] / 2
                cy = bbox[1] + bbox[3] / 2
                if smoothed_cx is None:
                    smoothed_cx, smoothed_cy = cx, cy
                else:
                    smoothed_cx = smooth_alpha * cx + (1 - smooth_alpha) * smoothed_cx
                    smoothed_cy = smooth_alpha * cy + (1 - smooth_alpha) * smoothed_cy
                frames_with_bbox += 1

            if smoothed_cx is None:
                # No bbox seen yet — emit a centre crop placeholder so the
                # output frame count stays in sync with the source.
                cx_src, cy_src = width / 2, height / 2
            else:
                cx_src, cy_src = smoothed_cx, smoothed_cy

            x1 = int(cx_src - out_w / 2)
            y1 = int(cy_src - out_h / 2)
            x1 = max(0, min(x1, width - out_w))
            y1 = max(0, min(y1, height - out_h))
            cropped = frame[y1:y1 + out_h, x1:x1 + out_w]
            if cropped.shape[:2] != (out_h, out_w):
                cropped = cv2.resize(cropped, (out_w, out_h))
            writer.write(cropped)
            frames_written += 1

        frame_idx += 1

    cap.release()
    writer.release()

    return {
        "track_id": chosen_id,
        "frames_written": frames_written,
        "frames_with_bbox": frames_with_bbox,
        "video_duration": duration,
        "fps": fps,
        "output_path": video_out,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# "Show me everyone" mode
# ---------------------------------------------------------------------------


# Distinct, high-contrast BGR colors. Picked to read clearly on dark mats /
# bright canvas. Indexed by (track_id - 1) % len(...).
_TRACK_COLORS: List[Tuple[int, int, int]] = [
    (0, 255, 0),     # green
    (0, 165, 255),   # orange
    (255, 0, 255),   # magenta
    (0, 255, 255),   # yellow
    (255, 255, 0),   # cyan
    (255, 0, 0),     # blue
    (0, 0, 255),     # red
    (203, 192, 255), # pink
    (128, 0, 128),   # purple
    (0, 128, 128),   # teal
    (255, 128, 0),   # azure
    (128, 255, 0),   # spring green
]


def _color_for(track_id: int) -> Tuple[int, int, int]:
    return _TRACK_COLORS[(track_id - 1) % len(_TRACK_COLORS)]


class TrackSummary(TypedDict):
    track_id: int
    first_t: float
    last_t: float
    duration: float
    frame_count: int
    coverage: float            # frame_count / total_frames in track range
    avg_conf: float
    samples: List[Sample]


def _summarize_per_frame(per_frame: PerFrame, fps: float, duration: float, sample_fps: float) -> dict:
    """Pivot raw per-frame tracker output into a per-track summary + samples."""
    rows_by_track: Dict[int, List[Tuple[int, List[float], float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, conf in rows:
            rows_by_track.setdefault(tid, []).append((f, bbox, conf))

    stride = max(1, int(round(fps / sample_fps)))
    summaries: List[TrackSummary] = []
    for tid, rows in rows_by_track.items():
        rows.sort(key=lambda r: r[0])
        first_f, _, _ = rows[0]
        last_f, _, _ = rows[-1]
        avg_conf = sum(c for _, _, c in rows) / len(rows) if rows else 0.0
        samples: List[Sample] = [
            {"t": f / fps, "bbox": bbox, "conf": conf}
            for f, bbox, conf in rows
            if f % stride == 0
        ]
        span = max(1, last_f - first_f + 1)
        summaries.append(
            {
                "track_id": tid,
                "first_t": first_f / fps,
                "last_t": last_f / fps,
                "duration": (last_f - first_f) / fps,
                "frame_count": len(rows),
                "coverage": len(rows) / span,
                "avg_conf": avg_conf,
                "samples": samples,
            }
        )

    summaries.sort(key=lambda s: s["frame_count"], reverse=True)
    return {
        "tracks": summaries,
        "track_count": len(summaries),
        "video_duration": duration,
        "fps": fps,
    }


def track_all_video(
    video_path: str,
    sample_fps: float = 8.0,
    weights: str = DEFAULT_WEIGHTS,
) -> dict:
    """Return summary + downsampled samples for *every* tracked person.

    Use this to answer "who did the tracker see?" without picking anyone.
    """
    fps, duration, _, _ = _video_meta(video_path)
    per_frame = _run_tracking(video_path, weights)
    return _summarize_per_frame(per_frame, fps, duration, sample_fps)


def embed_tracks(
    video_path: str,
    per_frame: PerFrame,
    samples_per_track: int = 8,
    min_bbox_area: int = 64 * 64,
    verbose: bool = True,
) -> Dict[int, np.ndarray]:
    """For each track_id, sample N frames and return the mean ReID embedding.

    Reads the video sequentially (no random seeks) for fast crop extraction
    even on H.264 sources where seeking can re-decode whole GOPs.
    """
    from embedder import _crop_bbox, embed_crops

    # Pivot per_frame -> {track_id: [(frame_idx, bbox), ...]}, sorted by frame.
    rows_by_track: Dict[int, List[Tuple[int, List[float]]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, _ in rows:
            if bbox[2] * bbox[3] < min_bbox_area:
                continue
            rows_by_track.setdefault(tid, []).append((f, bbox))
    for rows in rows_by_track.values():
        rows.sort(key=lambda r: r[0])

    # Choose which (frame_idx, track_id, bbox) tuples to embed.
    wanted: Dict[int, List[Tuple[int, List[float]]]] = {}  # frame_idx -> [(tid, bbox), ...]
    for tid, rows in rows_by_track.items():
        n = len(rows)
        if n == 0:
            continue
        k = min(samples_per_track, n)
        indices = [int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)] if k > 1 else [0]
        for i in indices:
            f, bbox = rows[i]
            wanted.setdefault(f, []).append((tid, bbox))

    if not wanted:
        return {}

    target_frames = set(wanted.keys())
    last_target = max(target_frames)

    # Sequential read — much faster than cap.set(POS_FRAMES, ...) per frame.
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    crops_by_track: Dict[int, List[np.ndarray]] = {}
    frame_idx = 0
    while frame_idx <= last_target:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if frame_idx in target_frames:
            for tid, bbox in wanted[frame_idx]:
                crop = _crop_bbox(frame, bbox)
                if crop is not None:
                    crops_by_track.setdefault(tid, []).append(crop)
        frame_idx += 1
    cap.release()

    # Flatten for one batched embedding call.
    all_crops: List[np.ndarray] = []
    spans: List[Tuple[int, int, int]] = []  # (track_id, start, end)
    cursor = 0
    for tid, crops in crops_by_track.items():
        if not crops:
            continue
        spans.append((tid, cursor, cursor + len(crops)))
        all_crops.extend(crops)
        cursor += len(crops)

    if not all_crops:
        return {}

    if verbose:
        print(f"      embed_tracks: {len(all_crops)} crops across {len(spans)} tracks")
    feats = embed_crops(all_crops)

    centroids: Dict[int, np.ndarray] = {}
    for tid, start, end in spans:
        block = feats[start:end]
        if block.shape[0] == 0:
            continue
        c = block.mean(axis=0)
        n = float(np.linalg.norm(c))
        centroids[tid] = (c / n).astype(np.float32) if n > 1e-9 else c.astype(np.float32)
    return centroids


def revalidate_per_box(
    video_path: str,
    per_frame: PerFrame,
    centroids: Dict[int, np.ndarray],
    margin: float = 0.15,
    min_box_area: int = 64 * 64,
    min_centroid_sim: float = 0.5,
    verbose: bool = True,
) -> Tuple[PerFrame, dict]:
    """Re-check every per-frame box against the centroid bank and reassign
    when a different identity is a clearly better match.

    Same algorithm as before but reads the video SEQUENTIALLY (no random
    seeking) and chunks the embedding work into 64-crop batches with
    progress prints.
    """
    from embedder import _crop_bbox, embed_crops

    if not centroids:
        return per_frame, {"reassignments": 0, "boxes_checked": 0, "boxes_embedded": 0}

    centroid_ids = sorted(centroids.keys())
    centroid_matrix = np.stack([centroids[tid] for tid in centroid_ids])  # (K, 512)
    centroid_id_to_k = {tid: k for k, tid in enumerate(centroid_ids)}

    # Sequential video pass — collect all crops we want to embed.
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    crops: List[np.ndarray] = []
    crop_meta: List[Tuple[int, int, int]] = []  # (frame, idx_in_row, current_tid)
    boxes_checked = 0
    frame_idx = 0
    last_frame_in_data = max(per_frame.keys()) if per_frame else -1

    while frame_idx <= last_frame_in_data:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        rows = per_frame.get(frame_idx)
        if rows:
            for i, (tid, bbox, _) in enumerate(rows):
                if tid not in centroids:
                    continue
                if bbox[2] * bbox[3] < min_box_area:
                    continue
                boxes_checked += 1
                crop = _crop_bbox(frame, bbox)
                if crop is None:
                    continue
                crops.append(crop)
                crop_meta.append((frame_idx, i, tid))
        frame_idx += 1
    cap.release()

    if not crops:
        return per_frame, {
            "reassignments": 0,
            "boxes_checked": boxes_checked,
            "boxes_embedded": 0,
        }

    if verbose:
        print(f"      revalidate: embedding {len(crops)} boxes ...")

    def _progress(done: int, total: int) -> None:
        if not verbose:
            return
        if done == total or done % 256 == 0:
            print(f"        embed {done}/{total}")

    feats = embed_crops(crops, on_progress=_progress)  # (M, 512), L2-normalized
    sims = feats @ centroid_matrix.T  # (M, K)

    # Mutate a shallow copy of per_frame (keep original immutable).
    reassignments = 0
    flips_per_pair: Dict[Tuple[int, int], int] = {}
    new_per_frame: PerFrame = {f: list(rows) for f, rows in per_frame.items()}

    for box_idx, (f, i, current_tid) in enumerate(crop_meta):
        sims_row = sims[box_idx]
        current_k = centroid_id_to_k[current_tid]
        current_sim = float(sims_row[current_k])
        best_k = int(sims_row.argmax())
        best_sim = float(sims_row[best_k])
        best_tid = centroid_ids[best_k]
        if best_tid == current_tid:
            continue
        if best_sim < min_centroid_sim:
            continue
        if best_sim - current_sim < margin:
            continue
        bbox, conf = new_per_frame[f][i][1], new_per_frame[f][i][2]
        new_per_frame[f][i] = (best_tid, bbox, conf)
        reassignments += 1
        flips_per_pair[(current_tid, best_tid)] = flips_per_pair.get((current_tid, best_tid), 0) + 1

    # Per-frame dedupe: reassignment can create two boxes sharing one tid
    # in the same frame; keep the higher-confidence one.
    dedupe_drops = 0
    for f, rows in new_per_frame.items():
        seen: Dict[int, Tuple[int, List[float], float]] = {}
        for idx, (tid, bbox, conf) in enumerate(rows):
            existing = seen.get(tid)
            if existing is None or conf > existing[2]:
                seen[tid] = (idx, bbox, conf)
        if len(seen) != len(rows):
            new_per_frame[f] = [(tid, bbox, conf) for tid, (_, bbox, conf) in seen.items()]
            dedupe_drops += len(rows) - len(seen)

    return new_per_frame, {
        "reassignments": reassignments,
        "boxes_checked": boxes_checked,
        "boxes_embedded": len(crops),
        "flips_per_pair": flips_per_pair,
        "dedupe_drops": dedupe_drops,
    }


def merge_tracks_with_embeddings(
    per_frame: PerFrame,
    centroids: Dict[int, np.ndarray],
    cos_thresh: float = 0.7,
    max_gap_frames: int = 300,
    max_dist_px: float = 600.0,
    min_size_ratio: float = 0.4,
) -> Tuple[PerFrame, Dict[int, int]]:
    """Like merge_tracks(), but the deciding signal is appearance similarity
    (cosine) between per-track centroid embeddings.

    Geometric checks remain as a safety net — two visually similar people
    standing in opposite corners shouldn't merge. But the gates are
    intentionally loose (max_gap=10s, max_dist=600px) because a strong
    embedding match should be enough to bridge longer occlusions than the
    pure-geometric merge could handle.
    """
    # Same edge-table prep as merge_tracks().
    rows_by_track: Dict[int, List[Tuple[int, List[float], float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, conf in rows:
            rows_by_track.setdefault(tid, []).append((f, bbox, conf))
    for rows in rows_by_track.values():
        rows.sort(key=lambda r: r[0])

    edges: Dict[int, Tuple[int, int, List[float], List[float]]] = {}
    for tid, rows in rows_by_track.items():
        first_f, first_bbox, _ = rows[0]
        last_f, last_bbox, _ = rows[-1]
        edges[tid] = (first_f, last_f, first_bbox, last_bbox)

    canonical: Dict[int, int] = {tid: tid for tid in rows_by_track}

    def root(tid: int) -> int:
        while canonical[tid] != tid:
            canonical[tid] = canonical[canonical[tid]]
            tid = canonical[tid]
        return tid

    by_death = sorted(rows_by_track.keys(), key=lambda t: edges[t][1])
    consumed: set[int] = set()

    for tail_tid in by_death:
        tail_root = root(tail_tid)
        _, tail_last, _, tail_last_bbox = edges[tail_tid]
        tail_cx, tail_cy = _bbox_center(tail_last_bbox)
        tail_emb = centroids.get(tail_tid)
        if tail_emb is None:
            continue  # no embedding for this track, can't appearance-merge

        best_head: Optional[int] = None
        best_score = -1.0  # higher = better (cosine sim)
        for head_tid in rows_by_track:
            if head_tid == tail_tid or head_tid in consumed:
                continue
            head_root = root(head_tid)
            if head_root == tail_root:
                continue
            head_first, _, head_first_bbox, _ = edges[head_tid]
            gap = head_first - tail_last
            if gap < 1 or gap > max_gap_frames:
                continue
            if _size_ratio(tail_last_bbox, head_first_bbox) < min_size_ratio:
                continue
            head_cx, head_cy = _bbox_center(head_first_bbox)
            dist = ((tail_cx - head_cx) ** 2 + (tail_cy - head_cy) ** 2) ** 0.5
            if dist > max_dist_px:
                continue
            head_emb = centroids.get(head_tid)
            if head_emb is None:
                continue
            sim = float(np.dot(tail_emb, head_emb))
            if sim < cos_thresh:
                continue
            if sim > best_score:
                best_score = sim
                best_head = head_tid

        if best_head is not None:
            canonical[best_head] = tail_root
            consumed.add(best_head)

    final_mapping: Dict[int, int] = {tid: root(tid) for tid in rows_by_track}

    merged_per_frame: PerFrame = {}
    for f, rows in per_frame.items():
        seen: Dict[int, Tuple[List[float], float]] = {}
        for tid, bbox, conf in rows:
            cid = final_mapping[tid]
            if cid in seen and seen[cid][1] >= conf:
                continue
            seen[cid] = (bbox, conf)
        merged_per_frame[f] = [(cid, bbox, conf) for cid, (bbox, conf) in seen.items()]

    return merged_per_frame, final_mapping


def _bbox_center(bbox: List[float]) -> Tuple[float, float]:
    return bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2


def _size_ratio(a: List[float], b: List[float]) -> float:
    """Return min/max area ratio in [0, 1]. 1.0 = identical sized boxes."""
    area_a = max(1.0, a[2] * a[3])
    area_b = max(1.0, b[2] * b[3])
    return min(area_a, area_b) / max(area_a, area_b)


def merge_tracks(
    per_frame: PerFrame,
    max_gap_frames: int = 60,
    max_dist_px: float = 200.0,
    min_size_ratio: float = 0.5,
) -> Tuple[PerFrame, Dict[int, int]]:
    """Stitch ID-switched track fragments back into single tracks.

    Greedy: walk tracks in order of when they die. For each dying track,
    look for a NEW track that was born within ``max_gap_frames`` whose
    first bbox is close (by center distance or IoU) and similarly sized.
    If we find one, alias B -> A.

    Returns:
      merged_per_frame: same shape as per_frame but with B's track_id rewritten to A's
      mapping: { original_track_id -> canonical_track_id }
    """
    # Aggregate per-track first/last frame and edge bboxes.
    rows_by_track: Dict[int, List[Tuple[int, List[float], float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, conf in rows:
            rows_by_track.setdefault(tid, []).append((f, bbox, conf))
    for rows in rows_by_track.values():
        rows.sort(key=lambda r: r[0])

    edges: Dict[int, Tuple[int, int, List[float], List[float]]] = {}
    for tid, rows in rows_by_track.items():
        first_f, first_bbox, _ = rows[0]
        last_f, last_bbox, _ = rows[-1]
        edges[tid] = (first_f, last_f, first_bbox, last_bbox)

    # Mapping from any track_id to its canonical (= the earliest in its merged chain).
    canonical: Dict[int, int] = {tid: tid for tid in rows_by_track}

    def root(tid: int) -> int:
        # Path-compress so chained merges (A<-B<-C) resolve to A.
        while canonical[tid] != tid:
            canonical[tid] = canonical[canonical[tid]]
            tid = canonical[tid]
        return tid

    # Walk tracks in order of when they die. Each can be the "tail" we extend.
    by_death = sorted(rows_by_track.keys(), key=lambda t: edges[t][1])
    consumed: set[int] = set()  # track_ids already attached as a "head" to someone

    for tail_tid in by_death:
        tail_root = root(tail_tid)
        _, tail_last, _, tail_last_bbox = edges[tail_tid]
        tail_cx, tail_cy = _bbox_center(tail_last_bbox)

        best_head: Optional[int] = None
        best_score = float("inf")  # smaller is better (it's a distance)
        for head_tid in rows_by_track:
            if head_tid == tail_tid or head_tid in consumed:
                continue
            head_root = root(head_tid)
            if head_root == tail_root:
                continue  # already merged
            head_first, _, head_first_bbox, _ = edges[head_tid]
            gap = head_first - tail_last
            if gap < 1 or gap > max_gap_frames:
                continue
            if _size_ratio(tail_last_bbox, head_first_bbox) < min_size_ratio:
                continue
            iou = _iou_xywh(tail_last_bbox, head_first_bbox)
            head_cx, head_cy = _bbox_center(head_first_bbox)
            dist = ((tail_cx - head_cx) ** 2 + (tail_cy - head_cy) ** 2) ** 0.5
            if iou < 0.1 and dist > max_dist_px:
                continue
            # Score: prefer high IoU and small distance and small gap.
            # Negative IoU keeps high-IoU first; gap acts as tiebreaker.
            score = dist * (1 - iou) + gap * 2.0
            if score < best_score:
                best_score = score
                best_head = head_tid

        if best_head is not None:
            canonical[best_head] = tail_root
            consumed.add(best_head)

    # Resolve mapping fully.
    final_mapping: Dict[int, int] = {tid: root(tid) for tid in rows_by_track}

    # Rewrite per_frame with canonical IDs. If multiple sources collapse to
    # the same canonical id at the same frame (shouldn't happen if the
    # tracks really were the same person), keep the higher-confidence one.
    merged_per_frame: PerFrame = {}
    for f, rows in per_frame.items():
        seen: Dict[int, Tuple[List[float], float]] = {}
        for tid, bbox, conf in rows:
            cid = final_mapping[tid]
            if cid in seen and seen[cid][1] >= conf:
                continue
            seen[cid] = (bbox, conf)
        merged_per_frame[f] = [(cid, bbox, conf) for cid, (bbox, conf) in seen.items()]

    return merged_per_frame, final_mapping


def find_grappling_pair(per_frame: PerFrame, min_frames: int = 10) -> Optional[Tuple[int, int]]:
    """Return the two track_ids whose bboxes overlap most over the video.

    For BJJ/wrestling/MMA, the actively engaged pair spends most of the
    fight in physical contact, so their bboxes overlap heavily. Other
    people in the gym (coaches, spectators, other rolling pairs) won't
    have that signature with this specific pair.

    Returns None if there aren't at least two tracks above min_frames.
    """
    rows_by_track: Dict[int, List[Tuple[int, List[float], float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, conf in rows:
            rows_by_track.setdefault(tid, []).append((f, bbox, conf))

    eligible = [tid for tid, rows in rows_by_track.items() if len(rows) >= min_frames]
    if len(eligible) < 2:
        return None

    bbox_at: Dict[int, Dict[int, List[float]]] = {
        tid: {f: bbox for f, bbox, _ in rows_by_track[tid]} for tid in eligible
    }

    best_pair: Optional[Tuple[int, int]] = None
    best_score = -1.0
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            a, b = eligible[i], eligible[j]
            shared_frames = set(bbox_at[a].keys()) & set(bbox_at[b].keys())
            if len(shared_frames) < min_frames:
                continue
            ious = [_iou_xywh(bbox_at[a][f], bbox_at[b][f]) for f in shared_frames]
            mean_iou = sum(ious) / len(ious)
            # Reward pairs that are co-present often AND tightly overlapping.
            score = mean_iou * (len(shared_frames) ** 0.5)
            if score > best_score:
                best_score = score
                best_pair = (a, b)
    return best_pair


def render_and_summarize_all(
    video_in: str,
    video_out: str,
    weights: str = DEFAULT_WEIGHTS,
    min_frames: int = 0,
    sample_fps: float = 8.0,
    only_ids: Optional[List[int]] = None,
    auto_pair: bool = False,
    highlight_ids: Optional[List[int]] = None,
    merge: bool = False,
    merge_max_gap_s: float = 2.0,
    merge_max_dist_px: float = 200.0,
    merge_by: Literal["geometry", "appearance"] = "geometry",
    appearance_cos_thresh: float = 0.7,
    revalidate: bool = False,
    revalidate_margin: float = 0.15,
) -> dict:
    """One-pass: run tracking ONCE, then render the MP4 and build the
    per-track JSON summary.

    only_ids:      if set, only these track_ids are rendered (others omitted).
    auto_pair:     if True (and only_ids is None), automatically select the
                   pair of tracks with the highest bbox overlap over time
                   (the "grappling pair") and render only those two.
    highlight_ids: render these tracks with thicker boxes + bigger labels.
                   Defaults to whatever survived only_ids / auto_pair, so the
                   "chosen" people stand out from the background tracks.
    merge:         post-process per_frame with merge_tracks() to stitch
                   ID-switched fragments into single canonical tracks.
                   Useful when grapplers' bboxes overlap and BoT-SORT swaps IDs.
    """
    fps, duration, width, height = _video_meta(video_in)
    per_frame = _run_tracking(video_in, weights)

    merge_mapping: Dict[int, int] = {}
    centroids: Dict[int, np.ndarray] = {}
    if merge:
        max_gap_frames = max(1, int(round(merge_max_gap_s * fps)))
        if merge_by == "appearance":
            # 10s window for appearance merge — embeddings can bridge
            # much longer gaps than pure geometry can.
            app_max_gap_frames = max(max_gap_frames, int(round(10.0 * fps)))
            centroids = embed_tracks(video_in, per_frame)
            per_frame, merge_mapping = merge_tracks_with_embeddings(
                per_frame,
                centroids,
                cos_thresh=appearance_cos_thresh,
                max_gap_frames=app_max_gap_frames,
                max_dist_px=max(merge_max_dist_px, 600.0),
            )
        else:
            per_frame, merge_mapping = merge_tracks(
                per_frame,
                max_gap_frames=max_gap_frames,
                max_dist_px=merge_max_dist_px,
            )

    revalidation_stats: Optional[dict] = None
    if revalidate:
        # Recompute centroids on the (possibly merged) per_frame so canonical
        # tracks have richer signals than raw BoT-SORT fragments did.
        centroids = embed_tracks(video_in, per_frame)
        per_frame, revalidation_stats = revalidate_per_box(
            video_in,
            per_frame,
            centroids,
            margin=revalidate_margin,
        )

    summary = _summarize_per_frame(per_frame, fps, duration, sample_fps)

    # Pivot for renderer
    rows_by_track: Dict[int, Dict[int, List[float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, _ in rows:
            rows_by_track.setdefault(tid, {})[f] = bbox

    if only_ids is None and auto_pair:
        pair = find_grappling_pair(per_frame, min_frames=max(min_frames, 10))
        if pair is None:
            raise RuntimeError(
                "auto_pair: could not find two co-present tracks. "
                "Try lowering min_frames or running --all to inspect first."
            )
        only_ids = list(pair)

    keep_ids = {tid for tid, frames in rows_by_track.items() if len(frames) >= min_frames}
    if only_ids is not None:
        keep_ids &= set(only_ids)
        if not keep_ids:
            raise RuntimeError(f"only_ids={only_ids} matched nothing in tracks {sorted(rows_by_track)}")

    if highlight_ids is None:
        highlight_ids = sorted(keep_ids)
    highlight_set = set(highlight_ids)

    sorted_frames_by_track = {
        tid: sorted(frames.keys()) for tid, frames in rows_by_track.items() if tid in keep_ids
    }

    cap = cv2.VideoCapture(video_in)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_out, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open VideoWriter for {video_out}")

    frames_written = 0
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        for tid in keep_ids:
            bbox = _interpolate_bbox(
                rows_by_track[tid], sorted_frames_by_track[tid], frame_idx
            )
            if bbox is None:
                continue
            is_hi = tid in highlight_set
            thickness = 5 if is_hi else 2
            scale = 1.1 if is_hi else 0.6
            font_th = 3 if is_hi else 2
            x, y, w, h = bbox
            p1, p2 = (int(x), int(y)), (int(x + w), int(y + h))
            color = _color_for(tid)
            cv2.rectangle(frame, p1, p2, color, thickness)
            label = f"FIGHTER {tid}" if is_hi else f"id {tid}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, font_th)
            cv2.rectangle(frame, (p1[0], p1[1] - th - 12),
                          (p1[0] + tw + 10, p1[1]), color, -1)
            cv2.putText(frame, label, (p1[0] + 5, p1[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), font_th)
        writer.write(frame)
        frames_written += 1
        frame_idx += 1

    cap.release()
    writer.release()

    # Compact merge mapping for output: only show tracks that actually got merged.
    merge_chains: Dict[int, List[int]] = {}
    for src, dst in merge_mapping.items():
        if src != dst:
            merge_chains.setdefault(dst, []).append(src)

    return {
        "summary": summary,
        "render": {
            "output_path": video_out,
            "frames_written": frames_written,
            "track_ids": sorted(keep_ids),
            "track_count": len(keep_ids),
            "highlight_ids": sorted(highlight_set & keep_ids),
        },
        "merge_chains": merge_chains,  # canonical_id -> [absorbed source ids]
        "revalidation": revalidation_stats,
        "fps": fps,
        "video_duration": duration,
    }


def render_all_tracks_video(
    video_in: str,
    video_out: str,
    weights: str = DEFAULT_WEIGHTS,
    min_frames: int = 0,
) -> dict:
    """Render an annotated MP4 with EVERY tracked person boxed in their own color.

    min_frames: drop tracks that appear in fewer than this many frames
                (use to silence one-frame YOLO blips). 0 = keep all.
    """
    fps, duration, width, height = _video_meta(video_in)
    per_frame = _run_tracking(video_in, weights)

    # Build per-track frame coverage so we can apply min_frames and
    # interpolate per-track gaps independently.
    rows_by_track: Dict[int, Dict[int, List[float]]] = {}
    for f, rows in per_frame.items():
        for tid, bbox, _ in rows:
            rows_by_track.setdefault(tid, {})[f] = bbox

    keep_ids = {tid for tid, frames in rows_by_track.items() if len(frames) >= min_frames}
    sorted_frames_by_track = {
        tid: sorted(frames.keys()) for tid, frames in rows_by_track.items() if tid in keep_ids
    }

    cap = cv2.VideoCapture(video_in)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_out, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open VideoWriter for {video_out}")

    frames_written = 0
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for tid in keep_ids:
            bbox = _interpolate_bbox(
                rows_by_track[tid],
                sorted_frames_by_track[tid],
                frame_idx,
            )
            if bbox is None:
                continue
            x, y, w, h = bbox
            p1 = (int(x), int(y))
            p2 = (int(x + w), int(y + h))
            color = _color_for(tid)
            cv2.rectangle(frame, p1, p2, color, 3)
            label = f"id {tid}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(
                frame,
                (p1[0], p1[1] - th - 10),
                (p1[0] + tw + 8, p1[1]),
                color,
                -1,
            )
            cv2.putText(
                frame, label, (p1[0] + 4, p1[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2,
            )

        writer.write(frame)
        frames_written += 1
        frame_idx += 1

    cap.release()
    writer.release()

    return {
        "output_path": video_out,
        "frames_written": frames_written,
        "track_ids": sorted(keep_ids),
        "track_count": len(keep_ids),
        "video_duration": duration,
        "fps": fps,
    }
