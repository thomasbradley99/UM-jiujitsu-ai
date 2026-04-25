"""All MuBit SDK calls live here. Nothing else in flywheel/ imports `mubit`.

The flywheel touches MuBit in exactly four places:

  1. setup       → `find_agent`, `create_agent`
  2. predict     → `get_active_prompt`
  3. feedback    → `archive_event`, `record_outcome`
  4. improve     → `request_optimization`, `get_prompt_diff`

Everything else (video processing, scoring, HTML reporting) is plain Python
in this folder. This isolation makes it easy to swap MuBit out, mock it in
tests, or read what the integration actually does — it's just one file.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

from flywheel.config import AGENT_ID, PROJECT_ID, REPO_ROOT


@lru_cache(maxsize=1)
def _client():
    """Lazy MuBit Client. Loaded on first use so importing this module is cheap."""
    load_dotenv(REPO_ROOT / ".env.local")
    api_key = os.environ.get("MUBIT_API_KEY")
    if not api_key:
        raise SystemExit(
            "MUBIT_API_KEY missing. Add it to .env.local at the repo root."
        )
    from mubit import Client  # imported lazily; keeps this module light
    return Client(api_key=api_key)


# ---- 1. setup -------------------------------------------------------------


def find_agent() -> dict | None:
    """Return the existing agent definition, or None if not yet created."""
    resp = _client().advanced.list_agent_definitions(project_id=PROJECT_ID)
    agents = resp.get("agents", []) if isinstance(resp, dict) else []
    return next((a for a in agents if a.get("agent_id") == AGENT_ID), None)


def create_agent(*, role: str, description: str, system_prompt: str) -> dict:
    """Create the agent and seed its v1 prompt. Call once."""
    return _client().advanced.create_agent_definition(
        project_id=PROJECT_ID,
        agent_id=AGENT_ID,
        role=role,
        description=description,
        system_prompt_content=system_prompt,
    )


# ---- 2. predict -----------------------------------------------------------


def get_active_prompt() -> tuple[str, str]:
    """Return `(prompt_text, version_id)` for the currently active prompt.

    The SDK shape is `{"version": {"content": ..., "version_id": ...}}`. We
    fail loud if either field is empty rather than silently running with
    no rules.
    """
    resp = _client().advanced.get_prompt(agent_id=AGENT_ID)
    obj = resp.get("version") if isinstance(resp, dict) else None
    if not isinstance(obj, dict):
        raise RuntimeError(
            f"unexpected get_prompt response shape: {type(resp).__name__} -> {resp!r}"
        )
    content = str(obj.get("content") or "")
    version_id = str(obj.get("version_id") or "")
    if not content or not version_id:
        raise RuntimeError(
            f"MuBit returned an empty prompt for agent {AGENT_ID!r}. "
            f"Run `python -m flywheel.cli setup` first."
        )
    return content, version_id


# ---- 3. feedback ----------------------------------------------------------


def archive_event(
    run_id: str,
    *,
    content: str,
    kind: str,
    labels: list[str],
) -> str:
    """Archive a per-event artifact. Returns its `reference_id`."""
    resp = _client().archive(
        session_id=run_id,
        agent_id=AGENT_ID,
        content=content,
        artifact_kind=kind,
        labels=labels,
    )
    return (resp.get("reference_id") if isinstance(resp, dict) else None) or ""


def record_outcome(
    run_id: str,
    reference_id: str,
    *,
    success: bool,
    signal: float,
    rationale: str,
) -> None:
    """Record an outcome against an archived event. The optimizer reads `rationale`."""
    _client().record_outcome(
        session_id=run_id,
        reference_id=reference_id,
        outcome="success" if success else "failure",
        signal=signal,
        rationale=rationale,
        agent_id=AGENT_ID,
    )


# ---- 4. improve -----------------------------------------------------------


def request_optimization() -> dict:
    """Ask MuBit's LLM optimizer for a candidate prompt informed by recent outcomes.

    The candidate stays in `pending` state until a human (or `activate_version`)
    promotes it.
    """
    return _client().optimize_prompt(agent_id=AGENT_ID, project_id=PROJECT_ID)


def activate_version(version_id: str) -> dict:
    """Promote `version_id` to active for this agent.

    Used by `flywheel.cli loop` to run the wheel without a human gating
    every iteration. For a careful demo, use `flywheel.cli improve` (no
    --activate) and approve in the Console instead.
    """
    return _client().advanced.activate_prompt_version(
        agent_id=AGENT_ID,
        version_id=version_id,
    )


def get_prompt_diff(version_a: str, version_b: str) -> str:
    """Plain-text diff between two prompt versions for the same agent."""
    resp = _client().advanced.get_prompt_diff(
        agent_id=AGENT_ID,
        version_a_id=version_a,
        version_b_id=version_b,
    )
    if isinstance(resp, dict):
        return resp.get("diff_text", "") or ""
    return str(resp)
