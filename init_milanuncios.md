# Init: MilAnuncios Scraper — Guía de Arranque

Documento de referencia basado en lecciones aprendidas del proyecto **Spiritoni WhiskyBase Scraper**.
Usar como punto de partida para construir un scraper robusto para milanuncios.com.

---

## 1. Stack recomendado

| Propósito | Librería | Razón |
|-----------|----------|-------|
| Browser automation | `playwright` (sync) | Control total del DOM, headers, cookies |
| Anti-bot stealth | `playwright-stealth` | Oculta webdriver traces (navigator.webdriver, etc.) |
| Bypass Cloudflare (si aparece) | `nodriver` | Comunicación directa vía CDP, sin webdriver traces |
| Parsing HTML | `beautifulsoup4` | Robusto para estructuras HTML complejas |
| Retry logic | `tenacity` | Backoff exponencial configurable |
| Variables de entorno | `python-dotenv` | Nunca hardcodear credenciales |
| HTTP requests (Strapi/APIs) | `requests` | Para llamadas REST simples |

```
playwright
playwright-stealth
beautifulsoup4
tenacity
python-dotenv
requests
nodriver
```

---

## 2. Lecciones críticas aprendidas

### 2.1 Cloudflare es el enemigo principal
- **Playwright headless** → detectado inmediatamente (403 o loop de captcha infinito).
- **Playwright headful (visible)** → también detectado en muchos casos.
- **`playwright-stealth`** → ayuda pero no garantiza bypass en sitios con Cloudflare fuerte.
- **`nodriver`** → comunica con Chrome real vía DevTools Protocol (CDP). No inyecta webdriver. Bypasea Cloudflare. **Usar para login/sesión inicial.**
- **Estrategia ganadora**: usar `nodriver` para hacer login una sola vez, guardar cookies, luego usar `playwright` con esas cookies para el scraping masivo.

### 2.2 Sesión con cookies (no login automatizado)
Nunca intentar automatizar el formulario de login en sitios con Cloudflare.
El flujo correcto es:
1. Script manual (`save_session.py`) con `nodriver` — el usuario hace login a mano.
2. Cookies guardadas en `session.json` (formato Playwright-compatible).
3. El scraper carga las cookies al inicio con `context.add_cookies(cookies)`.
4. La sesión dura hasta que las cookies expiren (normalmente 7-30 días).

### 2.3 Serialización de cookies con nodriver
`nodriver` devuelve objetos `CookieSameSite` (enum), no strings.
Al guardar a JSON siempre usar:
```python
"sameSite": str(c.same_site.value) if c.same_site else "Lax"
```
Sin esto, `json.dump` lanza `TypeError: Object of type CookieSameSite is not JSON serializable`.

### 2.4 Cookies HttpOnly no visibles en extensiones
Las cookies de sesión de la mayoría de sitios usan `HttpOnly` — no aparecen en:
- DevTools → Application → Cookies
- Cookie-Editor extension
- JavaScript (`document.cookie`)

Solo se pueden extraer vía CDP (lo que hace `nodriver`):
```python
cookies = await page.send(uc.cdp.network.get_cookies())
```

### 2.5 Shared browser context (singleton)
Para scraping masivo, NO abrir un browser nuevo por cada URL.
Un solo contexto Playwright compartido ahorra ~2-3 segundos por petición y mantiene las cookies activas.
```python
_playwright = None
_browser = None
_context = None

def _get_context():
    global _playwright, _browser, _context
    if _context is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        _context = _browser.new_context(...)
        _context.add_cookies(load_cookies())
    return _context
```
Siempre llamar `browser.close()` y `playwright.stop()` al terminar.

### 2.6 Detección de ban / sesión expirada
Revisar después de cada `page.goto()`:
```python
# Ban por IP o rate limit
if response.status in [403, 429]:
    raise ScrapeBanException(...)

# Cloudflare challenge
if "Just a moment..." in html or "cf-browser-verification" in html:
    raise ScrapeBanException(...)

# Sesión expirada (redirect a login)
if "/login" in page.url or "/account/login" in page.url:
    print("⚠️ Sesión expirada. Renovar cookies con save_session.py")
```

### 2.7 Paginación en APIs REST (Strapi, cualquier backend)
**NUNCA** asumir que una API devuelve todos los resultados en una petición.
Siempre paginar:
```python
start = 0
page_size = 100
while True:
    url = f"{BASE_URL}/items?pagination[limit]={page_size}&pagination[start]={start}"
    data = requests.get(url).json()
    page = data.get("data", [])
    if not page:
        break
    all_items.extend(page)
    total = data.get("meta", {}).get("pagination", {}).get("total")
    if total and len(all_items) >= total:
        break
    start += page_size
```

