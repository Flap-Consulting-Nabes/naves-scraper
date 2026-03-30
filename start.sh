#!/bin/bash
# Inicia API y dashboard en segundo plano.
# Los PID se guardan en logs/api.pid y logs/dashboard.pid.
# Logs en logs/api.log y logs/dashboard.log.

cd "$(dirname "$0")"
mkdir -p logs

# Comprobar si ya hay procesos activos
if [ -f logs/api.pid ] && kill -0 "$(cat logs/api.pid)" 2>/dev/null; then
    echo "[WARN] La API ya esta en marcha (PID $(cat logs/api.pid)). Usa restart.sh para reiniciar."
    exit 1
fi
if [ -f logs/dashboard.pid ] && kill -0 "$(cat logs/dashboard.pid)" 2>/dev/null; then
    echo "[WARN] El dashboard ya esta en marcha (PID $(cat logs/dashboard.pid)). Usa restart.sh para reiniciar."
    exit 1
fi

nohup bash run_api.sh > logs/api.log 2>&1 &
echo $! > logs/api.pid
echo "[OK] API iniciada (PID $!) — logs en logs/api.log"

nohup bash run_dashboard.sh > logs/dashboard.log 2>&1 &
echo $! > logs/dashboard.pid
echo "[OK] Dashboard iniciado (PID $!) — logs en logs/dashboard.log"

echo ""
echo "  API:       http://localhost:8000"
echo "  Dashboard: http://localhost:8501"
