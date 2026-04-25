#!/usr/bin/env python3
"""BJJ submission detector — single coherent pipeline.

Three stages, one prompt that does the actual work:

    Stage 0  fighter profiles      ~10 frames sampled, described, synthesised
    Stage 1  windowed scan          overlapping clips, focused yes/no JSON
    Stage 2  cluster                 dedupe overlapping detections

The Stage-1 prompt is the entire detector. It looks at one short clip and
answers: did a submission finish here, who tapped, what move, when, how
confident. Nothing else. Stage 0 just gives it the two visual descriptors
to anchor on. Stage 2 just merges adjacent positives.

Output: result.json mirroring the subs.json GT shape:

    {
      "video": "...", "duration_sec": <float>,
      "fighters": {"<key>": {"visual": "..."}},
      "submissions": [
        {"timestamp": <float>, "technique": "...", "submitter": "...",
         "submittee": "...", "confidence": "high|medium|low",
         "reasoning": "...", "cluster_size": <int>}
      ],
      "metadata": {...}
    }
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from google.generativeai.types import HarmBlockThreshold, HarmCategory
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODEL = "gemini-2.5-pro"
DEFAULT_WINDOW_SEC = 40.0
DEFAULT_GRID_STEP = 15.0
DEFAULT_CLUSTER_TAU = 20.0
DEFAULT_WORKERS = 16
DEFAULT_PROFILE_FRAMES = 10

CANONICAL_TECHNIQUES = (
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


# ---------------------------------------------------------------------------
# config + utilities
# ---------------------------------------------------------------------------


def get_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        env_path = REPO_ROOT / ".env.local"
        if env_path.exists():
            load_dotenv(env_path)
            api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"GEMINI_API_KEY not in env or {REPO_ROOT / '.env.local'}"
        )
    return api_key


def _safety_settings() -> dict:
    return {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }


def extract_first_json_object(text: str) -> str:
    """Extract first balanced JSON object, tolerating ```fences``` and trailing text."""
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    start = s.find("{")
    if start == -1:
        raise ValueError("no '{' in response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    raise ValueError("unterminated JSON")


def _video_duration(video: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ---------------------------------------------------------------------------
# Stage 0 — fighter profiling
# ---------------------------------------------------------------------------


_PROFILE_FRAME_PROMPT = """Describe the two people in this BJJ training video frame.

Focus on PERMANENT visual features (clothing, body type, hair):
- Rashguard or gi colour and any visible markings
- Body type, hair colour / style, facial hair
- Anything else that makes each person recognisable across the whole video

Format: "Person 1: <description>. Person 2: <description>."
Keep under 40 words."""


_PROFILE_SYNTH_PROMPT = """You have {n} independent descriptions from frames of one BJJ training video.
Synthesise them into TWO consistent fighter profiles.

Descriptions:
{descs}

Output ONLY this JSON (no markdown):
{{
  "fighter1": {{"key": "<2-3 word visual key, ALL CAPS>", "visual": "<one-line visual description>"}},
  "fighter2": {{"key": "<2-3 word visual key, ALL CAPS>", "visual": "<one-line visual description>"}}
}}

