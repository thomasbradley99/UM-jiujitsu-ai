"""Single CLI entry point for the MuBit submission-detection demo.

Subcommands:
    setup     One-time: create the agent in the MuBit project.
    detect    Run Gemini submission detection on a video using the active prompt.
    eval      detect + match + compute metrics + record outcomes (full eval cycle).
    optimize  Ask MuBit for a candidate prompt and print the diff.
    report    Render a side-by-side HTML report comparing two prompt versions.

Examples:
    python -m mubit.cli setup
    python -m mubit.cli eval --video full-gym-short.mov --gt eval/gt.json
    python -m mubit.cli optimize
    python -m mubit.cli report --version-a abc123 --version-b def456
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from mubit import config


def _save_metrics(run_dir: Path, prompt_version_id: str, payload: dict) -> Path:
    out = run_dir / f"metrics.{prompt_version_id}.json"
    out.write_text(json.dumps(payload, indent=2))
    return out


def _save_matches(run_dir: Path, prompt_version_id: str, matches: list) -> Path:
    out = run_dir / f"matched.{prompt_version_id}.json"

    def _serialize(m):
        return {
            "kind": m.kind,
            "dt": m.dt,
            "type_match": m.type_match,
            "gt": asdict(m.gt) if m.gt else None,
            "pred": asdict(m.pred) if m.pred else None,
        }

    out.write_text(json.dumps({"matches": [_serialize(m) for m in matches]}, indent=2))
    return out


def cmd_setup(args: argparse.Namespace) -> None:
    from mubit.setup_project import main as setup_main

    setup_main()


def cmd_detect(args: argparse.Namespace) -> None:
    from mubit.detect import detect

    detect(args.video)


def cmd_eval(args: argparse.Namespace) -> None:
    from mubit.detect import detect
    from mubit.gt import load_submission_gt, gt_summary
    from mubit.match import Prediction, match_predictions
    from mubit.metrics import compute as compute_metrics
    from mubit.outcomes import record_outcomes_for_matches

    print("=== STEP 1: detect ===")
    payload = detect(args.video)
    predictions = [Prediction.from_dict(p) for p in payload["predictions"]]
    version_id = payload["prompt_version_id"]

    print()
    print("=== STEP 2: load GT ===")
    gt = load_submission_gt(args.gt)
    print(f"  {gt_summary(gt)}")

    print()
    print("=== STEP 3: match predictions to GT ===")
    matches = match_predictions(gt, predictions, tolerance_s=config.TIMESTAMP_TOLERANCE_S)
    print(f"  {sum(1 for m in matches if m.kind == 'true_positive')} TP")
    print(f"  {sum(1 for m in matches if m.kind == 'false_positive')} FP")
    print(f"  {sum(1 for m in matches if m.kind == 'false_negative')} FN")

    print()
    print("=== STEP 4: compute metrics ===")
    metrics = compute_metrics(matches)
    print(metrics.render())

    run_id = payload["run_id"]
    run_dir = config.OUTPUTS_DIR / "runs" / run_id

    metrics_payload = {
        "video": str(args.video),
        "run_id": run_id,
        "prompt_version_id": version_id,
        "n_gt": metrics.n_gt,
        "n_pred": metrics.n_pred,
        "tp": metrics.tp,
        "fp": metrics.fp,
        "fn": metrics.fn,
        "precision": metrics.precision,
        "recall": metrics.recall,
        "f1": metrics.f1,
        "timestamp_mae": metrics.timestamp_mae,
        "type_accuracy": metrics.type_accuracy,
        "per_type_recall": {k: list(v) for k, v in metrics.per_type_recall.items()},
    }
    _save_metrics(run_dir, version_id, metrics_payload)
    _save_matches(run_dir, version_id, matches)

    if args.skip_outcomes:
        print("\nSkipping outcome recording (--skip-outcomes).")
        return

    print()
    print("=== STEP 5: record outcomes to MuBit ===")
    out = record_outcomes_for_matches(matches, run_id=run_id)
    print(f"  recorded {len(out)} outcomes ({sum(1 for o in out if o['kind']=='tp')} TP, "
          f"{sum(1 for o in out if o['kind']=='fp')} FP, "
          f"{sum(1 for o in out if o['kind']=='fn')} FN)")
    print(
        f"\nDone. View runs in MuBit Console: project {config.PROJECT_ID}, "
        f"agent {config.AGENT_ID}."
    )


def cmd_optimize(args: argparse.Namespace) -> None:
    from mubit.optimize import request_candidate

    request_candidate()


def cmd_report(args: argparse.Namespace) -> None:
    from mubit.report import render

    render(
        run_id=args.run_id,
        version_a=args.version_a,
        version_b=args.version_b,
        label_a=args.label_a,
        label_b=args.label_b,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mubit.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Create the agent in the MuBit project.")
    p_setup.set_defaults(func=cmd_setup)

    p_detect = sub.add_parser("detect", help="Run Gemini detection only.")
    p_detect.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    p_detect.set_defaults(func=cmd_detect)

    p_eval = sub.add_parser("eval", help="Detect + match + metrics + outcomes.")
    p_eval.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    p_eval.add_argument("--gt", type=Path, default=config.DEFAULT_GT)
    p_eval.add_argument("--skip-outcomes", action="store_true",
                        help="Compute metrics but do not record outcomes to MuBit.")
    p_eval.set_defaults(func=cmd_eval)

    p_opt = sub.add_parser("optimize", help="Request a candidate prompt and print diff.")
    p_opt.set_defaults(func=cmd_optimize)

    p_rep = sub.add_parser("report", help="Render side-by-side HTML report.")
    p_rep.add_argument("--run-id", required=True)
    p_rep.add_argument("--version-a", required=True, help="Prompt version_id for left column.")
    p_rep.add_argument("--version-b", required=True, help="Prompt version_id for right column.")
    p_rep.add_argument("--label-a", default="v1")
    p_rep.add_argument("--label-b", default="v2")
    p_rep.set_defaults(func=cmd_report)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
