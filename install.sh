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

# ── 1. Verificar Python 3.11+ ────────────────────────────────────────────────
header "1 · Verificando Python"

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

# ── 2. Entorno virtual ───────────────────────────────────────────────────────
header "2 · Entorno virtual"

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

# ── 3. Dependencias ──────────────────────────────────────────────────────────
header "3 · Instalando dependencias"

info "pip install -r requirements.txt ..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
success "Dependencias instaladas"

# ── 4. Archivo .env ──────────────────────────────────────────────────────────
header "4 · Configuración .env"

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

# ── 5. Directorios ───────────────────────────────────────────────────────────
header "5 · Creando directorios"

for dir in logs images chrome_profile; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        success "Directorio $dir/ creado"
    else
        info "Directorio $dir/ ya existe"
    fi
done

# ── 6. Resumen ───────────────────────────────────────────────────────────────
header "═══════════════════════════════════════"
success "Setup completado"
header "═══════════════════════════════════════"

echo ""
echo -e "${BOLD}Próximos pasos:${RESET}"
echo ""
echo -e "  ${CYAN}1.${RESET} Edita ${BOLD}.env${RESET} con tus credenciales:"
echo -e "       ${YELLOW}nano .env${RESET}   (o código editor de tu elección)"
echo -e "       Variables obligatorias: WEBFLOW_TOKEN, WEBFLOW_COLLECTION_ID, DASHBOARD_PASSWORD"
echo ""
echo -e "  ${CYAN}2.${RESET} Configura la sesión de MilAnuncios (login manual ~1 min):"
echo -e "       ${YELLOW}source venv/bin/activate && python save_session.py${RESET}"
echo ""
echo -e "  ${CYAN}3.${RESET} Arranca los servicios:"
echo -e "       ${YELLOW}bash run_api.sh${RESET}        → API en http://localhost:8000"
echo -e "       ${YELLOW}bash run_dashboard.sh${RESET}  → Dashboard en http://localhost:8501"
echo ""
echo -e "  ${CYAN}4.${RESET} Para producción (background, sobrevive al cierre del terminal):"
echo -e "       ${YELLOW}nohup bash run_api.sh > logs/api.log 2>&1 &${RESET}"
echo -e "       ${YELLOW}nohup bash run_dashboard.sh > logs/dashboard.log 2>&1 &${RESET}"
echo ""

# ── Opcional: arrancar ahora ─────────────────────────────────────────────────
echo -e "${BOLD}¿Quieres arrancar la API y el Dashboard ahora en background? [s/N]${RESET} "
read -r start_now </dev/tty || true

if [[ "$start_now" =~ ^[sS]$ ]]; then
    # Verificar que .env tiene las variables mínimas
    dash_pass=$(grep "^DASHBOARD_PASSWORD=" .env | cut -d'=' -f2- | tr -d ' ')
    if [ -z "$dash_pass" ]; then
        warn "DASHBOARD_PASSWORD no está configurada en .env — arranca los servicios manualmente después de editarlo."
    else
        info "Arrancando API..."
        nohup bash run_api.sh > logs/api.log 2>&1 &
        echo $! > logs/api.pid
        success "API iniciada (PID $(cat logs/api.pid)) → logs/api.log"

        info "Arrancando Dashboard..."
        nohup bash run_dashboard.sh > logs/dashboard.log 2>&1 &
        echo $! > logs/dashboard.pid
        success "Dashboard iniciado (PID $(cat logs/dashboard.pid)) → logs/dashboard.log"

        echo ""
        echo -e "  API:       ${CYAN}http://localhost:8000/health${RESET}"
        echo -e "  Dashboard: ${CYAN}http://localhost:8501${RESET}"
        echo ""
        echo -e "  Para parar: ${YELLOW}kill \$(cat logs/api.pid) \$(cat logs/dashboard.pid)${RESET}"
    fi
fi

echo ""
