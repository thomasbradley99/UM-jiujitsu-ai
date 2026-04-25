"""Greedy bipartite matching of predicted submissions to GT submissions.

For each GT entry, find the closest unmatched prediction within
TIMESTAMP_TOLERANCE_S. Ties broken by smaller |dt|, then by higher confidence.

This is intentionally simple. Once we have working metrics we can swap in
proper Hungarian matching, type-conditional matching, or per-event-type
tolerance windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from mubit.config import TIMESTAMP_TOLERANCE_S
from mubit.gt import GTSubmission


@dataclass
class Prediction:
    """One predicted submission from Gemini."""

    timestamp: float
    sub_type: str
    attacker: str
    defender: str
    outcome: str
    confidence: float

    @classmethod
    def from_dict(cls, d: dict) -> "Prediction":
        return cls(
            timestamp=float(d["timestamp"]),
            sub_type=str(d.get("sub_type", "unknown")),
            attacker=str(d.get("attacker", "fighter1")),
            defender=str(d.get("defender", "fighter2")),
            outcome=str(d.get("outcome", "ongoing")),
            confidence=float(d.get("confidence", 0.5)),
        )


@dataclass
class Match:
    """One matched (gt, pred) pair, or one unmatched side."""

    gt: GTSubmission | None
    pred: Prediction | None

    @property
    def kind(self) -> str:
        if self.gt is not None and self.pred is not None:
            return "true_positive"
        if self.gt is not None:
            return "false_negative"  # GT had a sub, system missed it
        return "false_positive"  # system invented a sub

    @property
    def dt(self) -> float | None:
        if self.gt is None or self.pred is None:
            return None
        return self.pred.timestamp - self.gt.timestamp

    @property
    def type_match(self) -> bool | None:
        if self.gt is None or self.pred is None:
            return None
        if self.gt.sub_type == "unknown" or self.pred.sub_type == "unknown":
            return None  # can't judge
        return self.gt.sub_type == self.pred.sub_type


def match_predictions(
    gt: list[GTSubmission],
    predictions: list[Prediction],
    tolerance_s: float = TIMESTAMP_TOLERANCE_S,
) -> list[Match]:
    """Greedy match. Returns one Match per GT entry plus unmatched predictions
    as false positives.
    """
    remaining = list(predictions)
    matches: list[Match] = []

    for g in gt:
        best_idx = -1
        best_dt = float("inf")
        best_conf = -1.0
        for i, p in enumerate(remaining):
            dt = abs(p.timestamp - g.timestamp)
            if dt > tolerance_s:
                continue
            if dt < best_dt or (dt == best_dt and p.confidence > best_conf):
                best_idx = i
                best_dt = dt
                best_conf = p.confidence
        if best_idx >= 0:
            matches.append(Match(gt=g, pred=remaining.pop(best_idx)))
        else:
            matches.append(Match(gt=g, pred=None))

    for p in remaining:
        matches.append(Match(gt=None, pred=p))

    return matches
