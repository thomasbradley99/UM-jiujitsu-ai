"""Run the MuBit-driven submission detection pipeline on a video.

Two stages:

1. v3-fast pipeline (subprocess) — `VLM-gemini/video_processor_v3_fast.py`
   reads the video and writes `<vlm_out_dir>/result.json` (rich narrative,
   events, position_timeline, fighter_stats). This is slow (minutes per
   video) and doesn't depend on the MuBit prompt — we cache it.

2. submission filter (Gemini text call) — fetch the active prompt for
   AGENT_ID from MuBit, feed it the v3-fast events, get back a canonical
   list of completed submissions. This is fast (seconds) and IS what the
   MuBit optimizer iterates on. Different prompt → different filtered list.

Output: `mubit/outputs/runs/<run_id>/<prompt_version_id>/predicted.json`,
shaped like a v3-fast result.json so VLM-gemini/eval can read it natively.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from mubit.config import (
    AGENT_ID,
    DEFAULT_VLM_OUT,
    GEMINI_FILTER_MODEL,
    OUTPUTS_DIR,
    REPO_ROOT,
    VLM_PROCESSOR,
    run_id_for_video,
)


# --- Stage 1: v3-fast pipeline ----------------------------------------------


def run_v3_fast(video_path: Path, vlm_out_dir: Path, *, force: bool = False) -> Path:
    """Run video_processor_v3_fast.py on `video_path`. Returns the result.json path.

    If `<vlm_out_dir>/result.json` already exists and `force` is False, we skip
    the run. v3-fast is expensive — same video, same output is fine to reuse.
    """
    result_path = vlm_out_dir / "result.json"
    if result_path.exists() and not force:
        print(f"  reusing cached v3-fast result: {result_path}")
        return result_path

    if not VLM_PROCESSOR.exists():
        raise SystemExit(f"v3-fast script not found: {VLM_PROCESSOR}")

    vlm_out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  running v3-fast on {video_path}  (out={vlm_out_dir})")
    # Subprocess to isolate the older google.generativeai SDK from our
    # google-genai SDK; protobuf versions conflict in-process.
    subprocess.run(
        [sys.executable, str(VLM_PROCESSOR), str(video_path), "--out-dir", str(vlm_out_dir)],
        check=True,
    )
    if not result_path.exists():
        raise RuntimeError(f"v3-fast finished but {result_path} is missing.")
    return result_path


# --- Stage 2: MuBit-versioned filter ----------------------------------------


def _candidate_events(result_data: dict) -> list[dict]:
    """Extract events from a v3-fast result.json that the filter should look at.

    Pull from both `events[]` (with submission/attempt flags) and from
    `position_timeline.submissions[]` so we don't miss any candidate.
    """
    events: list[dict] = []
    for ev in result_data.get("events", []) or []:
        if ev.get("submission") or ev.get("attempt"):
            events.append({
                "source": "events",
                "timestamp": ev.get("timestamp"),
                "title": ev.get("title"),
                "description": ev.get("description"),
                "submission": bool(ev.get("submission")),
                "attempt": bool(ev.get("attempt")),
                "completed": ev.get("completed", True),
                "attacker": ev.get("attacker"),
                "defender": ev.get("defender"),
            })
    for s in (result_data.get("position_timeline") or {}).get("submissions", []) or []:
        events.append({
            "source": "position_timeline",
            "timestamp": s.get("timestamp"),
            "title": s.get("type"),
            "description": s.get("description"),
            "submission": True,
            "attempt": not s.get("completed", True),
            "completed": s.get("completed", True),
            "attacker": s.get("fighter"),
            "defender": None,
        })
    return events


def _strip_md_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # ```json\n...\n``` or ```\n...\n```
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _fetch_active_prompt(mubit_client) -> tuple[str, str]:
    """Returns (prompt_text, version_id)."""
    resp = mubit_client.get_prompt(agent_id=AGENT_ID)
    prompt_obj = resp.get("prompt", resp) if isinstance(resp, dict) else resp
    if isinstance(prompt_obj, dict):
        return str(prompt_obj.get("content", "")), str(prompt_obj.get("version_id", "unknown"))
    return str(prompt_obj), "unknown"


def filter_with_mubit_prompt(
    candidates: list[dict],
    *,
    mubit_client,
    genai_client,
) -> tuple[list[dict], str, str]:
    """Run the MuBit-versioned filter prompt over candidate events.

    Returns (filtered_events, prompt_text, prompt_version_id).
    """
    prompt_text, version_id = _fetch_active_prompt(mubit_client)
    print(f"  active prompt version: {version_id} ({len(prompt_text)} chars)")

    user_payload = json.dumps({"candidates": candidates}, indent=2)
    full_prompt = (
        prompt_text
        + "\n\n---\n\nINPUT (JSON):\n```json\n"
        + user_payload
        + "\n```\n\nOUTPUT (JSON array only):"
    )

    response = genai_client.models.generate_content(
        model=GEMINI_FILTER_MODEL,
        contents=full_prompt,
        config={"response_mime_type": "application/json"},
    )
    raw = (response.text or "[]").strip()
    raw = _strip_md_fences(raw)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        print("  WARN: filter returned non-JSON; using empty list. raw:")
        print(raw[:500])
        return [], prompt_text, version_id
    if not isinstance(out, list):
        print(f"  WARN: filter returned non-array ({type(out).__name__}); using empty list.")
        return [], prompt_text, version_id
    return out, prompt_text, version_id


# --- Output shaping ---------------------------------------------------------


def _to_v3_event(filtered_event: dict) -> dict:
    """Shape a filtered event into the v3-fast result.json events[] schema.

    The VLM-gemini/eval loader keys on submission/attempt/completed and reads
    timestamp/title/attacker/defender. Anything else is best-effort.
    """
    return {
        "timestamp": float(filtered_event.get("timestamp", 0)),
        "title": filtered_event.get("technique") or "other",
        "description": filtered_event.get("description") or "",
        "submission": True,
        "attempt": False,
        "completed": True,
        "attacker": filtered_event.get("attacker"),
        "defender": filtered_event.get("defender"),
    }


def _build_predicted_payload(result_data: dict, filtered: list[dict]) -> dict:
    """Wrap the filtered list in v3-fast result.json shape so eval can read it."""
    return {
        "fighter_stats": result_data.get("fighter_stats") or {},
        "match_summary": result_data.get("match_summary") or "",
        "events": [_to_v3_event(e) for e in filtered],
        "position_timeline": {"submissions": []},
        "key_moments": [],
    }


# --- Top-level orchestrator -------------------------------------------------


def detect(
    video_path: Path,
    *,
    vlm_out_dir: Path | None = None,
    force_v3_fast: bool = False,
) -> dict:
    """Full detection: v3-fast (cached) -> MuBit filter -> predicted.json.

    Returns the metadata dict written to predicted.run.json:
      {video, run_id, agent_id, prompt_version_id, vlm_result, predicted_path,
       n_candidates, n_kept}
    """
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("MUBIT_API_KEY"):
        raise SystemExit("MUBIT_API_KEY missing — set it in .env.local at the repo root.")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY missing — set it in .env.local at the repo root.")

    from mubit import Client as MubitClient  # noqa: WPS433
    from google import genai  # noqa: WPS433

    mubit_client = MubitClient(api_key=os.environ["MUBIT_API_KEY"])
    genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print("=== STAGE 1: v3-fast video analysis ===")
    vlm_out = vlm_out_dir or DEFAULT_VLM_OUT
    result_path = run_v3_fast(video_path, vlm_out, force=force_v3_fast)
    result_data = json.loads(result_path.read_text())
    candidates = _candidate_events(result_data)
    print(f"  v3-fast produced {len(candidates)} candidate submission events")

    print("\n=== STAGE 2: MuBit filter prompt ===")
    filtered, _prompt, version_id = filter_with_mubit_prompt(
        candidates, mubit_client=mubit_client, genai_client=genai_client,
    )
    print(f"  filter kept {len(filtered)} of {len(candidates)} candidates")

    run_id = run_id_for_video(video_path)
    out_dir = OUTPUTS_DIR / "runs" / run_id / version_id
    out_dir.mkdir(parents=True, exist_ok=True)
    predicted_path = out_dir / "predicted.json"
    predicted_path.write_text(json.dumps(_build_predicted_payload(result_data, filtered), indent=2))
    print(f"  wrote {predicted_path}")

    meta = {
        "video": str(video_path),
        "run_id": run_id,
        "agent_id": AGENT_ID,
        "prompt_version_id": version_id,
        "vlm_result": str(result_path),
        "predicted_path": str(predicted_path),
        "n_candidates": len(candidates),
        "n_kept": len(filtered),
    }
    (out_dir / "predicted.run.json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    import argparse

    from mubit.config import DEFAULT_VIDEO, DEFAULT_VLM_OUT

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--vlm-out", type=Path, default=DEFAULT_VLM_OUT)
    parser.add_argument("--force-v3-fast", action="store_true",
                        help="Re-run v3-fast even if result.json exists.")
    args = parser.parse_args()
    detect(args.video, vlm_out_dir=args.vlm_out, force_v3_fast=args.force_v3_fast)
