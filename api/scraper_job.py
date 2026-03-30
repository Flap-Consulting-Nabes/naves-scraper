"""
Gestión del subproceso del scraper.

El scraper corre como subproceso separado porque:
  - Usa zendriver con headless=False (Chrome headful)
  - Llama a asyncio.run() internamente (loop propio)
  - No puede compartir el loop de FastAPI sin conflictos

Estado persistido en scraper_status.json para sobrevivir reinicios de la API.
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
STATUS_FILE = PROJECT_ROOT / "scraper_status.json"
SESSION_STATUS_FILE = PROJECT_ROOT / "session_status.json"
LOG_FILE = PROJECT_ROOT / "logs" / "scraper.log"

# Proceso activo (módulo-level, compartido en el proceso FastAPI)
_proc: asyncio.subprocess.Process | None = None
_lock = asyncio.Lock()
_session_proc: asyncio.subprocess.Process | None = None
_session_lock = asyncio.Lock()


class ScraperStatus(TypedDict):
    state: Literal["idle", "running", "error", "stopped"]
    pid: int | None
    started_at: str | None
    finished_at: str | None
    last_error: str | None
    current_page: int
    total_new: int
    total_skipped: int
    needs_session_renewal: bool
    challenge_waiting: bool


_DEFAULT_STATUS: ScraperStatus = {
    "state": "idle",
    "pid": None,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "current_page": 0,
    "total_new": 0,
    "total_skipped": 0,
    "needs_session_renewal": False,
    "challenge_waiting": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(status: ScraperStatus) -> None:
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def read_status() -> ScraperStatus:
    if not STATUS_FILE.exists():
        return dict(_DEFAULT_STATUS)  # type: ignore[return-value]
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_STATUS)  # type: ignore[return-value]


def recover_stale_session_status() -> None:
    """
    Al iniciar FastAPI: si el estado de sesión dice "running" pero el PID ya no existe,
    corregir a "error" para que el dashboard no quede bloqueado.
    """
    sess = read_session_status()
    if sess.get("state") != "running":
        return
    pid = sess.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return  # proceso sigue vivo
        except (ProcessLookupError, PermissionError):
            pass
    sess["state"] = "error"
    sess["last_error"] = "Proceso no encontrado al iniciar la API (posible crash anterior)"
    sess["finished_at"] = _now()
    _write_session_status(sess)
    logger.warning("[Session] Estado zombie corregido: proceso %s no encontrado", pid)


def recover_stale_status() -> None:
    """
    Al iniciar FastAPI: si el estado dice "running" pero el PID ya no existe,
    significa que el proceso murió sin limpiar (crash, reboot, etc.).
    """
    status = read_status()
    if status["state"] != "running":
        return
    pid = status.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return  # proceso sigue vivo
        except (ProcessLookupError, PermissionError):
            pass
    status["state"] = "error"
    status["last_error"] = "Proceso no encontrado al iniciar la API (posible crash anterior)"
    status["finished_at"] = _now()
    _write_status(status)
    logger.warning("[Scraper] Estado zombie corregido: proceso %s no encontrado", pid)


# ── Logging del subproceso ────────────────────────────────────────────────────

def _get_log_handler() -> RotatingFileHandler:
    LOG_FILE.parent.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        str(LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


async def _monitor_proc(proc: asyncio.subprocess.Process) -> None:
    """Lee stdout del subproceso, parsea progreso y escribe en el log rotativo."""
    log_handler = _get_log_handler()
    status = read_status()

    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip()

        # Escribir en log rotativo
        record = logging.LogRecord(
            name="scraper", level=logging.INFO,
            pathname="", lineno=0, msg=line,
            args=(), exc_info=None,
        )
        log_handler.emit(record)

        # Parsear métricas del output del scraper
        if "PÁGINA" in line or "Página" in line:
            import re
            m = re.search(r"[Pp]ágina[^\d]*(\d+)", line)
            if m:
                status["current_page"] = int(m.group(1))
        elif "Nuevos insertados" in line:
            import re
            m = re.search(r"(\d+)\s*$", line)  # último número (evita capturar timestamp)
            if m:
                status["total_new"] = int(m.group(1))
        elif "Duplicados" in line or "saltados" in line.lower():
            import re
            m = re.search(r"(\d+)\s*$", line)  # último número (evita capturar timestamp)
            if m:
                status["total_skipped"] = int(m.group(1))
        elif "[CAPTCHA_REQUIRED]" in line or "[CAPTCHA_WAITING]" in line:
            status["challenge_waiting"] = True
        elif "[CAPTCHA_SOLVED]" in line:
            status["challenge_waiting"] = False
        elif "[CAPTCHA_TIMEOUT]" in line:
            status["challenge_waiting"] = False
            status["needs_session_renewal"] = True
            status["last_error"] = line[:200]
        elif any(kw in line.lower() for kw in ("ban", "bloqueado", "f5/incapsula", "kasada", "save_session")):
            status["last_error"] = line[:200]
            status["needs_session_renewal"] = True
        elif any(kw in line.lower() for kw in ("warm-up completo", "cooldown completo", "resumen:")):
            status["needs_session_renewal"] = False
            status["last_error"] = None

        _write_status(status)

    log_handler.close()

    rc = await proc.wait()
    status = read_status()
    status["challenge_waiting"] = False
    if rc == 0:
        status["state"] = "idle"
        status["needs_session_renewal"] = False
        status["last_error"] = None
    elif rc == -15 or rc == 143:  # SIGTERM
        status["state"] = "stopped"
    else:
        status["state"] = "error"
        if not status.get("last_error"):
            status["last_error"] = f"El proceso terminó con código {rc}"
    status["finished_at"] = _now()
    _write_status(status)
    logger.info("[Scraper] Proceso terminado con código %s → estado=%s", rc, status["state"])


# ── Renovación de sesión ──────────────────────────────────────────────────────

def _write_session_status(data: dict) -> None:
    tmp = SESSION_STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SESSION_STATUS_FILE)


def read_session_status() -> dict:
    if not SESSION_STATUS_FILE.exists():
        return {"state": "idle", "pid": None, "started_at": None, "finished_at": None, "last_error": None}
    try:
        return json.loads(SESSION_STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "idle", "pid": None, "started_at": None, "finished_at": None, "last_error": None}


async def _monitor_session_proc(proc: asyncio.subprocess.Process) -> None:
    log_handler = _get_log_handler()
    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        record = logging.LogRecord(
            name="session", level=logging.INFO,
            pathname="", lineno=0, msg=f"[SESSION] {line}",
            args=(), exc_info=None,
        )
        log_handler.emit(record)
        # Actualizar estado de espera de login
        sess = read_session_status()
        if "[LOGIN_WAITING]" in line:
            sess["waiting_for_login"] = True
        elif "Login detectado" in line or "login detectado" in line.lower():
            sess["waiting_for_login"] = False
            sess["login_detected"] = True
        elif "Navegando a naves" in line or "naves industriales" in line.lower():
            sess["navigating"] = True
        elif "Sesion guardada" in line or "sesion guardada" in line.lower():
            sess["waiting_for_login"] = False
        _write_session_status(sess)
    log_handler.close()

    rc = await proc.wait()
    sess = read_session_status()
    sess["state"] = "idle" if rc == 0 else "error"
    sess["finished_at"] = _now()
    sess["waiting_for_login"] = False
    sess["login_detected"] = False
    sess["navigating"] = False
    if rc != 0:
        sess["last_error"] = f"save_session.py terminó con código {rc}"
    _write_session_status(sess)

    # Si terminó OK, limpiar flag needs_session_renewal del scraper
    if rc == 0:
        status = read_status()
        status["needs_session_renewal"] = False
        status["last_error"] = None
        _write_status(status)
    logger.info("[Session] save_session.py terminó con código %s", rc)


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

        env = os.environ.copy()
        env.setdefault("DISPLAY", ":1")

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
        asyncio.create_task(_monitor_session_proc(_session_proc))
        return True


# ── Lanzar / detener ──────────────────────────────────────────────────────────

async def launch_scraper(
    max_pages: int = 0,
    dry_run: bool = False,
    reset: bool = False,
) -> bool:
    """
    Lanza scraper_engine.py como subproceso.
    Retorna False si ya hay uno corriendo.
    """
    global _proc
    async with _lock:
        if _proc is not None and _proc.returncode is None:
            return False  # ya corriendo

        env = os.environ.copy()
        env.setdefault("DISPLAY", ":1")  # Chrome headful necesita display

        cmd = [sys.executable, str(PROJECT_ROOT / "scraper_engine.py")]
        if max_pages:
            cmd += ["--pages", str(max_pages)]
        if dry_run:
            cmd.append("--dry-run")
        if reset:
            cmd.append("--reset")

        status: ScraperStatus = {
            **_DEFAULT_STATUS,  # type: ignore[misc]
            "state": "running",
            "started_at": _now(),
        }
        _write_status(status)

        _proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        status["pid"] = _proc.pid
        _write_status(status)
        logger.info("[Scraper] Lanzado PID %s: %s", _proc.pid, " ".join(cmd))

        asyncio.create_task(_monitor_proc(_proc))
        return True


async def stop_scraper() -> bool:
    """Envía SIGTERM al subproceso. Retorna False si no hay proceso activo."""
    global _proc
    async with _lock:
        if _proc is None or _proc.returncode is not None:
            return False

        _proc.terminate()
        try:
            await asyncio.wait_for(_proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            _proc.kill()
            await _proc.wait()

        status = read_status()
        status["state"] = "stopped"
        status["finished_at"] = _now()
        _write_status(status)
        logger.info("[Scraper] Detenido manualmente")
        return True
