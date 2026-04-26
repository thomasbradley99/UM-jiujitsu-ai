# UM Jiujitsu AI

AI-powered fight-video analysis and live coaching app.

> # 🥋 Hackathon submission — MuBit prompt-optimization flywheel
>
> ### 👉 Two reports, both rendered live in your browser
>
> | | |
> |--|--|
> | 📊 **[The results](https://htmlpreview.github.io/?https://github.com/thomasbradley99/UM-jiujitsu-ai/blob/main/flywheel/outputs/arc_report_handtuned.html)** | F1 climbs **57% → 77% → 50% → 100%** across 4 prompt versions. Side-by-side iterations, prompt diffs, optimizer rationales, per-event outcomes. |
> | 🔧 **[How we use MuBit](https://htmlpreview.github.io/?https://github.com/thomasbradley99/UM-jiujitsu-ai/blob/main/flywheel/outputs/mubit_integration.html)** | The integration tour. 5 SDK calls, 1 file of glue, 4 touch-points — with the actual code, the rationale strategy, and what MuBit does/doesn't do. |
>
> ---
>
> A **self-improving prompt loop** that uses MuBit as a versioned prompt
> store + outcome log + LLM-based prompt rewriter. We optimise the
> **DOMAIN RULES** layer of `VLM-gemini/analyze.py`'s BJJ submission
> detector. Each iteration: run the pipeline → score against ground
> truth → record per-event outcomes to MuBit → ask MuBit's optimizer for
> a better prompt → activate it → run again.
>
> ### Headline arc (4 iterations on the `ryan-thomas` 6-min sparring video)
>
> | Iter | F1 | Recall | Precision | Matched | Halls | Prompt version |
> |------|----|--------|-----------|---------|-------|----------------|
> | v1 (seed)         |  57% |  80% |  44% | 4/5 | 5 | `pv-ac5575b2-…` |
> | v2                |  77% | 100% |  62% | 5/5 | 3 | `pv-b535d177-…` |
> | v3 *(regression)* |  50% |  60% |  43% | 3/5 | 4 | `pv-853f6c04-…` |
> | **v4 (perfect)**  | **100%** | **100%** | **100%** | **5/5** | **0** | `pv-377be9c6-…` |
>
> Same fight, same `analyze.py`, same Gemini model. The only thing that
> changes between rows is the rules block MuBit owns. At v4: timestamp
> MAE **2.4s**, submitter attribution **80%** (4/5).
>
> ### Where everything lives
>
> | Where | What it is |
> |-------|------------|
> | [📊 **arc_report_handtuned.html** (rendered)](https://htmlpreview.github.io/?https://github.com/thomasbradley99/UM-jiujitsu-ai/blob/main/flywheel/outputs/arc_report_handtuned.html) | The headline F1 arc, fully visual |
> | [🔧 **mubit_integration.html** (rendered)](https://htmlpreview.github.io/?https://github.com/thomasbradley99/UM-jiujitsu-ai/blob/main/flywheel/outputs/mubit_integration.html) | How we use the MuBit SDK end-to-end |
> | [`flywheel/RESULTS.md`](./flywheel/RESULTS.md) | Plain-text tour of every result artifact |
> | [`flywheel/outputs/loop_arc_handtuned.json`](./flywheel/outputs/loop_arc_handtuned.json) | Raw per-iteration metrics |
> | [`flywheel/outputs/runs/verify:video/`](./flywheel/outputs/runs/verify:video/) | Per-prompt-version receipts: prompt text, predictions, eval scores |
> | [`flywheel/mubit_client.py`](./flywheel/mubit_client.py) | The only file that imports the MuBit SDK (160 lines) |
> | [`flywheel/README.md`](./flywheel/README.md) | Repo-internal how-it-works |
>
> Reproduce: `python -m flywheel.cli loop --iterations 4` (after
> `flywheel.cli setup`). See [`flywheel/README.md`](./flywheel/README.md).

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
