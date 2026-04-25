#!/usr/bin/env python3
"""
Analyze each 30s clip with Gemini 2.5 Pro and write per-clip JSON.
Output per clip: {"timestamp":"MM:SS","start_seconds":int,"events":[{timestamp,title,description}]} (segment-relative and absolute timestamps)
"""

import argparse
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai

from ..env import load_env_multisource, require


PROMPT = (
    "Jiu-jitsu analysis. Analyze ONLY the frames in this 30s clip.\n"
    "Return a JSON array of up to 3 EVENTS (no prose, no fences).\n"
    "Each event: { \"timestamp\": <RELATIVE seconds from 0 to 30>, \"title\": <short>, \"description\": <one sentence> }.\n"
    "FIGHTER NAMING: Use clothing-based identifiers only (e.g., 'Blue rashguard', 'Black shorts') and be consistent.\n"
    "FOCUS: positions, transitions, attempts (submissions, sweeps, passes, takedowns), defenses/escapes, mechanics (frames, grips, underhooks).\n"
)


def upload_video(path: Path):
    file = genai.upload_file(str(path))
    while getattr(file, 'state', None) and getattr(file.state, 'name', '') == 'PROCESSING':
        time.sleep(1)
        file = genai.get_file(file.name)
    if getattr(file, 'state', None) and getattr(file.state, 'name', '') == 'FAILED':
        raise RuntimeError('Upload failed to process')
    return file


def analyze_clip(model, clip_path: Path, start_seconds: int):
    uploaded = upload_video(clip_path)
    try:
        resp = model.generate_content([uploaded, {"text": PROMPT}])
        text = (resp.text or '').strip()
        try:
            events = json.loads(text)
        except Exception:
            if '```json' in text:
                s = text.find('```json') + 7
                e = text.find('```', s)
                events = json.loads(text[s:e].strip())
            else:
                events = []
        if not isinstance(events, list):
            events = []
        normalized = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            rel = ev.get('timestamp')
            title = ev.get('title') or ev.get('label') or ev.get('event') or ev.get('type')
            desc = ev.get('description') or ev.get('summary') or (title or '')
            if isinstance(rel, (int, float)) and isinstance(title, str):
                normalized.append({
                    'timestamp': float(rel),
                    'title': title,
                    'description': desc,
                    'absolute_seconds': float(start_seconds) + float(rel)
                })
        minutes = start_seconds // 60
        seconds = start_seconds % 60
        return {
            'timestamp': f"{int(minutes):02d}:{int(seconds):02d}",
            'start_seconds': start_seconds,
            'events': normalized
        }
    finally:
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description='Analyze 30s clips with Gemini 2.5 Pro')
    p.add_argument('--clips-dir', required=True, help='Directory with clip_*.mp4 and segments.json')
    p.add_argument('--out-dir', required=True, help='Directory to write per-clip JSON')
    p.add_argument('--max-workers', type=int, default=12)
    args = p.parse_args()

    clips_dir = Path(args.clips_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((clips_dir / 'segments.json').read_text())
    clips = manifest['clips']

    load_env_multisource()
    genai.configure(api_key=require('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-2.5-pro')

    tasks = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        for c in clips:
            clip_path = clips_dir / c['filename']
            out_path = out_dir / (clip_path.stem + '.json')
            if out_path.exists():
                continue
            tasks.append((out_path, ex.submit(analyze_clip, model, clip_path, int(c['start_seconds']))))

        for out_path, fut in tasks:
            try:
                result = fut.result()
                out_path.write_text(json.dumps(result, indent=2))
                print(f"✅ {out_path.name}")
            except Exception as e:
                print(f"❌ {out_path.name}: {e}")

    print(f"Done. Wrote {len([p for p,_ in tasks])} files to {out_dir}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


