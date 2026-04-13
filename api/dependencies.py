"""
Dependencias compartidas para FastAPI:
  - Conexión a SQLite (una por request)
  - Verificación de API key
  - Lectura/escritura de config.json
"""
import hmac
import json
import os
import sqlite3
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "naves.db")
API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "")
DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "")
CONFIG_FILE = Path("config.json")

_CONFIG_DEFAULTS = {
    "cron_expr": "0 6 * * *",
    "max_pages": 0,
    "dry_run": False,
}


# ── Base de datos ────────────────────────────────────────────────────────────

def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


# ── Autenticación ────────────────────────────────────────────────────────────

def verify_api_key(x_api_key: str = Header(...)) -> None:
    if not API_SECRET_KEY:
        raise HTTPException(status_code=500, detail="API_SECRET_KEY no configurada en .env")
    if not hmac.compare_digest(x_api_key, API_SECRET_KEY):
        raise HTTPException(status_code=403, detail="API key inválida")


# ── Configuración runtime ────────────────────────────────────────────────────

def get_config() -> dict:
    if not CONFIG_FILE.exists():
        return dict(_CONFIG_DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return {**_CONFIG_DEFAULTS, **data}
    except (json.JSONDecodeError, OSError):
        return dict(_CONFIG_DEFAULTS)


def save_config(data: dict) -> None:
    merged = {**get_config(), **data}
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_FILE)
