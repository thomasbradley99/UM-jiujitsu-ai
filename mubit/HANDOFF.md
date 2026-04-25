# Handoff — `mubit/` (for Ali)

> **TL;DR**: scaffold for prompt-optimization loop on submission detection is built and importing cleanly. Two things missing: (1) `mubit/detect.py` needs to call YOUR pipeline (`VLM-gemini/video_processor_v3_fast.py`) instead of the placeholder, and (2) we need GT loaded at `eval/gt.json`. Once those are wired, `python -m mubit.cli eval` runs the whole loop.

## If you only have 15 minutes today

1. Pull, install, run smoke commands:
   ```bash
   git pull
   source .venv/bin/activate
   pip install -r mubit/requirements.txt   # idempotent
   python -m mubit.cli --help              # confirm the CLI parses
   python -m mubit.cli setup               # creates the agent in the MuBit Console
   ```
2. Open the MuBit Console and confirm you see the agent:
   <https://console.mubit.ai/app/projects/proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099>
3. Read `mubit/README.md` (~5 min). It has the architecture diagram and file table.

That's it for setup. Now you can actually pick up work.

## What's built vs what's missing

**Built** (importing cleanly, no lints):

- `config.py` — project_id, agent_id, paths, tolerance constants
- `prompts/submission_v1.md` — the seed system prompt for submission detection
- `schema.py` — Gemini response schema (15 canonical sub_types)
- `setup_project.py` — idempotent agent provisioning
- `gt.py` — loads GT JSON, filters to submission events, infers `sub_type` from text
- `match.py` — greedy timestamp matching (predictions ↔ GT) within ±5s
- `metrics.py` — precision / recall / F1 / MAE / per-type recall
- `outcomes.py` — for each match: archive() then record_outcome() with directive rationale
- `optimize.py` — calls optimize_prompt, prints the diff, does NOT auto-activate
- `report.py` — side-by-side HTML report (the demo visual)
- `cli.py` — single argparse entry point with all subcommands

**Not built**:

- `detect.py` exists but uses the new `google-genai` SDK with a single `generate_content` call. **You should replace it with a wrapper around your `VLM-gemini/video_processor_v3_fast.py`** — see the next section. The current `detect.py` is the contract example, not the production path.
- `eval/gt.json` does not exist yet. The shape `gt.py` expects is in `eval/gt_template.json`. Either rename your annotated GT to that path with the right shape, or write a one-shot converter.

## Your lane (Lane B): wire `video_processor_v3_fast.py` into the loop

Your `video_processor_v3_fast.py` already produces `result_fast.json` with an `events` array where each event has `submission: true|false`. We just need to:

1. Run your processor on the video.
2. Filter `result['events']` to those where `event.get('submission')` or `event.get('attempt')` is true.
3. Normalize each event into a `mubit.match.Prediction` (timestamp / sub_type / attacker / defender / outcome / confidence).
4. Save as `outputs/runs/<run_id>/predicted.json`.

### Recommended approach: subprocess + JSON

The cleanest integration. No SDK conflicts (your pipeline uses old `google.generativeai`, mine uses new `google.genai` — they fight over `protobuf`). Subprocess gives full isolation.

Replace `mubit/detect.py` with something shaped like this:

```python
"""Wrapper around VLM-gemini/video_processor_v3_fast.py.

Subprocess + JSON read avoids the google.generativeai vs google-genai
SDK conflict. Each lives in its own process; we only consume the JSON output.
"""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from mubit.config import (
    AGENT_ID, GEMINI_MODEL, OUTPUTS_DIR, REPO_ROOT, run_id_for_video,
)
from mubit.match import Prediction


VLM_SCRIPT = REPO_ROOT / "VLM-gemini" / "video_processor_v3_fast.py"


def _fetch_active_prompt(mubit_client) -> tuple[str, str]:
    """Currently unused — VLM pipeline has its own prompts. See note below."""
    resp = mubit_client.get_prompt(agent_id=AGENT_ID)
    prompt = resp.get("prompt", resp) if isinstance(resp, dict) else resp
    return str(prompt.get("content", "")), str(prompt.get("version_id", "unknown"))


def _events_to_predictions(events: list[dict]) -> list[Prediction]:
    """Filter VLM events to submission-relevant ones, normalize into Prediction."""
    out: list[Prediction] = []
    for ev in events:
        if not (ev.get("submission") or ev.get("attempt")):
            continue
        # Map your VLM event shape into the Prediction dataclass.
        # Adjust these keys to match your actual JSON.
        out.append(Prediction(
            timestamp=float(ev.get("timestamp", 0.0)),
            sub_type=str(ev.get("title", "unknown")).lower().replace(" ", "_"),
            attacker=str(ev.get("attacker", "fighter1")),
            defender=str(ev.get("defender", "fighter2")),
            outcome="successful" if ev.get("submission") else "ongoing",
            confidence=float(ev.get("perspectives", {})
                              .get(ev.get("attacker", ""), {})
                              .get("score", 50)) / 100.0,
        ))
    return out


def detect(video_path: Path) -> dict:
    load_dotenv(REPO_ROOT / ".env.local")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY missing.")

    # Run your pipeline as a subprocess.
    print(f"Running video_processor_v3_fast.py on {video_path}...")
    result = subprocess.run(
        [sys.executable, str(VLM_SCRIPT), str(video_path)],
        check=True,
    )

    # Your pipeline writes result_fast.json next to the video.
    result_path = video_path.parent / "result_fast.json"
    payload_in = json.loads(result_path.read_text())
    predictions = _events_to_predictions(payload_in.get("events", []))

    # The prompt version is "n/a (vlm)" until we promote VLM prompts to MuBit.
    # See "Open question" section below.
    run_id = run_id_for_video(video_path)
    out_dir = OUTPUTS_DIR / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "video": str(video_path),
        "run_id": run_id,
        "agent_id": AGENT_ID,
        "prompt_version_id": "vlm-pipeline",
        "model": GEMINI_MODEL,
        "predictions": [asdict(p) for p in predictions],
    }
    (out_dir / "predicted.json").write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_dir / 'predicted.json'} ({len(predictions)} submission predictions)")
    return payload
```

