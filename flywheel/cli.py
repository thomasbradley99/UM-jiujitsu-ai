"""Single CLI entry point for the flywheel.

Subcommands map 1:1 to the steps:

    python -m flywheel.cli setup        Provision the agent in MuBit (one-time).
    python -m flywheel.cli spin         One rotation: predict → measure → feedback.
    python -m flywheel.cli improve      Ask MuBit's optimizer for a candidate prompt.
    python -m flywheel.cli report       Render side-by-side HTML for two prompt versions.

After `improve`, approve the candidate in the MuBit Console — that's the
only manual step. Then `spin` again with the new active prompt.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flywheel import config


def cmd_setup(_args: argparse.Namespace) -> None:
    from flywheel.setup import main as setup_main
    setup_main()


def cmd_spin(args: argparse.Namespace) -> None:
    from flywheel.spin import spin
    spin(
        args.video, args.gt,
        vlm_out=args.vlm_out,
        tau=args.tau,
        force_v3_fast=args.force_v3_fast,
        skip_feedback=args.skip_feedback,
    )


def cmd_improve(_args: argparse.Namespace) -> None:
    from flywheel.improve import main as improve_main
    improve_main()


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flywheel.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup", help="Provision the agent in MuBit (one-time).")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("spin", help="One rotation: predict → measure → feedback.")
    sp.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    sp.add_argument("--gt",    type=Path, default=config.DEFAULT_GT)
    sp.add_argument("--vlm-out", type=Path, default=config.DEFAULT_VLM_OUT,
                    help="Cache dir for v3-fast's result.json.")
    sp.add_argument("--tau", type=float, default=config.MATCH_TOLERANCE_S,
                    help="Match tolerance, seconds.")
    sp.add_argument("--force-v3-fast", action="store_true",
                    help="Re-run v3-fast even if its result.json is cached.")
    sp.add_argument("--skip-feedback", action="store_true",
                    help="Compute metrics but don't record outcomes to MuBit.")
    sp.set_defaults(func=cmd_spin)

    sp = sub.add_parser("improve", help="Ask MuBit for a candidate prompt.")
    sp.set_defaults(func=cmd_improve)

    sp = sub.add_parser("report", help="Side-by-side HTML for two prompt versions.")
    sp.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO,
                    help="Used to derive run_id when --run-id is not provided.")
    sp.add_argument("--run-id")
    sp.add_argument("--version-a", required=True, help="Prompt version_id for left column.")
    sp.add_argument("--version-b", required=True, help="Prompt version_id for right column.")
    sp.add_argument("--label-a", default="v1")
    sp.add_argument("--label-b", default="v2")
    sp.set_defaults(func=cmd_report)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
