# Handoff — flywheel/

Read `README.md` first for the concept. This page is just the operational
checklist.

## Setup (5 min)

```bash
# From repo root.
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`.env.local` at the repo root must have:

```
GEMINI_API_KEY=...
MUBIT_API_KEY=mbt_...
```

(Tom has both — DM if you don't.)

## One-time agent provisioning

```bash
python -m flywheel.cli setup
```

Idempotent. Re-runnable. If the `submission-detector` agent already exists in
the `jiujitsu-rt3hsz` project, this is a no-op.

## Spin the wheel

```bash
python -m flywheel.cli spin
```

What it does:

1. **predict** — runs `VLM-gemini/video_processor_v3_fast.py` on
   `VLM-gemini/input-data/ryan-thomas/video.mov` (cached after first run).
   Then fetches the active prompt from MuBit and runs the filter call.
2. **measure** — matches predictions against
   `VLM-gemini/input-data/ryan-thomas/subs.json`. Prints a pretty per-event
   table. Saves `outputs/runs/<run_id>/<prompt_version_id>/report.json`.
3. **feedback** — for each TP / FP / FN, archives the event in MuBit and
   records an outcome with a rationale describing what went right / wrong.

First spin is slow (v3-fast). Every subsequent spin reuses the cached
`result.json` and only re-runs the cheap filter call. Re-spinning with the
same prompt is fine — outcomes accumulate in the same MuBit run.

## Improve

```bash
python -m flywheel.cli improve
```

Asks MuBit's optimizer (an LLM) for a candidate prompt informed by recent
outcomes. Prints the diff. Does **not** auto-activate.

Then go to the MuBit Console (project `jiujitsu-rt3hsz`) → pending candidate →
click **Approve**.

## Spin again, then report

```bash
python -m flywheel.cli spin
python -m flywheel.cli report --version-a <v1-id> --version-b <v2-id>
open flywheel/outputs/runs/sub-detect:video/report.html
```

## Where things live

| What | Where |
|------|-------|
| MuBit calls | `flywheel/mubit_client.py` (the only file that touches the SDK) |
| Inference | `flywheel/spin.py` `predict()` |
| Scoring | `VLM-gemini/eval/` (delegated to) |
| Outcomes | `flywheel/spin.py` `feedback()` |
| Optimizer call | `flywheel/improve.py` |
| HTML report | `flywheel/report.py` |
| Seed prompt (only used at setup) | `flywheel/prompts/filter_v1.md` |
| Active prompt | MuBit (versioned), fetched via `get_active_prompt()` |
| Per-run artifacts | `flywheel/outputs/runs/<run_id>/<prompt_version_id>/` |

## Common gotchas

- **`MUBIT_API_KEY missing`** — it must be in repo-root `.env.local`, not
  inside `flywheel/`.
- **`VITE_*` env vars** — those are for the webapp; do not put MuBit keys
  there. MuBit calls are server-side only.
- **`v3-fast` failures** — Stage 1 narratives are persisted to
  `stage1_narratives.json` so a Stage 2 parse error doesn't lose work.
  Re-run with `--force-v3-fast` to retry.

## What "done" looks like

A side-by-side HTML report showing v2 has higher F1 / fewer hallucinations
than v1, with the per-event rows shifting from red (`hallucination` /
`missed_gt`) to green (`matched`). That's the demo.
