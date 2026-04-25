"""Sanity check: does OSNet actually separate the people in this video?

Two questions answered:
  1. Do crops from the SAME BoT-SORT track look similar to each other?
     (same-person similarity baseline)
  2. Do crops from DIFFERENT tracks that co-occur in time look DIFFERENT?
     (different-person similarity baseline)

If (1) clearly > (2), OSNet IS separating identities and our clustering
just isn't using it well. If (1) ~ (2), the embedding really is the
bottleneck.

Also dumps a few crops to disk so we can eyeball whether YOLO is even
giving us clean boxes per person.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import numpy as np
import cv2

from tracker import _run_tracking
from embedder import _crop_bbox, embed_crops


def main(video_path: str, weights: str = "yolov8s.pt") -> None:
    print(f"\n[1/4] Running BoT-SORT to get track IDs we trust ...")
    per_frame = _run_tracking(video_path, weights=weights)
    n_frames = len(per_frame)
    n_dets = sum(len(rows) for rows in per_frame.values())
    print(f"      {n_dets} detections across {n_frames} frames")

    # Find the longest-lived tracks (most reliable identities)
    track_frames: dict[int, list[int]] = defaultdict(list)
    for f, rows in per_frame.items():
        for tid, _, _ in rows:
            track_frames[tid].append(f)
    long_tracks = sorted(track_frames.items(), key=lambda kv: -len(kv[1]))[:6]
    print(f"      top tracks by length: " +
          ", ".join(f"id={tid}({len(fs)} frames)" for tid, fs in long_tracks))

    # Sample up to 12 crops per track, evenly spaced through its lifespan.
    print(f"\n[2/4] Sampling and embedding crops per track ...")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {video_path}")

    # Plan: {frame_idx: [(track_id, bbox), ...]}
    plan: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
    samples_per_track = 12
    for tid, frames in long_tracks:
        n = len(frames)
        idxs = [int(round(i * (n - 1) / max(1, samples_per_track - 1)))
                for i in range(samples_per_track)] if n >= 2 else [0]
        chosen_frames = sorted({frames[i] for i in idxs})
        for f in chosen_frames:
            for ftid, bbox, _ in per_frame[f]:
                if ftid == tid:
                    plan[f].append((tid, bbox))
                    break

    crops: list[np.ndarray] = []
    crop_meta: list[tuple[int, int]] = []  # (track_id, sample_idx_within_track)
    sample_counts: dict[int, int] = defaultdict(int)
    sample_dump_dir = Path("tracking_service/outputs/diag_crops")
    sample_dump_dir.mkdir(parents=True, exist_ok=True)

    last_target = max(plan.keys())
    frame_idx = 0
    while frame_idx <= last_target:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if frame_idx in plan:
            for tid, bbox in plan[frame_idx]:
                crop = _crop_bbox(frame, bbox)
                if crop is None:
                    continue
                idx_within = sample_counts[tid]
                sample_counts[tid] += 1
                crops.append(crop)
                crop_meta.append((tid, idx_within))
                # Save first 3 crops per track to disk so we can see what we embedded
                if idx_within < 3:
                    out_path = sample_dump_dir / f"track{tid}_sample{idx_within}_f{frame_idx}.jpg"
                    cv2.imwrite(str(out_path), crop)
        frame_idx += 1
    cap.release()

    print(f"      embedded crops: {len(crops)} from {len(sample_counts)} tracks")
    feats = embed_crops(crops)
    print(f"      feature shape: {feats.shape}")
    print(f"      saved sample crops to: {sample_dump_dir}/")

    # Build per-track feature blocks
    feats_by_track: dict[int, np.ndarray] = {}
    cursor = 0
    for tid in [t for t, _ in long_tracks]:
        n = sample_counts[tid]
        if n == 0:
            continue
        feats_by_track[tid] = feats[cursor:cursor + n]
        cursor += n

    print(f"\n[3/4] Same-track vs different-track cosine similarity:")
    print(f"      (high same / low diff = embeddings ARE separating identities)")
    print()

    # Same-track similarities (within each track, all unique pairs)
    same: list[float] = []
    for tid, block in feats_by_track.items():
        if block.shape[0] < 2:
            continue
        sims = block @ block.T
        iu = np.triu_indices(block.shape[0], k=1)
        same.extend(sims[iu].tolist())

    # Different-track similarities (centroid pair, then cross-block samples)
    diff: list[float] = []
    track_ids = list(feats_by_track.keys())
    centroid_table = []
    for tid in track_ids:
        c = feats_by_track[tid].mean(axis=0)
        n = float(np.linalg.norm(c))
        centroid_table.append((tid, c / n if n > 1e-9 else c))

    print(f"      Centroid x centroid cosine (across tracks):")
    print(f"      {'':>4} " + " ".join(f"{tid:>6}" for tid, _ in centroid_table))
    for tid_a, ca in centroid_table:
        row = []
        for tid_b, cb in centroid_table:
            row.append(f"{float(ca @ cb):>6.3f}")
        print(f"      {tid_a:>4} " + " ".join(row))
    print()

    for i, (tid_a, blk_a) in enumerate(feats_by_track.items()):
        for tid_b, blk_b in list(feats_by_track.items())[i + 1:]:
            sims = blk_a @ blk_b.T
            diff.extend(sims.flatten().tolist())

    same_arr = np.array(same)
    diff_arr = np.array(diff)
    print(f"      same-track  pairs: n={same_arr.size:>4}   "
          f"mean={same_arr.mean():.3f}   p10={np.percentile(same_arr, 10):.3f}   "
          f"p50={np.percentile(same_arr, 50):.3f}   p90={np.percentile(same_arr, 90):.3f}")
    print(f"      diff-track  pairs: n={diff_arr.size:>4}   "
          f"mean={diff_arr.mean():.3f}   p10={np.percentile(diff_arr, 10):.3f}   "
          f"p50={np.percentile(diff_arr, 50):.3f}   p90={np.percentile(diff_arr, 90):.3f}")
    print()

    gap = same_arr.mean() - diff_arr.mean()
    print(f"      ==> mean(same) - mean(diff) = {gap:+.3f}")
    overlap_zone = (same_arr.min(), diff_arr.max())
    print(f"      overlap zone: same.min={same_arr.min():.3f}  diff.max={diff_arr.max():.3f}")

    print(f"\n[4/4] Verdict:")
    if gap > 0.3 and same_arr.min() > diff_arr.max() - 0.05:
        print("      STRONG SEPARATION. Embeddings clearly tell people apart.")
        print("      Our K-means failure is not the embedding's fault — it's the clusterer.")
    elif gap > 0.15:
        print("      MODERATE SEPARATION. Embeddings have signal but distributions overlap.")
        print("      Pose/lighting variance within a person can exceed inter-person variance.")
        print("      Fix: prototype-anchored matching (seed each fighter from a clean frame).")
    else:
        print("      WEAK SEPARATION. Embeddings really aren't telling these people apart.")
        print("      Likely cause: similar uniforms + body shape + pose noise dominate.")
        print("      Fix: stronger primary signal — segmentation (SAM 2) or face recognition.")


if __name__ == "__main__":
    import sys
    video = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gym_first5.mp4"
    weights = sys.argv[2] if len(sys.argv) > 2 else "yolov8s.pt"
    main(video, weights)
