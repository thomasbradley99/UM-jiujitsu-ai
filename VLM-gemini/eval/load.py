"""Load + canonicalise GT (subs.json) and pipeline output (result.json).

Both schemas live in input-data/README.md and the v3-fast pipeline output spec
(see VLM-gemini/video_processor_v3_fast.py). This module turns both into a
single uniform shape the matcher and metrics can consume.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Canonical technique vocabulary (from input-data/README.md).
CANONICAL_TECHNIQUES: tuple[str, ...] = (
    "armbar",
    "rnc",
    "triangle",
    "arm_triangle",
    "americana",
    "kimura",
    "guillotine",
    "omoplata",
    "smother",
    "other",
)


# Free-text -> canonical technique. Order matters: earlier patterns win on
# ambiguous strings (e.g. "rear naked choke" before "choke" -> guillotine fallback).
_TECHNIQUE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brear[- ]?naked\b|\brnc\b", "rnc"),
    (r"\barm[- ]?triangle\b|\bkata[- ]?gatame\b", "arm_triangle"),
    (r"\btriangle\b", "triangle"),
    (r"\barm[- ]?bar\b", "armbar"),
    (r"\bamericana\b|\bkey ?lock\b|\bv1\b", "americana"),
    (r"\bkimura\b", "kimura"),
    (r"\bguillotine\b", "guillotine"),
    (r"\bomoplata\b", "omoplata"),
    (r"\bsmother\b", "smother"),
    (r"\bbow ?and ?arrow\b", "rnc"),  # bow & arrow is an RNC variant
)


def canonicalize_technique(text: str | None) -> str:
    """Map a free-text technique description to one of CANONICAL_TECHNIQUES."""
    if not text:
        return "other"
    s = text.lower()
    for pattern, canonical in _TECHNIQUE_PATTERNS:
        if re.search(pattern, s):
            return canonical
    return "other"


# ---------- canonical event shape used by match.py / metrics.py ----------


@dataclass(frozen=True)
class SubEvent:
    """A single submission event (GT or predicted), in canonical shape."""

    timestamp: float
    technique: str  # canonical token
    submitter: str  # canonical fighter id (see GT.fighter_aliases)
    submittee: str | None
    raw: dict = field(repr=False, compare=False, default_factory=dict)


@dataclass
class GroundTruth:
    """Parsed subs.json.

    `fighter_tokens[KEY]` is the set of distinctive tokens we'll match the AI's
    free-text fighter descriptors against. For a key like "BALD" with visual
    "bald, black rashguard", we get tokens {"BALD", "BLACK"} (RASHGUARD/GI etc.
    are stripped as too generic to disambiguate).
    """

    video_id: str
    duration_sec: float
    fighter_keys: list[str]
    fighter_tokens: dict[str, set[str]]
    subs: list[SubEvent]
    raw: dict = field(repr=False, compare=False, default_factory=dict)


@dataclass
class Prediction:
    """Parsed result.json subset relevant to submissions-only eval."""

    fighter_descriptors: list[str]  # e.g. ["BALD RASHGUARD", "STRIPED RASHGUARD"]
    subs: list[SubEvent]  # `submitter`/`submittee` left as raw AI descriptors
    raw: dict = field(repr=False, compare=False, default_factory=dict)


# ---------- loaders ----------


def _normalise_descriptor(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().upper())


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[A-Z0-9]+", s.upper()) if len(t) > 1}


# Generic tokens that aren't distinctive enough to disambiguate fighters.
_GENERIC_TOKENS = frozenset({
    "FIGHTER", "RASHGUARD", "RASH", "GI", "GUY",
    "PERSON", "ATHLETE", "PLAYER", "GRAPPLER", "BJJ",
})


def _build_fighter_tokens(fighters_block: dict) -> dict[str, set[str]]:
    """Distinctive token set per fighter key.

    Includes: the key itself + every token in `visual`, minus generic tokens.
    """
    tokens: dict[str, set[str]] = {}
    for key, info in fighters_block.items():
        s: set[str] = set()
        s.update(_tokens(key))
        visual = (info or {}).get("visual") or ""
        s.update(_tokens(visual))
        s -= _GENERIC_TOKENS
        tokens[key] = s
    return tokens


def resolve_fighter(descriptor: str | None, fighter_tokens: dict[str, set[str]]) -> str | None:
    """Map an AI-emitted fighter descriptor to a canonical GT fighter key.

    Strategy: pick the fighter whose distinctive-token set has the largest
    overlap with the descriptor. Returns None on tie or no overlap.
    """
    if not descriptor:
        return None
    desc_tokens = _tokens(descriptor) - _GENERIC_TOKENS
    if not desc_tokens:
        return None
    best_key: str | None = None
    best_score = 0
    for key, tok_set in fighter_tokens.items():
        score = len(desc_tokens & tok_set)
        if score > best_score:
            best_score = score
            best_key = key
        elif score == best_score and score > 0:
            best_key = None  # tie -> ambiguous
    return best_key


def load_gt(path: str | Path) -> GroundTruth:
    p = Path(path)
    data = json.loads(p.read_text())
    fighters = data.get("fighters", {})
    fighter_tokens = _build_fighter_tokens(fighters)
    subs = [
        SubEvent(
            timestamp=float(s["timestamp"]),
            technique=canonicalize_technique(s.get("technique")),
            submitter=s["submitter"],
            submittee=s.get("submittee"),
            raw=s,
        )
        for s in data.get("submissions", [])
    ]
    return GroundTruth(
        video_id=data.get("video", p.parent.name),
        duration_sec=float(data.get("duration_sec", 0)),
        fighter_keys=list(fighters.keys()),
        fighter_tokens=fighter_tokens,
        subs=subs,
        raw=data,
    )


def _iter_predicted_subs(result: dict) -> Iterable[dict]:
    """Yield raw predicted submission dicts from the v3-fast result.json.

    Two sources in the schema; we union them and dedupe by (rounded_ts, attacker).

    1. events[] with {submission: true, completed: true, attempt: false}
    2. position_timeline.submissions[] with {completed: true}
    """
    seen: set[tuple[int, str]] = set()
    for ev in result.get("events", []) or []:
        if not ev.get("submission"):
            continue
        if ev.get("attempt"):
            continue
        if ev.get("completed") is False:  # accept missing == treat as completed
            continue
        key = (int(round(float(ev.get("timestamp", 0)))), str(ev.get("attacker") or ""))
        if key in seen:
            continue
        seen.add(key)
        yield {
            "timestamp": ev.get("timestamp"),
            "title": ev.get("title") or ev.get("description") or "",
            "attacker": ev.get("attacker"),
            "defender": ev.get("defender"),
            "source": "events",
            "raw": ev,
        }
    pt_subs = (result.get("position_timeline") or {}).get("submissions") or []
    for s in pt_subs:
        if s.get("completed") is False:
            continue
        key = (int(round(float(s.get("timestamp", 0)))), str(s.get("fighter") or ""))
        if key in seen:
            continue
        seen.add(key)
        yield {
            "timestamp": s.get("timestamp"),
            "title": s.get("type") or "",
            "attacker": s.get("fighter"),
            "defender": None,
            "source": "position_timeline",
            "raw": s,
        }


def load_prediction(path: str | Path) -> Prediction:
    p = Path(path)
    data = json.loads(p.read_text())
    fighter_stats = data.get("fighter_stats") or {}
    descriptors = list(fighter_stats.keys())
    subs = [
        SubEvent(
            timestamp=float(s["timestamp"]),
            technique=canonicalize_technique(s.get("title")),
            submitter=str(s.get("attacker") or ""),
            submittee=str(s.get("defender") or "") or None,
            raw=s,
        )
        for s in _iter_predicted_subs(data)
    ]
    return Prediction(fighter_descriptors=descriptors, subs=subs, raw=data)
