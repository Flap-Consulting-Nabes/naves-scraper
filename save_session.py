"""
Script de login manual con nodriver para generar session.json.
Usa un perfil Chrome PERSISTENTE (chrome_profile/) para que el scraper
pueda reutilizar el mismo fingerprint y pasar Kasada sin captcha.

Uso:
    python save_session.py

Pasos:
    1. Se abrirá un Chrome real con el perfil guardado en chrome_profile/
    2. Inicia sesión manualmente en MilAnuncios (solo la primera vez)
    3. El sistema detectará el login automáticamente y guardará las cookies
"""
import asyncio
import json
import logging
import os
from pathlib import Path

import zendriver as uc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_URL = "https://www.milanuncios.com"
MIS_ANUNCIOS_URL = "https://www.milanuncios.com/mis-anuncios/"
NAVES_URL = "https://www.milanuncios.com/naves-industriales/?desde=1000&orden=date&pagina=1"
OUTPUT_FILE = "session.json"
PROFILE_DIR = os.path.abspath("chrome_profile")

LOGIN_POLL_INTERVAL = 13   # segundos entre comprobaciones
LOGIN_TIMEOUT = 600         # máximo 10 minutos esperando login


def _fix_chrome_exit_type() -> None:
    """Marca el perfil como salida normal para evitar el diálogo 'restaurar ventanas'."""
    prefs_path = Path(PROFILE_DIR) / "Default" / "Preferences"
    if not prefs_path.exists():
        return
    try:
        data = json.loads(prefs_path.read_text(encoding="utf-8"))
        profile = data.setdefault("profile", {})
        profile["exit_type"] = "Normal"
        profile["exited_cleanly"] = True
        prefs_path.write_text(json.dumps(data), encoding="utf-8")
        logger.info("Preferencias Chrome corregidas (exit_type=Normal).")
    except Exception as e:
        logger.warning(f"No se pudo corregir Preferences: {e}")


async def _is_logged_in(browser) -> bool:
    """
    Comprueba si el usuario está autenticado observando la URL de todas las pestañas abiertas.
    No fuerza navegación para evitar interrumpir al usuario resolviendo captchas.
    """
    try:
        for tab in browser.targets:
            url = getattr(tab, "url", "")
            if "mis-anuncios" in str(url):
                return True
        return False
    except Exception:
        return False


async def main() -> None:
    os.makedirs(PROFILE_DIR, exist_ok=True)
    _fix_chrome_exit_type()
    logger.info(f"Usando perfil Chrome persistente: {PROFILE_DIR}")
    logger.info("Iniciando Chrome para login manual...")

    # Añadir --no-sandbox solo si corre como root (necesario en Docker/root)
    browser_args = [
        "--disable-blink-features=AutomationControlled",
        "--restore-last-session=false",
        "--no-restore-last-session",
    ]
    if os.getuid() == 0:
        browser_args.insert(0, "--no-sandbox")

    browser = await uc.start(
        headless=False,
        user_data_dir=PROFILE_DIR,
        browser_args=browser_args,
    )

    page = await browser.get(TARGET_URL)
    logger.info(f"Página cargada: {TARGET_URL}")
    print("=====================================================================")
    print("INFO: Chrome abierto. INSTRUCCIONES:")
    print(" 1. Si aparece un Captcha, resuélvelo manualmente ahora.")
    print(" 2. Inicia sesión en tu cuenta de Milanuncios si no lo estás.")
    print(" 3. OBLIGATORIO: Ve a la sección 'Mis Anuncios' (o dale click al menú).")
    print(" El script guardará la sesión automáticamente cuando vea esa página.")
    print("=====================================================================")

    # ── Esperar login automáticamente ─────────────────────────────────────────
    loop = asyncio.get_event_loop()
    deadline = loop.time() + LOGIN_TIMEOUT
    logged_in = False

    while loop.time() < deadline:
        if await _is_logged_in(browser):
            logged_in = True
            print("\nINFO: Login detectado correctamente (página de mis anuncios).")
            logger.info("Login en Milanuncios detectado.")
            break
        remaining = int(deadline - loop.time())
        print(f"INFO: Esperando ({remaining}s)... Por favor, inicia sesión y navega a 'Mis Anuncios'.", end="\r")
        await asyncio.sleep(LOGIN_POLL_INTERVAL)

    print() # Salto de línea limpio después del bucle

    if not logged_in:
        print("ERROR: Tiempo de espera agotado (10 min) sin detectar login. Cerrando.")
        logger.error("Tiempo de espera de login agotado.")
        try:
            browser.stop()
        except Exception:
            pass
        return

    # ── Navegar a naves industriales para registrar el fingerprint ─────────────
    logger.info("Navegando a naves-industriales para registrar fingerprint de categoria...")
    print("INFO: Navegando a naves industriales para terminar. Espera 15 segundos...")
    await page.get(NAVES_URL)
    await asyncio.sleep(15)

    # ── Extraer y guardar cookies ──────────────────────────────────────────────
    cookies = await _extract_cookies(page)
    logger.info(f"Extraidas {len(cookies)} cookies.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info(f"Sesion guardada en {OUTPUT_FILE}")
    logger.info(f"Perfil Chrome guardado en {PROFILE_DIR}")
    print(f"INFO: Sesion guardada correctamente ({len(cookies)} cookies). Cerrando Chrome.")

    try:
        await browser.stop()
    except Exception:
        pass


async def _extract_cookies(page) -> list[dict]:
    try:
        result = await page.send(uc.cdp.network.get_all_cookies())
        raw_cookies = result
    except Exception as e:
        logger.warning(f"Error extrayendo cookies via CDP ({e}).")
        raw_cookies = []

    cookies = []
    for c in raw_cookies:
        try:
            same_site = c.same_site
            if hasattr(same_site, "value"):
                same_site = same_site.value
            elif same_site is None:
                same_site = "None"
            else:
                same_site = str(same_site)

            cookies.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires if c.expires else -1,
                "httpOnly": c.http_only,
                "secure": c.secure,
                "sameSite": same_site,
            })
        except Exception as e:
            logger.warning(f"Error procesando cookie {getattr(c, 'name', '?')}: {e}")

    return cookies


if __name__ == "__main__":
    asyncio.run(main())
