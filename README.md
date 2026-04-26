# UM Jiujitsu AI

AI-powered fight-video analysis and live coaching app.

> ## Hackathon submission — MuBit prompt-optimization flywheel
>
> The submitted track is a **self-improving prompt loop** that uses MuBit
> as a versioned prompt store + outcome log + LLM-based prompt rewriter.
> We optimise the **DOMAIN RULES** layer of `VLM-gemini/analyze.py`'s scan
> prompt — the slab that defines what counts as a finished BJJ submission
> in training footage.
>
> **Headline result on the `ryan-thomas` 6-min sparring video:**
> F1 climbs **57% → 77% → 50% → 100%** across 4 prompt versions, ending
> at perfect precision/recall (5/5 matched, 0 hallucinations) with
> 2.4s timestamp MAE.
>
> | Where to look | What it is |
> |---------------|------------|
> | [`flywheel/RESULTS.md`](./flywheel/RESULTS.md) | **Start here.** Tour of every result artifact, with explanation. |
> | [`flywheel/outputs/arc_report_handtuned.html`](./flywheel/outputs/arc_report_handtuned.html) | Self-contained HTML — open in a browser to see the full arc, prompt diffs, optimizer rationales, per-event TP/FP/FN. |
> | [`flywheel/outputs/arc_report_naive.html`](./flywheel/outputs/arc_report_naive.html) | Contrast: same loop, weaker seed → F1 drifts down. Demonstrates why anchoring/ground-truth feedback matters. |
> | [`flywheel/outputs/loop_arc_handtuned.json`](./flywheel/outputs/loop_arc_handtuned.json) | Raw per-iteration metrics. |
> | [`flywheel/outputs/runs/verify:video/`](./flywheel/outputs/runs/verify:video/) | Per-prompt-version snapshots: prompt text, predictions, eval scores. |
> | [`flywheel/outputs/cross_eval/chris-instructor/`](./flywheel/outputs/cross_eval/chris-instructor/) | Same 4 prompts run on a held-out video — generalisation evidence (and v4-overfit warning). |
> | [`flywheel/`](./flywheel/) source | All glue code. `mubit_client.py` is the only file that touches the SDK. |
>
> Reproduce with `python -m flywheel.cli loop --iterations 4` (after
> `flywheel.cli setup`). See [`flywheel/README.md`](./flywheel/README.md)
> for the full how-it-works.

---

The rest of this README covers the original product — an interactive
fight-analysis web app, built for the Antler / ElevenLabs hackathon.

- **Vision / event detection**: Google Gemini (`@google/genai`)
- **Live talking-head coach**: Anam AI (`@anam-ai/js-sdk`)
- **Frontend**: React 19 + Vite + TypeScript + Tailwind
- **Backend**: tiny Express server (`server.js`) that holds the Anam API key and
  mints session tokens for the browser

```
.
├── App.tsx                  # main UI (~1k lines)
├── index.tsx / index.html
├── server.js                # Express, port 3001, /api/anam/session-token
├── components/              # React UI (video player, overlays, persona picker, ...)
├── services/                # geminiService, anamService, personas, logger
├── mma_gemini/              # offline Python pipeline (clip cutter + Gemini analysis)
└── ...
```

## Prerequisites

- Node 20.x (the project was developed against `v20.19.5`)
- `GEMINI_API_KEY` (Google AI Studio)
- `ANAM_API_KEY` (https://anam.ai)

## Run locally

```bash
git clone https://github.com/thomasbradley99/UM-jiujitsu-ai.git
cd UM-jiujitsu-ai
npm install

# create env file with your keys (no quotes)
cat > .env.local <<'EOF'
GEMINI_API_KEY=your_gemini_key
ANAM_API_KEY=your_anam_key
EOF
chmod 600 .env.local

# in one terminal: backend (Express, port 3001)
npm run server

# in another terminal: frontend (Vite, port 5173)
npm run dev
```

Open http://localhost:5173.

## Run on a remote VM, access from your laptop (SSH tunnel)

On the VM:

```bash
cd ~/UM-jiujitsu-ai
npm run server                                  # terminal 1
npm run dev -- --host 127.0.0.1 --port 5173     # terminal 2
```

On your laptop:

```bash
ssh -N -L 5174:127.0.0.1:5173 -i ~/.ssh/<your-key> ubuntu@<vm-ip>
# then open http://localhost:5174
```

## Quick checks

```bash
# laptop
curl -I http://localhost:5174 | head -n1

# VM
curl -I 127.0.0.1:5173 | head -n1
curl -I 127.0.0.1:3001 | head -n1   # 404 at / is expected; only /api/anam/session-token is mounted
```

## Troubleshooting

```bash
# nvm .npmrc prefix warning
. "$HOME/.nvm/nvm.sh"; nvm use --delete-prefix v20.19.5

# ports busy
pkill -f "node server.js" || true
pkill -f "vite" || true

# verify listeners
ss -ltnp | grep -E ":(5173|3001) "

# white screen on frontend: confirm keys exist, then restart Vite
test -f .env.local && grep -E "^(GEMINI_API_KEY|ANAM_API_KEY)=" .env.local
```

## License

See `LICENSE`.
