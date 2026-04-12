# CLAUDE.md

**Repository:** `https://github.com/Flap-Consulting-Nabes/naves-scraper`

Guidance for Claude Code when working in this repository.

## Project Overview

Automated scraper for industrial warehouse listings (naves industriales) from MilAnuncios.com. Microservices architecture: CLI scraper + FastAPI REST API + Next.js dashboard + APScheduler cron + Webflow CMS integration.

**Target site:** milanuncios.com — protected by Kasada (hard bot block) and F5/Incapsula reese84 (interactive captcha).

---

## Quick Start

```bash
source venv/bin/activate
pip install -r requirements.txt

python save_session.py                     # First time: manual login
python scraper_engine.py --pages 2 --dry-run  # Test run
bash run_api.sh                            # FastAPI on :8000
bash run_frontend.sh                       # Next.js on :3000
```

Dashboard: http://localhost:3000 (login with `DASHBOARD_PASSWORD` from `.env`)

---

## Architecture

### Data Flow
```
save_session.py → session.json → scraper_engine.py
  → integrations/milanuncios.py (zendriver headful Chrome)
  → integrations/parser.py (window.__INITIAL_PROPS__ JSON)
  → db.py (SQLite WAL, INSERT OR IGNORE)
  → integrations/webflow_sync.py → Webflow CMS API
```

### Service Communication
```
frontend/ (Next.js :3000)
  ↓ HTTP + x-api-key            ↓ WebSocket (react-vnc)
api/main.py (FastAPI :8000)     websockify :6080 → x11vnc :5900
  ↓ subprocess + scraper_status.json              ↓
scraper_engine.py               Xvfb :99
  ↓ async                            ↓
integrations/milanuncios.py → Chrome (headful on :99)
```

VPS: Chrome on Xvfb :99 → x11vnc → websockify → react-vnc in dashboard.
Mac: Chrome on real display, VNC services not started, panel hidden.

---

## Key Components

| Component | File | Role |
|-----------|------|------|
| Core scraper | `integrations/milanuncios.py` | zendriver (not playwright/selenium), headful, persistent `chrome_profile/`, warm-up sequence, browser rotation every 10 requests |
| Subprocess mgr | `api/scraper_job.py` | Launches scraper subprocess, parses stdout markers → `scraper_status.json` |
| API | `api/main.py` | REST endpoints (scraper, listings, logs, cron, session, webflow, VNC status). All require `x-api-key` |
| Dashboard | `frontend/` | Next.js 15 + React 19 + shadcn/ui + SWR. 6 pages: Resumen, Control, Programacion, Registros, Anuncios, Webflow |
| Manual login | `save_session.py` | Opens Chrome → user logs in → extracts cookies via CDP → `session.json` |
| Orchestration | `scraper_engine.py` | Pagination, dedup, checkpoint resume, ban recovery (exponential backoff) |
| Parser | `integrations/parser.py` | Extracts 30+ fields from `__INITIAL_PROPS__` JSON; fallback: CSS + regex |
| Database | `db.py` | SQLite WAL, 30+ columns, INSERT OR IGNORE, auto-migration via `_NEW_COLUMNS` |
| Scheduler | `scheduler.py` | APScheduler → `scheduler.db`, default `0 6 * * *` Europe/Madrid |

### Print Marker Protocol (stdout → `api/scraper_job.py`)

Scraper: `[CAPTCHA_REQUIRED]`, `[CAPTCHA_WAITING]`, `[CAPTCHA_SOLVED]`, `[CAPTCHA_TIMEOUT]`
Session: `[LOGIN_WAITING]`, `[SESSION_SAVED]`, `[SESSION_TIMEOUT]`

### Custom Exceptions (`integrations/milanuncios.py`)

