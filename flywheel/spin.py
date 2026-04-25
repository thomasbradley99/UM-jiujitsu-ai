"""One rotation of the flywheel.

  predict → measure → feedback

predict:  fetch the active prompt from MuBit, run v3-fast (cached) + filter call.
measure:  match predictions vs GT, compute metrics. Delegates to VLM-gemini/eval.
feedback: archive each event and record_outcome to MuBit (per TP / FP / FN).

Outputs (all under `outputs/runs/<run_id>/<prompt_version_id>/`):
  predicted.json   — filtered submissions, shaped like a v3-fast result.json
  report.json      — VLM-gemini/eval/metrics.py:Report dataclass, serialized
  spin.json        — small run-metadata blob

Re-running with the same active prompt overwrites these. Re-running after
`improve` (which produced a new active version) writes a new sub-folder.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from flywheel.config import (
    DEFAULT_VLM_OUT,
    GEMINI_FILTER_MODEL,
    MATCH_TOLERANCE_S,
    OUTPUTS_DIR,
    REPO_ROOT,
    VLM_GEMINI_DIR,
    VLM_PROCESSOR,
    run_id_for_video,
)
from flywheel.mubit_client import (
    archive_event,
    get_active_prompt,
    record_outcome,
)


# Make `from eval.<mod>` resolve — VLM-gemini/eval is a sibling package and
# its parent dir needs to be on sys.path. Mirrors VLM-gemini/eval/run_eval.py.
if str(VLM_GEMINI_DIR) not in sys.path:
    sys.path.insert(0, str(VLM_GEMINI_DIR))


# ---- predict --------------------------------------------------------------


def _run_v3_fast(video: Path, vlm_out: Path, *, force: bool) -> Path:
    """Run video_processor_v3_fast.py, or reuse its cached result.json."""
    result_path = vlm_out / "result.json"
    if result_path.exists() and not force:
        print(f"  reusing cached v3-fast result: {result_path}")
        return result_path
    if not VLM_PROCESSOR.exists():
        raise SystemExit(f"v3-fast script not found: {VLM_PROCESSOR}")
    vlm_out.mkdir(parents=True, exist_ok=True)
    print(f"  running v3-fast on {video}  (out={vlm_out})")
    # Subprocess isolates the older google.generativeai SDK from our
    # google-genai SDK; protobuf versions conflict in-process.
    subprocess.run(
        [sys.executable, str(VLM_PROCESSOR), str(video), "--out-dir", str(vlm_out)],
        check=True,
    )
    if not result_path.exists():
        raise RuntimeError(f"v3-fast finished but {result_path} is missing.")
    return result_path


def _candidate_events(result_data: dict) -> list[dict]:
    """Pull every event v3-fast considers submission-adjacent from result.json."""
    events: list[dict] = []
    for ev in result_data.get("events", []) or []:
        if ev.get("submission") or ev.get("attempt"):
            events.append({
                "source": "events",
                "timestamp": ev.get("timestamp"),
                "title": ev.get("title"),
                "description": ev.get("description"),
                "submission": bool(ev.get("submission")),
                "attempt": bool(ev.get("attempt")),
                "completed": ev.get("completed", True),
                "attacker": ev.get("attacker"),
                "defender": ev.get("defender"),
            })
    for s in (result_data.get("position_timeline") or {}).get("submissions", []) or []:
        events.append({
            "source": "position_timeline",
            "timestamp": s.get("timestamp"),
            "title": s.get("type"),
            "description": s.get("description"),
            "submission": True,
            "attempt": not s.get("completed", True),
            "completed": s.get("completed", True),
            "attacker": s.get("fighter"),
            "defender": None,
        })
    return events


def _strip_md_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _filter_with_gemini(prompt_text: str, candidates: list[dict]) -> list[dict]:
    """Text-only Gemini call: prompt_text + candidates → filtered JSON array."""
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY missing in .env.local.")
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    full_prompt = (
        prompt_text
        + "\n\n---\n\nINPUT (JSON):\n```json\n"
        + json.dumps({"candidates": candidates}, indent=2)
        + "\n```\n\nOUTPUT (JSON array only):"
    )
    resp = client.models.generate_content(
        model=GEMINI_FILTER_MODEL,
        contents=full_prompt,
        config={"response_mime_type": "application/json"},
    )
    raw = _strip_md_fences(resp.text or "[]")
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        print("  WARN: filter returned non-JSON; treating as empty list.")
        print(raw[:500])
        return []
    return out if isinstance(out, list) else []


def _to_v3_event(filtered: dict) -> dict:
    """Shape a filtered event into v3-fast's events[] schema so eval can read it."""
    return {
        "timestamp": float(filtered.get("timestamp", 0)),
        "title": filtered.get("technique") or "other",
        "description": filtered.get("description") or "",
        "submission": True,
        "attempt": False,
        "completed": True,
        "attacker": filtered.get("attacker"),
        "defender": filtered.get("defender"),
    }


