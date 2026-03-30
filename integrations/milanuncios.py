"""
Motor de scraping para MilAnuncios usando zendriver (fork activo de nodriver).
zendriver evita llamar a Runtime.enable (vector de detección de Kasada/F5)
y mantiene un perfil Chrome persistente para acumular fingerprint de confianza.
Todo el módulo es async — el entry point es scraper_engine.py via asyncio.run().
"""
import asyncio
import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Optional

import zendriver as uc
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_not_exception_type,
)

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


async def _start_browser() -> uc.Browser:
    # headless=False es obligatorio: F5/Kasada detecta --headless=new y bloquea.
    # user_data_dir persistente: reutiliza el fingerprint del perfil donde se
    # resolvió el challenge en save_session.py, evitando el re-challenge.
    # Viewport aleatorio: evita la firma fija 1920x1080 que es flag de automation.
    if not os.path.isdir(PROFILE_DIR):
        logger.warning(f"Perfil Chrome no encontrado en {PROFILE_DIR}. Ejecuta save_session.py primero.")
    _w, _h = random.choice(_VIEWPORTS)
    browser = await uc.start(
        headless=False,
        user_data_dir=PROFILE_DIR,
        browser_args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            f"--window-size={_w},{_h}",
            "--start-maximized",
        ],
    )
    logger.info(f"Browser iniciado ({_w}x{_h}) con perfil persistente: {PROFILE_DIR}")
    await _warmup(browser)
    return browser


async def _warmup(browser: uc.Browser) -> None:
    """
    Secuencia de warm-up en 3 pasos para que p.js/reese84 genere el token
    de confianza antes de navegar a la URL de búsqueda real.
    Sin este warm-up, el challenge se activa en la primera petición.
    """
    # Paso 1: homepage — deja que los scripts anti-bot corran
    logger.info("Warm-up paso 1/3: homepage...")
    page = await browser.get(BASE_URL)
    try:
        await page.wait_for_ready_state(until="complete")
    except Exception:
        await asyncio.sleep(5)

    # Verificar URL real — page.url devuelve la URL solicitada, no la cargada
    for attempt in range(3):
        try:
            actual_url = await page.evaluate("window.location.href") or ""
            if actual_url and "about:blank" not in actual_url:
                break
        except Exception:
            actual_url = ""
        logger.info("Warm-up: reintentando navegación a %s (intento %d/3)...", BASE_URL, attempt + 1)
        await page.get(BASE_URL)
        try:
            await page.wait_for_ready_state(until="complete")
        except Exception:
            await asyncio.sleep(5)

    await asyncio.sleep(random.uniform(2.0, 4.0))
    title = await page.evaluate("document.title") or ""

    if "pardon" in title.lower():
        logger.warning("Homepage bloqueada en warm-up — perfil caducado. Re-ejecuta save_session.py")
        return

    logger.info(f"Warm-up paso 1 OK: {title}")

    # Paso 2: scroll suave para simular lectura humana
    try:
        await page.scroll_down(random.randint(200, 500))
    except Exception:
        pass
    await asyncio.sleep(random.uniform(1.5, 3.0))

    # Paso 3: navegar a la categoría objetivo para activar el token de esa sección
    logger.info("Warm-up paso 2/3: categoría naves-industriales...")
    await page.get("https://www.milanuncios.com/naves-industriales/")
    await asyncio.sleep(random.uniform(3.0, 5.0))
    html = await page.get_content()

    if "pardon" in html.lower() or "geetest" in html.lower():
        logger.warning("Categoría bloqueada en warm-up — re-ejecuta save_session.py y resuelve el captcha manualmente.")
    else:
        logger.info("Warm-up paso 2/3 OK.")

    try:
        await page.scroll_down(random.randint(100, 300))
    except Exception:
        pass
    await asyncio.sleep(random.uniform(1.0, 2.0))
    logger.info("Warm-up completo.")


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
# Espera interactiva de captcha
# ---------------------------------------------------------------------------

_CAPTCHA_MARKERS = ("geetest", "pardon our interruption", "just a moment", "checking your browser")

async def _wait_for_captcha_solve(page, url: str, timeout: int = 600) -> None:
    """Mantiene Chrome abierto y espera hasta que el usuario resuelva el captcha.

    Imprime marcadores que `scraper_job.py` detecta para actualizar el dashboard.
    Timeout: 10 minutos → raise ScrapeBanException.
    """
    print("[CAPTCHA_REQUIRED] Captcha detectado — resuelve el captcha en la ventana de Chrome para continuar", flush=True)
    logger.warning(f"[CAPTCHA] Captcha interactivo en {url} — esperando resolución manual (max {timeout}s)")
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(5)
        remaining = int(deadline - loop.time())
        try:
            title = await page.evaluate("document.title") or ""
            html = await page.get_content()
            if not any(kw in html.lower() for kw in _CAPTCHA_MARKERS):
                print("[CAPTCHA_SOLVED] Captcha resuelto — continuando scraping", flush=True)
                logger.info("[CAPTCHA] Captcha resuelto por el usuario — continuando.")
                return
        except Exception:
            pass
        print(f"[CAPTCHA_WAITING] Esperando resolución del captcha ({remaining}s restantes)...", flush=True)
    print("[CAPTCHA_TIMEOUT] Tiempo agotado esperando el captcha — se requiere renovar sesión", flush=True)
    logger.error("[CAPTCHA] Tiempo agotado (%ds) sin resolver captcha en %s", timeout, url)
    raise ScrapeBanException(f"Captcha no resuelto en {timeout}s en {url} — re-ejecuta save_session.py")


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
        await _wait_for_captcha_solve(page, url)
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
        await _wait_for_captcha_solve(page, url)
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
