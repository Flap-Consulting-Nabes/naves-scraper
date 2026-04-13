#!/usr/bin/env bash
# =============================================================================
# install.sh — Naves Scraper: setup en un comando para Mac y Linux
# =============================================================================
set -euo pipefail

# ── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[•]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${BLUE}$*${RESET}\n"; }

# ── Directorio del proyecto ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

header "═══════════════════════════════════════"
header "   Naves Scraper — Setup de producción "
header "═══════════════════════════════════════"

# ── 1. Verify Google Chrome ──────────────────────────────────────────────────
header "1 · Checking Google Chrome"

CHROME_FOUND=false
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [ -d "/Applications/Google Chrome.app" ]; then
        CHROME_FOUND=true
        CHROME_VER=$("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version 2>/dev/null || echo "installed")
        success "Google Chrome found: $CHROME_VER"
    fi
else
    for chrome_cmd in google-chrome google-chrome-stable chromium-browser chromium; do
        if command -v "$chrome_cmd" &>/dev/null; then
            CHROME_FOUND=true
            CHROME_VER=$("$chrome_cmd" --version 2>/dev/null || echo "installed")
            success "Chrome found: $CHROME_VER"
            break
        fi
    done
fi

if [ "$CHROME_FOUND" = "false" ]; then
    error "Google Chrome is required but was not found."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        warn "Install Chrome from: https://www.google.com/chrome/"
        echo "   Or with Homebrew:  brew install --cask google-chrome"
    else
        warn "Install Chrome:"
        echo "   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
        echo "   sudo dpkg -i google-chrome-stable_current_amd64.deb"
    fi
    exit 1
fi

# ── 2. Verify Python 3.11+ ──────────────────────────────────────────────────
header "2 · Checking Python"

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(sys.version_info[:2])")
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python 3.11 o superior no encontrado."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        warn "Instala Homebrew y Python:"
        echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "   brew install python@3.12"
    else
        warn "Instala Python 3.12 en Ubuntu/Debian:"
        echo "   sudo apt update && sudo apt install python3.12 python3.12-venv -y"
    fi
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')")
success "Python $PY_VERSION encontrado en: $(command -v "$PYTHON")"

# ── 3. System dependencies (Linux) ───────────────────────────────────────────
header "3 · System dependencies"

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if ! command -v Xvfb &>/dev/null; then
        info "Instalando xvfb (display virtual — Chrome corre en background)..."
        if command -v sudo &>/dev/null; then
            sudo apt-get install -y xvfb
            success "xvfb instalado"
        else
            warn "No se encontró sudo. Instala manualmente: apt-get install -y xvfb"
        fi
    else
        success "xvfb ya esta instalado"
    fi

    # VNC para panel Chrome remoto (resolver captchas desde el dashboard)
    if ! command -v x11vnc &>/dev/null || ! command -v websockify &>/dev/null; then
        info "Instalando x11vnc + websockify (panel Chrome remoto)..."
        if command -v sudo &>/dev/null; then
            sudo apt-get install -y x11vnc novnc websockify 2>/dev/null && \
                success "x11vnc + websockify instalados" || \
                warn "No se pudieron instalar x11vnc/websockify — panel Chrome remoto no estara disponible"
        else
            warn "No se encontro sudo. Instala manualmente: apt-get install -y x11vnc novnc websockify"
        fi
    else
        success "x11vnc + websockify ya estan instalados"
    fi

    # Fluxbox: window manager minimo para que Chrome se maximice en Xvfb
    if ! command -v fluxbox &>/dev/null; then
        info "Instalando fluxbox (window manager para Xvfb)..."
        if command -v sudo &>/dev/null; then
            sudo apt-get install -y fluxbox 2>/dev/null && \
                success "fluxbox instalado" || \
                warn "No se pudo instalar fluxbox — Chrome puede no llenar la pantalla virtual"
        else
            warn "No se encontro sudo. Instala manualmente: apt-get install -y fluxbox"
        fi
    else
        success "fluxbox ya esta instalado"
    fi
else
    info "macOS detectado — xvfb/VNC no necesarios (Chrome usa la pantalla del sistema)"
fi

# ── 4. Virtual environment ───────────────────────────────────────────────────
header "4 · Virtual environment"


if [ ! -d "venv" ]; then
    info "Creando venv/..."
    "$PYTHON" -m venv venv
    success "venv/ creado"
else
    success "venv/ ya existe"
fi

# Activar venv
source venv/bin/activate
PYTHON="python"  # A partir de aquí usar el python del venv

# ── 5. Python dependencies ───────────────────────────────────────────────────
header "5 · Installing Python dependencies"

info "pip install -r requirements.txt ..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
success "Dependencias instaladas"

# ── 6. .env config ───────────────────────────────────────────────────────────
header "6 · .env configuration"

if [ ! -f ".env" ]; then
    info "Copiando .env.example → .env"
    cp .env.example .env

    # Auto-generar API_SECRET_KEY
    API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$API_KEY|" .env
    else
        sed -i "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$API_KEY|" .env
    fi
    success ".env creado con API_SECRET_KEY generada automáticamente"
    warn "Edita .env y rellena: WEBFLOW_TOKEN, WEBFLOW_COLLECTION_ID, DASHBOARD_PASSWORD"
else
    success ".env ya existe"

    # Verificar que API_SECRET_KEY está configurada
    current_key=$(grep "^API_SECRET_KEY=" .env | cut -d'=' -f2- | tr -d ' ')
    if [ -z "$current_key" ]; then
        API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$API_KEY|" .env
        else
            sed -i "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$API_KEY|" .env
        fi
        success "API_SECRET_KEY generada automáticamente"
    fi
fi

# ── 7. Directories ───────────────────────────────────────────────────────────
header "7 · Creating directories"

for dir in logs images chrome_profile; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        success "Directorio $dir/ creado"
    else
        info "Directorio $dir/ ya existe"
    fi
done

# ── 8. Frontend (Next.js) ────────────────────────────────────────────────────
header "8 · Frontend (dashboard)"

if ! command -v node &>/dev/null; then
    warn "Node.js no encontrado — el dashboard no se podra compilar."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   Instala con: brew install node"
    else
        echo "   Instala con: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
    fi
else
    NODE_VERSION=$(node -v)
    success "Node.js $NODE_VERSION encontrado"

    if [ -d "frontend" ]; then
        cd frontend

        # Copy .env.local from example if missing
        if [ ! -f ".env.local" ] && [ -f ".env.local.example" ]; then
            cp .env.local.example .env.local
            success ".env.local created from example"
        fi

        info "Installing frontend dependencies..."
        if npm install --legacy-peer-deps; then
            success "Frontend dependencies installed"
        else
            error "npm install failed — check the output above"
            exit 1
        fi

        info "Building dashboard (npm run build)..."
        if npm run build; then
            success "Dashboard built — ready for production"
        else
            error "npm run build failed — check the output above"
            exit 1
        fi
        cd "$SCRIPT_DIR"
    else
        warn "frontend/ folder not found — skipping"
    fi
fi

# ── 9. Summary ───────────────────────────────────────────────────────────────
header "═══════════════════════════════════════"
success "Instalacion completada"
header "═══════════════════════════════════════"

API_KEY_VALUE=$(grep "^API_SECRET_KEY=" .env | cut -d'=' -f2- | tr -d ' ')
echo ""
echo -e "${BOLD}API_SECRET_KEY generada:${RESET}"
echo -e "  ${CYAN}${API_KEY_VALUE}${RESET}"
echo -e "  ${YELLOW}(guarda este valor — lo necesitaras para configurar el dashboard)${RESET}"
echo ""
echo -e "${BOLD}Proximos pasos:${RESET}"
echo ""
echo -e "  ${CYAN}1.${RESET} Edita ${BOLD}.env${RESET} con tus 3 credenciales:"
echo -e "       WEBFLOW_TOKEN, WEBFLOW_COLLECTION_ID, DASHBOARD_PASSWORD"
echo -e "       ${YELLOW}nano .env${RESET}"
echo ""
echo -e "  ${CYAN}2.${RESET} Guarda la sesion de MilAnuncios (login manual, una sola vez):"
echo -e "       ${YELLOW}source venv/bin/activate && python save_session.py${RESET}"
echo -e "       Se abrira Chrome — inicia sesion y navega a Mis Anuncios."
echo -e "       El script detecta el login automaticamente y guarda las cookies."
echo ""
echo -e "  ${CYAN}3.${RESET} Arranca los servicios:"
echo -e "       ${YELLOW}bash start.sh${RESET}"
echo ""
echo -e "  Dashboard: ${CYAN}http://localhost:3000${RESET}"
echo ""
