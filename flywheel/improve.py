"""Ask MuBit's optimizer for the next prompt version.

The optimizer is an LLM that reads the recent outcomes (rationales we sent
during `spin`) and proposes a new prompt aimed at fixing the failures it
saw. By default the candidate is held in `pending` state — a human approves
it via the MuBit Console. With `--activate` (or `auto_activate=True`) we
promote the candidate immediately so the next `spin` sees it as active.

    python -m flywheel.improve            # propose only
    python -m flywheel.improve --activate # propose + activate
"""

from __future__ import annotations

import argparse

from flywheel.config import AGENT_ID, PROJECT_ID
from flywheel.mubit_client import (
    activate_version,
    get_active_prompt,
    get_prompt_diff,
    request_optimization,
)


def main(*, auto_activate: bool = False) -> dict:
    """Request a candidate prompt; optionally activate it.

    Returns:
        {
          "candidate_version_id": str | None,
          "active_before": str,
          "active_after": str,
          "summary": str,
          "confidence": float,
          "diff": str,
          "activated": bool,
        }
    """
    print(f"Requesting optimization candidate for agent '{AGENT_ID}'…")
    resp = request_optimization() or {}

    candidate = resp.get("candidate") or {} if isinstance(resp, dict) else {}
    summary = resp.get("optimization_summary") or "(no summary)"
    confidence = float(resp.get("confidence") or 0.0)
    activated_by_server = bool(resp.get("activated"))

    cand_v = (candidate.get("version_id") if isinstance(candidate, dict) else None) or None
    _, active_before = get_active_prompt()

    print()
    print("=" * 72)
    print(f"Optimization summary  (confidence={confidence:.2f}, activated={activated_by_server})")
    print("=" * 72)
    print(summary)
    print("=" * 72)

    diff = ""
    if active_before and cand_v and active_before != cand_v:
        diff = get_prompt_diff(active_before, cand_v) or ""
        print()
        print(f"Diff (active {active_before[:12]}  →  candidate {cand_v[:12]}):")
        print(diff or "(no diff returned)")

    activated = activated_by_server
    if auto_activate and cand_v and not activated_by_server:
        print()
        print(f"Activating candidate {cand_v[:12]} …")
        activate_version(cand_v)
        activated = True

    _, active_after = get_active_prompt()
    if not activated:
        print()
        print(
            f"Approve in the MuBit Console (project {PROJECT_ID}) to activate the candidate.\n"
            f"Then run:  python -m flywheel.cli spin"
        )
    else:
        print(f"\nActive prompt is now: {active_after[:12]} (was {active_before[:12]}).")

    return {
        "candidate_version_id": cand_v,
        "active_before": active_before,
        "active_after": active_after,
        "summary": summary,
        "confidence": confidence,
        "diff": diff,
        "activated": activated,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="flywheel.improve")
    p.add_argument("--activate", action="store_true",
                   help="Auto-promote the candidate to active (skip human approval).")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(auto_activate=args.activate)
