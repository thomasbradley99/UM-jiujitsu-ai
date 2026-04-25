# Handoff — `mubit/` (for Ali)

> **TL;DR**: scaffold for prompt-optimization loop on submission detection is built and importing cleanly. The eval spine is `VLM-gemini/eval/`. The MuBit-versioned filter prompt is at `mubit/prompts/submission_v1.md`. The default dataset is `ryan-thomas` (committed). Run `python -m mubit.cli setup` then `python -m mubit.cli eval`.

## If you only have 15 minutes today

```bash
git pull
source .venv/bin/activate
pip install -r mubit/requirements.txt   # idempotent
python -m mubit.cli --help              # confirm CLI parses
python -m mubit.cli setup               # creates the agent in the MuBit Console
```

Then read `mubit/README.md` (~5 min). It has the architecture diagram and file table.

That's it for setup. You don't need to download anything: the ryan-thomas annotated GT is committed at `VLM-gemini/input-data/ryan-thomas/subs.json`. You DO need the video — it's gitignored (272MB). Ask Tom for it; drop it at `VLM-gemini/input-data/ryan-thomas/video.mov`.

## Architecture summary

The pipeline runs in two stages:

1. **v3-fast** (`VLM-gemini/video_processor_v3_fast.py`, slow ~minutes, cached). Reads the video, writes a rich `result.json` with narrative + candidate events. This pipeline is **untouched** by MuBit.
2. **MuBit filter** (text-only Gemini call, fast ~seconds). Fetches the active filter prompt from MuBit, applies it to the v3-fast events, outputs a canonical submission list. This is what the optimizer iterates on.

The output is shaped like a v3-fast `result.json` so `VLM-gemini/eval/{load,match,metrics}.py` can read it natively. We delegate eval entirely — `mubit/` does not re-implement matching or metrics.

## What's built vs what's missing

**Built and imports cleanly:**

- `config.py` — IDs, paths (default `ryan-thomas`), tolerance constants
- `prompts/submission_v1.md` — seed filter prompt
- `setup_project.py` — idempotent agent provisioning
- `detect.py` — subprocesses v3-fast (cached) + MuBit-versioned filter call
- `outcomes.py` — converts a `VLM-gemini.eval.metrics.Report` into archive + record_outcome calls
- `optimize.py` — calls `optimize_prompt`, prints the diff
- `report.py` — side-by-side HTML report from two saved Report dicts
- `cli.py` — single argparse entry point

**Not built / open:**

- We've never run end-to-end on real data with both keys live. First eval run is the smoke test.
- The filter prompt v1 is a v0-quality first draft. We expect 2–3 iteration rounds before the demo.
- Ali should sanity-check the candidate-event extraction in `detect.py:_candidate_events()` against an actual `result.json`. The keys we read (`submission`, `attempt`, `completed`, `attacker`, `defender`) match what `VLM-gemini/eval/load.py:_iter_predicted_subs` reads, but the actual v3-fast output may have inconsistencies in those flags.

## Your lane

Once the smoke test passes, the highest-leverage work is:

1. **Improve `_candidate_events()` in `detect.py`**. Right now we only pass the bare event fields. Consider also feeding the filter the relevant slice of `match_summary` or `position_timeline` narrative for richer context. The trade-off is prompt token cost vs filter quality.
2. **Sharpen rationales in `outcomes.py`**. The optimizer reads these — they're more important than the numeric signal. Look at the FP rationale especially: it says "Tighten the filter — require explicit tap" but the optimizer might be helped by referencing the *specific* candidate event field (e.g. "this event had `attempt: true`, you should have skipped it").
3. **Multi-game eval**. The CLI defaults to ryan-thomas, but takes `--video` / `--gt` / `--vlm-out` overrides. If we get a second game annotated before the demo, run eval on both and average the metrics — single-game eval with 5 GT events is too easy to overfit to.

## Tom's lane

Tom is iterating on:
- `prompts/submission_v1.md` — the filter prompt itself
- The demo narrative (which slide shows what)
- Reviewing optimizer candidates in the Console

You don't need to touch these.

## End-to-end loop

```bash
# Detect (cached v3-fast + filter) + match + record outcomes.
python -m mubit.cli eval

# Look at the metrics that print. Look at the Console for recorded outcomes.

# Once we have ~10–20 outcomes, ask MuBit for a candidate prompt.
python -m mubit.cli optimize

# Copy the candidate version_id from the output. Open the Console,
# review the diff, click "Approve & Activate".

# Re-run eval. detect.py picks up the new active prompt automatically.
# v3-fast result.json is reused — only the filter call re-runs (fast).
python -m mubit.cli eval

# Render side-by-side HTML report comparing prompt v1 to v2.
python -m mubit.cli report \
    --run-id sub-detect:video \
    --version-a <v1_id> \
    --version-b <v2_id>
```

That last `report.html` is the slide for the demo.

## Common pitfalls

- **`mubit-sdk` import** — `from mubit import Client`. Not `import mubit`.
- **`google-genai` vs `google-generativeai`** — incompatible `protobuf` versions. v3-fast uses the old SDK and runs in a subprocess; the filter call uses the new SDK in our process. Don't try to call v3-fast directly in-process.
- **Cache busting v3-fast** — pass `--force-v3-fast` to re-run the slow stage. Useful if you change `video.mov` or want to test pipeline determinism.
- **`predicted.json` shape** — must match `result.json` shape so `VLM-gemini/eval/load.py:load_prediction` works. `detect.py:_build_predicted_payload()` handles this — don't change the keys without updating the loader.
- **Run IDs** — `sub-detect:<video-stem>` (see `config.run_id_for_video`). Same video → same run_id, accumulating outcomes across runs.
- **Outcome rationales** — wording matters more than signal magnitude. Read `outcomes.py` to see the directive style.
- **Per-version output dirs** — `outputs/runs/<run_id>/<prompt_version_id>/` keeps `predicted.json` and `report.json` separate per prompt version, so `report.py` can compare two versions side by side without overwriting.

## When you're stuck

- `mubit/README.md` — architecture diagram and file table
- `VLM-gemini/eval/run_eval.py` — standalone evaluator if you want to test a `predicted.json` without touching MuBit
- MuBit docs: <https://docs.mubit.ai/llms.txt> lists every page
  - `getting-started`
  - `sdk/sdk-methods` — every helper method
  - `recipes/prompt-optimization` — the full optimization lifecycle
- Tom — for anything about prompts, rationales, or demo narrative
