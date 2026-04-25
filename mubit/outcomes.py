"""Convert a VLM-gemini.eval Report into MuBit outcome calls.

For each EventDetail in the report we:
  1. archive() a short artifact describing what happened (TP / FP / FN)
  2. record_outcome() against that reference_id with a signal in [-1, 1]
     and a rationale that the prompt optimizer will read.

The optimizer's quality hinges on the *rationale text*. Be specific: name
the technique, reference the timestamp, and tell the prompt what to do
differently next time.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from mubit.config import AGENT_ID, REPO_ROOT


# --- signal helpers ---------------------------------------------------------


def _hms(t: float | None) -> str:
    if t is None:
        return "—"
    m, s = divmod(float(t), 60)
    return f"{int(m):02d}:{s:05.2f}"


def _signal_for_match(detail) -> float:
    """+0.4..+1.0 depending on how clean the match was."""
    base = 0.5
    if detail.technique_correct:
        base += 0.25
    if detail.submitter_correct:
        base += 0.15
    # Penalise sloppy timestamps a little.
    if detail.delta_t is not None and abs(detail.delta_t) > 5:
        base -= 0.1
    return max(0.3, min(1.0, base))


def _signal_for_hallucination() -> float:
    return -0.7


def _signal_for_miss() -> float:
    return -0.85


# --- main entry point -------------------------------------------------------


def record_outcomes_for_report(
    report,
    run_id: str,
    *,
    agent_id: str = AGENT_ID,
) -> list[dict[str, Any]]:
    """Emit one (archive + record_outcome) pair per EventDetail in `report`.

    `report` is an instance of VLM-gemini/eval/metrics.py:Report.
    """
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("MUBIT_API_KEY"):
        raise SystemExit("MUBIT_API_KEY missing.")

    from mubit import Client  # noqa: WPS433

    client = Client(api_key=os.environ["MUBIT_API_KEY"])
    out: list[dict[str, Any]] = []

    for d in report.details:
        if d.status == "matched":
            tech_tick = "✓" if d.technique_correct else "✗"
            sub_tick = "✓" if d.submitter_correct else "✗"
            content = (
                f"TP — predicted {d.pred_technique} at {_hms(d.pred_t)} "
                f"matches GT {d.gt_technique} at {_hms(d.gt_t)} "
                f"(Δt={d.delta_t:+.1f}s, technique {tech_tick}, attacker {sub_tick})."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_prediction_tp",
                labels=["submission", "true_positive", d.gt_technique or "other"],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            signal = _signal_for_match(d)
            rationale_bits = [
                f"Correctly detected {d.gt_technique} at {_hms(d.gt_t)} "
                f"(within {abs(d.delta_t or 0):.1f}s of GT). Keep this behavior."
            ]
            if not d.technique_correct:
                rationale_bits.append(
                    f"BUT mis-classified the technique as {d.pred_technique}; the correct "
                    f"canonical name is {d.gt_technique}. Be strict about technique names."
                )
            if not d.submitter_correct:
                rationale_bits.append(
                    f"BUT attributed the submission to the wrong fighter "
                    f"({d.pred_submitter_raw!r}); should be {d.gt_submitter}. "
                    "Use the fighter descriptor verbatim from the input event."
                )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="success",
                signal=signal,
                rationale=" ".join(rationale_bits),
                agent_id=agent_id,
            )
            out.append({"kind": "tp", "reference_id": ref_id, "signal": signal})

        elif d.status == "hallucination":
            content = (
                f"FP — predicted {d.pred_technique} at {_hms(d.pred_t)} "
                f"with no GT submission within tolerance. Likely a scramble, "
                f"position change, or sub attempt that did not finish."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_prediction_fp",
                labels=["submission", "false_positive", d.pred_technique or "other"],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            rationale = (
                f"Hallucinated submission: kept a candidate event at {_hms(d.pred_t)} "
                f"({d.pred_technique}) that turned out NOT to be a real, completed submission. "
                "Tighten the filter: require either an explicit tap, a clearly isolated "
                "joint or windpipe under attack, or a description that includes 'taps' / "
                "'finished'. Drop attempts, scrambles, and position changes."
            )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="failure",
                signal=_signal_for_hallucination(),
                rationale=rationale,
                agent_id=agent_id,
            )
            out.append({"kind": "fp", "reference_id": ref_id, "signal": _signal_for_hallucination()})

        elif d.status == "missed_gt":
            content = (
                f"FN — GT submission MISSED: {d.gt_technique} at {_hms(d.gt_t)} "
                f"by {d.gt_submitter}. The pipeline either didn't surface this as "
                f"a candidate or the filter incorrectly rejected it."
            )
            archived = client.archive(
                session_id=run_id,
                agent_id=agent_id,
                content=content,
                artifact_kind="sub_gt_missed",
                labels=["submission", "false_negative", d.gt_technique or "other"],
            )
            ref_id = (archived.get("reference_id") if isinstance(archived, dict) else None) or ""
            rationale = (
                f"Missed a real {d.gt_technique} at {_hms(d.gt_t)}. Possible causes: "
                f"(a) the v3-fast pipeline didn't flag it as a candidate, "
                f"(b) the filter discarded it because the candidate had attempt=true "
                f"or completed=false. If candidates with technique={d.gt_technique} "
                "are appearing in the input, keep them when title or description "
                "includes the technique name even if attempt flags are inconsistent."
            )
            client.record_outcome(
                run_id=run_id,
                reference_id=ref_id,
                outcome="failure",
                signal=_signal_for_miss(),
                rationale=rationale,
                agent_id=agent_id,
            )
            out.append({"kind": "fn", "reference_id": ref_id, "signal": _signal_for_miss()})

    return out
