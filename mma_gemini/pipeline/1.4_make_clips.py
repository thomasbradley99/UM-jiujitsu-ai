#!/usr/bin/env python3
"""
Make 30s clips (default) from a local fight video, fast and idempotent.
Outputs deterministic names: clip_MMmSSs.mp4 and a segments.json manifest.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path


def ffprobe_duration(video: Path) -> float:
    try:
        res = subprocess.run([
            'ffprobe','-v','quiet','-print_format','json','-show_format',str(video)
        ], capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        return float(data['format']['duration'])
    except Exception:
        return 0.0


def segment_fast(video: Path, out_dir: Path, segment: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_pattern = out_dir / 'temp_clip_%04d.mp4'
    cmd = [
        'ffmpeg',
        '-i', str(video),
        '-f', 'segment',
        '-segment_time', str(segment),
        '-segment_format', 'mp4',
        '-c', 'copy',
        '-reset_timestamps', '1',
        '-segment_start_number', '0',
        '-y', str(tmp_pattern)
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    temp_clips = sorted(out_dir.glob('temp_clip_*.mp4'))
    for i, tmp in enumerate(temp_clips):
        start_seconds = i * segment
        minutes = start_seconds // 60
        seconds = start_seconds % 60
        new_name = out_dir / f"clip_{int(minutes):02d}m{int(seconds):02d}s.mp4"
        tmp.rename(new_name)
    return len(temp_clips)


def main() -> int:
    p = argparse.ArgumentParser(description='Create fixed-length clips from a fight video')
    p.add_argument('--video', required=True, help='Path to input MP4/MOV')
    p.add_argument('--out-dir', required=True, help='Directory to write clips into')
    p.add_argument('--segment', type=int, default=30, help='Segment length seconds (default 30)')
    args = p.parse_args()

    video = Path(args.video).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not video.exists():
        print(f"Video not found: {video}")
        return 2

    print(f"✂️  Clipping {video.name} into {args.segment}s segments …")
    start = time.time()
    count = segment_fast(video, out_dir, args.segment)
    dur = time.time() - start
    print(f"✅ Created {count} clips in {dur:.1f}s")

    # Write manifest
    duration = ffprobe_duration(video)
    clips = []
    for i in range(count):
        start_seconds = i * args.segment
        end_seconds = min(start_seconds + args.segment, int(duration) if duration else start_seconds + args.segment)
        minutes = start_seconds // 60
        seconds = start_seconds % 60
        clips.append({
            'filename': f"clip_{int(minutes):02d}m{int(seconds):02d}s.mp4",
            'start_seconds': start_seconds,
            'end_seconds': end_seconds,
            'duration': end_seconds - start_seconds,
            'timestamp': f"{int(minutes):02d}:{int(seconds):02d}"
        })
    manifest = {
        'video': str(video),
        'segment_seconds': args.segment,
        'video_duration_seconds': duration,
        'total_clips': count,
        'clips': clips,
    }
    (out_dir / 'segments.json').write_text(json.dumps(manifest, indent=2))
    print(f"📄 Manifest: {out_dir/'segments.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