This works *as a starting point*. There's a real design question about how the VLM pipeline's prompts relate to MuBit — see "Open question" below.

## The GT question

`mubit/gt.py` expects:

```json
{
  "video": "full-gym-short.mov",
  "duration_s": 281,
  "fighter1_id": "blue gi",
  "fighter2_id": "white gi",
  "events": [
    { "timestamp": 12.4, "event_type": "submission", "who": "fighter1",
      "title": "Armbar", "description": "Armbar from closed guard",
      "importance": 4 }
  ]
}
```

`gt.py` filters to `event_type ∈ {submission, sub_attempt, near_finish}` (defined in `config.SUBMISSION_EVENT_TYPES`).

If your annotated GT is already in this shape: copy/symlink to `eval/gt.json` and you're done. If it's in a different shape, write a one-shot converter that emits this format. Don't bend `gt.py` to read multiple formats.

Tom said he has annotated GT — ask him for the path / format before you start.

## Lane A (Tom's lane, FYI)

Tom is iterating on:
- `prompts/submission_v1.md` — the seed prompt itself
- `outcomes.py` rationales — the wording the optimizer reads
- Reviewing optimizer candidates in the Console

You don't need to touch these.

## End-to-end loop, once both pieces are in place

```bash
# Detect + match + metrics + record outcomes
python -m mubit.cli eval --video full-gym-short.mov --gt eval/gt.json

# Look at the metrics that print. Look at the Console for the recorded outcomes.

# Once we have ~10-20 outcomes, ask MuBit for a candidate prompt.
python -m mubit.cli optimize

# Copy the candidate version_id from the output. Open the Console,
# review the diff, click "Approve & Activate".

# Re-run eval. detect.py picks up the new active prompt automatically.
python -m mubit.cli eval --video full-gym-short.mov --gt eval/gt.json

# Render side-by-side HTML report comparing prompt v1 to v2.
python -m mubit.cli report \
    --run-id sub-detect:full-gym-short \
    --version-a <v1_id> \
    --version-b <v2_id>
```

That last `report.html` is the slide for the demo.

## Open question: how does the MuBit prompt relate to your VLM pipeline?

Your `video_processor_v3_fast.py` has its own prompts hardcoded in `build_clip_prompt()`, `build_narrative_prompt()`, `build_parsing_prompt()`. Currently `mubit/setup_project.py` seeds an entirely **separate** prompt (`prompts/submission_v1.md`) into MuBit, which `mubit/detect.py` would fetch via `client.get_prompt()`.

There are two ways to resolve this. Pick one with Tom:

1. **MuBit owns a "submission filter" prompt that runs AFTER your VLM pipeline.** Your pipeline produces a verbose narrative-style output; we add a final Gemini call that takes the narrative + the MuBit-versioned prompt and outputs strict submission JSON. This is a clean separation and lets the optimizer iterate on submission detection specifically without messing with your existing pipeline.

2. **MuBit owns the `build_parsing_prompt()` text.** We extract the parsing prompt from `video_processor_v3_fast.py` into MuBit, refactor your pipeline to fetch it from `client.get_prompt()` at runtime, and the optimizer iterates on that. Bigger refactor of your code.

For the hackathon I'd push hard for option 1 — it keeps your pipeline untouched and gives MuBit a clean job. The "submission filter" call is fast (text-only, no video) and is the perfect surface for prompt optimization.

## Common pitfalls

- **`mubit-sdk` import** — `from mubit import Client`. Not `import mubit`. Not `from mubit.client import Client`.
- **`google-genai` vs `google-generativeai`** — incompatible `protobuf` versions. Don't try to use both in the same Python process. Subprocess your VLM pipeline.
- **MuBit key** — read from `<repo-root>/.env.local` via `dotenv.load_dotenv(REPO_ROOT / ".env.local")`. Never commit. Never put it in any `VITE_*` variable.
- **Run IDs** — we use `sub-detect:<video-stem>` (see `config.run_id_for_video`). Same video → same run_id, so re-running `eval` accumulates outcomes against the same run rather than creating new ones.
- **Outcome rationales** — the wording matters more than the signal magnitude. Read `mubit/outcomes.py` to see the directive style we're using.

## When you're stuck

- `mubit/README.md` for the bird's-eye view
- MuBit docs: <https://docs.mubit.ai/llms.txt> lists every page
  - `getting-started` — the absolute basics
  - `sdk/sdk-methods` — every helper method explained
  - `recipes/prompt-optimization` — the full optimization lifecycle
- Tom — for anything about the prompts, the rationales, or the demo narrative
