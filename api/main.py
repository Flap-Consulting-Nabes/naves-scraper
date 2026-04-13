"""
Microservicio FastAPI para el scraper de naves industriales.

Endpoints:
  GET  /health
  POST /api/scraper/run
  GET  /api/scraper/status
  POST /api/scraper/stop
  GET  /api/listings
  GET  /api/logs
  GET  /api/cron
  PUT  /api/cron
  POST /api/webflow/sync
  GET  /api/webflow/status
  GET  /api/vnc/status
"""
import asyncio
import collections
import hmac
import logging
import math
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from croniter import CroniterBadCronError, croniter
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.dependencies import API_SECRET_KEY, DASHBOARD_PASSWORD, DB_PATH, get_config, get_db, save_config, verify_api_key
from utils.logging_config import setup_logging

setup_logging(api_mode=True)
from api.scraper_job import (
    launch_scraper, read_status, recover_stale_status, recover_stale_session_status, stop_scraper,
)
from api.session_job import launch_session_renewal, read_session_status, stop_session_renewal
from db import get_listings_paginated, init_db

logger = logging.getLogger(__name__)

LOG_FILE = Path("logs/scraper.log")
ERROR_LOG_FILE = Path("logs/errors.log")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar DB y correr migraciones (añade columnas nuevas si faltan)
    conn = init_db(DB_PATH)
    conn.close()
    logger.info("[API] DB inicializada y migrada")

    # Corregir estado zombie si hubo crash previo
    recover_stale_status()
    recover_stale_session_status()

    # Iniciar scheduler
    from scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("[API] Scheduler iniciado")

    yield

    # Drain tracked async tasks before shutting down
    from api.task_registry import drain
    await drain(timeout=30.0)

    scheduler.shutdown(wait=False)
    logger.info("[API] Scheduler detenido")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Naves Scraper API",
    version="1.0.0",
    description="Microservicio para scraping de naves industriales en Milanuncios",
    lifespan=lifespan,
)

_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class CronConfigRequest(BaseModel):
    cron_expr: str
    max_pages: int = 0


class ScrapeRunRequest(BaseModel):
    max_pages: int = 0
    batch: int = 0
    dry_run: bool = False
    reset: bool = False


class LoginRequest(BaseModel):
    password: str


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login", tags=["auth"])
async def auth_login(body: LoginRequest):
    if not DASHBOARD_PASSWORD or not hmac.compare_digest(body.password, DASHBOARD_PASSWORD):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    return {"api_key": API_SECRET_KEY}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["sistema"])
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Scraper ───────────────────────────────────────────────────────────────────

@app.post("/api/scraper/run", dependencies=[Depends(verify_api_key)], tags=["scraper"])
async def scraper_run(body: ScrapeRunRequest = ScrapeRunRequest()):
    launched = await launch_scraper(
        max_pages=body.max_pages,
        batch=body.batch,
        dry_run=body.dry_run,
        reset=body.reset,
    )
    if not launched:
        raise HTTPException(status_code=409, detail="El scraper ya está en ejecución")
    return {"status": "iniciado"}


@app.get("/api/scraper/status", dependencies=[Depends(verify_api_key)], tags=["scraper"])
async def scraper_status():
    return read_status()


@app.post("/api/scraper/stop", dependencies=[Depends(verify_api_key)], tags=["scraper"])
async def scraper_stop():
    stopped = await stop_scraper()
    if not stopped:
        raise HTTPException(status_code=409, detail="El scraper no está en ejecución")
    return {"status": "detenido"}


# ── Listings ──────────────────────────────────────────────────────────────────

