# `mubit/` — Submission detection driven by MuBit prompt optimization

This folder contains the **MuBit-track hackathon work**. It's self-contained: the React webapp (`App.tsx`, `services/`, `server.js`) is the existing product demo and is left alone. Everything in here is about **using MuBit's prompt-optimization loop to make submission detection better over time** — by iterating on a prompt that filters the output of the existing `VLM-gemini/video_processor_v3_fast.py` pipeline.

## Architecture

```
                    ┌────────────────────────────┐
                    │   MuBit project            │
                    │   jiujitsu-rt3hsz          │
                    │   ┌──────────────────────┐ │
                    │   │ submission-detector  │ │
                    │   │   v1 (active)        │ │   <- get_prompt
                    │   │   v2 (candidate)     │ │
                    │   └──────────────────────┘ │
                    └────────────┬───────────────┘
                                 │
   video.mov ──► v3-fast ──► result.json
                              │   (rich narrative + candidate events)
                              ▼
                       MuBit filter prompt ──► filtered events ──► predicted.json
                                                                       │
                                                                       ▼
   subs.json (GT) ────────────────────────► VLM-gemini/eval ──► Report (TP/FP/FN, prec/rec/F1)
                                                                       │
                                                                       ▼
                                                           mubit/outcomes.py
                                                                       │  archive + record_outcome
                                                                       ▼
                                                                MuBit run history
                                                                       │  optimize_prompt
                                                                       ▼
                                                              v2 candidate (review in Console)
```

The CLI runs the loop. We run once with prompt v1, accumulate outcomes, ask MuBit for a candidate, approve in the Console, re-run with v2, render the side-by-side HTML report.

**Key design choice**: MuBit owns the *filter prompt*, not the video-analysis prompt. The v3-fast pipeline runs unchanged and produces a noisy candidate list. The MuBit-versioned filter decides which candidates are real, completed submissions. This is what the optimizer iterates on. Trade-off: the filter can't recover submissions v3-fast missed entirely, but the iteration is fast (text-only Gemini call, no video upload).

## Setup

This folder uses the project root `.venv` (Python 3.13). It does NOT create its own.

```bash
# From repo root
source .venv/bin/activate
pip install -r requirements.txt   # already done; lists mubit-sdk, google-genai, python-dotenv
```

### Required env vars

Both keys live in `<repo-root>/.env.local`:

```
GEMINI_API_KEY=...
MUBIT_API_KEY=mbt_<instance>_<key_id>_<secret>
```

`MUBIT_API_KEY` must NEVER be exposed to the browser. Keep it server-side / CLI-side only.

### One-time agent provisioning

```bash
python -m mubit.cli setup
```

Idempotent. Creates the `submission-detector` agent in project `proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099` if it doesn't exist, seeded with `prompts/submission_v1.md` as its v1 active PromptVersion. Re-run safely after `config.py` edits.

## Running the loop

The default CLI args target the committed `ryan-thomas` dataset (`VLM-gemini/input-data/ryan-thomas/`).

```bash
# Full eval cycle. First run is SLOW (~minutes) because v3-fast processes the video.
# Subsequent runs reuse VLM-gemini/runs/ryan-thomas/baseline/result.json — fast.
python -m mubit.cli eval

# After 10-20 outcomes accumulate, ask MuBit for a candidate prompt + print diff.
python -m mubit.cli optimize

# (You go to the MuBit Console and click "Approve & Activate" on the candidate.)

# Run eval again. detect.py picks up the now-active v2 prompt automatically.
# v3-fast result.json is reused; only the filter call re-runs.
python -m mubit.cli eval

# Render the side-by-side HTML report.
python -m mubit.cli report \
    --run-id sub-detect:video \
    --version-a <v1_version_id> \
    --version-b <v2_version_id>
```

To run on a different game (after Ali drops more annotated data into `VLM-gemini/input-data/<game>/`):

```bash
python -m mubit.cli eval \
    --video VLM-gemini/input-data/<game>/video.mov \
    --gt    VLM-gemini/input-data/<game>/subs.json \
    --vlm-out VLM-gemini/runs/<game>/baseline
```

## File layout

