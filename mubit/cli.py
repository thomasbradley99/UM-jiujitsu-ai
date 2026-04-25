"""Single CLI entry point for the MuBit submission-detection demo.

Subcommands:
    setup     One-time: create the agent in MuBit and seed the v1 prompt.
    detect    Run v3-fast (cached) + MuBit-versioned filter on a video.
    eval      detect + match-against-GT + record outcomes back to MuBit.
    optimize  Ask MuBit for a candidate prompt and print the diff.
    report    Render the side-by-side HTML report comparing two prompt versions.

The eval command does NOT re-implement matching/metrics — it delegates to
VLM-gemini/eval/{load,match,metrics}.py, which is the canonical eval spine.
mubit/ only owns the MuBit-orchestration parts (prompt fetch, filter call,
outcomes, optimization, report).

Examples:
    python -m mubit.cli setup
    python -m mubit.cli eval                                  # uses default ryan-thomas dataset
    python -m mubit.cli eval --video VLM-gemini/input-data/<game>/video.mov \\
                             --gt    VLM-gemini/input-data/<game>/subs.json
    python -m mubit.cli optimize
    python -m mubit.cli report --run-id sub-detect:video --version-a <v1> --version-b <v2>
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from mubit import config


# Make `from eval.<mod>` work — VLM-gemini/eval is a sibling package whose
# parent dir (VLM-gemini/) needs to be on sys.path. Mirrors run_eval.py.
sys.path.insert(0, str(config.VLM_GEMINI_DIR))


def cmd_setup(args: argparse.Namespace) -> None:
    from mubit.setup_project import main as setup_main

    setup_main()


def cmd_detect(args: argparse.Namespace) -> None:
    from mubit.detect import detect

    detect(args.video, vlm_out_dir=args.vlm_out, force_v3_fast=args.force_v3_fast)


def cmd_eval(args: argparse.Namespace) -> None:
    from mubit.detect import detect

    print("=== STEP 1: detect (v3-fast + MuBit filter) ===")
    meta = detect(args.video, vlm_out_dir=args.vlm_out, force_v3_fast=args.force_v3_fast)
    predicted_path = Path(meta["predicted_path"])
    version_id = meta["prompt_version_id"]
    run_id = meta["run_id"]

    # Imports deferred until after sys.path is set up.
    from eval.load import load_gt, load_prediction  # type: ignore[import-not-found]
    from eval.match import greedy_match  # type: ignore[import-not-found]
    from eval.metrics import evaluate, format_report  # type: ignore[import-not-found]

    print("\n=== STEP 2: eval against GT ===")
    gt = load_gt(args.gt)
    pred = load_prediction(predicted_path)
    mr = greedy_match(gt.subs, pred.subs, tau=args.tau)
    report = evaluate(gt, mr, config=f"{run_id}:{version_id[:12]}")
    print(format_report(report))

    out_dir = predicted_path.parent
    report_dict = asdict(report)
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report_dict, indent=2, default=str))
    print(f"\n  wrote {report_path}")

    if args.skip_outcomes:
        print("Skipping outcome recording (--skip-outcomes).")
        return

    print("\n=== STEP 3: record outcomes to MuBit ===")
    from mubit.outcomes import record_outcomes_for_report

    out = record_outcomes_for_report(report, run_id=run_id)
    counts = {"tp": 0, "fp": 0, "fn": 0}
    for o in out:
        counts[o["kind"]] = counts.get(o["kind"], 0) + 1
    print(f"  recorded {len(out)} outcomes  ({counts['tp']} TP, {counts['fp']} FP, {counts['fn']} FN)")
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

    def _add_detect_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
        p.add_argument("--vlm-out", type=Path, default=config.DEFAULT_VLM_OUT,
                       help="Where v3-fast writes result.json + clips/.")
        p.add_argument("--force-v3-fast", action="store_true",
                       help="Re-run v3-fast even if result.json exists.")

    p_detect = sub.add_parser("detect", help="v3-fast (cached) + MuBit filter only.")
    _add_detect_args(p_detect)
    p_detect.set_defaults(func=cmd_detect)

    p_eval = sub.add_parser("eval", help="Detect + match against GT + record outcomes.")
    _add_detect_args(p_eval)
    p_eval.add_argument("--gt", type=Path, default=config.DEFAULT_GT)
    p_eval.add_argument("--tau", type=float, default=config.MATCH_TOLERANCE_S,
                        help="Match tolerance in seconds.")
    p_eval.add_argument("--skip-outcomes", action="store_true",
                        help="Compute metrics but do not record outcomes to MuBit.")
    p_eval.set_defaults(func=cmd_eval)

    p_opt = sub.add_parser("optimize", help="Request a candidate prompt and print diff.")
    p_opt.set_defaults(func=cmd_optimize)

    p_rep = sub.add_parser("report", help="Side-by-side HTML report for two prompt versions.")
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
