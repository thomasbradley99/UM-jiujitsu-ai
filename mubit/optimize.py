"""Trigger a prompt optimization candidate and print the diff.

Does NOT auto-activate. Activation is done via the MuBit Console (Approve)
or by calling client.activate_prompt_version() explicitly.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from mubit.config import AGENT_ID, PROJECT_ID, REPO_ROOT


def request_candidate(llm_override: dict | None = None) -> dict:
    """Ask MuBit for a candidate prompt informed by recent outcomes."""
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("MUBIT_API_KEY"):
        raise SystemExit("MUBIT_API_KEY missing.")

    from mubit import Client

    client = Client(api_key=os.environ["MUBIT_API_KEY"])

    print(f"Requesting optimization candidate for agent '{AGENT_ID}'...")
    kwargs: dict = {"agent_id": AGENT_ID, "project_id": PROJECT_ID}
    if llm_override:
        kwargs["llm_override"] = llm_override
    resp = client.optimize_prompt(**kwargs)

    candidate = resp.get("candidate", {}) if isinstance(resp, dict) else {}
    summary = resp.get("optimization_summary", "(no summary)")
    confidence = resp.get("confidence", 0.0)
    activated = resp.get("activated", False)

    print()
    print("=" * 72)
    print(f"Optimization summary (confidence={confidence:.2f}, activated={activated}):")
    print(summary)
    print("=" * 72)

    active = client.get_prompt(agent_id=AGENT_ID)
    active_v = (active.get("prompt", {}) if isinstance(active, dict) else {}).get("version_id")
    cand_v = candidate.get("version_id")

    if active_v and cand_v:
        diff = client.get_prompt_diff(
            agent_id=AGENT_ID,
            version_a_id=active_v,
            version_b_id=cand_v,
        )
        print()
        print("Diff (active vs candidate):")
        print(diff.get("diff_text", "(no diff returned)") if isinstance(diff, dict) else diff)

    print()
    print(
        f"To activate: open the MuBit Console for project {PROJECT_ID}, "
        f"click 'Review' on the pending-candidate banner, then 'Approve & Activate'.\n"
        f"Or run:  python -c \"from mubit import Client; "
        f"Client().activate_prompt_version(agent_id='{AGENT_ID}', version_id='{cand_v}')\""
    )

    return resp


if __name__ == "__main__":
    request_candidate()
