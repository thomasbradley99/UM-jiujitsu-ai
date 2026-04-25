"""Convert match results into MuBit outcomes.

For each match we:
  1. archive() the prediction or the missed GT entry to get a reference_id
  2. record_outcome() against that reference_id with a signal in [-1, 1]
     and a rationale that the prompt optimizer will read.

The optimizer's quality depends on the *rationale* text more than anything
else — invest in clear, specific rationales.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from mubit.config import AGENT_ID, REPO_ROOT
from mubit.match import Match


def _hms(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def _sig_for_tp(m: Match) -> float:
    conf = m.pred.confidence if m.pred else 0.5
    return max(0.3, min(1.0, 0.4 + conf * 0.6))


def _sig_for_fp(m: Match) -> float:
    conf = m.pred.confidence if m.pred else 0.5
    return -max(0.3, min(1.0, conf))


def _sig_for_fn(m: Match) -> float:
    importance = m.gt.importance if m.gt else 3
    return -max(0.3, min(1.0, importance / 5.0))


def record_outcomes_for_matches(
    matches: list[Match],
    run_id: str,
    agent_id: str = AGENT_ID,
) -> list[dict[str, Any]]:
    """Iterate through matches and emit one (archive + record_outcome) pair each."""
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("MUBIT_API_KEY"):
        raise SystemExit("MUBIT_API_KEY missing.")

    from mubit import Client

    client = Client(api_key=os.environ["MUBIT_API_KEY"])
    out: list[dict[str, Any]] = []

    for m in matches:
        if m.kind == "true_positive":
            assert m.pred is not None and m.gt is not None
            content = (
                f"Submission detected: {m.pred.sub_type} at {_hms(m.pred.timestamp)} "
                f"(attacker={m.pred.attacker}, outcome={m.pred.outcome}, "
                f"confidence={m.pred.confidence:.2f}). "
                f"GT note: {m.gt.title!r} - {m.gt.description!r}."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_prediction_tp",
                labels=["submission", "true_positive", m.pred.sub_type],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            signal = _sig_for_tp(m)
            rationale = (
                f"Correctly detected {m.pred.sub_type} within "
                f"{abs(m.dt or 0):.1f}s of GT. Keep flagging this submission type with this specificity."
            )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="success",
                signal=signal,
                rationale=rationale,
                agent_id=agent_id,
            )
            out.append({"kind": "tp", "reference_id": ref_id, "signal": signal})

        elif m.kind == "false_positive":
            assert m.pred is not None
            content = (
                f"Submission predicted but NOT in GT: {m.pred.sub_type} at "
                f"{_hms(m.pred.timestamp)} (confidence={m.pred.confidence:.2f}, "
                f"attacker={m.pred.attacker})."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_prediction_fp",
                labels=["submission", "false_positive", m.pred.sub_type],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            signal = _sig_for_fp(m)
            rationale = (
                f"Hallucinated submission: predicted {m.pred.sub_type} at "
                f"{_hms(m.pred.timestamp)}, no actual submission attempt within tolerance. "
                "Be more conservative; do not call a submission unless an arm/leg/neck is "
                "clearly isolated and the joint or windpipe is being attacked."
            )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="failure",
                signal=signal,
                rationale=rationale,
                agent_id=agent_id,
            )
            out.append({"kind": "fp", "reference_id": ref_id, "signal": signal})

        elif m.kind == "false_negative":
            assert m.gt is not None
            content = (
                f"GT submission MISSED by the system: {m.gt.sub_type} at "
                f"{_hms(m.gt.timestamp)} (importance={m.gt.importance}). "
                f"GT title: {m.gt.title!r}. GT description: {m.gt.description!r}."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_gt_missed",
                labels=["submission", "false_negative", m.gt.sub_type],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            signal = _sig_for_fn(m)
            rationale = (
                f"Missed a real {m.gt.sub_type} at {_hms(m.gt.timestamp)} "
                f"({m.gt.description!r}). The system should attend more carefully to "
                f"{m.gt.sub_type} setups and finishes; recurring miss of this submission type."
            )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="failure",
                signal=signal,
                rationale=rationale,
                agent_id=agent_id,
            )
            out.append({"kind": "fn", "reference_id": ref_id, "signal": signal})

    return out
