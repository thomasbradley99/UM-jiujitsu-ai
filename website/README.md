# BJJ submission detector — website

Static-site home for the experimental record.

## Layout

```
website/
├── build.py          compiles raw experiment artifacts → clean JSON bundle
├── index.html        minimal scaffold; replace with real frontend
├── README.md         this file
├── SCHEMA.md         JSON shape reference for every file under data/
├── data/             ← READ THIS from the frontend
│   ├── manifest.json         top-level summary
│   ├── games/                list of input videos + GT
│   ├── runs/                 flywheel arc data (per-iteration metrics + prompts)
│   └── cross_eval/           N prompts × M games matrix
└── public/           ← VIDEOS + IMAGES served as static assets
    └── games/<game>/video.mov
```

## Building the bundle

```bash
.venv/bin/python website/build.py
```

This:
1. Reads `VLM-gemini/input-data/<game>/{video.mov, subs.json}`
2. Reads `flywheel/outputs/runs/verify:video/<pv>/{result.json, report.json, domain_rules.md}` for each curated arc
3. Reads `flywheel/outputs/cross_eval/<game>/<pv-dir>/{result.json, report.json}`
4. Writes a clean, denormalized JSON bundle into `website/data/`
5. Copies videos into `website/public/games/<game>/video.mov`

Re-run after every experiment. The build is idempotent and ~1 second.

## Curated arcs

`build.py` only includes arcs listed in `CURATED_ARCS` in the script. Add new
runs by appending to that list. This keeps scratch experiments out of the
public surface.

## Serving locally

Any static server works:

```bash
cd website
python -m http.server 8000
# open http://localhost:8000
```

Or `npx serve` / `live-server` / Caddy / nginx — anything that serves files.

## Building a real frontend

The minimal `index.html` is just a scaffold. To replace with a real app:

1. Pick a framework (Next.js / Vite + React / SvelteKit / Astro)
2. Initialize inside `website/` (or a new `website/app/` if you prefer)
3. Have your build output to `website/dist/` or wherever
4. Read JSON via `fetch("/data/...")` — see `SCHEMA.md` for shapes
5. Reference videos with `<video src="/public/games/<game>/video.mov" />`

The data/public split is intentional: data is small enough to commit to git
(~500KB), public is gitignored (~300MB of video).

## Adding a new experiment

1. Run the experiment via `flywheel/scripts/cross_eval.sh` or
   `flywheel.cli loop` — outputs land in `flywheel/outputs/`
2. If it's a flywheel arc you want surfaced, add an entry to `CURATED_ARCS`
   in `build.py`
3. Re-run `build.py`
4. Refresh the site

## Pages worth building (suggested)

- **Game library** — index of all videos with GT timeline; click to play
- **Arc explorer** — sparkline of F1 per iteration; click an iteration to see
  the prompt, eval, and per-event detail
- **Per-window inspector** — for any prompt × game, all 25 windows with the
  model's `is_submission` decision and `reasoning` text
- **Cross-eval matrix** — N prompts × M games heatmap; drill down to per-event
  detail per cell
- **Prompt diff viewer** — pick two prompt versions, see annotated diff
