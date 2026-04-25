#!/usr/bin/env python3
"""
Generate jiu-jitsu/MMA timeline events JSON using Gemini 2.5.

Input: a local MP4 (path), optional fighter names/styles, and chunk size.
Output: JSON array of events compatible with the web app IMPORT/EXPORT flow:
  [{ "timestamp": <float seconds>, "title": <str>, "description": <str> }, ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any

import google.generativeai as genai

from .env import load_env_multisource, require


@dataclass
class Fighter:
    name: str | None = None
    style: str | None = None

    def format_line(self, label: str) -> str:
        name = self.name or label
        style = f" ({self.style})" if self.style else ""
        return f"{name}{style}"


def upload_video_file(path: Path):
    file = genai.upload_file(str(path))
    # Poll until ACTIVE
    import time
    while getattr(file, 'state', None) and getattr(file.state, 'name', '') == 'PROCESSING':
        time.sleep(1)
        file = genai.get_file(file.name)
    if getattr(file, 'state', None) and getattr(file.state, 'name', '') == 'FAILED':
        raise RuntimeError('Video upload failed to process')
    return file


def chunk_prompts(f1: Fighter, f2: Fighter, start: int, end: int) -> str:
    return (
        f"Jiu-jitsu analysis. Analyze ONLY {start}-{end}s of this fight.\n"
        f"Return up to 3 KEY EVENTS as a STRICT JSON array (no prose, no fences).\n"
        f"Each event: {{ \"timestamp\": <ABSOLUTE seconds>, \"title\": <short>, \"description\": <one sentence> }}.\n\n"
        f"FIGHTER NAMING: Describe fighters by clothing. Choose TWO SINGLE, DISTINCT identifiers (e.g., 'Blue rashguard' and 'Black shorts').\n"
        f"Stick to EXACTLY those two identifiers consistently in EVERY event. Do not invent names.\n\n"
        f"CONTENT FOCUS (be precise, no speculation):\n"
        f"- Positions and transitions (closed guard, half guard, mount, back control, side control).\n"
        f"- Attempts: submissions (armbar, RNC, guillotine, triangle), sweeps, passes, takedowns.\n"
        f"- Defenses/escapes: frames, hip escape, posture, underhooks, head control.\n"
        f"- Control direction: who initiates, who counters, outcomes (attempt succeeds/fails).\n"
        f"- Include small mechanics when visible (grips, hooks, knee slice, cross-face).\n\n"
        f"TIMING: Use ABSOLUTE seconds from the START of the full video, not segment-relative.\n"
        f"OUTPUT: JSON array only. No commentary outside JSON."
    )


def run(video_path: Path, out_path: Path, fighter1: Fighter, fighter2: Fighter, segment_seconds: int, max_segments: int) -> List[Dict[str, Any]]:
    load_env_multisource()
    api_key = require('GEMINI_API_KEY')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-pro')

    # Upload video once and reuse handle in prompts
    uploaded = upload_video_file(video_path)

    # Probe duration via ffprobe if available; else, assume 10 min cap and let user set segments
    duration = None
    try:
        import subprocess, json as _json
        res = subprocess.run([
            'ffprobe','-v','error','-show_entries','format=duration','-of','json',str(video_path)
        ], capture_output=True, text=True, check=True)
        info = _json.loads(res.stdout)
        duration = int(float(info['format']['duration']))
    except Exception:
        pass

    # Segment plan
    if duration is None:
        duration = segment_seconds * max_segments
    total_segments = max(1, min(max_segments, (duration + segment_seconds - 1) // segment_seconds))

    aggregated: List[Dict[str, Any]] = []

    for i in range(total_segments):
        start = i * segment_seconds
        end = min(duration, start + segment_seconds)
        prompt = chunk_prompts(fighter1, fighter2, start, end)

        try:
            response = model.generate_content([
                uploaded,
                {"text": prompt}
            ])
            text = (response.text or '').strip()
            # Expect JSON array or attempt to coerce
            try:
                events = json.loads(text)
            except Exception:
                # Loose parse: look for a fenced json block
                if '```json' in text:
                    s = text.find('```json') + 7
                    e = text.find('```', s)
                    events = json.loads(text[s:e].strip())
                else:
                    events = []

            if isinstance(events, dict):
                # Accept { timeline_events: [...] }
                if isinstance(events.get('timeline_events'), list):
                    events = events['timeline_events']
                else:
                    events = []

            if not isinstance(events, list):
                events = []

            # Normalize
            normalized: List[Dict[str, Any]] = []
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                ts = ev.get('timestamp')
                if ts is None:
                    ts = ev.get('start_seconds')
                title = ev.get('title') or ev.get('label') or ev.get('event') or ev.get('type')
                desc = ev.get('description') or ev.get('summary') or (title or '')
                if isinstance(ts, (int, float)) and isinstance(title, str):
                    normalized.append({
                        'timestamp': float(ts),
                        'title': title,
                        'description': desc,
                    })

            # Deduplicate by rounded timestamp + title
            for ev in normalized:
                exists = any(round(x['timestamp']) == round(ev['timestamp']) and x['title'] == ev['title'] for x in aggregated)
                if not exists:
                    aggregated.append(ev)

        except Exception as e:
            print(f"Segment {i+1}/{total_segments} failed: {e}")
            continue

    aggregated.sort(key=lambda x: x['timestamp'])
    # Best-effort cleanup
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(aggregated, indent=2))
    return aggregated


def write_overall_summary(aggregated: List[Dict[str, Any]], out_path: Path, f1: Fighter, f2: Fighter) -> None:
    """Generate a concise technical narrative of the full fight."""
    load_env_multisource()
    api_key = require('GEMINI_API_KEY')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-pro')

    def fmt_ts(sec: float) -> str:
        s = int(round(sec))
        return f"{s//60:02d}:{s%60:02d}"

    lines = [f"- {fmt_ts(e['timestamp'])} {e['title']}: {e['description']}" for e in aggregated]
    context = "\n".join(lines[:400])  # cap context

    prompt = (
        "You are an expert Brazilian jiu-jitsu analyst. Provide a precise, technical summary of this fight.\n"
        "Describe actions for BOTH fighters, using clothing-based identifiers (e.g., 'Blue rashguard', 'Black shorts').\n"
        "Focus on positions, transitions, control, attempts, defenses, and outcomes. Avoid speculation.\n\n"
        f"EVENTS:\n{context}\n\n"
        "Write 2–4 short paragraphs. Keep it concise and high-signal."
    )

    try:
        resp = model.generate_content(prompt)
        text = (resp.text or '').strip()
        out_path.write_text(text)
    except Exception as e:
        out_path.write_text(f"Summary generation failed: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description='Generate MMA/BJJ timeline events JSON using Gemini 2.5.')
    p.add_argument('--video', required=True, help='Path to local MP4')
    p.add_argument('--out', required=True, help='Output JSON path')
    p.add_argument('--f1', default=None, help='Fighter 1 name')
    p.add_argument('--f1-style', default=None, help='Fighter 1 style')
    p.add_argument('--f2', default=None, help='Fighter 2 name')
    p.add_argument('--f2-style', default=None, help='Fighter 2 style')
    p.add_argument('--segment', type=int, default=30, help='Segment size seconds (default 30)')
    p.add_argument('--max-segments', type=int, default=12, help='Max segments to analyze (default 12)')
    args = p.parse_args()

    video = Path(args.video).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        return 2

    f1 = Fighter(args.f1, args.f1_style)
    f2 = Fighter(args.f2, args.f2_style)

    try:
        events = run(video, out_path, f1, f2, args.segment, args.max_segments)
        print(f"Wrote {len(events)} events to {out_path}")
        # Also write an overall summary next to the JSON
        summary_path = out_path.with_suffix('.summary.txt')
        write_overall_summary(events, summary_path, f1, f2)
        print(f"Wrote fight summary to {summary_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())


