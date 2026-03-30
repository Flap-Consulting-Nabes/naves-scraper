#!/bin/bash
# Detiene API y dashboard.

cd "$(dirname "$0")"

stop_service() {
    local name="$1"
    local pidfile="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "[OK] $name detenido (PID $pid)"
        else
            echo "[INFO] $name no estaba en marcha (PID $pid ya muerto)"
        fi
        rm -f "$pidfile"
    else
        echo "[INFO] $name: no se encontro $pidfile"
    fi
}

stop_service "API"       logs/api.pid
stop_service "Dashboard" logs/dashboard.pid
