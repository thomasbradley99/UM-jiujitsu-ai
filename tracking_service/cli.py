"""Interactive CLI: pick a fighter from a video, render a tracked video.

Usage:
  python cli.py path/to/fight.mp4
  python cli.py path/to/fight.mp4 --at 30 --mode crop
  python cli.py path/to/fight.mp4 --pick 1     # skip prompt, pick person idx 1
  python cli.py path/to/fight.mp4 --all        # show ALL tracks, no picker
  python cli.py path/to/fight.mp4 --all --weights yolov8s.pt --min-frames 5

Flow (single-target, default):
  1. Grab a frame at --at seconds (default: midpoint of the video).
  2. Run YOLO detection on that frame, save a preview JPG with numbered
     boxes around each person.
  3. Print the list, prompt for a number.
  4. Run YOLO + BoT-SORT(+ReID) over the whole video and write an MP4
     showing only that fighter (boxed, or follow-cam crop).

Flow (--all):
  1. Skip picker entirely.
  2. Run YOLO + BoT-SORT(+ReID) over the whole video.
  3. Write an MP4 with EVERY tracked person boxed in their own color +
     id label, plus a JSON sidecar with one row per track ID.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

from detector import detect_people
from tracker import render_and_summarize_all, render_tracked_video


def _grab_frame(video_path: str, t_seconds: float) -> tuple[float, "cv2.typing.MatLike"]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target_frame = max(0, min(int(round(t_seconds * fps)), total_frames - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise SystemExit(f"Could not read frame at t={t_seconds}s")
    return target_frame / fps, frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Pick a fighter and render a tracked video.")
    parser.add_argument("video", help="path to source video file")
    parser.add_argument("--at", type=float, default=None,
                        help="picker timestamp in seconds (default: midpoint)")
    parser.add_argument("--mode", choices=["box", "crop"], default="box",
                        help="box: draw bbox on full frame; crop: follow-cam")
    parser.add_argument("--out", default=None, help="output path (default: <name>_tracked_<mode>.mp4)")
    parser.add_argument("--pick", type=int, default=None,
                        help="skip the prompt and use this person index from the picker")
    parser.add_argument("--all", action="store_true",
                        help="skip picker, render every tracked person in their own color")
    parser.add_argument("--auto-pair", action="store_true",
                        help="(--all only) automatically render only the two tracks "
                             "with the highest bbox overlap (the grappling pair)")
    parser.add_argument("--only-ids", default=None,
                        help="(--all only) comma-separated track_ids to keep, "
                             "e.g. --only-ids 1,2 (renders only those two)")
    parser.add_argument("--min-frames", type=int, default=0,
                        help="(--all only) drop tracks seen in fewer than N frames")
    parser.add_argument("--merge", action="store_true",
                        help="(--all only) stitch ID-switched fragments into one track per fighter")
    parser.add_argument("--merge-by", choices=["geometry", "appearance"], default="geometry",
                        help="merge strategy: 'geometry' = bbox proximity (default, fast). "
                             "'appearance' = OSNet ReID cosine similarity (slower, more robust). "
                             "Implies --merge.")
    parser.add_argument("--merge-max-gap", type=float, default=2.0,
                        help="merge: max gap in seconds between a dying track and a "
                             "newly-born one to consider them the same person (default 2s; "
                             "auto-relaxed to 10s for --merge-by appearance)")
    parser.add_argument("--merge-max-dist", type=float, default=200.0,
                        help="merge: max pixel distance between bbox centers across "
                             "the gap (default 200; auto-relaxed for appearance)")
    parser.add_argument("--appearance-cos", type=float, default=0.7,
                        help="(--merge-by appearance) min cosine similarity to merge "
                             "two tracks. 0.7 default; raise to 0.8 for stricter, lower "
                             "to 0.5 if mid-roll tracks fail to stitch.")
    parser.add_argument("--revalidate", action="store_true",
                        help="after merge, re-embed every box and reassign it to "
                             "whichever track centroid is the best appearance match. "
                             "Catches BoT-SORT mistakes the merge step can't fix. "
                             "Auto-enabled with --merge-by appearance unless --no-revalidate is set.")
    parser.add_argument("--no-revalidate", dest="revalidate", action="store_false",
                        help="opt out of the per-box revalidation pass")
    parser.set_defaults(revalidate=None)
    parser.add_argument("--revalidate-margin", type=float, default=0.15,
                        help="cosine-sim margin needed to overrule the current track "
                             "(default 0.15; raise for stricter, lower to react more)")
    parser.add_argument("--weights", default=None,
                        help="YOLO weights to use (default: yolov8x.pt). "
                             "Use yolov8s.pt or yolov8n.pt for ~5-10x speedup on long videos.")
    parser.add_argument("--cluster", type=int, default=None, metavar="K",
                        help="PURE-APPEARANCE pipeline: skip the tracker entirely, "
                             "just detect every person, embed each box with OSNet, "
                             "and K-means cluster all embeddings into K identities. "
                             "Best for cases where BoT-SORT keeps swapping IDs "
                             "(e.g. BJJ grappling). Try K=2 for the fighters, K=4 "
                             "if there are coaches/spectators in frame.")
    parser.add_argument("--cluster-only-ids", default=None,
                        help="(--cluster only) comma-separated cluster ids to render, "
                             "e.g. 0,1 to keep only the two main fighters once you "
                             "see which clusters they ended up in.")
    parser.add_argument("--no-unique-per-frame", dest="unique_per_frame",
                        action="store_false",
                        help="(--cluster only) skip per-frame Hungarian assignment "
                             "and let two boxes in the same frame share a cluster id "
                             "(only useful for debugging the raw K-means output)")
    parser.set_defaults(unique_per_frame=True)
    parser.add_argument("--conf", type=float, default=0.4,
                        help="(--cluster only) YOLO confidence threshold "
                             "(default 0.4). Lower = more boxes, more noise to cluster.")
    parser.add_argument("--crop-w", type=int, default=1280)
    parser.add_argument("--crop-h", type=int, default=720)
    args = parser.parse_args()

    video_in = args.video
    if not Path(video_in).exists():
        raise SystemExit(f"File not found: {video_in}")

    # Late binding so detector.DEFAULT_WEIGHTS stays the source of truth.
    if args.weights is None:
        from detector import DEFAULT_WEIGHTS as weights
    else:
        weights = args.weights

    if args.cluster is not None:
        return _run_cluster(video_in, args, weights)

    if args.all:
        return _run_all(video_in, args, weights)

    cap = cv2.VideoCapture(video_in)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    duration = total_frames / fps if fps else 0.0

    target_t = args.at if args.at is not None else max(0.0, duration / 2)
    actual_t, frame = _grab_frame(video_in, target_t)

    print(f"\n[1/3] Detecting people at t={actual_t:.2f}s ...")
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise SystemExit("Failed to encode picker frame")
    detections = detect_people(buf.tobytes())
    if not detections:
        raise SystemExit("No people detected on picker frame. Try a different --at.")

    preview = frame.copy()
    for det in detections:
        x, y, w, h = det["bbox"]
        i = det["id"]
        cv2.rectangle(preview, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 0), 3)
        label = f"{i}"
        cv2.rectangle(preview, (int(x), int(y) - 36), (int(x) + 48, int(y)), (0, 255, 0), -1)
        cv2.putText(preview, label, (int(x) + 8, int(y) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 3)

    base = Path(video_in).stem
    preview_path = f"{base}_picker.jpg"
    cv2.imwrite(preview_path, preview)
    print(f"      preview saved: {preview_path}")
    print(f"      open the file to see numbered boxes")

    print(f"\n      detected {len(detections)} people:")
    for det in detections:
        x, y, w, h = det["bbox"]
        print(f"        [{det['id']}]  bbox=({x:.0f},{y:.0f},{w:.0f},{h:.0f})  conf={det['conf']:.2f}")

    if args.pick is not None:
        try:
            chosen = next(d for d in detections if d["id"] == args.pick)
        except StopIteration:
            raise SystemExit(f"--pick {args.pick} not in {[d['id'] for d in detections]}")
    else:
        while True:
            choice = input("\n[2/3] Which person to track? (number, q to quit): ").strip()
            if choice.lower() == "q":
                sys.exit(0)
            try:
                idx = int(choice)
                chosen = next(d for d in detections if d["id"] == idx)
                break
            except (ValueError, StopIteration):
                print(f"      invalid. pick from: {[d['id'] for d in detections]}")

    out_path = args.out or f"{base}_tracked_{args.mode}.mp4"
    print(f"\n[3/3] Running BoT-SORT + ReID over the whole video ...")
    print(f"      this can take a while on CPU. output: {out_path}")

    result = render_tracked_video(
        video_in=video_in,
        video_out=out_path,
        target_bbox=chosen["bbox"],
        target_t=actual_t,
        mode=args.mode,
        crop_size=(args.crop_w, args.crop_h),
        weights=weights,
    )

    print("\nDone.")
    print(f"  output:           {result['output_path']}")
    print(f"  resolved track:   id={result['track_id']}")
    print(f"  frames written:   {result['frames_written']}")
    print(f"  frames with bbox: {result['frames_with_bbox']}")
    print(f"  fps:              {result['fps']:.2f}")
    print(f"  duration:         {result['video_duration']:.2f}s")


def _run_all(video_in: str, args: argparse.Namespace, weights: str) -> None:
    """--all (with optional --auto-pair / --only-ids): track everyone in
    one YOLO pass, render the chosen subset, dump JSON for the rest.
    """
    base = Path(video_in).stem
    suffix = "_pair" if args.auto_pair else ("_filtered" if args.only_ids else "_all")
    out_path = args.out or f"{base}_tracked{suffix}.mp4"
    json_path = f"{base}_tracks.json"

    only_ids: list[int] | None = None
    if args.only_ids:
        try:
            only_ids = [int(x.strip()) for x in args.only_ids.split(",") if x.strip()]
        except ValueError:
            raise SystemExit(f"--only-ids must be a comma-separated list of ints, got: {args.only_ids}")

    print(f"\n[1/1] Tracking + rendering (weights={weights}) ...")
    if args.auto_pair:
        print("      mode: auto-pair (will pick the most-overlapping two tracks)")
    elif only_ids:
        print(f"      mode: only_ids={only_ids}")
    else:
        print("      mode: all tracks")
    print(f"      output: {out_path}")

    # --merge-by appearance implies --merge
    do_merge = args.merge or args.merge_by == "appearance"

    # --merge-by appearance defaults to revalidate=True; user can opt out
    # with --no-revalidate. Pure-geometric runs default to revalidate=False.
    if args.revalidate is None:
        do_revalidate = args.merge_by == "appearance"
    else:
        do_revalidate = args.revalidate

    result = render_and_summarize_all(
        video_in=video_in,
        video_out=out_path,
        weights=weights,
        min_frames=args.min_frames,
        only_ids=only_ids,
        auto_pair=args.auto_pair,
        merge=do_merge,
        merge_max_gap_s=args.merge_max_gap,
        merge_max_dist_px=args.merge_max_dist,
        merge_by=args.merge_by,
        appearance_cos_thresh=args.appearance_cos,
        revalidate=do_revalidate,
        revalidate_margin=args.revalidate_margin,
    )

    summary = result["summary"]
    Path(json_path).write_text(json.dumps(summary, indent=2))
    tracks = summary["tracks"]
    if args.min_frames:
        tracks = [t for t in tracks if t["frame_count"] >= args.min_frames]

    print("\nDone.")
    print(f"  output video:    {result['render']['output_path']}")
    print(f"  json summary:    {json_path}")
    print(f"  tracks rendered: {result['render']['track_count']}  ids={result['render']['track_ids']}")
    print(f"  highlighted:     {result['render']['highlight_ids']}")
    print(f"  total tracks:    {summary['track_count']}")
    if result.get("merge_chains"):
        print(f"  merge_chains:    {result['merge_chains']}")
    rv = result.get("revalidation")
    if rv:
        print(
            f"  revalidation:    {rv['reassignments']} reassigned / "
            f"{rv['boxes_embedded']} embedded / "
            f"{rv['boxes_checked']} checked"
        )
        flips = rv.get("flips_per_pair") or {}
        if flips:
            top = sorted(flips.items(), key=lambda kv: kv[1], reverse=True)[:5]
            print("    top flips (from -> to: count):")
            for (src, dst), n in top:
                print(f"      {src:>3} -> {dst:<3}  {n}")
        if rv.get("dedupe_drops"):
            print(f"    dedupe drops:  {rv['dedupe_drops']}")
    print(f"  fps:             {result['fps']:.2f}")
    print(f"  duration:        {result['video_duration']:.2f}s")

    if not tracks:
        return

    print("\n  Per-track summary (sorted by frame_count desc):")
    print("    id   frames   first_t   last_t   duration   avg_conf")
    print("    ---  -------  --------  -------  ---------  --------")
    for t in tracks:
        print(
            f"    {t['track_id']:<3}  "
            f"{t['frame_count']:<7}  "
            f"{t['first_t']:>7.2f}s  "
            f"{t['last_t']:>6.2f}s  "
            f"{t['duration']:>8.2f}s  "
            f"{t['avg_conf']:>7.2f}"
        )


def _run_cluster(video_in: str, args: argparse.Namespace, weights: str) -> None:
    """--cluster K: pure-appearance pipeline, no tracker.

    Detects every person in every frame, embeds each crop with OSNet,
    spherical-K-means clusters into K identities, renders boxes coloured
    by cluster.
    """
    from cluster_pipeline import run_cluster_pipeline

    base = Path(video_in).stem
    out_path = args.out or f"{base}_clustered_k{args.cluster}.mp4"
    json_path = f"{base}_clustered_k{args.cluster}.json"

    only_clusters: list[int] | None = None
    if args.cluster_only_ids:
        try:
            only_clusters = [int(x.strip()) for x in args.cluster_only_ids.split(",") if x.strip()]
        except ValueError:
            raise SystemExit(f"--cluster-only-ids must be comma-separated ints, got: {args.cluster_only_ids}")

    print(f"\n[1/1] Pure-appearance clustering pipeline (K={args.cluster}, weights={weights}) ...")
    print(f"      output: {out_path}")
    if only_clusters is not None:
        print(f"      rendering only clusters: {only_clusters}")

    result = run_cluster_pipeline(
        video_in=video_in,
        video_out=out_path,
        k=args.cluster,
        weights=weights,
        conf_threshold=args.conf,
        only_clusters=only_clusters,
        unique_per_frame=args.unique_per_frame,
    )

    Path(json_path).write_text(json.dumps({
        "diagnostics": result["diagnostics"],
        "clusters": result["clusters"],
        "total_detections": result["total_detections"],
        "embedded_detections": result["embedded_detections"],
    }, indent=2))

    print("\nDone.")
    print(f"  output video:        {result['render']['output_path']}")
    print(f"  json summary:        {json_path}")
    print(f"  total detections:    {result['total_detections']}")
    print(f"  embedded:            {result['embedded_detections']}")
    print(f"  frames with box:     {result['render']['frames_with_box']}/{result['render']['frames_total']}")
    diag = result["diagnostics"]
    print(f"\n  Cluster diagnostics:")
    print(f"    cluster sizes:     {diag['counts']}")
    print(f"    cohesion (cos to own):  {[f'{x:.3f}' for x in diag['cohesion']]}")
    print(f"    separation (cos between centroids, lower=better): {diag['mean_separation']:.3f}")
    print(f"    low-margin points: {diag['pct_low_margin']*100:.1f}%  "
          f"(<0.05 closer to a different cluster — these are the ambiguous boxes)")
    if diag["mean_separation"] > 0.7:
        print("    !! warning: clusters are very similar in appearance; consider raising K")
    if diag["pct_low_margin"] > 0.2:
        print("    !! warning: >20% of points are ambiguous; identity assignments may be noisy")
    print(f"\n  Per-cluster summary:")
    print(f"    id   detections   first_frame   last_frame")
    print(f"    ---  -----------  ------------  ----------")
    for c in result["clusters"]:
        ff = c["first_frame"] if c["first_frame"] is not None else "-"
        lf = c["last_frame"] if c["last_frame"] is not None else "-"
        print(f"    {c['cluster_id']:<3}  {c['detections']:<11}  {ff:<12}  {lf}")


if __name__ == "__main__":
    main()
