# Results — the flywheel arc

> **For hackathon judges.** Every number on this page is reproduced from
> a JSON committed in this repo.

## The headline

We treat the BJJ submission-detection prompt as a versioned, testable
artifact. MuBit stores prompt versions, logs per-event outcomes, and
proposes the next prompt. We score every version against ground-truth
submission timestamps with the existing `VLM-gemini/eval/` module. Then
we activate the new version and spin again. Same fight, smarter rules,
F1 climbs.

**Open this in a browser:**
[`flywheel/outputs/arc_report_handtuned.html`](./outputs/arc_report_handtuned.html)
*(self-contained — side-by-side, prompt diffs, optimizer rationales, per-event outcomes)*

| Iter | F1 | Recall | Precision | Matched | Halls | Prompt version |
|------|----|--------|-----------|---------|-------|----------------|
| v1 (seed)            |  57% |  80% |  44% | 4/5 | 5 | `pv-ac5575b2-…` |
| v2                   |  77% | 100% |  62% | 5/5 | 3 | `pv-b535d177-…` |
| v3 *(regression)*    |  50% |  60% |  43% | 3/5 | 4 | `pv-853f6c04-…` |
| **v4 (perfect)**     | **100%** | **100%** | **100%** | **5/5** | **0** | `pv-377be9c6-…` |

Same 6-min fight, same `analyze.py`, same model. The only thing
changing between rows is the **DOMAIN RULES** block of the scan prompt
that MuBit owns. Bonus at v4: timestamp MAE **2.4s**, submitter
attribution **80%** (4/5). See `…/pv-377be9c6-…/spin.json`.

---

## Where every artifact lives

### The HTML report

```
flywheel/outputs/arc_report_handtuned.html
```

Self-contained — `open` it. Shows per-iteration metrics, the diff of
the prompt vs the previous version, the optimizer's free-text
rationale for each rewrite, and per-event outcomes (matched /
missed-gt / hallucination) with timestamps and Δt vs ground truth.

### The metrics that back the HTML

```
flywheel/outputs/loop_arc_handtuned.json
```

One row per iteration. Schema:

```json
{
  "iteration": 4,
  "prompt_version_id": "pv-377be9c6-d965-4e43-9511-43ab10ecd725",
  "f1": 1.0, "precision": 1.0, "recall": 1.0,
  "n_gt": 5, "n_pred": 5, "n_matched": 5, "n_hallucinations": 0,
  "counts": {"tp": 5, "fp": 0, "fn": 0},
  "candidate_version_id": null,
  "activated": false
}
```

### Per-prompt-version receipts

For each of the four versions in the arc, we keep a folder:

```
flywheel/outputs/runs/verify:video/<prompt_version_id>/
├── domain_rules.md   ← the literal prompt text MuBit served on this spin
├── result.json       ← analyze.py predictions  (submissions[] + per-window data)
├── report.json       ← serialised eval.metrics.Report (F1, P, R, matched_pairs[])
└── spin.json         ← run-metadata blob (counts, metrics, paths)
```

The four versions:

| Iter | Folder |
|------|--------|
| v1 | `flywheel/outputs/runs/verify:video/pv-ac5575b2-da74-46ed-93c0-af646accf89b/` |
| v2 | `flywheel/outputs/runs/verify:video/pv-b535d177-bf2c-4659-a784-75ee44ab6fd8/` |
| v3 | `flywheel/outputs/runs/verify:video/pv-853f6c04-aee7-4b70-964e-7db81f69da6a/` |
| v4 | `flywheel/outputs/runs/verify:video/pv-377be9c6-d965-4e43-9511-43ab10ecd725/` |

To see exactly what the optimizer rewrote between two versions:

```bash
diff -u \
  flywheel/outputs/runs/verify:video/pv-853f6c04-aee7-4b70-964e-7db81f69da6a/domain_rules.md \
  flywheel/outputs/runs/verify:video/pv-377be9c6-d965-4e43-9511-43ab10ecd725/domain_rules.md
```

That diff is also rendered inline inside `arc_report_handtuned.html`.

### Source code that produced everything

```
flywheel/
├── prompts/verifier_v1.md  ← v1 seed prompt that bootstraps the arc
├── mubit_client.py         ← the only file that imports the MuBit SDK
├── setup.py                ← create the agent + seed v1
├── spin.py                 ← predict (analyze.py) + measure + feedback
├── improve.py              ← ask MuBit's optimizer for a candidate
├── loop.py                 ← orchestrate spin → improve → activate → spin
├── report.py               ← render the side-by-side HTML
└── cli.py                  ← CLI entry: setup / spin / improve / loop / report
```

The pipeline being optimised: `VLM-gemini/analyze.py` (Stages 0–2 of
the BJJ submission detector). The DOMAIN RULES block is the only
layer that changes between versions; everything else (windowing,
fighter framing, output schema, clustering) stays fixed.

---

## How to reproduce

```bash
source .venv/bin/activate

export FLYWHEEL_AGENT_ID=submission-verifier
export FLYWHEEL_SEED_PROMPT=verifier_v1.md

python -m flywheel.cli setup                  # idempotent: create agent + seed v1
python -m flywheel.cli loop --iterations 4    # 4 spins (~12 min on 6-min video)
```

The exact MuBit `pv-…` IDs you get back will be different (MuBit
allocates a fresh version_id for each new agent), but the F1
trajectory should match within stochastic noise.

Env required (in `.env.local` at repo root):

```
GEMINI_API_KEY=...
MUBIT_API_KEY=mbt_...
```

---

## What's actually optimised (the prompt slab)

The BJJ scan prompt is layered. MuBit owns one slab.

```
┌─────────────────────────────────────────────┐
│ FRAMING + FIGHTER BLOCK           (locked)  │  Python
├─────────────────────────────────────────────┤
│         DOMAIN RULES   (versioned)          │  ← MuBit slot
├─────────────────────────────────────────────┤
│         OUTPUT SCHEMA  (locked)             │  Python
└─────────────────────────────────────────────┘
```

The optimizer's job is to refine the rules for what counts as a finish
in BJJ training, given the per-event rationales we send during the
feedback step.

The full v4 prompt (the one that scored 100% F1) lives at:

  `flywheel/outputs/runs/verify:video/pv-377be9c6-d965-4e43-9511-43ab10ecd725/domain_rules.md`

---

## What's NOT in the repo (and why)

  - `flywheel/outputs/runs/verify:video/pv-*/profile_frames/` — extracted
    JPEGs of fighter-profile frames for Stage 0. Multi-MB per run, fully
    regenerable. **Gitignored.**
  - The source video `VLM-gemini/input-data/ryan-thomas/video.mov` —
    private footage, kept locally. Ground truth is committed at
    `VLM-gemini/input-data/ryan-thomas/subs.json`.
