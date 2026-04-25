"""End-to-end CLI: cluster identities in a video, render a follow-cam crop.

Pipeline:
  1. Detect every person every frame (no tracker).
  2. Embed every detection's crop with OSNet (appearance vector).
  3. K-means cluster the embeddings into K identities.
  4. Hungarian per-frame to enforce one cluster per person per frame.
  5. Render thumbnails so the user can see who each cluster is.
  6. Optionally render the all-clusters annotated MP4 (colour-coded).
  7. Prompt for a cluster id (or take --pick).
  8. Build a smoothed bbox path for that cluster + render a follow-cam MP4.

Steps 1-4 are slow; their output is cached under ``.cache_<name>_k<K>.pkl``
so re-running with a different ``--pick`` skips straight to rendering.

Usage:
  python cluster_cli.py path/to/fight.mp4 --k 2
  python cluster_cli.py path/to/full-gym.mov --k 8 --pick 3
  python cluster_cli.py video.mp4 --k 4 --no-clustered     # skip the all-IDs preview mp4
  python cluster_cli.py video.mp4 --k 4 --no-cache         # force re-run
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

from cluster_pipeline import (
    _color_for_cluster,
    assign_unique_per_frame,
    cluster_embeddings,
    detect_only,
    embed_detections,
    render_clustered_video,
)
from crop_from_clusters import build_smoothed_path, render_cropped_for_cluster


def _save_thumbnails(
    video_path: str,
    detections: list,
    kept_ids: list,
    labels: np.ndarray,
    out_path: str,
    thumb_h: int = 240,
) -> dict:
    """Pick the top-confidence detection per cluster, render a thumbnail strip."""
    label_for_det = {kept_ids[m]: int(labels[m]) for m in range(len(kept_ids))}

    by_cluster: dict[int, list[tuple[int, float]]] = {}
    for det_idx, det in enumerate(detections):
        cid = label_for_det.get(det_idx)
        if cid is None or cid < 0:
            continue
        by_cluster.setdefault(cid, []).append((det_idx, det["conf"]))

    picks: dict[int, int] = {}
    for cid, lst in by_cluster.items():
        lst.sort(key=lambda x: -x[1])
        picks[cid] = lst[0][0]

    sorted_picks = sorted(picks.items(), key=lambda kv: detections[kv[1]]["frame"])

    cap = cv2.VideoCapture(video_path)
    thumbs: dict[int, np.ndarray] = {}
    for cid, det_idx in sorted_picks:
        target_frame = detections[det_idx]["frame"]
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        x, y, w, h = detections[det_idx]["bbox"]
        pad = 0.15
        x_pad = max(0, x - w * pad)
        y_pad = max(0, y - h * pad)
        w_pad = w * (1 + 2 * pad)
        h_pad = h * (1 + 2 * pad)
        crop = frame[int(y_pad):int(y_pad + h_pad), int(x_pad):int(x_pad + w_pad)]
        if crop.size == 0:
            continue
        scale = thumb_h / crop.shape[0]
        new_w = max(1, int(crop.shape[1] * scale))
        thumb = cv2.resize(crop, (new_w, thumb_h))
        color = _color_for_cluster(cid)
        cv2.rectangle(thumb, (0, 0), (new_w - 1, thumb_h - 1), color, 6)
        label = f"cluster {cid}"
        cv2.putText(thumb, label, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6)
        cv2.putText(thumb, label, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        thumbs[cid] = thumb
    cap.release()

    if not thumbs:
        return {"output_path": None, "clusters_in_strip": []}

    sorted_cids = sorted(thumbs.keys())
    strip = cv2.hconcat([thumbs[cid] for cid in sorted_cids])
    cv2.imwrite(out_path, strip)
    return {"output_path": out_path, "clusters_in_strip": sorted_cids}


def _video_meta(video_path: str) -> tuple[float, int]:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return fps, total


def _summarise_clusters(detections: list, kept_ids: list, labels: np.ndarray, fps: float) -> None:
    label_for_det = {kept_ids[m]: int(labels[m]) for m in range(len(kept_ids))}
    by_cluster: dict[int, list[int]] = {}
    for det_idx, det in enumerate(detections):
        cid = label_for_det.get(det_idx)
        if cid is None:
            continue
        by_cluster.setdefault(cid, []).append(det["frame"])
    print()
    for cid in sorted(c for c in by_cluster.keys() if c >= 0):
        frames = by_cluster[cid]
        first_t = min(frames) / fps
        last_t = max(frames) / fps
        print(
            f"  cluster {cid:>2}: {len(frames):>5} dets  "
            f"first={first_t:>6.1f}s  last={last_t:>6.1f}s  span={last_t - first_t:>5.1f}s"
        )
    if -1 in by_cluster:
        print(f"  unknown : {len(by_cluster[-1]):>5} dets  (surplus / unassignable)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cluster identities in a video and render a follow-cam crop of one of them."
    )
    parser.add_argument("video", help="path to source video")
    parser.add_argument("--k", type=int, default=6, help="expected number of unique people")
    parser.add_argument("--pick", type=int, default=None, help="skip prompt; cluster id to crop")
    parser.add_argument("--crop-w", type=int, default=1280)
    parser.add_argument("--crop-h", type=int, default=720)
    parser.add_argument("--no-clustered", action="store_true",
                        help="skip the all-clusters annotated preview mp4")
    parser.add_argument("--no-cache", action="store_true",
                        help="ignore cached detections/embeddings/labels and re-run")
    parser.add_argument("--out", default=None, help="cropped output path")
    parser.add_argument("--clustered-out", default=None, help="all-clusters mp4 path")
    parser.add_argument("--thumbs-out", default=None, help="thumbnail strip jpg path")
    args = parser.parse_args()

    video_in = args.video
    if not Path(video_in).exists():
        raise SystemExit(f"File not found: {video_in}")

    base = Path(video_in).stem
    cache_path = Path(f".cache_{base}_k{args.k}.pkl")

    detections = None
    kept_ids = None
    labels = None
    centroids = None

    if not args.no_cache and cache_path.exists():
        print(f"[cache] loading {cache_path}")
        with open(cache_path, "rb") as f:
            z = pickle.load(f)
        detections = z["detections"]
        kept_ids = z["kept_ids"]
        labels = z["labels"]
        centroids = z["centroids"]
        print(f"[cache] loaded {len(detections)} detections, "
              f"{len(kept_ids)} embedded, k={centroids.shape[0]}")

    if detections is None:
        print(f"\n[1/5] Detecting people across the whole video ...")
        detections = detect_only(video_in, verbose=True)
        if not detections:
            raise SystemExit("No people detected.")

        print(f"\n[2/5] Embedding {len(detections)} detections with OSNet ...")
        features, kept_ids = embed_detections(video_in, detections, verbose=True)
        if features.shape[0] == 0:
            raise SystemExit("All detections too small to embed.")

        print(f"\n[3/5] Clustering into k={args.k} identities ...")
        labels, centroids, _ = cluster_embeddings(features, k=args.k, verbose=True)
        labels = assign_unique_per_frame(detections, kept_ids, features, centroids, verbose=True)

        print(f"\n[cache] saving {cache_path}")
        with open(cache_path, "wb") as f:
            pickle.dump(
                {
                    "detections": detections,
                    "kept_ids": kept_ids,
                    "labels": labels,
                    "centroids": centroids,
                },
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    fps, total_frames = _video_meta(video_in)
    _summarise_clusters(detections, kept_ids, labels, fps)

    thumbs_out = args.thumbs_out or f"{base}_clusters.jpg"
    print(f"\n[4/5] Rendering cluster thumbnails -> {thumbs_out}")
    info = _save_thumbnails(video_in, detections, kept_ids, labels, thumbs_out)
    if info["output_path"]:
        print(f"      strip contains clusters {info['clusters_in_strip']}")
        print(f"      open {thumbs_out} to see who is who")

    if not args.no_clustered:
        cl_out = args.clustered_out or f"{base}_clusters.mp4"
        print(f"      rendering all-clusters preview -> {cl_out}  (slow)")
        render_clustered_video(
            video_in=video_in,
            video_out=cl_out,
            detections=detections,
            kept_ids=kept_ids,
            labels=labels,
            verbose=False,
        )

    unique_cids = sorted({int(label) for label in labels if label >= 0})
    if not unique_cids:
        raise SystemExit("No assigned clusters — try a smaller --k.")

    if args.pick is not None:
        if args.pick not in unique_cids:
            raise SystemExit(f"--pick {args.pick} not in {unique_cids}")
        chosen_cid = args.pick
    else:
        while True:
            choice = input(
                f"\n[5/5] Which cluster to crop? choices={unique_cids}  (q to quit): "
            ).strip()
            if choice.lower() == "q":
                sys.exit(0)
            try:
                chosen_cid = int(choice)
                if chosen_cid not in unique_cids:
                    raise ValueError
                break
            except ValueError:
                print(f"      pick from {unique_cids}")

    print(f"\n      building smoothed path for cluster {chosen_cid} ...")
    path = build_smoothed_path(
        detections=detections,
        kept_ids=kept_ids,
        labels=labels,
        target_cluster=chosen_cid,
    )
    if not path:
        raise SystemExit(f"      cluster {chosen_cid} has no usable detections")

    coverage = len(path) / total_frames if total_frames else 0.0
    print(f"      smoothed path covers {len(path)}/{total_frames} frames ({coverage*100:.1f}%)")
    if coverage < 0.2:
        print("      WARN: cluster appears in < 20% of the video — output will mostly be a held frame.")

    out_path = args.out or f"{base}_cluster{chosen_cid}_crop.mp4"
    print(f"      rendering follow-cam crop -> {out_path}")
    info = render_cropped_for_cluster(
        video_in=video_in,
        video_out=out_path,
        smoothed_path=path,
        crop_size=(args.crop_w, args.crop_h),
    )

    print("\nDone.")
    print(f"  thumbnails:    {thumbs_out}")
    print(f"  cropped video: {info['output_path']}  ({info['out_w']}x{info['out_h']})")
    print(f"  frames:        {info['frames_total']}  (with bbox: {info['frames_with_bbox']})")
    print(f"  fps:           {info['fps']:.2f}")


if __name__ == "__main__":
    main()
