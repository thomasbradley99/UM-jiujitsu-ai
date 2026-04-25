"""Metrics for submissions-only eval.

Inputs: a `MatchResult` plus the GT (for fighter alias resolution).
Outputs: a flat dict of numbers + per-event detail rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .load import GroundTruth, resolve_fighter
from .match import MatchResult


@dataclass
class EventDetail:
    gt_t: float | None
    gt_technique: str | None
    gt_submitter: str | None
    pred_t: float | None
    pred_technique: str | None
    pred_submitter_raw: str | None
    pred_submitter_resolved: str | None
    delta_t: float | None
    technique_correct: bool | None
    submitter_correct: bool | None
    status: str  # "matched" | "missed_gt" | "hallucination"


@dataclass
class Report:
    config: str
    tau: float
    n_gt: int
    n_pred: int
    matched: int
    sub_recall: float
    sub_precision: float
    f1: float
    technique_acc: float | None
    submitter_acc: float | None
    timestamp_mae: float | None
    hallucinations: int
    details: list[EventDetail] = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def evaluate(gt: GroundTruth, mr: MatchResult, *, config: str = "baseline") -> Report:
    aliases = gt.fighter_aliases

    technique_hits: list[bool] = []
    submitter_hits: list[bool] = []
    deltas: list[float] = []
    details: list[EventDetail] = []

    for m in mr.matches:
        tech_ok = m.pred.technique == m.gt.technique
        technique_hits.append(tech_ok)

        resolved = resolve_fighter(m.pred.submitter, aliases)
        submitter_ok = (resolved is not None) and (resolved == m.gt.submitter)
        submitter_hits.append(submitter_ok)

        deltas.append(abs(m.delta_t))
        details.append(
            EventDetail(
                gt_t=m.gt.timestamp,
                gt_technique=m.gt.technique,
                gt_submitter=m.gt.submitter,
                pred_t=m.pred.timestamp,
                pred_technique=m.pred.technique,
                pred_submitter_raw=m.pred.submitter,
                pred_submitter_resolved=resolved,
                delta_t=m.delta_t,
                technique_correct=tech_ok,
                submitter_correct=submitter_ok,
                status="matched",
            )
        )

    for g in mr.unmatched_gt:
        details.append(
            EventDetail(
                gt_t=g.timestamp,
                gt_technique=g.technique,
                gt_submitter=g.submitter,
                pred_t=None,
                pred_technique=None,
                pred_submitter_raw=None,
                pred_submitter_resolved=None,
                delta_t=None,
                technique_correct=None,
                submitter_correct=None,
                status="missed_gt",
            )
        )

    for p in mr.unmatched_pred:
        details.append(
            EventDetail(
                gt_t=None,
                gt_technique=None,
                gt_submitter=None,
                pred_t=p.timestamp,
                pred_technique=p.technique,
                pred_submitter_raw=p.submitter,
                pred_submitter_resolved=resolve_fighter(p.submitter, aliases),
                delta_t=None,
                technique_correct=None,
                submitter_correct=None,
                status="hallucination",
            )
        )

    n_gt = len(gt.subs)
    n_pred = len(mr.matches) + len(mr.unmatched_pred)
    matched = len(mr.matches)
    recall = _safe_div(matched, n_gt)
    precision = _safe_div(matched, n_pred)
    f1 = _safe_div(2 * recall * precision, recall + precision)

    return Report(
        config=config,
        tau=mr.tau,
        n_gt=n_gt,
        n_pred=n_pred,
        matched=matched,
        sub_recall=recall,
        sub_precision=precision,
        f1=f1,
        technique_acc=(_safe_div(sum(technique_hits), len(technique_hits)) if technique_hits else None),
        submitter_acc=(_safe_div(sum(submitter_hits), len(submitter_hits)) if submitter_hits else None),
        timestamp_mae=(mean(deltas) if deltas else None),
        hallucinations=len(mr.unmatched_pred),
        details=details,
    )


def format_report(r: Report) -> str:
    """Pretty plain-text report suitable for stdout / a hackathon judge."""

    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x*100:.0f}%"

    def f(x: float | None, suf: str = "") -> str:
        return "—" if x is None else f"{x:.2f}{suf}"

    lines: list[str] = []
    lines.append(f"=== {r.config} (τ={r.tau:.0f}s) ===")
    lines.append(
        f"GT={r.n_gt}  Pred={r.n_pred}  Matched={r.matched}  Hallucinations={r.hallucinations}"
    )
    lines.append(
        f"Recall={pct(r.sub_recall)}  Precision={pct(r.sub_precision)}  F1={pct(r.f1)}"
    )
    lines.append(
        f"TechniqueAcc={pct(r.technique_acc)}  SubmitterAcc={pct(r.submitter_acc)}  "
        f"TimestampMAE={f(r.timestamp_mae, 's')}"
    )

    lines.append("")
    lines.append("per-event detail:")
    header = f"  {'status':<14} {'gt_t':>6} {'tech':<13} {'sub':<8} → {'pred_t':>6} {'tech':<13} {'sub':<14} {'Δt':>5}  ✓tech ✓sub"
    lines.append(header)
    for d in r.details:
        gt_t = "—" if d.gt_t is None else f"{d.gt_t:.0f}s"
        pred_t = "—" if d.pred_t is None else f"{d.pred_t:.0f}s"
        dt = "—" if d.delta_t is None else f"{d.delta_t:+.1f}s"
        tick = lambda b: " " if b is None else ("✓" if b else "✗")  # noqa: E731
        gt_sub = d.gt_submitter or "—"
        pred_sub = (d.pred_submitter_resolved or d.pred_submitter_raw or "—")[:14]
        lines.append(
            f"  {d.status:<14} {gt_t:>6} {(d.gt_technique or '—'):<13} {gt_sub:<8} → "
            f"{pred_t:>6} {(d.pred_technique or '—'):<13} {pred_sub:<14} {dt:>5}  "
            f"  {tick(d.technique_correct)}     {tick(d.submitter_correct)}"
        )

    return "\n".join(lines)
