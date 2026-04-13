#!/bin/bash
# Starts API and frontend in the background.
# PIDs saved to logs/api.pid and logs/frontend.pid.

cd "$(dirname "$0")"
mkdir -p logs

# Check for already running services
if [ -f logs/api.pid ] && kill -0 "$(cat logs/api.pid)" 2>/dev/null; then
    echo "[WARN] API already running (PID $(cat logs/api.pid)). Use restart.sh to restart."
    exit 1
fi
if [ -f logs/frontend.pid ] && kill -0 "$(cat logs/frontend.pid)" 2>/dev/null; then
    echo "[WARN] Frontend already running (PID $(cat logs/frontend.pid)). Use restart.sh to restart."
    exit 1
fi

nohup bash run_api.sh > logs/api.log 2>&1 &
echo $! > logs/api.pid
echo "[OK] API started (PID $!) — logs at logs/api.log"

nohup bash run_frontend.sh > logs/frontend.log 2>&1 &
echo $! > logs/frontend.pid
echo "[OK] Frontend started (PID $!) — logs at logs/frontend.log"

echo ""
echo "  API:       http://localhost:8000"
echo "  Dashboard: http://localhost:3000"

if command -v x11vnc &>/dev/null && command -v websockify &>/dev/null; then
    echo "  VNC:       ws://localhost:6080 (remote Chrome panel active)"
else
    echo "  VNC:       not available (install x11vnc + websockify for remote Chrome panel)"
fi

# Health check — wait for API to respond (max 15s)
echo ""
echo "Waiting for API to start..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[OK] API is healthy and responding on :8000"
        exit 0
    fi
    sleep 0.5
done
echo "[WARN] API did not respond within 15s — check logs/api.log for errors"
exit 1