def predict(video: Path, *, vlm_out: Path, force_v3_fast: bool) -> dict:
    """Stage-1 (v3-fast, cached) + Stage-2 (MuBit-versioned filter call)."""
    print("=== PREDICT ===")
    result_path = _run_v3_fast(video, vlm_out, force=force_v3_fast)
    result_data = json.loads(result_path.read_text())
    candidates = _candidate_events(result_data)
    print(f"  v3-fast surfaced {len(candidates)} candidate events")

    prompt_text, version_id = get_active_prompt()
    print(f"  active prompt: {version_id}  ({len(prompt_text)} chars)")

    filtered = _filter_with_gemini(prompt_text, candidates)
    print(f"  filter kept {len(filtered)} of {len(candidates)} candidates")

    run_id = run_id_for_video(video)
    out_dir = OUTPUTS_DIR / "runs" / run_id / version_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fighter_stats": result_data.get("fighter_stats") or {},
        "match_summary": result_data.get("match_summary") or "",
        "events": [_to_v3_event(e) for e in filtered],
        "position_timeline": {"submissions": []},
        "key_moments": [],
    }
    predicted_path = out_dir / "predicted.json"
    predicted_path.write_text(json.dumps(payload, indent=2))
    print(f"  wrote {predicted_path}")

    return {
        "video": str(video),
        "run_id": run_id,
        "prompt_version_id": version_id,
        "predicted_path": str(predicted_path),
        "n_candidates": len(candidates),
        "n_kept": len(filtered),
    }


# ---- measure --------------------------------------------------------------


def measure(predicted_path: Path, gt_path: Path, *, tau: float, label: str):
    """Match predictions vs GT and compute metrics. Returns a Report dataclass."""
    print("=== MEASURE ===")
    from eval.load import load_gt, load_prediction  # type: ignore[import-not-found]
    from eval.match import greedy_match  # type: ignore[import-not-found]
    from eval.metrics import evaluate, format_report  # type: ignore[import-not-found]

    gt = load_gt(gt_path)
    pred = load_prediction(predicted_path)
    mr = greedy_match(gt.subs, pred.subs, tau=tau)
    report = evaluate(gt, mr, config=label)
    print(format_report(report))
    return report


# ---- feedback -------------------------------------------------------------


def _hms(t: float | None) -> str:
    if t is None:
        return "—"
    m, s = divmod(float(t), 60)
    return f"{int(m):02d}:{s:05.2f}"


def _signal_for_match(d) -> float:
    s = 0.5 + (0.25 if d.technique_correct else 0) + (0.15 if d.submitter_correct else 0)
    if d.delta_t is not None and abs(d.delta_t) > 5:
        s -= 0.1
    return max(0.3, min(1.0, s))


