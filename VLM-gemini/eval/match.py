"""Greedy temporal matching of GT submissions to predicted submissions.

We match within a tolerance window τ. Rather than the optimal Hungarian
assignment, we use the simpler greedy "smallest |Δt| first" — for sub-eval
on 5 GT events that's plenty (and more legible in the report).
"""

from __future__ import annotations

from dataclasses import dataclass

from .load import SubEvent


@dataclass
class Match:
    gt: SubEvent
    pred: SubEvent
    delta_t: float  # pred.timestamp - gt.timestamp


@dataclass
class MatchResult:
    matches: list[Match]
    unmatched_gt: list[SubEvent]
    unmatched_pred: list[SubEvent]
    tau: float


def greedy_match(
    gt_subs: list[SubEvent],
    pred_subs: list[SubEvent],
    tau: float,
) -> MatchResult:
    """Pair each GT sub to the closest predicted sub within ±τ seconds.

    Pairs are chosen greedily by smallest |Δt|; once a prediction is paired
    it cannot be reused. Predictions outside ±τ of every GT become
    hallucinations (unmatched_pred). GTs with no candidate become misses
    (unmatched_gt).
    """
    pairs: list[tuple[float, int, int]] = []  # (|Δt|, gt_idx, pred_idx)
    for gi, g in enumerate(gt_subs):
        for pi, p in enumerate(pred_subs):
            delta = abs(p.timestamp - g.timestamp)
            if delta <= tau:
                pairs.append((delta, gi, pi))

    pairs.sort(key=lambda x: x[0])

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    matches: list[Match] = []
    for _, gi, pi in pairs:
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        matches.append(
            Match(
                gt=gt_subs[gi],
                pred=pred_subs[pi],
                delta_t=pred_subs[pi].timestamp - gt_subs[gi].timestamp,
            )
        )

    unmatched_gt = [g for i, g in enumerate(gt_subs) if i not in used_gt]
    unmatched_pred = [p for i, p in enumerate(pred_subs) if i not in used_pred]
    matches.sort(key=lambda m: m.gt.timestamp)
    return MatchResult(
        matches=matches,
        unmatched_gt=unmatched_gt,
        unmatched_pred=unmatched_pred,
        tau=tau,
    )
