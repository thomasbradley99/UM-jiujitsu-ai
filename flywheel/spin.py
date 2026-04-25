"""One rotation of the flywheel.

    predict → measure → feedback

predict:  fetch the active DOMAIN RULES from MuBit, run the full pipeline
          (VLM-gemini/analyze.py) with those rules injected into the
          Stage 1 scan prompt, write result.json.
measure:  match clustered submissions vs GT and compute metrics. Delegates
          to VLM-gemini/eval.
feedback: archive each cluster + each missed-GT window-set and record an
          outcome in MuBit. The optimizer reads `rationale` text — we go
          out of our way to make per-event rationales specific (quote the
          window's own reasoning, name the technique, name the submitter).

Outputs (all under `outputs/runs/<run_id>/<prompt_version_id>/`):
  domain_rules.md  — the rules text we passed to analyze.py (for audit)
  result.json      — analyze.py output (`submissions` + per-window data)
  report.json      — eval Report dataclass, serialized
  spin.json        — small run-metadata blob

Re-running with the same active prompt re-uses `result.json` (pipeline
calls are slow + expensive). Force a re-run with `--force`. Re-running
after `improve` (which produces a new active version) writes a new sub-
folder and a fresh analysis.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from flywheel.config import (
    ANALYZE_CLUSTER_TAU,
    ANALYZE_GRID_STEP,
    ANALYZE_MODEL,
    ANALYZE_PYTHON,
    ANALYZE_SCRIPT,
    ANALYZE_WINDOW_SEC,
    ANALYZE_WORKERS,
    DEFAULT_GT,  # noqa: F401  (re-exported for callers)
    MATCH_TOLERANCE_S,
    OUTPUTS_DIR,
    REPO_ROOT,
    VLM_GEMINI_DIR,
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


def _run_analyze(
    *,
    video: Path,
    out_dir: Path,
    domain_rules_path: Path,
) -> Path:
    """Subprocess into VLM-gemini/analyze.py.

    Lives in a different SDK ecosystem (google.generativeai vs google-genai)
    so we keep it process-isolated. analyze.py writes `result.json` directly
    under `out_dir`. Returns the path to that result.json.
    """
    if not ANALYZE_SCRIPT.exists():
        raise SystemExit(f"analyze script not found: {ANALYZE_SCRIPT}")

    cmd = [
        str(ANALYZE_PYTHON), str(ANALYZE_SCRIPT),
        str(video),
        "--out-dir", str(out_dir),
        "--domain-rules-file", str(domain_rules_path),
        "--model", ANALYZE_MODEL,
        "--window-sec", str(ANALYZE_WINDOW_SEC),
        "--grid-step", str(ANALYZE_GRID_STEP),
        "--cluster-tau", str(ANALYZE_CLUSTER_TAU),
        "--workers", str(ANALYZE_WORKERS),
    ]
    # Force-reload .env.local so a stale GEMINI_API_KEY in the parent shell
    # doesn't leak into the subprocess. python-dotenv's default override=False
    # would let a stale value win silently.
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env.local", override=True)

    # analyze.py uses google.generativeai, which forks ffmpeg from worker
    # threads while gRPC has live event-engine threads. macOS gRPC writes a
    # FATAL Check failure to stderr per worker; the analysis still completes.
    # Mute the noise here rather than re-architect the pipeline.
    env = os.environ.copy()
    env.setdefault("GRPC_VERBOSITY", "NONE")
    env.setdefault("GRPC_TRACE", "")
    env.setdefault("GLOG_minloglevel", "3")
    env.setdefault("ABSL_min_log_level", "3")
    env.setdefault("PYTHONWARNINGS", "ignore::FutureWarning,ignore::DeprecationWarning")
    print(f"  ▶ {' '.join(cmd[:4])} … (see analyze.py stdout below)")
    subprocess.run(cmd, check=True, env=env)

    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError(f"analyze.py finished but {result_path} is missing.")
    return result_path


def predict(
    video: Path,
    gt: Path,
    *,
    force: bool = False,
) -> dict:
    """Run analyze.py with the MuBit-active DOMAIN RULES injected."""
    print("=== PREDICT ===")
    prompt_text, version_id = get_active_prompt()
    print(f"  active rules: {version_id}  ({len(prompt_text)} chars)")

    run_id = run_id_for_video(video)
    out_dir = OUTPUTS_DIR / "runs" / run_id / version_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rules_path = out_dir / "domain_rules.md"
    rules_path.write_text(prompt_text)

    result_path = out_dir / "result.json"
    if result_path.exists() and not force:
        print(f"  reusing cached pipeline output: {result_path}")
        print(f"  (pass --force to rerun analyze.py on the same prompt)")
    else:
        print(f"  running analyze.py on {video.name} …")
        _run_analyze(
            video=video,
            out_dir=out_dir,
            domain_rules_path=rules_path,
        )

    data = json.loads(result_path.read_text())
    n_subs = len(data.get("submissions") or [])
    md = data.get("metadata") or {}
    n_windows = md.get("n_windows", 0)
    n_yes = md.get("n_yes_windows", 0)
    print(f"  pipeline saw {n_yes}/{n_windows} YES windows → {n_subs} clustered submissions")

    return {
        "video": str(video),
        "run_id": run_id,
        "prompt_version_id": version_id,
        "result_path": str(result_path),
        "n_windows": n_windows,
        "n_yes_windows": n_yes,
        "n_clustered_subs": n_subs,
    }


# ---- measure --------------------------------------------------------------


def measure(result_path: Path, gt_path: Path, *, tau: float, label: str):
    """Match clustered submissions vs GT and compute metrics.

    `result.json` from analyze.py is the canonical schema eval expects, so
    we use `eval.load.load_prediction()` directly — no adapter needed.
    """
    print("=== MEASURE ===")
    from eval.load import load_gt, load_prediction  # type: ignore[import-not-found]
    from eval.match import greedy_match  # type: ignore[import-not-found]
    from eval.metrics import evaluate, format_report  # type: ignore[import-not-found]

    gt = load_gt(gt_path)
    pred = load_prediction(result_path)
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


def _windows_covering(rows: list[dict], t: float) -> list[dict]:
    """Per-window rows whose [start, end] contains t."""
    out: list[dict] = []
    for v in rows:
        ws = v.get("start")
        we = v.get("end")
        if ws is None or we is None:
            continue
        if float(ws) <= float(t) <= float(we):
            out.append(v)
    return out


def _windows_near(rows: list[dict], t: float, *, slop: float = 5.0) -> list[dict]:
    """Per-window rows whose absolute_timestamp is within `slop` of t.

    For TP/FP we want the YES windows that voted into the cluster — these
    are typically clustered within ~cluster_tau seconds of the cluster
    center. We also include `slop` for floating-point + rounding noise.
    """
    out: list[dict] = []
    for v in rows:
        ts = v.get("absolute_timestamp")
        if ts is None:
            continue
        if abs(float(ts) - float(t)) <= slop:
            out.append(v)
    return out


def _short_reason(v: dict, max_len: int = 120) -> str:
    """One-line summary of a per-window row, for embedding in rationales."""
    verdict = "YES" if v.get("is_submission") else "NO"
    reasoning = (v.get("reasoning") or "").strip().replace("\n", " ")
    if len(reasoning) > max_len:
        reasoning = reasoning[: max_len - 1] + "…"
    ws = v.get("start")
    we = v.get("end")
    span = f"[{int(ws):>4}-{int(we):>4}s]" if ws is not None and we is not None else "[??]"
    return f"{span} {verdict}: {reasoning or '(no reasoning)'}"


def feedback(report, result_data: dict, run_id: str) -> dict[str, int]:
    """For every cluster-level event, archive an artifact and record an outcome.

    Three rationale styles by status:
      - matched:        "pipeline correctly fired here, keep this rule"
      - hallucination:  "this cluster shouldn't have fired; here's what
                         the windows said"
      - missed_gt:      "real submission at YYs; the windows covering it
                         all said NO. Their reasoning was ___. The rules
                         are missing whatever cue was in this clip"

    The third one is the killer — it literally tells the optimizer:
    "you said NO at the moments a real sub happened, here's why you said NO".
    """
    print("=== FEEDBACK ===")
    counts = {"tp": 0, "fp": 0, "fn": 0}

    md = result_data.get("metadata") or {}
    rows = md.get("all_window_rows") or []
    cluster_tau = md.get("cluster_tau") or ANALYZE_CLUSTER_TAU

    for d in report.details:
        if d.status == "matched":
            tech_tick = "✓" if d.technique_correct else "✗"
            sub_tick = "✓" if d.submitter_correct else "✗"
            voting = _windows_near(rows, d.pred_t or 0.0, slop=cluster_tau + 5.0)
            voting_yes = [v for v in voting if v.get("is_submission")]
            voting_lines = "\n  ".join(_short_reason(v) for v in voting_yes[:3]) or "(none)"
            content = (
                f"TP cluster — predicted {d.pred_technique} at {_hms(d.pred_t)} "
                f"matched GT {d.gt_technique} at {_hms(d.gt_t)} "
                f"(Δt={d.delta_t:+.1f}s, technique {tech_tick}, attacker {sub_tick}).\n"
                f"Voting windows (YES):\n  {voting_lines}"
            )
            ref_id = archive_event(
                run_id, content=content, kind="pipeline_cluster_tp",
                labels=["submission", "true_positive", d.gt_technique or "other"],
            )
            rationale = (
                f"Correctly detected {d.gt_technique} at {_hms(d.gt_t)} "
                f"(within {abs(d.delta_t or 0):.1f}s of GT). "
                f"The DOMAIN RULES produced YES on the windows around this moment. "
                f"Keep the parts of the rules that produced this detection."
            )
            if not d.technique_correct:
                rationale += (
                    f" Mis-classified technique as {d.pred_technique}; correct "
                    f"canonical name is {d.gt_technique}. Rules can be more "
                    f"specific about distinguishing similar techniques, OR push "
                    f"the model to commit to a specific technique rather than "
                    f"defaulting to 'other'."
                )
            if not d.submitter_correct:
                rationale += (
                    f" Wrong attacker ({d.pred_submitter_raw!r}); should be "
                    f"{d.gt_submitter}. The rules should emphasise that the "
                    f"submitter is whoever is applying pressure / has positional "
                    f"control just before the finish, not whoever moves last."
                )
            record_outcome(
                run_id, ref_id, success=True, signal=_signal_for_match(d), rationale=rationale,
            )
            counts["tp"] += 1

        elif d.status == "hallucination":
            voting = _windows_near(rows, d.pred_t or 0.0, slop=cluster_tau + 5.0)
            voting_yes = [v for v in voting if v.get("is_submission")]
            voting_lines = "\n  ".join(_short_reason(v) for v in voting_yes[:3]) or "(none)"
            content = (
                f"FP cluster — predicted {d.pred_technique} at {_hms(d.pred_t)} "
                f"with no GT submission within tolerance.\n"
                f"Voting windows (YES, but should have been NO):\n  {voting_lines}"
            )
            ref_id = archive_event(
                run_id, content=content, kind="pipeline_cluster_fp",
                labels=["submission", "false_positive", d.pred_technique or "other"],
            )
            sample_reasoning = ""
            if voting_yes:
                sample_reasoning = (voting_yes[0].get("reasoning") or "").strip()
            rationale = (
                f"Hallucinated submission at {_hms(d.pred_t)} ({d.pred_technique}). "
                f"The DOMAIN RULES were too liberal — these windows fired YES on "
                f"something that wasn't a real finish."
            )
            if sample_reasoning:
                rationale += (
                    f" Sample window reasoning: \"{sample_reasoning[:200]}\". "
                    f"Tighten the rules to require stronger corroboration: e.g. "
                    f"if a window only sees a position change / scramble / pause, "
                    f"that should remain is_submission=false unless additional "
                    f"finish signals are visible."
                )
            else:
                rationale += (
                    f" No YES windows found near this cluster timestamp — the "
                    f"clustering is over-merging adjacent windows. Cluster_tau "
                    f"or window settings may need adjustment, or rules should "
                    f"emit lower confidence on borderline cases."
                )
            record_outcome(
                run_id, ref_id, success=False, signal=-0.7, rationale=rationale,
            )
            counts["fp"] += 1

        elif d.status == "missed_gt":
            covering = _windows_covering(rows, d.gt_t or 0.0)
            covering_no = [v for v in covering if not v.get("is_submission")]
            covering_lines = "\n  ".join(_short_reason(v) for v in covering_no[:4]) or "(no windows covered this moment)"
            content = (
                f"FN — missed GT submission: {d.gt_technique} at {_hms(d.gt_t)} "
                f"by {d.gt_submitter}.\n"
                f"Windows that should have detected it (all returned NO):\n  {covering_lines}"
            )
            ref_id = archive_event(
                run_id, content=content, kind="pipeline_window_fn",
                labels=["submission", "false_negative", d.gt_technique or "other"],
            )
            rationale = (
                f"Missed real {d.gt_technique} by {d.gt_submitter} at {_hms(d.gt_t)}. "
                f"{len(covering_no)} window(s) covered this moment and ALL returned "
                f"is_submission=false."
            )
            if covering_no:
                first_reason = (covering_no[0].get("reasoning") or "").strip()
                if first_reason:
                    rationale += (
                        f" One window's reasoning: \"{first_reason[:200]}\". "
                        f"This means the DOMAIN RULES, as written, do not let the "
                        f"pipeline classify this kind of finish as a submission. "
                        f"Either the actual tap/yield was hidden, fast, or below "
                        f"frame, OR the round ended in a way (separation, pause, "
                        f"reset, fist bump, fighters disengaging) that the rules "
                        f"don't currently treat as sufficient evidence. To recover "
                        f"this case, the rules likely need to allow end-of-round "
                        f"\"reset\" signals as evidence of a finish, even without "
                        f"a directly visible tap."
                    )
            else:
                rationale += (
                    " No windows covered this moment — the grid stride or window "
                    "size may need to be smaller. (This is a config issue, not "
                    "a rules issue, but flagged here for completeness.)"
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
    tau: float = MATCH_TOLERANCE_S,
    force: bool = False,
    skip_feedback: bool = False,
) -> dict:
    """One full rotation: predict → measure → feedback."""
    meta = predict(video, gt, force=force)
    print()

    label = f"{meta['run_id']}:{meta['prompt_version_id'][:12]}"
    result_path = Path(meta["result_path"])
    report = measure(result_path, gt, tau=tau, label=label)

    out_dir = result_path.parent
    (out_dir / "report.json").write_text(json.dumps(asdict(report), indent=2, default=str))
    print(f"  wrote {out_dir / 'report.json'}")

    if skip_feedback:
        print("  (skipping feedback step; pass without --skip-feedback to record outcomes)")
    else:
        print()
        result_data = json.loads(result_path.read_text())
        meta["counts"] = feedback(report, result_data, run_id=meta["run_id"])

    meta["metrics"] = {
        "f1": float(getattr(report, "f1", 0.0) or 0.0),
        "precision": float(getattr(report, "sub_precision", 0.0) or 0.0),
        "recall": float(getattr(report, "sub_recall", 0.0) or 0.0),
        "n_gt": int(getattr(report, "n_gt", 0) or 0),
        "n_pred": int(getattr(report, "n_pred", 0) or 0),
        "n_matched": int(getattr(report, "matched", 0) or 0),
        "n_hallucinations": int(getattr(report, "hallucinations", 0) or 0),
        "technique_acc": float(getattr(report, "technique_acc", 0.0) or 0.0),
        "submitter_acc": float(getattr(report, "submitter_acc", 0.0) or 0.0),
        "timestamp_mae": float(getattr(report, "timestamp_mae", 0.0) or 0.0),
    }
    (out_dir / "spin.json").write_text(json.dumps(meta, indent=2))
    return meta
