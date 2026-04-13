"""
Gestión del subproceso de renovación de sesión (save_session.py).

Extraído de api/scraper_job.py para mantener cada archivo < 300 líneas.
"""
import asyncio
import glob
import json
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from api.task_registry import fire_and_track

from api.scraper_job import (
    PROJECT_ROOT, SESSION_STATUS_FILE,
    _now, _write_status, read_session_status, read_status,
)
from utils.logging_config import get_scraper_log_handler

logger = logging.getLogger(__name__)

# Proceso activo (módulo-level, compartido en el proceso FastAPI)
_session_proc: asyncio.subprocess.Process | None = None
_session_lock = asyncio.Lock()

SESSION_RENEWAL_TIMEOUT = 900  # 15 min (10 min login + 5 min buffer para navegación)

PROFILE_DIR = PROJECT_ROOT / "chrome_profile"


def _kill_stale_chrome() -> None:
    """Mata Chrome usando chrome_profile/ y limpia lock files del perfil."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "chrome.*chrome_profile"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.strip()]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        if pids:
            import time
            time.sleep(1)
            logger.warning("[Session] Chrome huérfano eliminado: PIDs %s", pids)
    except Exception as e:
        logger.warning("[Session] Error buscando Chrome huérfano: %s", e)
    # Limpiar lock files del perfil
    for lock in glob.glob(str(PROFILE_DIR / "Singleton*")):
        try:
            os.remove(lock)
        except OSError:
            pass


def _write_session_status(data: dict) -> None:
    tmp = SESSION_STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SESSION_STATUS_FILE)


async def _do_monitor_session(proc: asyncio.subprocess.Process) -> bool:
    """Monitorea stdout de save_session.py. Retorna True si la sesión fue guardada."""
    log_handler = get_scraper_log_handler()
    session_saved = False
    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        record = logging.LogRecord(
            name="session", level=logging.INFO,
            pathname="", lineno=0, msg=f"[SESSION] {line}",
            args=(), exc_info=None,
        )
        log_handler.emit(record)
        sess = read_session_status()
        if "[SESSION_SAVED]" in line:
            session_saved = True
            sess["login_detected"] = True
            sess["waiting_for_login"] = False
        elif "[SESSION_TIMEOUT]" in line:
            sess["last_error"] = "Tiempo de espera agotado — el login no se completó en 10 min."
        elif "[SESSION_NAV:failed]" in line:
            sess["last_error"] = "Chrome no pudo cargar la URL inicial (about:blank tras 3 reintentos)"
            sess["state"] = "error"
        elif "[SESSION_NAV:ok]" in line:
            sess["last_error"] = None
        elif "[SESSION_NAV:blank]" in line:
            sess["last_error"] = "Chrome en about:blank — reintentando navegación..."
        elif "[LOGIN_WAITING]" in line:
            sess["waiting_for_login"] = True
        elif "Login detectado" in line or "login detectado" in line.lower():
            sess["waiting_for_login"] = False
            sess["login_detected"] = True
        elif "Navegando a naves" in line or "naves industriales" in line.lower():
            sess["navigating"] = True
        _write_session_status(sess)
    log_handler.close()

    rc = await proc.wait()
    sess = read_session_status()
    sess["waiting_for_login"] = False
    sess["login_detected"] = False
    sess["navigating"] = False
    sess["finished_at"] = _now()
    if session_saved:
        sess["state"] = "idle"
        sess["last_error"] = None
    elif rc == 0:
        sess["state"] = "error"
        if not sess.get("last_error"):
            sess["last_error"] = "El proceso terminó sin guardar la sesión."
    else:
        sess["state"] = "error"
        if not sess.get("last_error"):
            sess["last_error"] = f"save_session.py terminó con código {rc}"
    _write_session_status(sess)

    # Solo limpiar needs_session_renewal si la sesión fue guardada correctamente
    if session_saved:
        status = read_status()
        status["needs_session_renewal"] = False
        status["last_error"] = None
        _write_status(status)
    logger.info("[Session] save_session.py terminó con código %s (session_saved=%s)", rc, session_saved)
    return session_saved


async def _monitor_session_proc(proc: asyncio.subprocess.Process) -> None:
    try:
        await asyncio.wait_for(_do_monitor_session(proc), timeout=SESSION_RENEWAL_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        sess = read_session_status()
        sess["state"] = "error"
        sess["finished_at"] = _now()
        sess["last_error"] = "Proceso colgado — sin respuesta por 15 min. Chrome puede estar bloqueado."
        sess["waiting_for_login"] = False
        sess["login_detected"] = False
        sess["navigating"] = False
        _write_session_status(sess)
        logger.error("[Session] Timeout de 15 min alcanzado — proceso forzado a terminar")


async def stop_session_renewal() -> bool:
    """Cancela el proceso save_session.py si está corriendo. Retorna False si no hay proceso activo."""
    global _session_proc
    async with _session_lock:
        if _session_proc is None or _session_proc.returncode is not None:
            return False
        _session_proc.terminate()
        try:
            await asyncio.wait_for(_session_proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            _session_proc.kill()
            await _session_proc.wait()
        sess = read_session_status()
        sess["state"] = "error"
        sess["finished_at"] = _now()
        sess["last_error"] = "Cancelado por el usuario."
        sess["waiting_for_login"] = False
        sess["login_detected"] = False
        sess["navigating"] = False
        _write_session_status(sess)
        logger.info("[Session] Renovación de sesión cancelada por el usuario")
        return True


async def launch_session_renewal() -> bool:
    """
    Lanza save_session.py como subproceso para renovar la sesión de Milanuncios.
    Abre Chrome en modo headful — el usuario debe interactuar con él.
    Retorna False si ya está corriendo.
    """
    global _session_proc
    async with _session_lock:
        if _session_proc is not None and _session_proc.returncode is None:
            return False

        # Matar proceso huérfano de un ciclo anterior de la API
        sess = read_session_status()
        stale_pid = sess.get("pid")
        if stale_pid:
            try:
                os.kill(stale_pid, signal.SIGKILL)
                logger.warning("[Session] Proceso huérfano %s terminado", stale_pid)
            except (ProcessLookupError, PermissionError):
                pass

        # Matar Chrome huérfano y limpiar locks del perfil
        _kill_stale_chrome()

        env = os.environ.copy()
        # session renewal must use the REAL display — the user needs to see Chrome to login.
        # REAL_DISPLAY is exported by run_api.sh before redirecting to the Xvfb virtual display.
        real_display = os.environ.get("REAL_DISPLAY", os.environ.get("DISPLAY", ":0"))
        env["DISPLAY"] = real_display

        _write_session_status({
            "state": "running",
            "pid": None,
            "started_at": _now(),
            "finished_at": None,
            "last_error": None,
        })

        _session_proc = await asyncio.create_subprocess_exec(
            sys.executable, str(PROJECT_ROOT / "save_session.py"),
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        sess = read_session_status()
        sess["pid"] = _session_proc.pid
        _write_session_status(sess)

        logger.info("[Session] save_session.py lanzado PID %s", _session_proc.pid)
        fire_and_track(_monitor_session_proc(_session_proc), name="session-monitor")
        return True