Rules:
- `key` is short, all-caps, distinctive (e.g. "BALD", "STRIPED RASH", "WHITE GI"). Used as the fighter's identifier everywhere downstream.
- `visual` is a single sentence describing what makes them recognisable.
- The two keys MUST be distinct.
- Ignore positions / actions / temporary state.
"""


def _extract_profile_frames(video: Path, work_dir: Path, n: int) -> list[Path]:
    """Pull n evenly-spaced frames as JPEGs into work_dir."""
    duration = _video_duration(video)
    work_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        out = work_dir / f"profile_{i:03d}.jpg"
        subprocess.run(
            [
                "ffmpeg", "-ss", f"{t:.2f}", "-i", str(video),
                "-frames:v", "1", "-q:v", "2", str(out),
                "-loglevel", "error", "-y",
            ],
            check=True,
        )
        if out.exists():
            paths.append(out)
    return paths


def _describe_frame(frame_path: Path, model_name: str) -> str:
    model = genai.GenerativeModel(model_name)
    img = Image.open(frame_path)
    resp = model.generate_content(
        [_PROFILE_FRAME_PROMPT, img],
        safety_settings=_safety_settings(),
    )
    return (resp.text or "").strip()


def profile_fighters(
    video: Path, work_dir: Path, model_name: str, n_frames: int
) -> dict:
    """Returns {key: {"visual": str}} ready to drop into the result schema."""
    print(f"\n🎯 Stage 0 — profiling fighters ({n_frames} frames)")
    frames = _extract_profile_frames(video, work_dir / "profile_frames", n_frames)

    descs: list[str] = []
    with ThreadPoolExecutor(max_workers=min(50, len(frames))) as pool:
        futs = {pool.submit(_describe_frame, fp, model_name): fp for fp in frames}
        for fut in as_completed(futs):
            try:
                descs.append(fut.result())
            except Exception as e:
                print(f"   ⚠️ frame failed: {e}")

    descs_text = "\n".join(f"- {d}" for d in descs if d)
    synth_prompt = _PROFILE_SYNTH_PROMPT.format(n=len(descs), descs=descs_text)

    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(
        synth_prompt,
        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
        safety_settings=_safety_settings(),
    )
    parsed = json.loads(extract_first_json_object(resp.text or ""))

    f1 = parsed["fighter1"]
    f2 = parsed["fighter2"]
    fighters = {
        f1["key"]: {"visual": f1["visual"]},
        f2["key"]: {"visual": f2["visual"]},
    }

    # Cleanup frames; we only kept them long enough to describe.
    for fp in frames:
        try:
            fp.unlink()
        except OSError:
            pass

    print(f"   profiled: {' vs '.join(fighters.keys())}")
    return fighters


# ---------------------------------------------------------------------------
# Stage 1 — windowed submission scan
# ---------------------------------------------------------------------------


# The scan prompt is the only prompt that does the actual detection work —
# everything else in this pipeline is plumbing. We split it into four layers
# so the DOMAIN RULES section is externalisable: flywheel/spin.py pulls a
# versioned variant from MuBit and passes it via --domain-rules-file. The
# other three layers (framing, fighter block, output schema) stay locked in
# Python so the optimizer can only change the part that actually encodes
# domain reasoning.
#
#   1. _SCAN_FRAMING                — task framing
#   2. _SCAN_FIGHTER_BLOCK          — which two athletes to track
#   3. _DEFAULT_DOMAIN_RULES        — *** the optimizable layer ***
#   4. _SCAN_OUTPUT_SCHEMA          — JSON contract


_SCAN_FRAMING = """You are scanning a {window_sec}s window of BJJ training footage for a completed submission.

Most {window_sec}s windows will NOT contain a finish — the round may be in
progress, the pair may be off-camera, or it may be between rounds. Be
honest: if no submission, set is_submission=false. False positives are
worse than false negatives."""


_SCAN_FIGHTER_BLOCK = """The two SPECIFIC athletes you are watching:
- {f1_key}: {f1_visual}
- {f2_key}: {f2_visual}

This footage may show OTHER PAIRS rolling alongside the target pair. IGNORE
everyone except the two specific athletes above. Find them first by their
visual descriptors, then track only that pair for the entire clip."""


# *** Optimisable layer ***
# The flywheel rewrites this slab. It owns the domain reasoning for "what
# counts as a finish in BJJ training". May reference {window_sec}; nothing
# else.
_DEFAULT_DOMAIN_RULES = """DOMAIN RULE — BJJ TRAINING ROUND FINISH:
Rounds in training do not end mid-roll without a submission. A submission
is confirmed by ANY of:
  (a) a clear tap (hand/foot tapping mat or partner), OR
  (b) a verbal yield, OR
  (c) the partner being put to sleep, OR
  (d) a RESET signal at the end of an active grappling sequence: pair
      stops, separates, fist bump, both stand up, brief pause before
      restarting. The reset by itself is sufficient evidence — taps are
      often hidden behind bodies or below frame.
Attribute the submission to whoever was applying pressure / had positional
control in the final 3-5 seconds before the reset.

Only return is_submission=false if the clip shows continuous grappling the
entire {window_sec} seconds with NO reset and NO end-of-round behaviour."""


_SCAN_OUTPUT_SCHEMA = """If you see a submission between the target pair:
  SUBMITTER = applied pressure / forced the tap.
  SUBMITTEE = tapped / yielded / was reset.
  technique ∈ {techniques}. Use "other" only if you saw a clear finish but
    cannot identify a specific technique from the list.
  tap_offset_sec = seconds from the START of this clip when the
    tap/finish happens (not the entry, not the setup).

Output ONLY this JSON object, no prose, no markdown:
{{
  "is_submission": <bool>,
  "technique": <one of {techniques}>,
  "submitter": "{f1_key}" or "{f2_key}" or "",
  "submittee": "{f1_key}" or "{f2_key}" or "",
  "tap_offset_sec": <number, 0 if is_submission=false>,
  "confidence": "low" | "medium" | "high",
  "reasoning": "<one sentence: what you actually saw on the target pair>"
}}

