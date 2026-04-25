# flywheel/

A self-improving prompt loop. Spin the wheel, the prompt gets better.

## The flywheel

```
       ┌──────────────────────────────────────────────────┐
       │                                                  │
       │     PREDICT  ──►  MEASURE  ──►  FEEDBACK         │
       │     (run the    (score vs    (log TP/FP/FN       │
       │      prompt)     GT)          to MuBit)          │
       │                                  │               │
       │                                  ▼               │
       │                              ┌────────┐          │
       │  ACTIVATE  ◄──  IMPROVE  ◄───┤ MuBit  │          │
       │  (human       (LLM rewrite   └────────┘          │
       │   approves     of the prompt)                    │
       │   in Console)                                    │
       │      │                                           │
       └──────┴───────────────────────────────────────────┘
```

Each `spin` runs the first three steps. `improve` runs the fourth. A human
approves the candidate in the MuBit Console (the fifth step). Then we spin
again — same fight, smarter prompt.

## Where MuBit fits

MuBit owns three things:

  - **versioned prompts** — v1, v2, v3, … with a single active version
  - **outcome log** — the per-event TP/FP/FN rationales we send during `feedback`
  - **prompt rewriter** — an LLM that proposes the next prompt given the outcomes

MuBit does **not** do inference, scoring, or anything video-related. That's all
local code in this folder. All MuBit calls live in **one file**: `mubit_client.py`.

## What we're optimizing

A submission filter prompt for BJJ video analysis. A separate (slow) pipeline,
`VLM-gemini/video_processor_v3_fast.py`, watches the video and produces
candidate events. Our prompt's job is to keep the real, completed submissions
and reject everything else (attempts, scrambles, position changes, hallucinations).

The prompt is a single text-only Gemini call — fast, cheap, easy to iterate.

## Quick start

```bash
# 1. Activate the project venv (lives at the repo root).
source ../.venv/bin/activate

# 2. One-time: create the agent in MuBit and seed v1 from prompts/filter_v1.md.
python -m flywheel.cli setup

# 3. Spin once. (First spin runs v3-fast, ~few minutes. Cached after that.)
python -m flywheel.cli spin

# 4. Ask MuBit's optimizer for a v2 candidate informed by step 3.
python -m flywheel.cli improve

# 5. Open the MuBit Console, click 'Approve' on the candidate.
#    Project: jiujitsu-rt3hsz  /  proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099

# 6. Spin again. New prompt active, same video, fast.
python -m flywheel.cli spin

# 7. Compare v1 vs v2 side-by-side as HTML.
python -m flywheel.cli report --version-a <v1-id> --version-b <v2-id>
open outputs/runs/sub-detect:video/report.html
```

## File layout

```
flywheel/
├── README.md            # this file
├── HANDOFF.md           # 1-page quick-start
├── config.py            # IDs and paths, one place
├── prompts/
│   └── filter_v1.md     # seed prompt — only used at `setup`
├── mubit_client.py      # ONLY file that imports the MuBit SDK
├── setup.py             # provision the agent
├── spin.py              # predict + measure + feedback
├── improve.py           # ask MuBit for a candidate
├── report.py            # side-by-side HTML
├── cli.py               # one entry point for all of the above
├── requirements.txt
└── outputs/             # gitignored — predicted.json / report.json / report.html
    └── runs/<run_id>/<prompt_version_id>/
```

## Eval delegation

The `measure` step delegates to `VLM-gemini/eval/`, which is the canonical
evaluation module in this repo. We import its `load_gt`, `greedy_match`, and
`evaluate` directly. We don't re-implement matching or metrics here.

## Ground truth

`VLM-gemini/input-data/<game>/subs.json` — schema documented in
`VLM-gemini/input-data/README.md`. The default video is `ryan-thomas`.

## Env

`.env.local` at the repo root:

```
GEMINI_API_KEY=...
MUBIT_API_KEY=mbt_...
```

## Mental model

> The flywheel is just: a versioned prompt + an outcome log + a prompt
> rewriter. Run the prompt, score the run, log what was right and what was
> wrong, ask the rewriter for a better prompt, approve, repeat. MuBit is
> the prompt store, the log, and the rewriter — three small APIs, one file
> of glue code (`mubit_client.py`).
