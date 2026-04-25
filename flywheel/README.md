# flywheel/

A self-improving prompt loop. Spin the wheel, the prompt gets better.

## The flywheel

```
       ┌──────────────────────────────────────────────────┐
       │                                                  │
       │     PREDICT  ──►  MEASURE  ──►  FEEDBACK         │
       │     (run            (score vs    (log TP/FP/FN   │
       │      analyze.py)    GT)          to MuBit)       │
       │                                  │               │
       │                                  ▼               │
       │                              ┌────────┐          │
       │  ACTIVATE  ◄──  IMPROVE  ◄───┤ MuBit  │          │
       │  (human       (LLM rewrite   └────────┘          │
       │   approves     of the rules)                     │
       │   in Console)                                    │
       │      │                                           │
       └──────┴───────────────────────────────────────────┘
```

Each `spin` runs the first three steps. `improve` runs the fourth. A human
approves the candidate in the MuBit Console (the fifth step). Then we spin
again — same fight, smarter rules.

## Where MuBit fits

MuBit owns three things:

  - **versioned prompts** — v1, v2, v3, … with a single active version
  - **outcome log** — per-event TP/FP/FN rationales sent during `feedback`
  - **prompt rewriter** — an LLM that proposes the next prompt given the outcomes

MuBit does **not** do inference, scoring, or anything video-related. That's all
local code in this folder. All MuBit calls live in **one file**: `mubit_client.py`.

## What we're optimizing

The **DOMAIN RULES** layer of the BJJ submission detection prompt baked into
`VLM-gemini/analyze.py`. analyze.py cuts the source video into ~40s windows on
a 15s grid stride, ships each clip to Gemini Pro, and asks one question per
window: "did a submission happen?" Per-window YES detections get clustered
into one submission per real event.

The scan prompt is layered:

```
┌─────────────────────────────────────────────┐
│ FRAMING + FIGHTER BLOCK           (locked)  │  Python-owned
├─────────────────────────────────────────────┤
│         DOMAIN RULES   (versioned)          │  ← MuBit owns this layer
├─────────────────────────────────────────────┤
│         OUTPUT SCHEMA  (locked)             │  Python-owned
└─────────────────────────────────────────────┘
```

Only the middle slab — what counts as a finish in BJJ training — is what we
optimize. Everything else (which two athletes to track, what JSON shape to
return) stays fixed in `analyze.py:_DEFAULT_DOMAIN_RULES` and adjacent
constants. `spin.py` writes the active version to disk and passes it via
`analyze.py --domain-rules-file`.

The seed v1 (`prompts/verifier_v1.md`) is deliberately strict: it requires a
visible tap, verbal yield, or unconsciousness. Lots of real submissions in
training don't meet that bar (taps are fast, hidden, or below frame). The
optimizer's job is to learn from FN windows that "round-end / reset /
disengagement" signals are also evidence of a finish.

## Quick start

```bash
# 0. The repo-root .venv has BOTH google-generativeai (analyze.py deps)
#    and google-genai + mubit-sdk (flywheel deps). If they conflict on
#    your machine, set FLYWHEEL_ANALYZE_PYTHON to a venv that has the
#    analyze.py deps; the flywheel venv keeps mubit-sdk.
source .venv/bin/activate

# 1. One-time: create the agent in MuBit and seed v1 from prompts/verifier_v1.md.
python -m flywheel.cli setup

# 2. Spin once. (analyze.py ~3 min on a 6-min video; cached per prompt version after that.)
python -m flywheel.cli spin

# 3. Ask MuBit's optimizer for a v2 candidate informed by step 2's outcomes.
python -m flywheel.cli improve

# 4. Open the MuBit Console, click 'Approve' on the candidate.
#    Project: jiujitsu-rt3hsz  /  proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099

# 5. Spin again. New rules active, same video.
python -m flywheel.cli spin

# 6. Compare v1 vs v2 side-by-side as HTML.
python -m flywheel.cli report --version-a <v1-id> --version-b <v2-id>
open flywheel/outputs/runs/verify:video/report.html
```

## File layout

```
flywheel/
├── README.md            # this file
├── HANDOFF.md           # 1-page quick-start
├── config.py            # IDs, paths, analyze.py knobs — one place
├── prompts/
│   └── verifier_v1.md   # seed DOMAIN RULES — only used at `setup`
├── mubit_client.py      # ONLY file that imports the MuBit SDK
├── setup.py             # provision the agent
├── spin.py              # predict (analyze.py) + measure + feedback
├── improve.py           # ask MuBit for a candidate
├── report.py            # side-by-side HTML
├── cli.py               # one entry point for all of the above
├── requirements.txt
└── outputs/             # gitignored
    └── runs/<run_id>/<prompt_version_id>/
        ├── domain_rules.md  # the rules text we sent analyze.py (audit)
        ├── result.json      # analyze.py output (clusters + per-window data)
        ├── report.json      # eval Report dataclass, serialised
        └── spin.json        # run-metadata blob
```

## How feedback talks to the optimizer

Per cluster-level event, we archive an artifact + record an outcome with a
specific rationale. The rationale is what the rewriter LLM reads.

  - **TP cluster** → "correctly fired here, keep these rules"
  - **FP cluster** → "this cluster shouldn't have fired; sample window
    reasoning was '<…>'; tighten the rules"
  - **FN (missed GT)** → "real submission at YYs; the windows covering this
    moment all returned is_submission=false. Their reasoning was '<…>'.
    The rules are missing whatever cue this clip contained"

The third one is the killer feedback — it literally quotes the pipeline's own
"NO" reasoning back at the optimizer. The optimizer sees: "you said NO at the
moment a real submission happened, here's why you said NO." That's how a
strict-tap-only v1 is supposed to evolve into a reset-rule v2.

## Eval delegation

The `measure` step delegates to `VLM-gemini/eval/`, which is the canonical
evaluation module in this repo. We import its `load_gt`, `load_prediction`,
`greedy_match`, and `evaluate` directly. We don't re-implement matching or
metrics here. analyze.py's `result.json` is the canonical schema eval expects,
so no schema adapter is needed.

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

> The flywheel is: a versioned DOMAIN RULES block + an outcome log + a prompt
> rewriter. The pipeline (`analyze.py`) is fixed; the rules slot inside its
> scan prompt changes. Run the pipeline, score the run, log what fired right
> and what didn't, ask the rewriter for a better rules block, approve,
> repeat. MuBit is the prompt store, the log, and the rewriter — three small
> APIs, one file of glue code (`mubit_client.py`).
