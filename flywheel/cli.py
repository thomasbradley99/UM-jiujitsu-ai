"""Single CLI entry point for the flywheel.

Subcommands map 1:1 to the steps:

    python -m flywheel.cli setup        Provision the agent in MuBit (one-time).
    python -m flywheel.cli spin         One rotation: predict → measure → feedback.
    python -m flywheel.cli improve      Ask MuBit's optimizer for a candidate prompt.
    python -m flywheel.cli loop         Self-driving N-iteration arc (no human gate).
    python -m flywheel.cli report       Render side-by-side HTML for two prompt versions.

`improve` proposes a candidate; you approve it in the MuBit Console, then
`spin` again. `loop` collapses that into a tight self-driving cycle
(spin → improve --activate → spin → …) for headless demos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flywheel import config

# Force line-buffered stdout/stderr so the loop's iteration markers, F1
# tables, and FLYWHEEL ARC stream live during long runs instead of getting
# block-buffered behind the analyze.py subprocess output. PYTHONUNBUFFERED
# would only work if set before Python started; reconfigure() works after.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass


def cmd_setup(_args: argparse.Namespace) -> None:
    from flywheel.setup import main as setup_main
    setup_main()


def cmd_spin(args: argparse.Namespace) -> None:
    from flywheel.spin import spin
    spin(
        args.video, args.gt,
        tau=args.tau,
        force=args.force,
        skip_feedback=args.skip_feedback,
    )


def cmd_improve(args: argparse.Namespace) -> None:
    from flywheel.improve import main as improve_main
    improve_main(auto_activate=args.activate)


def cmd_loop(args: argparse.Namespace) -> None:
    from flywheel.loop import loop
    loop(args.video, args.gt, iterations=args.iterations, tau=args.tau)


def cmd_report(args: argparse.Namespace) -> None:
    from flywheel.report import render
    run_id = args.run_id or config.run_id_for_video(args.video)
    render(
        run_id=run_id,
        version_a=args.version_a,
        version_b=args.version_b,
        label_a=args.label_a,
        label_b=args.label_b,
    )


def cmd_arc(args: argparse.Namespace) -> None:
    from flywheel.render_arc import parse_log, render, SUMMARIES_PATH
    import json as _json

    if args.log:
        if not args.log.exists():
            raise SystemExit(f"log not found: {args.log}")
        summaries = parse_log(args.log)
        SUMMARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARIES_PATH.write_text(_json.dumps(summaries, indent=2))
        print(f"Wrote {SUMMARIES_PATH}  ({len(summaries)} entries)")
    render(args.run_id)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flywheel.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup", help="Provision the agent in MuBit (one-time).")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("spin", help="One rotation: predict → measure → feedback.")
    sp.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    sp.add_argument("--gt",    type=Path, default=config.DEFAULT_GT)
    sp.add_argument("--tau", type=float, default=config.MATCH_TOLERANCE_S,
                    help="Match tolerance, seconds.")
    sp.add_argument("--force", action="store_true",
                    help="Re-run analyze.py even if result.json is cached "
                         "for this prompt version.")
    sp.add_argument("--skip-feedback", action="store_true",
                    help="Compute metrics but don't record outcomes to MuBit.")
    sp.set_defaults(func=cmd_spin)

    sp = sub.add_parser("improve", help="Ask MuBit for a candidate prompt.")
    sp.add_argument("--activate", action="store_true",
                    help="Auto-promote the candidate to active (skip human approval).")
    sp.set_defaults(func=cmd_improve)

    sp = sub.add_parser(
        "loop",
        help="Self-driving arc: spin → improve --activate → spin → …",
    )
    sp.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    sp.add_argument("--gt",    type=Path, default=config.DEFAULT_GT)
    sp.add_argument("--iterations", type=int, default=4,
                    help="Number of spin/improve rotations (default 4).")
    sp.add_argument("--tau", type=float, default=config.MATCH_TOLERANCE_S,
                    help="Match tolerance, seconds.")
    sp.set_defaults(func=cmd_loop)

    sp = sub.add_parser("report", help="Side-by-side HTML for two prompt versions.")
    sp.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO,
                    help="Used to derive run_id when --run-id is not provided.")
    sp.add_argument("--run-id")
    sp.add_argument("--version-a", required=True, help="Prompt version_id for left column.")
    sp.add_argument("--version-b", required=True, help="Prompt version_id for right column.")
    sp.add_argument("--label-a", default="v1")
    sp.add_argument("--label-b", default="v2")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser(
        "arc",
        help="Render the full N-iteration arc as one HTML page (uses outputs/loop_arc.json).",
    )
    sp.add_argument("--run-id", default="verify:video")
    sp.add_argument("--log", type=Path, default=None,
                    help="Path to the loop's terminal log to refresh optimizer notes.")
    sp.set_defaults(func=cmd_arc)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
