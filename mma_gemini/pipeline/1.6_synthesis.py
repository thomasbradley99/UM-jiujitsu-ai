#!/usr/bin/env python3
"""
Aggregate per-clip JSON into a single timeline.json for the app.
Deduplicates near-boundary duplicates and sorts chronologically.
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any


def load_clip_jsons(in_dir: Path) -> List[Dict[str, Any]]:
    items = []
    for p in sorted(in_dir.glob('clip_*.json')):
        try:
            data = json.loads(p.read_text())
            items.append(data)
        except Exception:
            continue
    return items


def synthesize(items: List[Dict[str, Any]], dedupe_window: float = 1.5) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for it in items:
        for ev in it.get('events', []):
            ts = float(ev.get('absolute_seconds', ev.get('timestamp', 0)))
            title = ev.get('title')
            desc = ev.get('description', title)
            if isinstance(title, str):
                events.append({'timestamp': ts, 'title': title, 'description': desc})

    events.sort(key=lambda x: x['timestamp'])

    # Simple dedupe: merge events with same title within dedupe_window seconds
    merged: List[Dict[str, Any]] = []
    for ev in events:
        if merged and ev['title'] == merged[-1]['title'] and abs(ev['timestamp'] - merged[-1]['timestamp']) <= dedupe_window:
            # keep the earliest
            continue
        merged.append(ev)

    return merged


def main() -> int:
    p = argparse.ArgumentParser(description='Synthesize per-clip analyses into timeline.json')
    p.add_argument('--clips-out', required=True, help='Directory with per-clip JSON (from 1.5)')
    p.add_argument('--out', required=True, help='Output timeline JSON path')
    args = p.parse_args()

    in_dir = Path(args.clips_out).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    items = load_clip_jsons(in_dir)
    timeline = synthesize(items)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(timeline, indent=2))
    print(f"Wrote {len(timeline)} events to {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


