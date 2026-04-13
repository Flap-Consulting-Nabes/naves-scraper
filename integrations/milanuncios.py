"""
Motor de scraping para MilAnuncios usando zendriver (fork activo de nodriver).
zendriver evita llamar a Runtime.enable (vector de detección de Kasada/F5)
y mantiene un perfil Chrome persistente para acumular fingerprint de confianza.
Todo el módulo es async — el entry point es scraper_engine.py via asyncio.run().
"""
import asyncio
import glob
import logging
import os
import random
import re
import signal
import subprocess
import time
from typing import Optional

import zendriver as uc
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_not_exception_type,
)

from integrations.browser_lifecycle import warmup, wait_for_captcha_solve

logger = logging.getLogger(__name__)

PROFILE_DIR = os.path.abspath("chrome_profile")

_BROWSER_REFRESH_EVERY = 10   # cerrar/reabrir browser cada N requests de listing

_session: dict = {
    "browser": None,
    "requests_count": 0,
}

_VIEWPORTS = [
    (1920, 1080),
    (1440, 900),
    (1366, 768),
    (1536, 864),
]


# ---------------------------------------------------------------------------
# Excepciones personalizadas
# ---------------------------------------------------------------------------

class ScrapeBanException(Exception):
    """El servidor ha detectado el scraper (captcha, 403, 429)."""

class SessionExpiredException(Exception):
    """La sesión ha caducado y se ha redirigido al login."""

class ListingNotFoundException(Exception):
    """El anuncio ya no existe (404)."""

class CaptchaRequiredException(Exception):
    """Captcha interactivo detectado — el usuario puede resolverlo en Chrome."""


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

BASE_URL = "https://www.milanuncios.com"
SESSION_FILE = "session.json"
SEARCH_URL = "https://www.milanuncios.com/naves-industriales/?desde={min_m2}&orden=date&pagina={page}"


# ---------------------------------------------------------------------------
# Singleton de browser
# ---------------------------------------------------------------------------


async def _close_browser_internal() -> None:
    """Cierra solo el objeto browser (no la tarea keepalive). Usado en rotaciones."""
    if _session["browser"]:
        try:
            await _session["browser"].stop()
        except Exception:
            pass
        _session["browser"] = None
        _session["requests_count"] = 0


async def get_browser() -> uc.Browser:
    """Devuelve el browser compartido, rotándolo cada _BROWSER_REFRESH_EVERY requests."""
    if (
        _session["browser"] is not None
        and _session["requests_count"] > 0
        and _session["requests_count"] % _BROWSER_REFRESH_EVERY == 0
    ):
        logger.info(
            f"[Anti-Ban] Rotando browser después de {_session['requests_count']} requests..."
        )
        await _close_browser_internal()

    if _session["browser"] is None:
        _session["browser"] = await _start_browser()

    return _session["browser"]