| Exception | Trigger | Recovery |
|-----------|---------|----------|
| `ScrapeBanException` | Cloudflare, Kasada header | Exponential backoff + browser reopen |
| `SessionExpiredException` | Redirect to `/login` | Exit; user runs `save_session.py` |
| `ListingNotFoundException` | 404 | Skip listing, continue |
| `CaptchaRequiredException` | F5/Incapsula, GeeTest | Pause up to 10 min, keep Chrome open for user |

---

## Scraper CLI

```bash
python scraper_engine.py                        # Incremental from checkpoint
python scraper_engine.py --pages 5              # Limit pages
python scraper_engine.py --batch 50             # Stop after 50 new
python scraper_engine.py --pages 1 --dry-run    # Test mode (no DB writes)
python scraper_engine.py --reset                # Ignore checkpoint
```

---

## Critical Rules

- **Never delete `chrome_profile/`** — accumulated anti-bot trust
- **Workers must be 1** — `uvicorn --workers 1` (singleton Chrome)
- **DISPLAY=:99** on Linux (Xvfb); real display on Mac
- **No emojis** — use SVG icons or plain text
- **English only** — all code, comments, commit messages, docs in English

---

## Documentation Map

| Doc | Content |
|-----|---------|
| `docs/frontend.md` | Full Next.js dashboard architecture and components |
| `docs/vnc-chrome-viewer.md` | VNC Chrome remote panel setup and architecture |
| `docs/init_milanuncios.md` | Setup notes and lessons from previous projects |
| `docs/plans/slug-system.md` | Title-based unique slug contract (page slug + image filenames) |
| `docs/plans/image-compression.md` | WebP compression (q=80, max 1200px) + Webflow asset re-upload fix |

---

## Common Tasks

**New parsed field:** `parser.py` → `db.py` (SCHEMA + `_NEW_COLUMNS`) → optionally `api/main.py` → `anuncios/page.tsx`

**New API endpoint:** Pydantic model → route with `Depends(verify_api_key)` → update `ScraperStatus` TypedDict if needed → `frontend/src/lib/api.ts`

**New frontend page:** `frontend/src/app/(app)/<page>/page.tsx` → sidebar link in `sidebar.tsx` → `useSWR` + types in `types.ts`

**Change ban detection:** Edit `_check_for_ban()` in `milanuncios.py`. Hard bans → `ScrapeBanException`. Captchas → `CaptchaRequiredException`.

**Slug generation:** Title-based unique slugs live in `utils/slugify.py` (`slugify_title` + `generate_unique_slug`). New listings compute their slug in `scraper_engine.run()` before `insert_listing()`; the same value feeds Webflow page slugs and local image filenames. One-shot back-fill: `python scripts/migrate_slugs.py --dry-run`. See `docs/plans/slug-system.md`.

**Image compression:** `utils/image_compressor.compress_to_webp()` (q=80, max 1200px, Pillow, LANCZOS) is called from `utils/image_downloader.py` on every scraped photo — filenames are always `{slug}-image-{i}.webp`. Back-fill existing files + re-upload to Webflow Assets CDN: `python scripts/migrate_images.py --dry-run`. Phase G requires `WEBFLOW_TOKEN` with `assets:read` / `assets:write` (auth probe aborts with exit code 2 otherwise). See `docs/plans/image-compression.md`.

**Webflow locale:** All CMS items are created with the Spanish `cmsLocaleId` (auto-discovered from `GET /sites/{siteId}`). `webflow_client.resolve_spanish_locale_id()` finds the locale by `tag` starting with `es`. Back-fill existing items: `python scripts/backfill_locale.py --dry-run`.

---

## Global Invariants

See `~/.claude/CLAUDE.md` for full rules:

0. **English only** — all outputs regardless of input language
1. **Document first** — spec with `[DRAFT]` before code, mark `[IMPLEMENTED]` after
2. **Max 300 lines/file** — split at 250; single responsibility; DRY
3. **WebSearch before coding** — fetch latest docs for any external library/API
4. **Ask before architecture** — never assume patterns, libraries, schemas. Ask Alejandro first
