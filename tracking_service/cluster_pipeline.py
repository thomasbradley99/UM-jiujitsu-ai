"""Pure-appearance identity pipeline (no tracker).

The BoT-SORT pipeline in tracker.py keeps inventing new track_ids whenever
two people overlap, then we try to stitch them back together with merges
and revalidation. For BJJ that fails because half the video is one big
overlap, so we never get clean per-track centroids.

This module does the opposite:

  1. detect_only()         – run YOLO per-frame, throw away track_ids,
                             keep just (frame_idx, bbox, conf).
  2. embed_detections()    – sequential video read, OSNet ReID embedding
                             for every detection's crop.
  3. cluster_embeddings()  – spherical K-means over the L2-normalized
                             features. K is the number of identities the
                             user expects in the video (e.g. K=2 for the
                             grappling pair, K=5 if there are also coaches
                             watching).
  4. render_clustered()    – write an MP4 where each box is coloured by
                             its cluster_id, plus a JSON summary.

Identity is determined by appearance ALONE — there is no temporal
coherence assumption, so two people who get tangled can never swap
identities by accident. The trade-off: if two fighters look very
similar (same gi, same body type), their embeddings may overlap and
the clusterer won't be able to separate them. A purity diagnostic in
cluster_embeddings() warns when this happens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypedDict

import cv2
import numpy as np


# Reuse the colour palette from tracker.py for visual consistency.
_CLUSTER_COLORS: List[Tuple[int, int, int]] = [
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
]


def _color_for_cluster(cluster_id: int) -> Tuple[int, int, int]:
    return _CLUSTER_COLORS[cluster_id % len(_CLUSTER_COLORS)]


# A detection without any track_id — pure (frame, bbox, conf).
class Detection(TypedDict):
    frame: int
    bbox: List[float]   # [x, y, w, h]
    conf: float


def detect_only(
    video_path: str,
    weights: str = "yolov8x.pt",
    conf_threshold: float = 0.4,
    verbose: bool = True,
) -> List[Detection]:
    """Run YOLO on every frame, return all person detections (no tracker).

    Sequential read; each detection is (frame_idx, bbox=[x,y,w,h], conf).
    """
    from detector import PERSON_CLASS_ID, get_model

    model = get_model(weights)
    results = model.predict(
        source=video_path,
        classes=[PERSON_CLASS_ID],
        conf=conf_threshold,
        stream=True,
        verbose=False,
    )

    detections: List[Detection] = []
    frame_count = 0
    for frame_idx, r in enumerate(results):
        frame_count = frame_idx + 1
        if r.boxes is None or len(r.boxes) == 0:
            continue
        xyxys = r.boxes.xyxy.tolist()
        confs = r.boxes.conf.tolist()
        for (x1, y1, x2, y2), c in zip(xyxys, confs):
            detections.append(
                {
                    "frame": frame_idx,
                    "bbox": [float(x1), float(y1), float(x2 - x1), float(y2 - y1)],
                    "conf": float(c),
                }
            )

    if verbose:
        print(f"      detect_only: {len(detections)} detections across {frame_count} frames")
    return detections


def embed_detections(
    video_path: str,
    detections: List[Detection],
    min_box_area: int = 64 * 64,
    verbose: bool = True,
) -> Tuple[np.ndarray, List[int]]:
    """Sequential pass: read each frame once, crop every detection, embed.

    Returns:
      features:  (M, 512) L2-normalized float32 array
      kept_ids:  index into ``detections`` that each row of features came
                 from (skipped detections — too tiny, or off-frame —
                 don't appear here)
    """
    from embedder import _crop_bbox, embed_crops

    if not detections:
        return np.zeros((0, 512), dtype=np.float32), []

    # Group detections by frame for sequential read.
    by_frame: Dict[int, List[int]] = {}
    for i, d in enumerate(detections):
        if d["bbox"][2] * d["bbox"][3] < min_box_area:
            continue
        by_frame.setdefault(d["frame"], []).append(i)

    if not by_frame:
        return np.zeros((0, 512), dtype=np.float32), []

    last_frame = max(by_frame.keys())

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    crops: List[np.ndarray] = []
    kept_ids: List[int] = []
    frame_idx = 0
    while frame_idx <= last_frame:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        idxs = by_frame.get(frame_idx)
        if idxs:
            for i in idxs:
                crop = _crop_bbox(frame, detections[i]["bbox"])
                if crop is None:
                    continue
                crops.append(crop)
                kept_ids.append(i)
        frame_idx += 1
    cap.release()

    if not crops:
        return np.zeros((0, 512), dtype=np.float32), []

    if verbose:
        print(f"      embed_detections: embedding {len(crops)} crops ...")

    def _progress(done: int, total: int) -> None:
        if not verbose:
            return
        if done == total or done % 256 == 0:
            print(f"        embed {done}/{total}")

    feats = embed_crops(crops, on_progress=_progress)
    return feats, kept_ids


def _spherical_kmeans(
    features: np.ndarray,
    k: int,
    max_iter: int = 50,
    n_init: int = 10,
    seed: int = 0,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """Spherical K-means on L2-normalized features.

    Maximizes mean cosine similarity to the assigned centroid. Equivalent
    to standard K-means with L2 distance on unit-norm vectors (since
    ||x - c||^2 = 2 - 2 x.c when both have unit norm), but we re-normalize
    centroids each iteration so they stay on the sphere.

    Picks the best of ``n_init`` random starts by final inertia (sum of
    1 - cos_sim, lower is better).

    Returns: (labels (M,), centroids (k, D), inertia)
    """
    M, D = features.shape
    if k <= 0:
        raise ValueError("k must be >= 1")
    if M < k:
        raise ValueError(f"Need at least k={k} samples, got {M}")

    best_labels: np.ndarray = np.zeros(M, dtype=np.int32)
    best_centroids: np.ndarray = np.zeros((k, D), dtype=np.float32)
    best_inertia = float("inf")

    for run in range(n_init):
        rng = np.random.default_rng(seed + run)
        # k-means++ init in cosine space: pick first centroid randomly,
        # each subsequent centroid weighted by (1 - max_sim_so_far)^2.
        idx0 = int(rng.integers(0, M))
        centroids = np.empty((k, D), dtype=np.float32)
        centroids[0] = features[idx0]
        max_sim = features @ centroids[0]
        for ci in range(1, k):
            d = np.clip(1.0 - max_sim, 0.0, 2.0)
            probs = d ** 2
            s = probs.sum()
            if s <= 1e-12:
                pick = int(rng.integers(0, M))
            else:
                pick = int(rng.choice(M, p=probs / s))
            centroids[ci] = features[pick]
            sims = features @ centroids[ci]
            max_sim = np.maximum(max_sim, sims)

        labels = np.zeros(M, dtype=np.int32)
        for _ in range(max_iter):
            sims = features @ centroids.T  # (M, k)
            new_labels = sims.argmax(axis=1).astype(np.int32)
            if np.array_equal(new_labels, labels):
                labels = new_labels
                break
            labels = new_labels
            for ci in range(k):
                mask = labels == ci
                if not mask.any():
                    # Empty cluster: re-seed it on the worst-fit point.
                    worst = int((sims.max(axis=1)).argmin())
                    centroids[ci] = features[worst]
                    continue
                c = features[mask].mean(axis=0)
                n = float(np.linalg.norm(c))
                centroids[ci] = c / n if n > 1e-9 else c

        sims = features @ centroids.T
        inertia = float((1.0 - sims[np.arange(M), labels]).sum())
        if inertia < best_inertia:
            best_inertia = inertia
            best_labels = labels.copy()
            best_centroids = centroids.copy()

    return best_labels, best_centroids, best_inertia


def cluster_embeddings(
    features: np.ndarray,
    k: int,
    max_iter: int = 50,
    n_init: int = 10,
    verbose: bool = True,
) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Spherical K-means + cluster diagnostics.

    Returns: (labels (M,), centroids (k, 512), diagnostics)
    """
    if features.shape[0] == 0:
        return np.zeros(0, dtype=np.int32), np.zeros((k, 512), dtype=np.float32), {}

    labels, centroids, inertia = _spherical_kmeans(
        features, k=k, max_iter=max_iter, n_init=n_init
    )

    counts = np.bincount(labels, minlength=k).tolist()

    # Per-cluster mean cosine similarity to its own centroid (cohesion).
    sims = features @ centroids.T
    own_sim = sims[np.arange(features.shape[0]), labels]
    cohesion = []
    for ci in range(k):
        mask = labels == ci
        cohesion.append(float(own_sim[mask].mean()) if mask.any() else 0.0)

    # Mean similarity between centroids (separation; lower = better).
    centroid_sim = centroids @ centroids.T
    iu = np.triu_indices(k, k=1)
    mean_separation = float(centroid_sim[iu].mean()) if k > 1 else 0.0

    # Worst-case neighbour gap: for each point, sim_to_own - sim_to_best_other.
    # Negative values mean the point is closer to a different cluster's
    # centroid than its own — those are the suspicious assignments.
    second_best = sims.copy()
    second_best[np.arange(len(labels)), labels] = -np.inf
    second_sim = second_best.max(axis=1)
    margin = own_sim - second_sim
    pct_low_margin = float((margin < 0.05).mean())

    diag = {
        "k": k,
        "n_points": int(features.shape[0]),
        "counts": counts,
        "cohesion": cohesion,            # mean cos_sim to own centroid
        "mean_separation": mean_separation,  # mean cos_sim between centroids (lower = better)
        "inertia": inertia,
        "pct_low_margin": pct_low_margin,    # fraction of points within 0.05 of nearest other cluster
    }

    if verbose:
        print(f"      cluster k={k}:  counts={counts}")
        print(f"        cohesion (cos to own centroid):   {[f'{x:.3f}' for x in cohesion]}")
        print(f"        separation (cos between centroids, lower better): {mean_separation:.3f}")
        print(f"        low-margin points (< 0.05 to other): {pct_low_margin*100:.1f}%")

    return labels, centroids, diag


def assign_unique_per_frame(
    detections: List[Detection],
    kept_ids: List[int],
    features: np.ndarray,
    centroids: np.ndarray,
    verbose: bool = True,
) -> np.ndarray:
    """Reassign each frame's detections to centroids under the constraint
    that no centroid is used more than once per frame.

    Why: K-means is global — it lets two boxes in the same frame land on
    the same cluster centroid even though they're physically two different
    people. We solve the per-frame problem with the Hungarian algorithm:
    maximize the total cosine similarity of (detection -> cluster) edges
    subject to "each cluster used at most once".

    If a frame has more detections than there are centroids, the surplus
    detections (the ones with the worst fit to any free centroid) are
    labeled -1 (= "unknown", drawn dimmed in the rendered video). This is
    intentional — saying "I don't know which fighter this is" is more
    honest than randomly guessing.

    Returns a new (M,) int32 array of labels (-1 means unassigned).
    """
    from scipy.optimize import linear_sum_assignment

    M = features.shape[0]
    K = centroids.shape[0]
    new_labels = np.full(M, -1, dtype=np.int32)

    # Group rows of `features` by frame using the original detection's frame.
    rows_by_frame: Dict[int, List[int]] = {}
    for row_idx, det_idx in enumerate(kept_ids):
        f = detections[det_idx]["frame"]
        rows_by_frame.setdefault(f, []).append(row_idx)

    n_frames = 0
    n_unassigned = 0
    for f, rows in rows_by_frame.items():
        n_frames += 1
        block = features[rows]                      # (n_dets_in_frame, D)
        sims = block @ centroids.T                  # (n_dets, K)
        n_dets = sims.shape[0]
        # linear_sum_assignment minimizes cost; we want to MAXIMIZE sim,
        # so use cost = -sim. Function handles rectangular matrices: it
        # returns min(n_dets, K) pairs, each row/col used at most once.
        row_ind, col_ind = linear_sum_assignment(-sims)
        for r, c in zip(row_ind, col_ind):
            new_labels[rows[r]] = int(c)
        if n_dets > K:
            n_unassigned += n_dets - K

    if verbose:
        print(f"      assign_unique_per_frame: {n_frames} frames, "
              f"{n_unassigned} surplus detections labeled as 'unknown'")
    return new_labels


def render_clustered_video(
    video_in: str,
    video_out: str,
    detections: List[Detection],
    kept_ids: List[int],
    labels: np.ndarray,
    highlight_clusters: Optional[List[int]] = None,
    verbose: bool = True,
) -> dict:
    """Write an MP4 with each detection boxed in its cluster's colour.

    ``highlight_clusters``: if set, only those cluster ids get drawn
    (others are dimmed out). Useful for "show me just the two fighters".
    """
    # Build {frame_idx -> [(cluster_id, bbox, conf), ...]} for fast lookup.
    # cluster_id == -1 means "unknown" (per-frame uniqueness left this box
    # unmatched because there were more dets than centroids in that frame).
    by_frame: Dict[int, List[Tuple[int, List[float], float]]] = {}
    label_for_det: Dict[int, int] = {kept_ids[m]: int(labels[m]) for m in range(len(kept_ids))}
    for det_idx, det in enumerate(detections):
        cid = label_for_det.get(det_idx, -1)
        if highlight_clusters is not None and cid != -1 and cid not in highlight_clusters:
            continue
        by_frame.setdefault(det["frame"], []).append((cid, det["bbox"], det["conf"]))

    cap = cv2.VideoCapture(video_in)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_in}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    Path(video_out).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(video_out, fourcc, fps, (width, height))

    frame_idx = 0
    frames_with_box = 0
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        rows = by_frame.get(frame_idx)
        if rows:
            frames_with_box += 1
            for cid, bbox, conf in rows:
                x, y, w, h = bbox
                p1 = (int(x), int(y))
                p2 = (int(x + w), int(y + h))
                if cid < 0:
                    # Unknown: dim gray, thin outline, no text label.
                    cv2.rectangle(frame, p1, p2, (110, 110, 110), 1)
                    continue
                color = _color_for_cluster(cid)
                cv2.rectangle(frame, p1, p2, color, 3)
                label = f"id {cid}  {conf:.2f}"
                tw, th = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                cv2.rectangle(frame, (p1[0], p1[1] - th - 8), (p1[0] + tw + 8, p1[1]), color, -1)
                cv2.putText(frame, label, (p1[0] + 4, p1[1] - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        writer.write(frame)
        frame_idx += 1
    cap.release()
    writer.release()

    return {
        "output_path": video_out,
        "frames_total": frame_idx,
        "frames_with_box": frames_with_box,
        "fps": fps,
    }


def run_cluster_pipeline(
    video_in: str,
    video_out: str,
    k: int,
    weights: str = "yolov8x.pt",
    conf_threshold: float = 0.4,
    only_clusters: Optional[List[int]] = None,
    unique_per_frame: bool = True,
    verbose: bool = True,
) -> dict:
    """End-to-end: detect → embed → cluster (→ per-frame Hungarian) → render."""
    if verbose:
        print(f"      [1/5] Detecting people (weights={weights}, conf={conf_threshold}) ...")
    detections = detect_only(video_in, weights=weights,
                             conf_threshold=conf_threshold, verbose=verbose)
    if not detections:
        raise RuntimeError("No people detected — is the video readable?")

    if verbose:
        print(f"      [2/5] Embedding detections with OSNet ...")
    features, kept_ids = embed_detections(video_in, detections, verbose=verbose)
    if features.shape[0] == 0:
        raise RuntimeError("All detections were too small to embed.")

    if verbose:
        print(f"      [3/5] Clustering into k={k} identities ...")
    labels, centroids, diag = cluster_embeddings(features, k=k, verbose=verbose)

    if unique_per_frame:
        if verbose:
            print(f"      [4/5] Per-frame Hungarian assignment (unique IDs per frame) ...")
        labels = assign_unique_per_frame(detections, kept_ids, features,
                                         centroids, verbose=verbose)
    else:
        if verbose:
            print(f"      [4/5] (skipping per-frame uniqueness; raw cluster labels)")

    if verbose:
        print(f"      [5/5] Rendering clustered video ...")
    render_info = render_clustered_video(
        video_in=video_in,
        video_out=video_out,
        detections=detections,
        kept_ids=kept_ids,
        labels=labels,
        highlight_clusters=only_clusters,
        verbose=verbose,
    )

    # Per-cluster summary. -1 (unassigned) gets its own line.
    summary: List[dict] = []
    label_for_det = {kept_ids[m]: int(labels[m]) for m in range(len(kept_ids))}
    by_cluster: Dict[int, List[int]] = {}
    for det_idx, det in enumerate(detections):
        cid = label_for_det.get(det_idx)
        if cid is None:
            continue
        by_cluster.setdefault(cid, []).append(det["frame"])
    for cid in range(k):
        frames = by_cluster.get(cid, [])
        if frames:
            summary.append({
                "cluster_id": cid,
                "detections": len(frames),
                "first_frame": min(frames),
                "last_frame": max(frames),
            })
        else:
            summary.append({"cluster_id": cid, "detections": 0,
                            "first_frame": None, "last_frame": None})
    if -1 in by_cluster:
        unk = by_cluster[-1]
        summary.append({
            "cluster_id": -1,
            "detections": len(unk),
            "first_frame": min(unk),
            "last_frame": max(unk),
        })

    return {
        "render": render_info,
        "diagnostics": diag,
        "clusters": summary,
        "total_detections": len(detections),
        "embedded_detections": int(features.shape[0]),
        "unique_per_frame": unique_per_frame,
    }