If is_submission is false: submitter/submittee = "", technique = "other",
tap_offset_sec = 0."""


def _render_domain_rules(domain_rules: str | None, window_sec: float) -> str:
    """Substitute {window_sec} in the (default or supplied) rules.

    Plain text replacement — not str.format — so a flywheel-supplied prompt
    can contain literal `{` / `}` (e.g. example JSON in the optimizer's
    rewrite) without us teaching the optimizer to escape them.

    Empty / whitespace-only overrides fall back to the default rather than
    silently running with no domain rules.
    """
    raw = (
        _DEFAULT_DOMAIN_RULES
        if domain_rules is None or not domain_rules.strip()
        else domain_rules
    )
    return raw.replace("{window_sec}", str(int(window_sec)))


def _build_scan_prompt(
    fighters: dict, window_sec: float, domain_rules: str | None = None
) -> str:
    keys = list(fighters.keys())
    f1_key, f2_key = keys[0], keys[1]
    framing = _SCAN_FRAMING.format(window_sec=int(window_sec))
    fighter_block = _SCAN_FIGHTER_BLOCK.format(
        f1_key=f1_key, f1_visual=fighters[f1_key]["visual"],
        f2_key=f2_key, f2_visual=fighters[f2_key]["visual"],
    )
    rules = _render_domain_rules(domain_rules, window_sec)
    schema = _SCAN_OUTPUT_SCHEMA.format(
        techniques=list(CANONICAL_TECHNIQUES),
        f1_key=f1_key, f2_key=f2_key,
    )
    return "\n\n".join([framing, fighter_block, rules, schema])


def _generate_windows(duration: float, window_sec: float, step: float) -> list[dict]:
    """Build overlapping windows over [0, duration]. Skip degenerate trailing slivers (<5s)."""
    out: list[dict] = []
    start = 0.0
    while start < duration:
        end = min(start + window_sec, duration)
        if end - start < 5.0:
            break
        out.append({"start": start, "end": end, "duration": end - start})
        start += step
    return out


def _cut_window_clip(video: Path, start: float, duration: float, out_path: Path) -> Path:
    """Re-encode short clips (libx264 veryfast) — `-c copy` snaps to keyframes
    and a 1-2s drift on a 40s window can hide the tap."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-ss", f"{start:.2f}",
            "-i", str(video),
            "-t", f"{duration:.2f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-an",
            str(out_path),
            "-loglevel", "error",
            "-y",
        ],
        check=True,
    )
    return out_path


def _upload_and_wait(clip_path: Path):
    f = genai.upload_file(path=str(clip_path), mime_type="video/mp4")
    while f.state.name == "PROCESSING":
        time.sleep(2)
        f = genai.get_file(f.name)
    if f.state.name != "ACTIVE":
        raise RuntimeError(f"upload state={f.state.name}")
    return f


def scan_window(
    video: Path,
    window: dict,
    prompt: str,
    clips_dir: Path,
    model_name: str,
) -> dict:
    """Cut, upload, query, parse. Returns a row with absolute_timestamp on YES."""
    start = window["start"]
    duration = window["duration"]
    clip = clips_dir / f"win_{int(start):04d}s_{int(duration):02d}s.mp4"

    _cut_window_clip(video, start, duration, clip)
    uploaded = _upload_and_wait(clip)

    model = genai.GenerativeModel(model_name)
    try:
        resp = model.generate_content(
            [uploaded, prompt],
            safety_settings=_safety_settings(),
            generation_config={"response_mime_type": "application/json"},
        )
    finally:
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass

    if not resp.candidates or not getattr(resp, "parts", None):
        return {**window, "error": "safety-blocked", "is_submission": False}

    text = resp.text or ""
    try:
        parsed = json.loads(extract_first_json_object(text))
    except Exception as e:
        return {**window, "error": f"json: {e}", "raw_response": text, "is_submission": False}

    tap_offset = float(parsed.get("tap_offset_sec") or 0)
    return {
        **window,
        "is_submission": bool(parsed.get("is_submission")),
        "technique": parsed.get("technique") or "other",
        "submitter": parsed.get("submitter") or "",
        "submittee": parsed.get("submittee") or "",
        "confidence": parsed.get("confidence") or "low",
        "reasoning": parsed.get("reasoning") or "",
        "tap_offset_sec": tap_offset,
        "absolute_timestamp": start + tap_offset,
        "raw_response": text,
    }


# ---------------------------------------------------------------------------
# Stage 2 — cluster overlapping detections
# ---------------------------------------------------------------------------


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, None: 0, "": 0}


