#!/bin/bash
# Quick local start: kill any old servers and run backend + frontend in the
# background, logging to ./logs/.
# Usage: ./start-dev.sh

set -e
cd "$(dirname "$0")"

mkdir -p logs

echo "Stopping any previous dev servers..."
pkill -f "node server.js" 2>/dev/null || true
pkill -f "vite"           2>/dev/null || true
sleep 1

echo "Starting backend (Express, :3001)..."
nohup npm run server > logs/server.log 2>&1 &
echo "  pid=$!"

echo "Starting frontend (Vite, :5173)..."
nohup npm run dev > logs/vite.log 2>&1 &
echo "  pid=$!"

cat <<EOF

Frontend: http://localhost:5173
Backend:  http://localhost:3001

Tail logs:
  tail -f logs/server.log
  tail -f logs/vite.log

Stop:
  ./stop-dev.sh
EOF
