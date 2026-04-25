# `mubit/` — Submission detection driven by MuBit

This folder contains the **MuBit-track hackathon work**. It's self-contained: the React
webapp (`App.tsx`, `services/`, `server.js`) is the existing product demo and is left
alone. Everything in here is about **using MuBit's prompt-optimization loop to make
Gemini detect BJJ submissions better over time**.

## What it does

```
                  ┌──────────────────────┐
                  │   MuBit Project       │
                  │   jiujitsu-rt3hsz     │
                  │   ┌────────────────┐  │
                  │   │ submission-    │  │
                  │   │ detector       │  │
                  │   │  v1 (active)   │  │
                  │   │  v2 (candidate)│  │
                  │   └────────────────┘  │
                  └──────────┬────────────┘
                             │ get_prompt
                             ▼
  GT events ──► detect.py ──► Gemini ──► predictions
       │                                       │
       └───────► match.py ◄────────────────────┘
                     │
                     ▼
                metrics.py + outcomes.py
                     │
                     ▼
                ┌───────────┐
                │ MuBit     │  ── outcomes accumulate ──► optimize_prompt → v2 candidate
                │ outcomes  │
                └───────────┘
```

The CLI runs the whole loop. We run it once with prompt v1, accumulate outcomes,
ask MuBit for a candidate, approve it in the Console, then re-run with v2 and
compare.

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

Idempotent. Creates the `submission-detector` agent in project
`proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099` if it doesn't exist, seeded with
`prompts/submission_v1.md` as its v1 active PromptVersion. Re-run safely after
`config.py` edits.

## Running the loop

```bash
# Full eval cycle: detect on the video, match against GT, compute metrics, record outcomes.
python -m mubit.cli eval --video full-gym-short.mov --gt eval/gt.json

# After 10-20 outcomes accumulate, ask MuBit for a candidate prompt + print diff.
python -m mubit.cli optimize

# (You go to the MuBit Console and click "Approve & Activate" on the candidate.)

# Run the eval again — `detect.py` fetches the now-active v2 prompt automatically.
python -m mubit.cli eval --video full-gym-short.mov --gt eval/gt.json

# Render the side-by-side HTML report.
python -m mubit.cli report \
    --run-id sub-detect:full-gym-short \
    --version-a <v1_version_id> \
    --version-b <v2_version_id>
```

## File layout

| File | Role |
| ---- | ---- |
| `config.py` | Project ID, agent ID, paths, tolerance constants. Edit if Ali used a different agent name in the Console. |
| `prompts/submission_v1.md` | Seed v1 system prompt. Source of truth lives in MuBit after `setup` runs. |
| `schema.py` | Gemini response schema (the JSON shape Gemini must produce). |
| `setup_project.py` | One-time agent provisioning. |
| `detect.py` | Fetches active prompt from MuBit, uploads video to Gemini File API, gets predictions. |
| `gt.py` | Loads GT JSON, filters to submission-relevant events, infers `sub_type` from text. |
| `match.py` | Greedy timestamp matching of predictions to GT (within `TIMESTAMP_TOLERANCE_S`). |
| `metrics.py` | Precision / recall / F1 / MAE + per-type recall. |
| `outcomes.py` | For each match, archive the event in MuBit and record_outcome with rationale. |
| `optimize.py` | Asks MuBit's optimizer for a candidate prompt, prints diff. Does NOT auto-activate. |
| `report.py` | Renders side-by-side HTML report. |
| `cli.py` | Single argparse entry point with `setup / detect / eval / optimize / report` subcommands. |
| `outputs/` | Gitignored. Per-run JSON: `predicted.json`, `matched.<ver>.json`, `metrics.<ver>.json`, `report.html`. |

## GT format

`mubit/gt.py` expects JSON shaped exactly like `eval/gt_template.json`:

```json
{
  "video": "full-gym-short.mov",
  "duration_s": 281,
  "fighter1_id": "blue gi",
  "fighter2_id": "white gi",
  "events": [
    {
      "timestamp": 12.4,
      "event_type": "submission",
      "who": "fighter1",
      "title": "Armbar",
      "description": "Armbar from closed guard, opponent taps",
      "importance": 4
    }
  ]
}
```

`gt.py` filters to events where `event_type ∈ {submission, sub_attempt, near_finish}`
(see `config.SUBMISSION_EVENT_TYPES`) and infers a canonical `sub_type` from the
title/description so we can score type accuracy. If your annotated GT is in a
different shape, write a one-shot converter rather than making the loader polymorphic.

## How outcomes feed prompt optimization

For each match, we:

1. `archive(content, labels)` the event in MuBit → returns a `reference_id`.
2. `record_outcome(reference_id, signal, rationale)` against that reference.
   - **TP**: `signal ∈ [+0.4, +1.0]` scaled by Gemini's confidence. Rationale: "Correctly detected X."
   - **FP**: `signal ∈ [-1.0, -0.3]` scaled by confidence. Rationale: "Hallucinated X — be more conservative."
   - **FN**: `signal ∈ [-1.0, -0.3]` scaled by GT importance. Rationale: "Missed real X — attend more carefully."

The MuBit optimizer reads these rationales heavily — the **wording matters more than
the signal magnitude**. If you want the optimizer to push Gemini in a specific
direction, make the rationale text read like a directive (`outcomes.py` does this).

## MuBit Console

- Project: <https://console.mubit.ai/app/projects/proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099>
- Agent (after `setup` runs): `.../agents/submission-detector`
  - **Prompts** tab — version history, candidate review, approve/activate
  - **Runs** tab — outcome aggregates per run
  - **Memory** tab — archived predictions and missed GT events

## Division of labour suggestion

- **One person**: prompt iteration. Edits `prompts/submission_v1.md` for hand-tweaks,
  reviews optimizer candidates in the Console, designs the response schema in `schema.py`.
- **Other person**: the eval spine. Iterates on `gt.py` (better sub_type inference),
  `match.py` (better matching logic), `outcomes.py` (sharper rationales), `report.py` (demo polish).

Both run `python -m mubit.cli eval` and look at the same MuBit Console.

## Out of scope (deliberately)

- The React webapp / `App.tsx` — left alone. Demo points at it in slide 1, then we move to the loop.
- `tracking_service/` — abandoned for the MuBit track.
- Other agents (`fighter-identifier`, `coach-overlay`) — focusing one wedge: submissions.
