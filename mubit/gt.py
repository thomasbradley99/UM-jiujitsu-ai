"""Ground-truth loader.

Expects a JSON file shaped like /eval/gt_template.json. If your GT lives in
a different format, write a one-off converter that emits this shape rather
than trying to make this loader polymorphic.

Canonical shape:
{
  "video": "full-gym-short.mov",
  "duration_s": 281,
  "fighter1_id": "blue gi",
  "fighter2_id": "white gi",
  "events": [
    {
      "timestamp": 12.4,
      "event_type": "submission",
      "who": "fighter1",
      "title": "Armbar",
      "description": "Armbar from closed guard",
      "importance": 4
    },
    ...
  ]
}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mubit.config import SUBMISSION_EVENT_TYPES
from mubit.schema import SUB_TYPES


@dataclass(frozen=True)
class GTSubmission:
    """Normalized GT entry, restricted to submission-relevant events."""

    timestamp: float
    event_type: str
    who: str  # 'fighter1' | 'fighter2' | 'both'
    title: str
    description: str
    importance: int
    sub_type: str  # 'unknown' if we can't infer it from title/description


def _infer_sub_type(title: str, description: str) -> str:
    """Best-effort match against SUB_TYPES based on free text in the GT.

    Returns 'unknown' if no sub_type token appears. We match against the
    canonical names AND a small set of human aliases.
    """
    aliases = {
        "rear_naked_choke": ["rnc", "rear naked", "rear-naked"],
        "guillotine": ["guillotine", "front choke"],
        "armbar": ["armbar", "arm bar", "juji"],
        "kimura": ["kimura"],
        "americana": ["americana", "key lock"],
        "triangle": ["triangle"],
        "omoplata": ["omoplata"],
        "ankle_lock": ["ankle lock", "straight ankle"],
        "knee_bar": ["knee bar", "kneebar"],
        "heel_hook": ["heel hook", "heelhook"],
        "ezekiel": ["ezekiel", "ezequiel"],
        "bow_and_arrow": ["bow and arrow"],
        "north_south_choke": ["north south", "north-south"],
        "gogoplata": ["gogoplata"],
    }
    blob = f"{title} {description}".lower()
    for canon, words in aliases.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", blob):
                return canon
    for canon in SUB_TYPES:
        if canon != "unknown" and canon.replace("_", " ") in blob:
            return canon
    return "unknown"


def load_submission_gt(path: Path) -> list[GTSubmission]:
    """Load GT JSON and return only the submission-relevant events."""
    raw = json.loads(Path(path).read_text())
    events: Iterable[dict] = raw.get("events", [])
    out: list[GTSubmission] = []
    for ev in events:
        if ev.get("event_type") not in SUBMISSION_EVENT_TYPES:
            continue
        title = str(ev.get("title", ""))
        desc = str(ev.get("description", ""))
        out.append(
            GTSubmission(
                timestamp=float(ev["timestamp"]),
                event_type=str(ev["event_type"]),
                who=str(ev.get("who", "fighter1")),
                title=title,
                description=desc,
                importance=int(ev.get("importance", 3)),
                sub_type=_infer_sub_type(title, desc),
            )
        )
    out.sort(key=lambda g: g.timestamp)
    return out


def gt_summary(gt: list[GTSubmission]) -> str:
    """One-line summary used in CLI output."""
    types = sorted({g.sub_type for g in gt})
    return f"{len(gt)} GT submissions across types: {', '.join(types) or '(none)'}"
