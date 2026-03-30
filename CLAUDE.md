# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated scraper for industrial warehouse listings (naves industriales) from MilAnuncios.com. Microservices architecture: CLI scraper + FastAPI REST API + Streamlit dashboard + APScheduler, with Webflow CMS integration.

## Running the Project

### Setup
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Session Management (run when cookies expire, ~30 min lifetime)
```bash
python save_session.py
# Opens Chrome, wait for manual login, saves cookies to session.json
```

### Scraper CLI
```bash
python scraper_engine.py                  # Incremental, resume from checkpoint
python scraper_engine.py --pages 5        # Limit to N pages
python scraper_engine.py --batch 50       # Stop after N new listings
python scraper_engine.py --pages 1 --dry-run  # No DB writes
python scraper_engine.py --reset          # Reset checkpoint, scrape from page 1
```

### Services
```bash
bash run_api.sh        # FastAPI on port 8000 (sets DISPLAY for headful Chrome)
bash run_dashboard.sh  # Streamlit on port 8501
```

Or directly:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
```

## Architecture

### Data Flow
```
save_session.py → session.json → scraper_engine.py
    → integrations/milanuncios.py (zendriver Chrome)
    → integrations/parser.py (extract from window.__INITIAL_PROPS__ JSON)
    → db.py (SQLite: naves.db)
    → integrations/webflow_sync.py → Webflow CMS
```

The API (`api/main.py`) wraps the scraper as a subprocess via `api/scraper_job.py`, enabling the dashboard and external triggers to control scraping.

### Key Components

**`integrations/milanuncios.py`** — Core scraping engine
- Uses **zendriver** (not playwright/selenium) — required for Kasada bypass (avoids `Runtime.enable()` detection)
- Must run **headful** (`headless=False`) — headless is detected and blocked
- Persistent Chrome profile in `chrome_profile/` accumulates fingerprint trust
- Warm-up sequence on startup: homepage → scroll → category page (allows reese84 anti-bot scripts to generate trust token)
- Keep-alive background task refreshes anti-bot token every 10 min
- Custom exceptions: `ScrapeBanException`, `SessionExpiredException`, `ListingNotFoundException`

**`integrations/parser.py`** — Data extraction
- Primary source: embedded `window.__INITIAL_PROPS__` JSON (complete data)
- Fallback: CSS selectors + regex patterns

**`db.py`** — SQLite with 30+ columns, WAL mode, `INSERT OR IGNORE` for deduplication
- `init_db()` auto-migrates old databases by adding missing columns from `_NEW_COLUMNS`
- `listing_exists()` for pre-request deduplication
- Indices on: `listing_id`, `scraped_at`, `surface_m2`, `province`, `price_numeric`, `webflow_item_id`

**`checkpoint_manager.py`** — Saves `last_page` + `last_listing_id` to `checkpoint.json` after each new listing

**`scheduler.py`** — APScheduler with persistent SQLAlchemy job store (`scheduler.db`), default cron `0 6 * * *` Europe/Madrid, configurable via `PUT /api/cron`

**`api/main.py`** — Key endpoints:
- `POST /api/scraper/run` — launch scraper subprocess
- `GET /api/scraper/status` — read `scraper_status.json`
- `POST /api/scraper/stop` — send SIGTERM
- `POST /api/session/renew` — launch `save_session.py` in background
- `POST /api/webflow/sync` — sync pending listings

Authentication: `x-api-key` header (value from `API_SECRET_KEY` env var)

### Anti-Detection Strategy

1. zendriver avoids `Runtime.enable()` detection vector used by Kasada
2. Persistent Chrome profile — fingerprint continuity across sessions
3. Headful mode — headless detected by Kasada
4. Session cookies — reuse authenticated context
5. Warm-up sequence — let anti-bot scripts initialize before scraping
6. Keep-alive task — refresh anti-bot token every 10 min
7. Jitter (`utils/jitter.py`) — 3–12 sec delays between requests
8. Viewport randomization — avoid fixed 1920×1080 signature

### Ban Recovery

- Exponential backoff: 10 → 20 → 40 → 60 min (max 6 retries)
- Close and reopen browser on ban
- `ScrapeBanException` triggers cooldown; `SessionExpiredException` exits immediately

## Environment Variables (`.env`)

```
DB_PATH=naves.db
MAX_PAGES=0               # 0 = unlimited
MIN_SURFACE_M2=1000
DOWNLOAD_IMAGES=true
IMAGES_DIR=images
WEBFLOW_TOKEN=...
WEBFLOW_COLLECTION_ID=...
API_SECRET_KEY=...
DASHBOARD_PASSWORD=...
API_BASE_URL=http://localhost:8000
```

## Runtime Files

| File | Purpose |
|------|---------|
| `session.json` | Login cookies (regenerate with `save_session.py`) |
| `checkpoint.json` | Current scraping page/position |
| `scraper_status.json` | Live scraper state (read by API) |
| `session_status.json` | Session renewal progress |
| `naves.db` | Main SQLite database |
| `scheduler.db` | APScheduler job store |
| `chrome_profile/` | Persistent Chrome fingerprint — do not delete |
| `scraper.log` | Rotating main log |
| `logs/*.csv` | Per-run listing results |

## Important Notes

- **Never delete `chrome_profile/`** — it contains accumulated anti-bot trust
- **`DISPLAY` env var** must be set on Linux for headful Chrome (handled by `run_api.sh`)
- Incremental mode stops pagination on first duplicate (assumes listings sorted by date)
- `docs/init_milanuncios.md` contains detailed setup notes and lessons from previous projects
- `docs/plans/` contains historical planning documents (webflow, captcha, images, notifications, 409 fixes)
