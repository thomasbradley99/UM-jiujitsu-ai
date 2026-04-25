"""CLI: evaluate a single (game, run) pair against its GT subs.json.

Usage:
    python -m VLM-gemini.eval.run_eval \\
        --gt   VLM-gemini/input-data/ryan-thomas/subs.json \\
        --pred VLM-gemini/runs/ryan-thomas/baseline/result.json \\
        --tau  10 \\
        --config baseline

Or the path-shorthand form:
    python VLM-gemini/eval/run_eval.py \\
        VLM-gemini/runs/ryan-thomas/baseline/result.json
(infers gt path as input-data/<game>/subs.json from the run dir name).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Make the script runnable both as `python VLM-gemini/eval/run_eval.py ...`
# and `python -m eval.run_eval ...` from inside VLM-gemini/. When run directly,
# the parent dir (VLM-gemini/) needs to be on sys.path so `eval.<mod>` resolves.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.load import load_gt, load_prediction  # noqa: E402
from eval.match import greedy_match  # noqa: E402
from eval.metrics import evaluate, format_report  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
INPUT_DATA = REPO_ROOT / "VLM-gemini" / "input-data"


def _infer_gt_from_pred(pred_path: Path) -> Path | None:
    """A pred at runs/<game>/<config>/result.json -> input-data/<game>/subs.json."""
    parts = pred_path.resolve().parts
    if "runs" in parts:
        idx = parts.index("runs")
        if idx + 1 < len(parts):
            game = parts[idx + 1]
            candidate = INPUT_DATA / game / "subs.json"
            if candidate.exists():
                return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a v3-fast result against subs.json GT.")
    parser.add_argument(
        "pred",
        nargs="?",
        help="path to result.json (positional shorthand). Alternatively use --pred.",
    )
    parser.add_argument("--pred", dest="pred_kw", help="path to result.json")
    parser.add_argument("--gt", help="path to subs.json (default: inferred from pred path)")
    parser.add_argument(
        "--tau",
        type=float,
        default=10.0,
        help="match tolerance in seconds (default: 10)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="config label for the report header (default: parent dir name of pred)",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        help="optional path to write the full report (with details) as JSON",
    )
    args = parser.parse_args(argv)

    pred_arg = args.pred_kw or args.pred
    if not pred_arg:
        parser.error("must supply pred (positional) or --pred")
    pred_path = Path(pred_arg).resolve()
    if not pred_path.exists():
        parser.error(f"pred not found: {pred_path}")

    if args.gt:
        gt_path = Path(args.gt).resolve()
    else:
        inferred = _infer_gt_from_pred(pred_path)
        if not inferred:
            parser.error(
                "could not infer GT path; pass --gt explicitly. "
                "Expected pred under runs/<game>/<config>/result.json."
            )
        gt_path = inferred

    if not gt_path.exists():
        parser.error(f"gt not found: {gt_path}")

    config_label = args.config or pred_path.parent.name

    gt = load_gt(gt_path)
    pred = load_prediction(pred_path)
    mr = greedy_match(gt.subs, pred.subs, tau=args.tau)
    report = evaluate(gt, mr, config=config_label)

    print(format_report(report))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # asdict handles dataclasses; details are dataclasses too.
        out.write_text(json.dumps(asdict(report), indent=2, default=str))
        print(f"\n💾 wrote full report to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