| File | Role |
| ---- | ---- |
| `config.py` | Project + agent IDs, default paths, match tolerance. Edit if you change the agent name in the Console. |
| `prompts/submission_v1.md` | Seed v1 filter prompt. Source of truth lives in MuBit after `setup` runs. |
| `setup_project.py` | One-time agent provisioning. |
| `detect.py` | Stage 1: subprocess `video_processor_v3_fast.py` (cached). Stage 2: fetch active prompt from MuBit, run filter Gemini call, write `predicted.json` in v3-fast result.json shape. |
| `outcomes.py` | For each `EventDetail` in the eval `Report`: archive + record_outcome with directive rationale. |
| `optimize.py` | Asks MuBit's optimizer for a candidate prompt, prints diff. Does NOT auto-activate. |
| `report.py` | Renders side-by-side HTML report comparing two prompt versions on the same fight. |
| `cli.py` | Single argparse entry point with `setup / detect / eval / optimize / report` subcommands. |
| `outputs/` | Gitignored. Per-run + per-prompt-version JSON: `predicted.json`, `report.json`, plus a `report.html` per run. |

**Eval is delegated, not duplicated.** Matching, metrics, fighter-alias resolution, and per-event reporting all live in `VLM-gemini/eval/{load,match,metrics}.py`. `mubit/cli.py` imports them; `mubit/` does NOT re-implement that logic.

## Data shapes

**GT** lives at `VLM-gemini/input-data/<game>/subs.json`. Schema:

```json
{
  "video": "ryan-thomas",
  "video_file": "video.mov",
  "duration_sec": 370,
  "fighters": {
    "ryan":   { "ai_descriptor": "BALD FIGHTER",    "rich_gt_descriptor": "BLACK RASHGUARD" },
    "thomas": { "ai_descriptor": "STRIPED FIGHTER", "rich_gt_descriptor": "GREEN STRIPE" }
  },
  "submissions": [
    { "timestamp": 68, "technique": "armbar", "submitter": "ryan", "submittee": "thomas",
      "notes": "1:08 - Ryan armbars Thomas" }
  ]
}
```

`VLM-gemini/eval/load.py` canonicalises techniques and resolves AI fighter descriptors (e.g. `"BALD FIGHTER"`) to GT fighter keys (e.g. `"ryan"`) by token overlap.

**Predicted** is shaped like a v3-fast `result.json`. We only populate the fields the loader cares about:

```json
{
  "fighter_stats": {"BALD FIGHTER": {...}, "STRIPED FIGHTER": {...}},
  "events": [
    {"timestamp": 68, "title": "armbar", "submission": true, "attempt": false,
     "completed": true, "attacker": "BALD FIGHTER", "defender": "STRIPED FIGHTER"}
  ],
  "position_timeline": {"submissions": []},
  "key_moments": []
}
```

## How outcomes feed prompt optimization

For each event in the `Report`:

1. `archive(content, labels)` the event in MuBit → returns a `reference_id`.
2. `record_outcome(reference_id, signal, rationale)`:
   - **matched (TP)**: `signal ∈ [+0.3, +1.0]` based on technique-match + submitter-match + |Δt|. Rationale: "Correctly detected X."
   - **hallucination (FP)**: `signal = -0.7`. Rationale: "Tighten the filter — require explicit tap or clearly isolated joint."
   - **missed_gt (FN)**: `signal = -0.85`. Rationale: "Don't discard candidates whose title contains the technique name."

The MuBit optimizer reads these rationales heavily — the **wording matters more than the signal magnitude**. If you want the optimizer to push the prompt in a specific direction, make the rationale read like a directive (`outcomes.py` does this).

## MuBit Console

- Project: <https://console.mubit.ai/app/projects/proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099>
- Agent (after `setup` runs): `.../agents/submission-detector`
  - **Prompts** tab — version history, candidate review, approve/activate
  - **Runs** tab — outcome aggregates per run
  - **Memory** tab — archived predictions and missed GT events

## Out of scope (deliberately)

- The React webapp / `App.tsx` — left alone. Demo points at it in slide 1, then we move to the loop.
- `tracking_service/` — abandoned for the MuBit track.
- Other agents (`fighter-identifier`, `coach-overlay`) — focusing one wedge: submissions.
- The video-analysis prompt itself (inside `video_processor_v3_fast.py`) — we filter its output rather than rewriting it.
