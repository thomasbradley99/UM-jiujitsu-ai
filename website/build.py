"""Build the website data bundle from raw experimental artifacts.

Reads:
  - VLM-gemini/input-data/<game>/{video.mov, subs.json}
  - flywheel/outputs/runs/<run_id>/<pv>/{result.json, report.json, domain_rules.md}
  - flywheel/outputs/cross_eval/<game>/<v#>-<pv>/{result.json, report.json}
  - flywheel/outputs/loop_arc_*.json

Writes everything as clean JSON into website/data/ and copies media into
website/public/. The frontend reads only from those two folders, so the
experimental scratch can be reorganized without breaking the site.

Run from repo root:
    python website/build.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DATA = REPO_ROOT / "VLM-gemini" / "input-data"
RUNS_DIR = REPO_ROOT / "flywheel" / "outputs" / "runs"
CROSS_EVAL_DIR = REPO_ROOT / "flywheel" / "outputs" / "cross_eval"
FLYWHEEL_OUT = REPO_ROOT / "flywheel" / "outputs"

WEB_ROOT = Path(__file__).resolve().parent
WEB_DATA = WEB_ROOT / "data"
WEB_PUBLIC = WEB_ROOT / "public"


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def build_games() -> list[dict]:
    """Index all input games + their GT, copy videos into public/."""
    games = []
    for game_dir in sorted(INPUT_DATA.iterdir()):
        if not game_dir.is_dir():
            continue
        gt_path = game_dir / "subs.json"
        video_path = game_dir / "video.mov"
        if not gt_path.exists():
            continue
        gt = json.loads(gt_path.read_text())
        games.append({
            "id": game_dir.name,
            "duration_sec": gt.get("duration_sec"),
            "description": gt.get("description"),
            "fighters": gt.get("fighters", {}),
            "submissions": gt.get("submissions", []),
            "video_url": f"/public/games/{game_dir.name}/video.mov" if video_path.exists() else None,
        })

        # Copy GT next to the video for self-contained per-game folder
        out_dir = WEB_DATA / "games" / game_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gt_path, out_dir / "subs.json")

        if video_path.exists():
            pub_dir = WEB_PUBLIC / "games" / game_dir.name
            pub_dir.mkdir(parents=True, exist_ok=True)
            target = pub_dir / "video.mov"
            if not target.exists() or target.stat().st_mtime < video_path.stat().st_mtime:
                shutil.copy2(video_path, target)

    (WEB_DATA / "games" / "index.json").write_text(json.dumps(games, indent=2))
    print(f"  {len(games)} games → website/data/games/")
    return games


# ---------------------------------------------------------------------------
# Flywheel runs (arcs)
# ---------------------------------------------------------------------------

# Curated arcs: the runs we want surfaced in the website. Manual list so we
# don't drown the site in scratch experiments.
CURATED_ARCS = [
    {
        "id": "handtuned-ryan-thomas",
        "label": "Hand-tuned arc · ryan-thomas",
        "video": "ryan-thomas",
        "model": "gemini-3-flash-preview",
        "loop_arc_file": "loop_arc_handtuned.json",
    },
    {
        "id": "naive-ryan-thomas",
        "label": "Naive seed arc · ryan-thomas",
        "video": "ryan-thomas",
        "model": "gemini-3-flash-preview",
        "loop_arc_file": "loop_arc_naive.json",
    },
]


def build_arcs() -> list[dict]:
    """For each curated arc, compile per-iteration data into a clean bundle."""
    arc_index = []
    for arc in CURATED_ARCS:
        arc_path = FLYWHEEL_OUT / arc["loop_arc_file"]
        if not arc_path.exists():
            print(f"  skip {arc['id']}: missing {arc['loop_arc_file']}")
            continue

        loop_arc = json.loads(arc_path.read_text())

        out_dir = WEB_DATA / "runs" / arc["id"]
        out_dir.mkdir(parents=True, exist_ok=True)

        iterations = []
        for entry in loop_arc:
            pv = entry["prompt_version_id"]
            run_dir = RUNS_DIR / "verify:video" / pv
            iter_meta = {
                "iteration": entry.get("iteration"),
                "prompt_version_id": pv,
                "f1": entry.get("f1"),
                "precision": entry.get("precision"),
                "recall": entry.get("recall"),
                "n_gt": entry.get("n_gt"),
                "n_pred": entry.get("n_pred"),
                "n_matched": entry.get("n_matched"),
                "n_hallucinations": entry.get("n_hallucinations"),
                "candidate_version_id": entry.get("candidate_version_id"),
                "activated": entry.get("activated"),
            }
            # Pull report + prompt + result if available
            iter_dir = out_dir / pv
            iter_dir.mkdir(parents=True, exist_ok=True)
            for fname in ("report.json", "result.json"):
                src = run_dir / fname
                if src.exists():
                    shutil.copy2(src, iter_dir / fname)
            rules = run_dir / "domain_rules.md"
            if rules.exists():
                shutil.copy2(rules, iter_dir / "prompt.md")
                iter_meta["prompt_chars"] = len(rules.read_text())

            iterations.append(iter_meta)

        (out_dir / "index.json").write_text(json.dumps({
            **{k: arc[k] for k in ("id", "label", "video", "model")},
            "iterations": iterations,
        }, indent=2))
        arc_index.append({
            "id": arc["id"],
            "label": arc["label"],
            "video": arc["video"],
            "model": arc["model"],
            "n_iterations": len(iterations),
            "peak_f1": max((it.get("f1") or 0) for it in iterations) if iterations else None,
        })
        print(f"  {arc['id']}: {len(iterations)} iterations")

    (WEB_DATA / "runs" / "index.json").write_text(json.dumps(arc_index, indent=2))
    return arc_index


# ---------------------------------------------------------------------------
# Cross-eval matrix
# ---------------------------------------------------------------------------

def build_cross_eval() -> list[dict]:
    """Read flywheel/outputs/cross_eval/ and emit a clean matrix."""
    if not CROSS_EVAL_DIR.exists():
        print("  no cross_eval data on disk")
        return []

    matrix = []
    for game_dir in sorted(CROSS_EVAL_DIR.iterdir()):
        if not game_dir.is_dir():
            continue
        cells = []
        for prompt_dir in sorted(game_dir.iterdir()):
            if not prompt_dir.is_dir():
                continue
            label = prompt_dir.name.split("-", 1)[0]  # v1, v2, ...
            pv = prompt_dir.name.split("-", 1)[1] if "-" in prompt_dir.name else None
            report_path = prompt_dir / "report.json"
            if not report_path.exists():
                continue
            report = json.loads(report_path.read_text())
            cell = {
                "label": label,
                "prompt_version_id": pv,
                "f1": report.get("f1"),
                "precision": report.get("sub_precision"),
                "recall": report.get("sub_recall"),
                "technique_acc": report.get("technique_acc"),
                "submitter_acc": report.get("submitter_acc"),
                "n_gt": report.get("n_gt"),
                "matched": report.get("matched"),
                "hallucinations": report.get("hallucinations"),
            }
            cells.append(cell)

            # Copy per-cell artifacts
            out = WEB_DATA / "cross_eval" / game_dir.name / prompt_dir.name
            out.mkdir(parents=True, exist_ok=True)
            for fname in ("report.json", "result.json"):
                src = prompt_dir / fname
                if src.exists():
                    shutil.copy2(src, out / fname)

        matrix.append({
            "game": game_dir.name,
            "cells": cells,
        })
        print(f"  cross_eval/{game_dir.name}: {len(cells)} cells")

    (WEB_DATA / "cross_eval" / "index.json").write_text(json.dumps(matrix, indent=2))
    return matrix


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(games, arcs, cross_eval):
    """Top-level summary so the frontend can do one fetch and know everything."""
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "games": [g["id"] for g in games],
        "arcs": [{"id": a["id"], "label": a["label"], "peak_f1": a.get("peak_f1")} for a in arcs],
        "cross_eval_games": [m["game"] for m in cross_eval],
    }
    (WEB_DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote website/data/manifest.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    print("Building website data bundle…\n")

    print("Games:")
    games = build_games()
    print("\nArcs:")
    arcs = build_arcs()
    print("\nCross-eval:")
    cross_eval = build_cross_eval()

    write_manifest(games, arcs, cross_eval)


if __name__ == "__main__":
    main()
