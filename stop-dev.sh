#!/bin/bash
# Stop dev servers started by start-dev.sh
# Usage: ./stop-dev.sh

echo "Stopping backend..."
pkill -f "node server.js" && echo "  backend stopped" || echo "  backend not running"

echo "Stopping frontend..."
pkill -f "vite" && echo "  frontend stopped" || echo "  frontend not running"
