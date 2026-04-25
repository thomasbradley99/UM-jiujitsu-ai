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

Idempotent. Re-runnable. If the `submission-verifier` agent already exists in
the `jiujitsu-rt3hsz` project, this is a no-op.

## Spin the wheel

```bash
python -m flywheel.cli spin
```

What it does:

1. **predict** — fetches the active DOMAIN RULES from MuBit, writes them to
   `outputs/runs/<run_id>/<prompt_version_id>/domain_rules.md`, then runs
   `VLM-gemini/analyze.py --domain-rules-file …` with those rules. analyze.py
   slides a 40s window across the video on a 15s stride, asks Gemini Pro per
   window whether a submission happened, and clusters YES windows into one
   submission per real event. Output: `result.json`.
2. **measure** — matches the clustered submissions against
   `VLM-gemini/input-data/ryan-thomas/subs.json` using the `VLM-gemini/eval/`
   package (`load_prediction` reads `result.json` natively). Prints a
   per-event table. Saves `report.json` next to `result.json`.
3. **feedback** — for each cluster-level TP / FP / FN, archives an artifact
   in MuBit and records an outcome with a *specific* rationale. For misses,
   the rationale quotes the per-window reasoning ("you said NO here, here's
   what you said you saw") — that's the signal the optimizer rewrites against.

First spin on a fresh prompt is slow (~3 min for a 6-min video, 25 windows ×
Gemini Pro). Subsequent spins on the **same prompt version** reuse the cached
`result.json`. Force a re-run with `--force`.

## Improve

```bash
python -m flywheel.cli improve
```

Asks MuBit's optimizer (an LLM) for a candidate DOMAIN RULES variant
informed by recent outcomes. Prints the diff. Does **not** auto-activate.

Then go to the MuBit Console (project `jiujitsu-rt3hsz`) → pending candidate →
click **Approve**.

## Spin again, then report

```bash
python -m flywheel.cli spin
python -m flywheel.cli report --version-a <v1-id> --version-b <v2-id>
open flywheel/outputs/runs/verify:video/report.html
```

## The demo arc

| Spin | Active rules | Expected behaviour |
|------|---|---|
| 1 | v1 (strict tap, seeded) | Many FN — windows that should have detected resets/disengagements return NO. Some TP for clearly visible taps. |
| 2 | v2 (after `improve`) | Optimizer should have added "reset / disengagement / fist bump" as evidence based on the rationales from spin 1. F1 climbs. |
| 3 | v3 (optional second spin of `improve`) | Smaller fixes — submitter attribution, mistime corrections. |

## Where things live

| What | Where |
|------|-------|
| MuBit calls | `flywheel/mubit_client.py` (the only file that touches the SDK) |
| analyze.py subprocess | `flywheel/spin.py` `predict()` (calls `VLM-gemini/analyze.py --domain-rules-file …`) |
| Scoring | `VLM-gemini/eval/` (delegated to via `load_prediction` / `greedy_match` / `evaluate`) |
| Outcomes | `flywheel/spin.py` `feedback()` |
| Optimizer call | `flywheel/improve.py` |
| HTML report | `flywheel/report.py` |
| Seed prompt (only used at setup) | `flywheel/prompts/verifier_v1.md` |
| Active rules | MuBit (versioned), fetched via `get_active_prompt()` |
| Per-run artifacts | `flywheel/outputs/runs/<run_id>/<prompt_version_id>/` |

## Common gotchas

- **`MUBIT_API_KEY missing`** — it must be in repo-root `.env.local`, not
  inside `flywheel/`.
- **`VITE_*` env vars** — those are for the webapp; do not put MuBit keys
  there. MuBit calls are server-side only.
- **analyze.py subprocess fails to find `google.generativeai`** — the
  flywheel venv must have both the legacy `google-generativeai` package
  (analyze.py) and `google-genai` + `mubit-sdk` (flywheel). If they conflict
  on your machine, install analyze.py deps in a separate venv and point
  `FLYWHEEL_ANALYZE_PYTHON=/path/to/that/python` before running spin.
- **Same prompt, want to re-run** — `python -m flywheel.cli spin --force`.

## What "done" looks like

A side-by-side HTML report showing v2 has higher F1 / fewer FNs than v1, with
the per-event rows shifting from amber (`missed_gt`) to green (`matched`).
That's the demo.
