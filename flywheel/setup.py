"""One-time agent provisioning. Idempotent.

    python -m flywheel.setup

If the agent already exists in PROJECT_ID, this no-ops. Otherwise it creates
the agent and seeds it with `flywheel/prompts/verifier_v1.md` as the v1
prompt. After that, MuBit owns the prompt — we never overwrite from disk
again. Subsequent versions come from `flywheel improve` (MuBit's optimizer)
or human edits in the MuBit Console.
"""

from __future__ import annotations

from flywheel.config import AGENT_ID, PROJECT_ID, SEED_PROMPT
from flywheel.mubit_client import create_agent, find_agent


_AGENT_ROLE = "bjj submission detector"
_AGENT_DESCRIPTION = (
    "Owns the DOMAIN RULES layer of the BJJ submission detection prompt "
    "used by VLM-gemini/analyze.py. analyze.py slides a 40s window across "
    "the source video on a 15s stride; for each window the prompt decides "
    "is_submission and (when true) names the technique + submitter. The "
    "framing, fighter block, and JSON output schema stay locked in Python; "
    "only the rules for what counts as a finish in BJJ training are "
    "versioned here. After the windowed scan, analyze.py clusters the YES "
    "windows into a final list of submissions. Outcomes recorded by "
    "flywheel/spin.py (per-cluster TP / FP and per-GT FN against ground "
    "truth) feed the optimizer, which proposes a new rules variant we "
    "approve manually in the MuBit Console."
)


def main() -> None:
    existing = find_agent()
    if existing:
        print(f"OK: agent '{AGENT_ID}' already exists in project {PROJECT_ID}.")
        print(f"   role: {existing.get('role')!r}")
        return

    print(f"Creating agent '{AGENT_ID}' in project {PROJECT_ID}…")
    created = create_agent(
        role=_AGENT_ROLE,
        description=_AGENT_DESCRIPTION,
        system_prompt=SEED_PROMPT.read_text(),
    )
    print("Done.")
    print(created)


if __name__ == "__main__":
    main()