def feedback(report, run_id: str) -> dict[str, int]:
    """For every EventDetail, archive an artifact and record an outcome.

    The optimizer reads each `rationale` text — that's where we tell it what
    the prompt should do differently. Specifics matter: name the technique,
    reference the timestamp, give a concrete instruction.
    """
    print("=== FEEDBACK ===")
    counts = {"tp": 0, "fp": 0, "fn": 0}

    for d in report.details:
        if d.status == "matched":
            tech_tick = "✓" if d.technique_correct else "✗"
            sub_tick = "✓" if d.submitter_correct else "✗"
            content = (
                f"TP — predicted {d.pred_technique} at {_hms(d.pred_t)} matches GT "
                f"{d.gt_technique} at {_hms(d.gt_t)} (Δt={d.delta_t:+.1f}s, "
                f"technique {tech_tick}, attacker {sub_tick})."
            )
            ref_id = archive_event(
                run_id, content=content, kind="sub_prediction_tp",
                labels=["submission", "true_positive", d.gt_technique or "other"],
            )
            rationale = (
                f"Correctly detected {d.gt_technique} at {_hms(d.gt_t)} "
                f"(within {abs(d.delta_t or 0):.1f}s of GT). Keep this behavior."
            )
            if not d.technique_correct:
                rationale += (
                    f" Mis-classified technique as {d.pred_technique}; correct canonical "
                    f"name is {d.gt_technique}. Be strict about technique names."
                )
            if not d.submitter_correct:
                rationale += (
                    f" Wrong attacker ({d.pred_submitter_raw!r}); should be "
                    f"{d.gt_submitter}. Use the input event's attacker field verbatim."
                )
            record_outcome(
                run_id, ref_id, success=True, signal=_signal_for_match(d), rationale=rationale,
            )
            counts["tp"] += 1

        elif d.status == "hallucination":
            content = (
                f"FP — predicted {d.pred_technique} at {_hms(d.pred_t)} with no GT "
                f"submission within tolerance. Likely a scramble, position change, "
                f"or attempt that did not finish."
            )
            ref_id = archive_event(
                run_id, content=content, kind="sub_prediction_fp",
                labels=["submission", "false_positive", d.pred_technique or "other"],
            )
            rationale = (
                f"Hallucinated submission at {_hms(d.pred_t)} ({d.pred_technique}). "
                "Tighten the filter: require an explicit tap, an isolated joint or "
                "windpipe under attack, or a description containing 'taps' / 'finished'. "
                "Drop attempts, scrambles, position changes."
            )
            record_outcome(
                run_id, ref_id, success=False, signal=-0.7, rationale=rationale,
            )
            counts["fp"] += 1

        elif d.status == "missed_gt":
            content = (
                f"FN — missed GT submission: {d.gt_technique} at {_hms(d.gt_t)} "
                f"by {d.gt_submitter}."
            )
            ref_id = archive_event(
                run_id, content=content, kind="sub_gt_missed",
                labels=["submission", "false_negative", d.gt_technique or "other"],
            )
            rationale = (
                f"Missed real {d.gt_technique} at {_hms(d.gt_t)}. Either v3-fast "
                "didn't surface it as a candidate, or the filter rejected it because "
                "attempt=true / completed=false. If candidates with technique="
                f"{d.gt_technique} appear in the input, keep them when title or "
                "description mentions the technique even if attempt flags are inconsistent."
            )
            record_outcome(
                run_id, ref_id, success=False, signal=-0.85, rationale=rationale,
            )
            counts["fn"] += 1

    print(
        f"  recorded {sum(counts.values())} outcomes  "
        f"({counts['tp']} TP, {counts['fp']} FP, {counts['fn']} FN)"
    )
    return counts


# ---- top-level orchestrator -----------------------------------------------


def spin(
    video: Path,
    gt: Path,
    *,
    vlm_out: Path = DEFAULT_VLM_OUT,
    tau: float = MATCH_TOLERANCE_S,
    force_v3_fast: bool = False,
    skip_feedback: bool = False,
) -> dict:
    """One full rotation: predict → measure → feedback."""
    meta = predict(video, vlm_out=vlm_out, force_v3_fast=force_v3_fast)
    print()

    label = f"{meta['run_id']}:{meta['prompt_version_id'][:12]}"
    report = measure(Path(meta["predicted_path"]), gt, tau=tau, label=label)

    out_dir = Path(meta["predicted_path"]).parent
    (out_dir / "report.json").write_text(json.dumps(asdict(report), indent=2, default=str))
    print(f"  wrote {out_dir / 'report.json'}")

    if skip_feedback:
        print("  (skipping feedback step; pass without --skip-feedback to record outcomes)")
    else:
        print()
        meta["counts"] = feedback(report, run_id=meta["run_id"])

    (out_dir / "spin.json").write_text(json.dumps(meta, indent=2))
    return meta