### 2.8 Checkpoint / resumption
Para batches de miles de registros, guardar el último ID procesado:
```python
# checkpoint.json: {"last_id": 1234, "timestamp": "..."}
def save_checkpoint(item_id):
    with open("checkpoint.json", "w") as f:
        json.dump({"last_id": item_id, "timestamp": datetime.now().isoformat()}, f)

def load_checkpoint():
    if os.path.exists("checkpoint.json"):
        return json.load(open("checkpoint.json")).get("last_id")
    return None
```
Al iniciar: filtrar items con `id > last_checkpoint_id`.

### 2.9 Flush inmediato vs acumulación en memoria
**MAL**: acumular todos los resultados en una lista y guardar al final.
Si el proceso muere a mitad, se pierden todos los datos.

**BIEN**: guardar/publicar resultado por ítem inmediatamente después de procesarlo.
Combinar con checkpoint para garantizar exactamente-una-vez.

### 2.10 Jitter humanizado
Entre cada request, esperar un tiempo aleatorio:
```python
import random, time

def random_delay(min_sec=2.5, max_sec=6.5):
    time.sleep(random.uniform(min_sec, max_sec))
```
Sin esto, el patrón de requests es demasiado regular y activa rate limiting.

---

## 3. Arquitectura para el scraper de MilAnuncios

### Estructura de carpetas
```
milanuncios-scraper/
├── .env                        # Credenciales (nunca en git)
├── .gitignore                  # Incluir .env, session.json, *.pyc, venv/
├── requirements.txt
├── save_session.py             # Login manual con nodriver → guarda session.json
├── scraper_engine.py           # Orquestador principal
├── checkpoint_manager.py       # Lectura/escritura de estado
├── integrations/
│   ├── milanuncios.py          # Lógica de scraping de milanuncios.com
│   └── backend.py              # Lógica de guardado (DB, API, CSV...)
└── utils/
    └── jitter.py               # random_delay()
```

### Flujo de ejecución
```
1. save_session.py  →  session.json
         ↓
2. scraper_engine.py --batch 50
   ├── Cargar checkpoint
   ├── Paginar listings de MilAnuncios (search URL)
   ├── Por cada anuncio:
   │   ├── random_delay()
   │   ├── milanuncios.scrape_listing(url)
   │   ├── backend.save(data)         ← flush inmediato
   │   └── checkpoint.save(id)
   └── Si ban → parar batch, proteger IP
```

---

## 4. Consideraciones específicas de MilAnuncios

### 4.1 Estructura de URLs
- **Listado**: `https://www.milanuncios.com/anuncios/?s=QUERY&orden=relevance&fromSearch=1`
- **Anuncio individual**: cada card tiene su propia URL, normalmente `/CATEGORIA/TITULO-ID.htm`
- Paginar listado con parámetro `pagina=2`, `pagina=3`, etc.

### 4.2 Datos a extraer por anuncio
Típicamente disponibles en el HTML de la página de detalle:
- Título
- Precio (puede ser "a consultar")
- Descripción
- Localización (provincia, ciudad)
- Superficie (m²) — extraer con regex: `r'(\d[\d\.]+)\s*m[²2]'`
- Fecha de publicación
- ID del anuncio (en la URL o en el HTML)
- Fotos (URLs de imágenes)
- Teléfono (solo visible tras click — requiere interacción de página)
- Nombre/tipo de vendedor (particular vs profesional)

### 4.3 Bot protection en MilAnuncios
MilAnuncios usa protección anti-bot moderada (no tan agresiva como Cloudflare Enterprise).
- Intentar primero con `playwright` + `playwright-stealth` headless.
- Si hay captcha o redirect, cambiar a sesión con cookies (mismo flujo que WhiskyBase).
- User-agent realista es obligatorio.
- Respetar `robots.txt` en cuanto a delay — usar mínimo 3-5 seg entre requests.

### 4.4 Posible limitación de teléfonos
El teléfono en MilAnuncios suele estar oculto tras un botón "Ver teléfono" que requiere:
- Estar logueado, O
- Hacer click (que dispara un request AJAX)

Para extraerlo en scraping: capturar la respuesta de red al hacer click con Playwright.

---

## 5. Plantilla de `save_session.py`

```python
"""
Abre MilAnuncios con nodriver (bypasa bot detection).
El usuario hace login manualmente, luego presiona Enter.
Las cookies se guardan en session.json para el scraper.
"""
import asyncio, json, os
import nodriver as uc

SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")

async def main():
    print("Abriendo MilAnuncios... Haz login y luego presiona Enter aquí.")
    browser = await uc.start()
    page = await browser.get("https://www.milanuncios.com/acceso/")

    input(">>> Presiona Enter cuando hayas iniciado sesión...")

    cookies = await page.send(uc.cdp.network.get_cookies())
    ma_cookies = [
        {
            "name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "expires": c.expires,
            "httpOnly": c.http_only, "secure": c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies if "milanuncios" in (c.domain or "")
    ]
    save = ma_cookies if ma_cookies else [
        {
            "name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "expires": c.expires,
            "httpOnly": c.http_only, "secure": c.secure,
            "sameSite": str(c.same_site.value) if c.same_site else "Lax",
        }
        for c in cookies
    ]
    with open(SESSION_FILE, "w") as f:
        json.dump(save, f, indent=2)
    print(f"Sesión guardada: {SESSION_FILE} ({len(save)} cookies)")
    browser.stop()

if __name__ == "__main__":
    uc.loop().run_until_complete(main())
```

