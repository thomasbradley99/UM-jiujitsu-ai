"""Precision / recall / F1 / MAE on submission detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from mubit.match import Match


@dataclass
class Metrics:
    n_gt: int
    n_pred: int
    tp: int
    fp: int
    fn: int
    timestamp_mae: float | None  # mean absolute timestamp error on TP matches
    type_accuracy: float | None  # fraction of TP where sub_type matched
    per_type_recall: dict[str, tuple[int, int]] = field(default_factory=dict)  # canon -> (matched, total)

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0

    def render(self) -> str:
        """Pretty-print summary for terminal."""
        lines = [
            f"GT: {self.n_gt}    Pred: {self.n_pred}",
            f"TP: {self.tp}    FP: {self.fp}    FN: {self.fn}",
            f"Precision: {self.precision:.3f}    Recall: {self.recall:.3f}    F1: {self.f1:.3f}",
        ]
        if self.timestamp_mae is not None:
            lines.append(f"Timestamp MAE (TP only): {self.timestamp_mae:.2f}s")
        if self.type_accuracy is not None:
            lines.append(f"Sub-type accuracy on TP: {self.type_accuracy:.3f}")
        if self.per_type_recall:
            lines.append("Per-type recall:")
            for canon, (matched, total) in sorted(self.per_type_recall.items()):
                rate = matched / total if total else 0.0
                lines.append(f"  {canon:20s}  {matched}/{total}  ({rate:.2f})")
        return "\n".join(lines)


def compute(matches: list[Match]) -> Metrics:
    tp = sum(1 for m in matches if m.kind == "true_positive")
    fp = sum(1 for m in matches if m.kind == "false_positive")
    fn = sum(1 for m in matches if m.kind == "false_negative")

    n_gt = sum(1 for m in matches if m.gt is not None)
    n_pred = sum(1 for m in matches if m.pred is not None)

    tp_dts = [abs(m.dt) for m in matches if m.kind == "true_positive" and m.dt is not None]
    timestamp_mae = mean(tp_dts) if tp_dts else None

    judgable_type = [m for m in matches if m.kind == "true_positive" and m.type_match is not None]
    type_accuracy = (
        sum(1 for m in judgable_type if m.type_match) / len(judgable_type)
        if judgable_type
        else None
    )

    per_type: dict[str, list[int]] = {}
    for m in matches:
        if m.gt is None:
            continue
        bucket = per_type.setdefault(m.gt.sub_type, [0, 0])
        bucket[1] += 1
        if m.kind == "true_positive":
            bucket[0] += 1
    per_type_recall = {k: (v[0], v[1]) for k, v in per_type.items()}

    return Metrics(
        n_gt=n_gt,
        n_pred=n_pred,
        tp=tp,
        fp=fp,
        fn=fn,
        timestamp_mae=timestamp_mae,
        type_accuracy=type_accuracy,
        per_type_recall=per_type_recall,
    )
