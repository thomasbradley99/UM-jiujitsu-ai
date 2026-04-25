# UM Jiujitsu AI

AI-powered fight-video analysis and live coaching app, built originally for the
Antler / ElevenLabs hackathon.

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