---

## 6. Plantilla de `integrations/milanuncios.py`

```python
from playwright.sync_api import sync_playwright, BrowserContext
from playwright_stealth import stealth_sync
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
import re, os, json, time, random

SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "session.json")

class ScrapeBanException(Exception):
    pass

_playwright = None
_browser = None
_context: BrowserContext | None = None

def _get_context() -> BrowserContext:
    global _playwright, _browser, _context
    if _context is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        _context = _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="Europe/Madrid",
        )
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                _context.add_cookies(json.load(f))
            print("[MilAnuncios] Sesión cargada desde session.json")
    return _context

def close_session():
    global _playwright, _browser, _context
    if _browser:
        _browser.close()
    if _playwright:
        _playwright.stop()
    _browser = _context = _playwright = None

@retry(wait=wait_exponential(multiplier=1, min=5, max=30),
       stop=stop_after_attempt(4),
       retry=retry_if_exception_type(ScrapeBanException))
def scrape_listing(url: str) -> dict:
    """Scrape datos de un anuncio individual de MilAnuncios."""
    data = {
        "url": url, "titulo": None, "precio": None,
        "descripcion": None, "superficie_m2": None,
        "localizacion": None, "fecha": None, "id_anuncio": None,
    }
    ctx = _get_context()
    page = ctx.new_page()
    stealth_sync(page)
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if resp and resp.status in [403, 429]:
            raise ScrapeBanException(f"Bloqueado: HTTP {resp.status}")
        html = page.content()
        if "Just a moment" in html or "cf-browser-verification" in html:
            raise ScrapeBanException("Cloudflare captcha")
        if "/acceso/" in page.url:
            print("⚠️  Sesión expirada. Ejecuta: python save_session.py")

        soup = BeautifulSoup(html, "html.parser")
        # TODO: adaptar selectores a la estructura real de MilAnuncios
        # (inspeccionar HTML antes de codificar selectores)
        h1 = soup.find("h1")
        if h1:
            data["titulo"] = h1.get_text(strip=True)
        # Extraer superficie con regex
        text = soup.get_text()
        m = re.search(r'(\d[\d\.]*)\s*m[²2]', text)
        if m:
            data["superficie_m2"] = float(m.group(1).replace('.', ''))
    finally:
        page.close()
    return data

def scrape_search_page(query: str, pagina: int = 1) -> list[str]:
    """Devuelve lista de URLs de anuncios en una página de resultados."""
    url = f"https://www.milanuncios.com/anuncios/?s={query}&orden=relevance&fromSearch=1&pagina={pagina}"
    ctx = _get_context()
    page = ctx.new_page()
    stealth_sync(page)
    urls = []
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if resp and resp.status in [403, 429]:
            raise ScrapeBanException(f"Bloqueado: HTTP {resp.status}")
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        # TODO: adaptar selector al HTML real de las cards de listado
        for a in soup.select("a[href*='/anuncios/']"):
            href = a.get("href", "")
            if href and href not in urls:
                full = f"https://www.milanuncios.com{href}" if href.startswith("/") else href
                urls.append(full)
    finally:
        page.close()
    return urls
```

---

## 7. Variables de entorno (`.env`)

```
# Backend donde guardar los datos
BACKEND_URL=http://localhost:3000/api
BACKEND_API_KEY=tu_token_aqui

# Proxy opcional (formato: http://user:pass@ip:port)
# PROXY_URL=

# MilAnuncios (solo si requiere cuenta)
# MA_USERNAME=
# MA_PASSWORD=
```

---

## 8. Checklist antes de ejecutar en producción

- [ ] `python save_session.py` ejecutado y `session.json` existe
- [ ] `.env` configurado con el backend destino
- [ ] Testeado con batch pequeño (`--batch 5`) sin errores
- [ ] `checkpoint.json` vacío o inexistente para un run limpio
- [ ] Jitter configurado a mínimo 3 segundos entre requests
- [ ] `.gitignore` incluye: `.env`, `session.json`, `checkpoint.json`, `venv/`, `__pycache__/`

---

## 9. Comandos de ejecución

```bash
# Instalar entorno
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Guardar sesión (una vez, o cuando expiren las cookies)
python save_session.py

# Test con batch pequeño
python scraper_engine.py --batch 5

# Producción
python scraper_engine.py --batch 100

# Reanudar tras interrupción (el checkpoint lo hace automático)
python scraper_engine.py --batch 100
```
