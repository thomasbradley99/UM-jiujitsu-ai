"""Ask MuBit's optimizer for the next prompt version.

The optimizer is an LLM that reads the recent outcomes (rationales we sent
during `spin`) and proposes a new prompt aimed at fixing the failures it
saw. The candidate is held in `pending` state — a human approves it via
the MuBit Console (or by calling `client.activate_prompt_version` directly).

    python -m flywheel.improve
"""

from __future__ import annotations

from flywheel.config import AGENT_ID, PROJECT_ID
from flywheel.mubit_client import (
    get_active_prompt,
    get_prompt_diff,
    request_optimization,
)


def main() -> dict:
    print(f"Requesting optimization candidate for agent '{AGENT_ID}'…")
    resp = request_optimization()

    candidate = resp.get("candidate", {}) if isinstance(resp, dict) else {}
    summary = resp.get("optimization_summary", "(no summary)") if isinstance(resp, dict) else ""
    confidence = resp.get("confidence", 0.0) if isinstance(resp, dict) else 0.0
    activated = resp.get("activated", False) if isinstance(resp, dict) else False

    print()
    print("=" * 72)
    print(f"Optimization summary  (confidence={confidence:.2f}, activated={activated})")
    print("=" * 72)
    print(summary)
    print("=" * 72)

    _, active_v = get_active_prompt()
    cand_v = candidate.get("version_id") if isinstance(candidate, dict) else None

    if active_v and cand_v and active_v != cand_v:
        diff = get_prompt_diff(active_v, cand_v)
        print()
        print(f"Diff (active {active_v[:12]}  →  candidate {cand_v[:12]}):")
        print(diff or "(no diff returned)")

    print()
    print(
        f"Approve in the MuBit Console (project {PROJECT_ID}) to activate the candidate.\n"
        f"Then run:  python -m flywheel.cli spin"
    )
    return resp


if __name__ == "__main__":
    main()
