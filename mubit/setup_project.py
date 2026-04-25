"""One-time project + agent provisioning.

Idempotent: if AGENT_ID already exists in PROJECT_ID, this no-ops.
Run once before the first detect/eval cycle:

    python -m mubit.setup_project
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from mubit.config import AGENT_ID, PROJECT_ID, PROMPTS_DIR, REPO_ROOT


def main() -> None:
    load_dotenv(REPO_ROOT / ".env.local")

    api_key = os.environ.get("MUBIT_API_KEY")
    if not api_key:
        raise SystemExit(
            "MUBIT_API_KEY missing. Add it to .env.local at the repo root."
        )

    from mubit import Client

    client = Client(api_key=api_key)

    existing_agents = client.list_agent_definitions(project_id=PROJECT_ID)
    agents = existing_agents.get("agents", []) if isinstance(existing_agents, dict) else []
    matching = next((a for a in agents if a.get("agent_id") == AGENT_ID), None)

    if matching:
        print(f"OK: agent '{AGENT_ID}' already exists in project {PROJECT_ID}.")
        print(f"   role: {matching.get('role')!r}")
        print(f"   description: {matching.get('description')!r}")
        return

    prompt_path: Path = PROMPTS_DIR / "submission_v1.md"
    prompt_content = prompt_path.read_text()

    created = client.create_agent_definition(
        project_id=PROJECT_ID,
        agent_id=AGENT_ID,
        role="bjj submission filter",
        description=(
            "Takes candidate submission events from a BJJ video-analysis pipeline "
            "(VLM-gemini/video_processor_v3_fast.py) and decides which represent "
            "real, completed submissions vs hallucinations / attempts / scrambles. "
            "Outputs a strict JSON array with timestamp / technique / attacker / defender."
        ),
        system_prompt_content=prompt_content,
    )
    print(f"Created agent '{AGENT_ID}' in project {PROJECT_ID}.")
    print(created)


if __name__ == "__main__":
    main()
