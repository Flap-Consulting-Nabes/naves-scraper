#!/bin/bash
# Lanza el microservicio FastAPI.
# Chrome corre en modo headful (headless=False) para pasar Kasada/F5 anti-bot.
# El scraper usa un display virtual (Xvfb :99) — Chrome NO aparece en pantalla.
# En VPS, noVNC captura el display :99 para resolver captchas remotamente.
# En Mac, Chrome aparece en pantalla directamente (sin Xvfb ni VNC).

# Iniciar Xvfb si esta disponible (display virtual para el scraper)
if command -v Xvfb &>/dev/null; then
    if ! pgrep -f "Xvfb :99" > /dev/null 2>&1; then
        Xvfb :99 -screen 0 1920x1080x24 -ac &
        XVFB_PID=$!
        sleep 1
        mkdir -p logs
        echo "$XVFB_PID" > logs/xvfb.pid
        echo "[run_api] Xvfb iniciado en :99 (PID $XVFB_PID)"
    else
        echo "[run_api] Xvfb :99 ya estaba corriendo"
    fi
    # Fluxbox: window manager minimo para que --start-maximized funcione en Xvfb
    if command -v fluxbox &>/dev/null; then
        if ! pgrep -f "fluxbox" > /dev/null 2>&1; then
            # Config: Chrome without decorations and auto-maximized in Xvfb
            mkdir -p ~/.fluxbox
            if ! grep -q "name=google-chrome" ~/.fluxbox/apps 2>/dev/null; then
                cat >> ~/.fluxbox/apps <<'FLUXCONF'
[app] (name=google-chrome)
  [Maximized] {yes}
  [Deco] {NONE}
[end]
[app] (name=chromium-browser)
  [Maximized] {yes}
  [Deco] {NONE}
[end]
FLUXCONF
            fi
            DISPLAY=:99 fluxbox &
            FLUXBOX_PID=$!
            sleep 0.5
            echo "$FLUXBOX_PID" > logs/fluxbox.pid
            echo "[run_api] Fluxbox iniciado (PID $FLUXBOX_PID)"
        else
            echo "[run_api] Fluxbox ya estaba corriendo"
        fi
    else
        echo "[run_api] AVISO: fluxbox no instalado — Chrome puede no llenar Xvfb"
        echo "[run_api] Instala con: sudo apt-get install -y fluxbox"
    fi
    # Tanto scraper como save_session.py usan :99 — noVNC captura todo
    export DISPLAY=:99
    export REAL_DISPLAY=:99
    export VIRTUAL_DISPLAY=true
else
    echo "[run_api] AVISO: Xvfb no instalado — Chrome se mostrara en pantalla."
    echo "[run_api] Instala con: sudo apt-get install -y xvfb"
    export DISPLAY="${DISPLAY:-:0}"
    export REAL_DISPLAY="${DISPLAY:-:0}"
fi

# Iniciar x11vnc + websockify si estan disponibles (panel Chrome remoto)
export VNC_AVAILABLE=false
if command -v x11vnc &>/dev/null && command -v websockify &>/dev/null; then
    if ! pgrep -f "x11vnc.*display.*:99" > /dev/null 2>&1; then
        x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -localhost &
        sleep 0.5
        echo "[run_api] x11vnc iniciado en :5900 (localhost)"
    else
        echo "[run_api] x11vnc ya estaba corriendo"
    fi
    if ! pgrep -f "websockify.*6080" > /dev/null 2>&1; then
        websockify localhost:6080 localhost:5900 &
        sleep 0.5
        echo "[run_api] websockify iniciado en :6080"
    fi
    export VNC_AVAILABLE=true
else
    echo "[run_api] AVISO: x11vnc/websockify no instalados — panel Chrome remoto no disponible"
    echo "[run_api] Instala con: sudo apt-get install -y x11vnc novnc websockify"
fi

cd "$(dirname "$0")"
mkdir -p logs

# Guardar PIDs de VNC para cleanup (stop.sh)
if [ "$VNC_AVAILABLE" = "true" ]; then
    pgrep -f "x11vnc.*display.*:99" > logs/x11vnc.pid 2>/dev/null
    pgrep -f "websockify.*6080" > logs/websockify.pid 2>/dev/null
fi

# Activa virtualenv si existe
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

mkdir -p logs

exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