def cluster_detections(rows: list[dict], cluster_tau: float) -> list[dict]:
    """Merge YES detections within ±cluster_tau seconds into one submission.

    Per cluster:
      1. submitter = popular vote
      2. technique = popular vote, preferring non-"other"
      3. timestamp = median absolute_timestamp
      4. confidence/reasoning = highest-confidence row in the cluster
    """
    yes = sorted(
        (r for r in rows if r.get("is_submission")),
        key=lambda r: r.get("absolute_timestamp", 0),
    )

    clusters: list[list[dict]] = []
    for r in yes:
        t = r.get("absolute_timestamp", 0)
        if not clusters:
            clusters.append([r])
            continue
        last = clusters[-1]
        last_ts = sorted(x.get("absolute_timestamp", 0) for x in last)
        last_median = last_ts[len(last_ts) // 2]
        if abs(t - last_median) <= cluster_tau:
            last.append(r)
        else:
            clusters.append([r])

    submissions: list[dict] = []
    for cl in clusters:
        sub_votes: Counter[str] = Counter(
            x.get("submitter") for x in cl if x.get("submitter")
        )
        winning_sub = sub_votes.most_common(1)[0][0] if sub_votes else ""

        tech_specific: Counter[str] = Counter()
        tech_any: Counter[str] = Counter()
        for x in cl:
            tech = x.get("technique") or "other"
            tech_any[tech] += 1
            if tech != "other":
                tech_specific[tech] += 1
        winning_tech = (
            tech_specific.most_common(1)[0][0]
            if tech_specific
            else tech_any.most_common(1)[0][0]
        )

        ts_sorted = sorted(x.get("absolute_timestamp", 0) for x in cl)
        median_ts = ts_sorted[len(ts_sorted) // 2]

        top = max(
            cl,
            key=lambda x: _CONFIDENCE_RANK.get(x.get("confidence"), 0),
        )

        submittee = ""
        for x in cl:
            if x.get("submitter") == winning_sub and x.get("submittee"):
                submittee = x.get("submittee") or ""
                break

        submissions.append(
            {
                "timestamp": round(median_ts, 1),
                "technique": winning_tech,
                "submitter": winning_sub,
                "submittee": submittee,
                "confidence": top.get("confidence"),
                "reasoning": top.get("reasoning"),
                "cluster_size": len(cl),
                "window_starts": [round(x["start"], 1) for x in cl],
            }
        )

    submissions.sort(key=lambda s: s["timestamp"])
    return submissions


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def analyze(
    video: Path,
    out_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    window_sec: float = DEFAULT_WINDOW_SEC,
    grid_step: float = DEFAULT_GRID_STEP,
    cluster_tau: float = DEFAULT_CLUSTER_TAU,
    workers: int = DEFAULT_WORKERS,
    profile_frames: int = DEFAULT_PROFILE_FRAMES,
    keep_clips: bool = False,
    domain_rules: str | None = None,
) -> dict:
    """End-to-end pipeline. Writes <out_dir>/result.json and returns the dict."""
    video = Path(video).resolve()
    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    genai.configure(api_key=get_api_key())

    duration = _video_duration(video)
    print(f"\n🥋 BJJ submission detector")
    print(f"{'=' * 70}")
    print(f"video:       {video.name}  ({duration:.0f}s)")
    print(f"out:         {out_dir}")
    print(f"model:       {model}")
    print(f"window:      {window_sec:.0f}s @ {grid_step:.0f}s stride")
    print(f"cluster:     ±{cluster_tau:.0f}s")
    print(f"workers:     {workers}")
    print(f"{'=' * 70}")

    started = time.time()

    # Stage 0
    fighters = profile_fighters(video, out_dir, model, profile_frames)

    # Stage 1
    windows = _generate_windows(duration, window_sec, grid_step)
    print(f"\n📹 Stage 1 — scanning {len(windows)} windows in parallel")
    rules_label = "default" if domain_rules is None else f"custom ({len(domain_rules)} chars)"
    print(f"   domain_rules: {rules_label}")
    prompt = _build_scan_prompt(fighters, window_sec, domain_rules=domain_rules)
    n_workers = max(1, min(workers, len(windows)))

    rows: list[dict] = []
    stage1_started = time.time()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(scan_window, video, w, prompt, clips_dir, model): w
            for w in windows
        }
        done = 0
        for fut in as_completed(futs):
            w = futs[fut]
            try:
                row = fut.result()
                rows.append(row)
                verdict = "YES" if row.get("is_submission") else "NO "
                tech = row.get("technique") or "—"
                sub = row.get("submitter") or "—"
                conf = row.get("confidence") or "—"
                done += 1
                print(
                    f"  [{done:2}/{len(windows)}] "
                    f"{w['start']:5.0f}-{w['end']:5.0f}s → {verdict}  "
                    f"tech={tech:<13} sub={sub:<14} conf={conf}"
                )
            except Exception as e:
                done += 1
                rows.append({**w, "error": str(e), "is_submission": False})
                print(f"  [{done:2}/{len(windows)}] {w['start']:5.0f}s FAILED: {e}")
    rows.sort(key=lambda r: r.get("start", 0))
    stage1_elapsed = time.time() - stage1_started
    yes_count = sum(1 for r in rows if r.get("is_submission"))
    print(f"\n   {yes_count}/{len(rows)} windows said YES  ({stage1_elapsed:.1f}s)")

    # Stage 2
    print(f"\n🔗 Stage 2 — clustering YES detections (±{cluster_tau:.0f}s)")
    submissions = cluster_detections(rows, cluster_tau)
    print(f"   {len(submissions)} unique submissions after clustering\n")

    elapsed = time.time() - started

    result = {
        "video": video.name,
        "duration_sec": duration,
        "fighters": fighters,
        "submissions": submissions,
        "metadata": {
            "model": model,
            "window_sec": window_sec,
            "grid_step": grid_step,
            "cluster_tau": cluster_tau,
            "workers": n_workers,
            "n_windows": len(windows),
            "n_yes_windows": yes_count,
            "stage1_elapsed_sec": round(stage1_elapsed, 1),
            "total_elapsed_sec": round(elapsed, 1),
            "domain_rules_source": "custom" if domain_rules is not None else "default",
            "all_window_rows": rows,
        },
    }

    out_path = out_dir / "result.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    if not keep_clips:
        for clip in clips_dir.glob("*.mp4"):
            try:
                clip.unlink()
            except OSError:
                pass
        try:
            clips_dir.rmdir()
        except OSError:
            pass

    print(f"{'=' * 70}")
    print(f"✅ DONE  ({elapsed:.0f}s total, {elapsed/60:.1f} min)")
    print(f"💾 wrote {out_path}")
    print(f"{'=' * 70}\n")

    if submissions:
        print("Detected submissions:")
        for s in submissions:
            print(
                f"   • {s['timestamp']:6.1f}s  {s['technique']:<14} "
                f"submitter={s['submitter']:<14} conf={s['confidence']}  "
                f"(cluster_size={s['cluster_size']})"
            )
        print()

    return result


def main() -> None:
    p = argparse.ArgumentParser(
        description="BJJ submission detector. Profiles fighters, scans the "
                    "video in overlapping windows asking one focused "
                    "question per window, clusters overlapping yeses.",
    )
    p.add_argument("video", help="path to input video file")
    p.add_argument(
        "--out-dir",
        default=None,
        help="output directory (default: alongside the video)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--window-sec", type=float, default=DEFAULT_WINDOW_SEC)
    p.add_argument("--grid-step", type=float, default=DEFAULT_GRID_STEP)
    p.add_argument("--cluster-tau", type=float, default=DEFAULT_CLUSTER_TAU)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--profile-frames", type=int, default=DEFAULT_PROFILE_FRAMES)
    p.add_argument(
        "--keep-clips",
        action="store_true",
        help="keep window clips on disk after analysis (default: delete to save space)",
    )
    p.add_argument(
        "--domain-rules-file",
        default=None,
        help="path to a markdown/text file holding the DOMAIN RULES block to "
             "inject into the Stage 1 scan prompt. Replaces the default rules "
             "baked into _DEFAULT_DOMAIN_RULES. Used by flywheel/spin.py to "
             "swap in MuBit-versioned rule variants.",
    )
    args = p.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else video.parent

    domain_rules: str | None = None
    if args.domain_rules_file:
        rules_path = Path(args.domain_rules_file).resolve()
        if not rules_path.exists():
            sys.exit(f"domain rules file not found: {rules_path}")
        domain_rules = rules_path.read_text()
        print(f"📜 loaded domain rules from {rules_path} ({len(domain_rules)} chars)")

    analyze(
        video=video,
        out_dir=out_dir,
        model=args.model,
        window_sec=args.window_sec,
        grid_step=args.grid_step,
        cluster_tau=args.cluster_tau,
        workers=args.workers,
        profile_frames=args.profile_frames,
        keep_clips=args.keep_clips,
        domain_rules=domain_rules,
    )


if __name__ == "__main__":
    main()
