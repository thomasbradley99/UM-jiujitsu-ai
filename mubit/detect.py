"""Run submission detection on a video.

Pulls the active prompt for AGENT_ID from MuBit, uploads the video to Gemini's
File API (the inline 20MB limit blocks our ~400MB clip), and asks Gemini for a
structured list of submission events.

Returns the parsed prediction list AND the version_id of the prompt used,
so downstream scripts can attribute outcomes to a specific PromptVersion.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from mubit.config import AGENT_ID, GEMINI_MODEL, OUTPUTS_DIR, REPO_ROOT, run_id_for_video
from mubit.match import Prediction
from mubit.schema import submission_response_schema


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }.get(ext, "video/mp4")


def _fetch_active_prompt(mubit_client) -> tuple[str, str]:
    """Returns (prompt_text, version_id)."""
    resp = mubit_client.get_prompt(agent_id=AGENT_ID)
    prompt = resp.get("prompt", resp) if isinstance(resp, dict) else resp
    return str(prompt.get("content", "")), str(prompt.get("version_id", "unknown"))


def _upload_video(genai_client, video_path: Path):
    """Upload via Gemini File API. Polls until ACTIVE."""
    print(f"  uploading {video_path.name} ({video_path.stat().st_size / 1e6:.1f} MB)...")
    f = genai_client.files.upload(file=str(video_path), config={"mime_type": _mime_for(video_path)})
    while getattr(f, "state", None) and getattr(f.state, "name", "") == "PROCESSING":
        print("  waiting for Gemini to process the upload...")
        time.sleep(5)
        f = genai_client.files.get(name=f.name)
    state_name = getattr(getattr(f, "state", None), "name", "UNKNOWN")
    if state_name not in {"ACTIVE", "READY"}:
        raise RuntimeError(f"Upload entered unexpected state: {state_name}")
    return f


def detect(video_path: Path) -> dict:
    """Detect submissions in `video_path` using the active MuBit prompt.

    Returns a dict ready to be saved as outputs/runs/<run_id>/predicted.json:
        {
          "video": str,
          "run_id": str,
          "agent_id": str,
          "prompt_version_id": str,
          "model": str,
          "predictions": [ {timestamp, sub_type, ...}, ... ]
        }
    """
    load_dotenv(REPO_ROOT / ".env.local")

    if not os.environ.get("MUBIT_API_KEY"):
        raise SystemExit("MUBIT_API_KEY missing.")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY missing.")

    from mubit import Client as MubitClient
    from google import genai
    from google.genai import types as genai_types

    mubit_client = MubitClient(api_key=os.environ["MUBIT_API_KEY"])
    genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print(f"Fetching active prompt for agent '{AGENT_ID}'...")
    prompt_text, version_id = _fetch_active_prompt(mubit_client)
    print(f"  prompt version: {version_id}  ({len(prompt_text)} chars)")

    print("Uploading video to Gemini File API...")
    video_file = _upload_video(genai_client, video_path)

    print(f"Calling {GEMINI_MODEL}...")
    response = genai_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt_text, video_file],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=submission_response_schema(),
        ),
    )

    raw = response.text or "[]"
    try:
        predictions_raw = json.loads(raw.strip())
    except json.JSONDecodeError:
        print("WARN: Gemini returned non-JSON; using empty list.")
        print(raw[:500])
        predictions_raw = []

    predictions = [Prediction.from_dict(p) for p in predictions_raw]

    run_id = run_id_for_video(video_path)
    out_dir = OUTPUTS_DIR / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "video": str(video_path),
        "run_id": run_id,
        "agent_id": AGENT_ID,
        "prompt_version_id": version_id,
        "model": GEMINI_MODEL,
        "predictions": [asdict(p) for p in predictions],
    }
    (out_dir / "predicted.json").write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_dir / 'predicted.json'} ({len(predictions)} predictions)")
    return payload


if __name__ == "__main__":
    import argparse

    from mubit.config import DEFAULT_VIDEO

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    args = parser.parse_args()
    detect(args.video)
