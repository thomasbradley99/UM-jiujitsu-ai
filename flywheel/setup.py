"""One-time agent provisioning. Idempotent.

    python -m flywheel.setup

If the agent already exists in PROJECT_ID, this no-ops. Otherwise it creates
the agent and seeds it with `flywheel/prompts/filter_v1.md` as the v1 prompt.
After that, MuBit owns the prompt. We never overwrite from disk again.
"""

from __future__ import annotations

from flywheel.config import AGENT_ID, PROJECT_ID, SEED_PROMPT
from flywheel.mubit_client import create_agent, find_agent


_AGENT_ROLE = "bjj submission filter"
_AGENT_DESCRIPTION = (
    "Takes candidate submission events from a BJJ video-analysis pipeline "
    "(VLM-gemini/video_processor_v3_fast.py) and decides which represent "
    "real, completed submissions vs hallucinations / attempts / scrambles. "
    "Outputs a strict JSON array with timestamp / technique / attacker / defender."
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
