#!/bin/bash
set -e
cd "$(dirname "$0")/backend"

# Kill any existing instance
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

# Ensure data dirs exist
mkdir -p ../data/videos ../data/frames ../data/traces

echo "[Gofer Trace] Starting backend on port 8001..."
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/gofer_backend.log 2>&1 &
echo "[Gofer Trace] PID: $!"
sleep 2
curl -s http://localhost:8001/ && echo " — backend OK"
