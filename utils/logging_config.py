"""
Centralized logging configuration for the scraper project.

Provides a single setup_logging() entry point used by both the CLI scraper
and the FastAPI API process, ensuring errors are always persisted to disk.

Log files:
  logs/errors.log    — ERROR+ only (always enabled)
  logs/scraper.log   — All levels (CLI mode only, when stdout is a TTY or
                        explicitly requested via include_file_log=True)
  logs/api_errors.log — ERROR+ for the API process (api_mode=True)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
ERROR_LOG = LOG_DIR / "errors.log"
SCRAPER_LOG = LOG_DIR / "scraper.log"
API_ERROR_LOG = LOG_DIR / "api_errors.log"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

_configured = False


def setup_logging(
    *,
    level: int = logging.INFO,
    include_file_log: bool = False,
    api_mode: bool = False,
) -> None:
    """Configure root logger with console + persistent error file handlers.

    Args:
        level: Minimum log level for console and file output.
        include_file_log: If True, also write ALL levels to logs/scraper.log.
            Automatically enabled when stdout is a TTY (CLI execution).
        api_mode: If True, write errors to logs/api_errors.log instead of
            the generic errors.log — keeps API and scraper errors separated.
    """
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # 1. Console handler — always
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 2. Error file handler — always (ERROR+ only)
    error_path = API_ERROR_LOG if api_mode else ERROR_LOG
    error_handler = RotatingFileHandler(
        str(error_path),
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    # 3. Full file handler — CLI only (when running from terminal)
    if include_file_log or sys.stdout.isatty():
        file_handler = RotatingFileHandler(
            str(SCRAPER_LOG),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def reset_logging() -> None:
    """Remove all handlers from the root logger. Used only in tests."""
    global _configured
    _configured = False
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)


# ── Subprocess log helpers (used by api/scraper_job.py) ──────────────────────

# Keywords that indicate an error-level line from scraper subprocess output
ERROR_KEYWORDS = (
    "[error]", "[critical]", "traceback (most recent call last)",
    "exception:", "error:", "fatal", "unhandled exception",
    "runtimeerror", "stopiteration", "connectionerror",
    "scrapebanexception", "sessionexpiredexception",
)


def is_error_line(line: str) -> bool:
    """Detect whether a subprocess output line represents an error."""
    lower = line.lower()
    return any(kw in lower for kw in ERROR_KEYWORDS)


def get_scraper_log_handler() -> RotatingFileHandler:
    """Rotating handler for logs/scraper.log (all subprocess output)."""
    SCRAPER_LOG.parent.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        str(SCRAPER_LOG), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def get_error_log_handler() -> RotatingFileHandler:
    """Rotating handler for logs/errors.log (error-level subprocess output)."""
    ERROR_LOG.parent.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        str(ERROR_LOG), maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [SCRAPER-ERROR] %(message)s")
    )
    return handler