@app.get("/api/listings", dependencies=[Depends(verify_api_key)], tags=["datos"])
async def get_listings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    province: str | None = Query(None),
    min_surface: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    sort_by: str = Query("scraped_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows, total = get_listings_paginated(
        conn,
        page=page,
        page_size=page_size,
        province=province,
        min_surface=min_surface,
        max_price=max_price,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return {
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 1,
    }


@app.get("/api/listings/provinces", dependencies=[Depends(verify_api_key)], tags=["datos"])
async def get_provinces(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT DISTINCT province FROM listings WHERE province IS NOT NULL AND province != '' ORDER BY province"
    ).fetchall()
    return {"provinces": [r[0] for r in rows]}


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/api/logs", dependencies=[Depends(verify_api_key)], tags=["sistema"])
async def get_logs(lines: int = Query(200, ge=10, le=1000)):
    if not LOG_FILE.exists():
        return {"lines": [], "file": str(LOG_FILE)}
    dq: collections.deque[str] = collections.deque(maxlen=lines)
    with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            dq.append(line.rstrip())
    return {"lines": list(dq), "file": str(LOG_FILE)}


@app.get("/api/logs/errors", dependencies=[Depends(verify_api_key)], tags=["sistema"])
async def get_error_logs(lines: int = Query(200, ge=10, le=1000)):
    if not ERROR_LOG_FILE.exists():
        return {"lines": [], "file": str(ERROR_LOG_FILE)}
    dq: collections.deque[str] = collections.deque(maxlen=lines)
    with ERROR_LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            dq.append(line.rstrip())
    return {"lines": list(dq), "file": str(ERROR_LOG_FILE)}


# ── Cron ──────────────────────────────────────────────────────────────────────

@app.get("/api/cron", dependencies=[Depends(verify_api_key)], tags=["scheduler"])
async def get_cron():
    cfg = get_config()
    # Calcular próxima ejecución
    next_run = None
    if cfg.get("cron_expr"):
        try:
            cron = croniter(cfg["cron_expr"])
            next_run = cron.get_next(float)
            from datetime import timezone as tz
            next_run = datetime.fromtimestamp(next_run, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return {**cfg, "next_run": next_run}


@app.put("/api/cron", dependencies=[Depends(verify_api_key)], tags=["scheduler"])
async def update_cron(body: CronConfigRequest):
    # Validar expresión cron
    if body.cron_expr:
        try:
            croniter(body.cron_expr)
        except (CroniterBadCronError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"Expresión cron inválida: {e}")

    save_config({"cron_expr": body.cron_expr, "max_pages": body.max_pages})

    # Reagendar en caliente
    from apscheduler.triggers.cron import CronTrigger
    from scheduler import get_scheduler
    scheduler = get_scheduler()
    if body.cron_expr:
        scheduler.reschedule_job(
            "scraper_cron",
            trigger=CronTrigger.from_crontab(body.cron_expr, timezone="Europe/Madrid"),
        )
        logger.info("[Cron] Reagendado: %s", body.cron_expr)
    else:
        # Expresión vacía = desactivar
        scheduler.pause_job("scraper_cron")
        logger.info("[Cron] Job pausado (sin expresión)")

    return {"status": "actualizado", "cron_expr": body.cron_expr, "max_pages": body.max_pages}


# ── Sesión Milanuncios ────────────────────────────────────────────────────────

@app.post("/api/session/renew", dependencies=[Depends(verify_api_key)], tags=["sesion"])
async def session_renew():
    status = read_status()
    if status.get("state") == "running":
        raise HTTPException(status_code=409, detail="Debes detener el scraper antes de renovar la sesión")

    launched = await launch_session_renewal()
    if not launched:
        raise HTTPException(status_code=409, detail="La renovación de sesión ya está en curso")
    return {"status": "iniciado", "message": "save_session.py abierto — interactúa con Chrome para completar el login"}


@app.post("/api/session/stop", dependencies=[Depends(verify_api_key)], tags=["sesion"])
async def session_stop():
    stopped = await stop_session_renewal()
    if not stopped:
        raise HTTPException(status_code=409, detail="No hay renovación de sesión en curso")
    return {"status": "cancelado"}


@app.get("/api/session/status", dependencies=[Depends(verify_api_key)], tags=["sesion"])
async def session_status():
    return read_session_status()


# ── VNC (panel Chrome remoto) ────────────────────────────────────────────────

@app.get("/api/vnc/status", dependencies=[Depends(verify_api_key)], tags=["vnc"])
async def vnc_status():
    """Indica si el panel VNC esta disponible y en que puerto WebSocket."""
    available = os.environ.get("VNC_AVAILABLE", "false") == "true"
    return {"available": available, "ws_port": 6080 if available else None}


# ── Webflow ───────────────────────────────────────────────────────────────────

@app.post("/api/webflow/sync", dependencies=[Depends(verify_api_key)], tags=["webflow"])
async def webflow_sync():
    from api.task_registry import fire_and_track
    from integrations.webflow_sync import sync_pending_listings
    fire_and_track(sync_pending_listings(), name="webflow-manual-sync")
    return {"status": "sync_iniciado"}


@app.get("/api/webflow/status", dependencies=[Depends(verify_api_key)], tags=["webflow"])
async def webflow_status(conn: sqlite3.Connection = Depends(get_db)):
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    synced = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE webflow_item_id IS NOT NULL"
    ).fetchone()[0]
    last_sync = conn.execute(
        "SELECT MAX(webflow_synced_at) FROM listings WHERE webflow_synced_at IS NOT NULL"
    ).fetchone()[0]
    return {
        "total": total,
        "synced": synced,
        "pending": total - synced,
        "last_sync_at": last_sync,
    }
