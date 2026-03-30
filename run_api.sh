#!/bin/bash
# Lanza el microservicio FastAPI.
# DISPLAY es necesario para que zendriver abra Chrome en modo headful
# (headless=False requerido para pasar Kasada/F5 anti-bot).
#
# En servidor sin pantalla, instala Xvfb y descomenta:
#   Xvfb :1 -screen 0 1920x1080x24 -ac &
#   sleep 1

export DISPLAY="${DISPLAY:-:1}"

cd "$(dirname "$0")"

# Activa virtualenv si existe
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

mkdir -p logs

uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