def _kill_orphan_chromes() -> None:
    """Kill Chrome processes using OUR profile dir and clean up lock files.

    Only targets Chrome instances launched with chrome_profile/ — never
    kills the user's personal browser.  When the scraper crashes or is
    SIGKILLed, Chrome survives and holds the SingletonLock.  The next
    uc.start() cannot create a new instance, causing "Failed to connect
    to browser".
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"chrome.*{os.path.basename(PROFILE_DIR)}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.strip()]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if pids:
            time.sleep(1)
            # Force-kill survivors
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            logger.info("[Cleanup] Killed orphan Chrome PIDs: %s", pids)
    except Exception as e:
        logger.warning("[Cleanup] Error searching for orphan Chrome: %s", e)

    for lock in glob.glob(os.path.join(PROFILE_DIR, "Singleton*")):
        try:
            os.remove(lock)
        except OSError:
            pass
    logger.info("[Cleanup] Chrome lock files cleaned.")


async def _start_browser() -> uc.Browser:
    # Limpiar procesos Chrome huérfanos y lock files antes de iniciar.
    _kill_orphan_chromes()
    # headless=False es obligatorio: F5/Kasada detecta --headless=new y bloquea.
    # user_data_dir persistente: reutiliza el fingerprint del perfil donde se
    # resolvió el challenge en save_session.py, evitando el re-challenge.
    # Viewport aleatorio: evita la firma fija 1920x1080 que es flag de automation.
    if not os.path.isdir(PROFILE_DIR):
        logger.warning(f"Perfil Chrome no encontrado en {PROFILE_DIR}. Ejecuta save_session.py primero.")
    # En Xvfb Chrome se maximiza para llenar la pantalla virtual (noVNC).
    # En display real se usa viewport aleatorio para evitar fingerprint fijo.
    on_virtual_display = os.environ.get("VIRTUAL_DISPLAY", "false") == "true"
    _w, _h = (1920, 1080) if on_virtual_display else random.choice(_VIEWPORTS)
    browser = await uc.start(
        headless=False,
        user_data_dir=PROFILE_DIR,
        browser_connection_timeout=1.0,
        browser_connection_max_tries=20,
        browser_args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-restore-last-session",
            f"--window-size={_w},{_h}",
            "--window-position=0,0",
            "--start-maximized",
        ],
    )
    logger.info(f"Browser iniciado ({_w}x{_h}) con perfil persistente: {PROFILE_DIR}")
    await warmup(browser)
    return browser


_keepalive_task: Optional[asyncio.Task] = None


async def start_keepalive(interval_seconds: int = 600) -> None:
    """
    Desactivado: La navegación concurrente de la tarea keep-alive choca con la
    extracción activa del scraper porque usan la misma instancia del browser.
    El scraper renueva el token reese84 automáticamente al seguir navegando.
    """
    logger.info("[Keep-alive] Tarea desactivada (el scraper renueva el token activamente).")
    pass


async def close_browser() -> None:
    global _keepalive_task
    if _keepalive_task and not _keepalive_task.done():
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass
        _keepalive_task = None
    await _close_browser_internal()
    logger.info("Browser cerrado.")


# ---------------------------------------------------------------------------
# Detección de bloqueos
# ---------------------------------------------------------------------------

def _check_for_ban(url: str, html: str, title: str) -> None:
    title_lower = title.lower()
    html_lower = html.lower()

    # Cloudflare
    if "just a moment" in title_lower or "checking your browser" in title_lower:
        raise ScrapeBanException(f"Cloudflare challenge en {url}")
    # F5/Incapsula (reese84) — puzzle interactivo, el usuario puede resolverlo
    if "pardon our interruption" in title_lower or "pardon our interruption" in html_lower:
        raise CaptchaRequiredException(f"F5/Incapsula captcha interactivo en {url}")
    # Kasada — bot detection sin UI interactiva, requiere nueva sesión
    if "kasada" in html_lower or "x-kpsdk" in html_lower:
        raise ScrapeBanException(f"Kasada detectado en {url} — re-ejecuta save_session.py")
    # GeeTest captcha — puzzle interactivo, el usuario puede resolverlo
    if "geetest" in html_lower and ("captcha" in html_lower or "captcha-box" in html_lower):
        raise CaptchaRequiredException(f"GeeTest captcha interactivo en {url}")
    # Sesión expirada
    if "/login" in url or "/acceder" in url or "/acceso/" in url:
        raise SessionExpiredException(f"Redirigido a login desde {url}")


# ---------------------------------------------------------------------------
# Scraping de página de resultados
# ---------------------------------------------------------------------------

async def scrape_search_page(page_num: int, min_m2: int = 1000) -> list[str]:
    """Extrae las URLs de anuncios de una página de resultados."""
    url = SEARCH_URL.format(min_m2=min_m2, page=page_num)
    browser = await get_browser()

    logger.info(f"[Search] Cargando página {page_num}: {url}")
    page = await browser.get(url)
    await asyncio.sleep(3)

    title = await page.evaluate("document.title") or ""
    html = await page.get_content()

    try:
        _check_for_ban(url, html, title)
    except CaptchaRequiredException:
        await wait_for_captcha_solve(page, url)
        html = await page.get_content()
        title = await page.evaluate("document.title") or ""
        _check_for_ban(url, html, title)

    urls = _extract_urls_from_html(html)
    await page.get("about:blank")

    logger.info(f"[Search] Página {page_num}: {len(urls)} anuncios.")
    return urls


def _extract_urls_from_html(html: str) -> list[str]:
    # Formato actual: /venta-de-naves-industriales-en-ciudad/ciudad-123456789.htm
    # Formato antiguo: /naves-industriales/titulo-123456789.htm
    pattern = r'href="(/[^"]*naves-industriales[^"]*-\d{6,12}\.htm)"'
    matches = re.findall(pattern, html)
    seen = set()
    urls = []
    for path in matches:
        full_url = BASE_URL + path
        if full_url not in seen:
            seen.add(full_url)
            urls.append(full_url)
    return urls


# ---------------------------------------------------------------------------
# Scraping de anuncio individual
# ---------------------------------------------------------------------------

@retry(
    wait=wait_exponential(multiplier=2, min=10, max=60),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(
        (ScrapeBanException, SessionExpiredException, ListingNotFoundException, CaptchaRequiredException)
    ),
    reraise=True,
)
async def scrape_listing(url: str) -> dict:
    """Extrae todos los campos de un anuncio individual."""
    from integrations.parser import parse_listing_page

    browser = await get_browser()
    _session["requests_count"] += 1

    logger.info(f"[Listing] Scrapeando: {url}")
    page = await browser.get(url)
    await asyncio.sleep(2)

    title = await page.evaluate("document.title") or ""
    html = await page.get_content()

    try:
        _check_for_ban(url, html, title)
    except CaptchaRequiredException:
        await wait_for_captcha_solve(page, url)
        html = await page.get_content()
        title = await page.evaluate("document.title") or ""
        _check_for_ban(url, html, title)

    if "página no encontrada" in title.lower() or "error 404" in html.lower():
        await page.get("about:blank")
        raise ListingNotFoundException(f"404: {url}")

    await _try_reveal_phone(page)
    html = await page.get_content()
    await page.get("about:blank")

    data = parse_listing_page(url, html)
    logger.info(
        f"[Listing] OK: {data.get('listing_id')} | "
        f"{data.get('title', '')[:50]} | "
        f"{data.get('surface_m2')} m² | "
        f"{data.get('price')}"
    )
    return data


async def _try_reveal_phone(page) -> None:
    phone_selectors = [
        "button[class*='phone']",
        "button[class*='Phone']",
        "[data-testid*='phone']",
        "button:has-text('Ver teléfono')",
    ]
    for selector in phone_selectors:
        try:
            btn = await page.find(selector, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(1.5)
                logger.debug("Teléfono revelado.")
                break
        except Exception:
            continue
