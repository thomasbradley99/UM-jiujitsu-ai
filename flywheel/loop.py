"""Run the flywheel without a human in the loop.

Each iteration is:

    spin           — predict + measure + record outcomes
    improve        — ask MuBit's optimizer for a candidate
    activate       — promote the candidate to active

Then repeat. The next `spin` automatically uses the freshly-activated
prompt because `predict` always pulls the latest active version from MuBit.

This is the "set it and watch the F1 climb" entry point. For a careful
demo where you want to eyeball each candidate before activating it, use
`flywheel.cli improve` (no --activate) and approve in the Console.

    python -m flywheel.cli loop --iterations 4
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from flywheel.config import (
    DEFAULT_GT,
    DEFAULT_VIDEO,
    MATCH_TOLERANCE_S,
    OUTPUTS_DIR,
)
from flywheel.improve import main as improve_main
from flywheel.spin import spin


@dataclass
class IterationResult:
    iteration: int
    prompt_version_id: str
    f1: float
    precision: float
    recall: float
    n_gt: int
    n_pred: int
    n_matched: int
    n_hallucinations: int
    counts: dict
    candidate_version_id: str | None = None
    activated: bool = False


def _row(it: IterationResult) -> str:
    cnt = it.counts or {}
    return (
        f"  v{it.iteration:<2}  {it.prompt_version_id[:12]}  "
        f"F1={it.f1*100:5.1f}%  P={it.precision*100:5.1f}%  R={it.recall*100:5.1f}%  "
        f"matched={it.n_matched}/{it.n_gt}  halluc={it.n_hallucinations}  "
        f"(TP={cnt.get('tp', 0)}, FP={cnt.get('fp', 0)}, FN={cnt.get('fn', 0)})"
    )


def loop(
    video: Path,
    gt: Path,
    *,
    iterations: int = 4,
    tau: float = MATCH_TOLERANCE_S,
) -> list[IterationResult]:
    """Run `iterations` rotations of spin → improve → activate."""
    results: list[IterationResult] = []

    for i in range(1, iterations + 1):
        print()
        print("#" * 72)
        print(f"# ITERATION {i}/{iterations}")
        print("#" * 72)

        meta = spin(video, gt, tau=tau)
        metrics = meta.get("metrics") or {}
        counts = meta.get("counts") or {}

        result = IterationResult(
            iteration=i,
            prompt_version_id=meta["prompt_version_id"],
            f1=metrics.get("f1", 0.0),
            precision=metrics.get("precision", 0.0),
            recall=metrics.get("recall", 0.0),
            n_gt=metrics.get("n_gt", 0),
            n_pred=metrics.get("n_pred", 0),
            n_matched=metrics.get("n_matched", 0),
            n_hallucinations=metrics.get("n_hallucinations", 0),
            counts=counts,
        )
        results.append(result)

        # Skip improve on the last iteration — we just want the final
        # measurement, not another candidate that won't be evaluated.
        if i == iterations:
            break

        print()
        improve_resp = improve_main(auto_activate=True)
        result.candidate_version_id = improve_resp.get("candidate_version_id")
        result.activated = improve_resp.get("activated", False)

        if not result.activated:
            print(
                "\n⚠️  optimizer did not return an activatable candidate "
                "— stopping the loop early."
            )
            break

    print()
    print("=" * 72)
    print("FLYWHEEL ARC")
    print("=" * 72)
    for r in results:
        print(_row(r))
    print("=" * 72)

    arc_path = OUTPUTS_DIR / "loop_arc.json"
    arc_path.parent.mkdir(parents=True, exist_ok=True)
    arc_path.write_text(
        json.dumps(
            [
                {
                    "iteration": r.iteration,
                    "prompt_version_id": r.prompt_version_id,
                    "f1": r.f1,
                    "precision": r.precision,
                    "recall": r.recall,
                    "n_gt": r.n_gt,
                    "n_pred": r.n_pred,
                    "n_matched": r.n_matched,
                    "n_hallucinations": r.n_hallucinations,
                    "counts": r.counts,
                    "candidate_version_id": r.candidate_version_id,
                    "activated": r.activated,
                }
                for r in results
            ],
            indent=2,
        )
    )
    print(f"\nWrote {arc_path}")
    return results


if __name__ == "__main__":
    loop(DEFAULT_VIDEO, DEFAULT_GT)
