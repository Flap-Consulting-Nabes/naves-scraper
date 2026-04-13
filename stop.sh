#!/bin/bash
# Stops API, frontend, and VNC services.

cd "$(dirname "$0")"

stop_service() {
    local name="$1"
    local pidfile="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "[OK] $name stopped (PID $pid)"
        else
            echo "[INFO] $name was not running (PID $pid already dead)"
        fi
        rm -f "$pidfile"
    else
        echo "[INFO] $name: $pidfile not found"
    fi
}

stop_service "API"         logs/api.pid
stop_service "Frontend"    logs/frontend.pid

# VNC / display services started by run_api.sh
stop_service "x11vnc"      logs/x11vnc.pid
stop_service "websockify"  logs/websockify.pid
stop_service "Fluxbox"     logs/fluxbox.pid
stop_service "Xvfb"        logs/xvfb.pid
