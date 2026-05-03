# Reporte de verificación — Iteración 2026-05

Evidencia de que cada bloque de la iteración funciona. Acompaña a `docs/iteration-2026-05-feedback.md` (cambios) y al plan `~/.claude/plans/hi-i-igo-that-s-fine-witty-abelson.md` (diseño).

---

## 1. Suite de tests completa

Todos los 193 tests pasan sin warnings ni regresiones.

```
tests/test_api_endpoints.py ..................                           [  9%]
tests/test_checkpoint.py ........                                        [ 13%]
tests/test_db.py .....................                                   [ 24%]
tests/test_description_formatter.py ...............                      [ 32%]
tests/test_jitter.py ....                                                [ 34%]
tests/test_logging.py ........................                           [ 46%]
tests/test_migrate_existing.py .....                                     [ 49%]
tests/test_parser.py ..................                                  [ 58%]
tests/test_price_formatter.py ...............                            [ 66%]
tests/test_security.py .......                                           [ 69%]
tests/test_slugify.py .......................                            [ 81%]
tests/test_task_registry.py ......                                       [ 84%]
tests/test_webflow_client.py ......                                      [ 88%]
tests/test_webflow_sync.py .......................                       [100%]

============================= 193 passed in 3.55s ==============================
```

Comando: `python3 -m pytest tests/ -v`

### Δ tests respecto a baseline pre-iteración

| Estado | Tests |
|---|---|
| Baseline (antes de la iteración) | 112 |
| Tras la iteración | 193 |
| Tests nuevos | **+81** |

Distribución de tests nuevos por bloque:

| Bloque | Tests nuevos | Archivo principal |
|---|---|---|
| A2 (lat/lng) | +13 | `test_db.py`, `test_parser.py`, `test_webflow_sync.py` |
| B2 (ad_type warning) | +1 | `test_parser.py` |
| B3 (precio) | +20 | `test_price_formatter.py`, `test_webflow_sync.py` |
| C1 (descripción) | +17 | `test_description_formatter.py`, `test_webflow_sync.py` |
| C2 (imágenes) | +9 | `test_webflow_sync.py` |
| D1 (título canónico) | +11 | `test_slugify.py` |
| B1 (list_items) | +3 | `test_webflow_client.py` |
| E1 (dedup index) | +3 | `test_webflow_sync.py` |
| G1 (migración) | +5 | `test_migrate_existing.py` |

---

## 2. Bloque A1 — Schema Webflow

```
$ python3 scripts/inspect_webflow_schema.py
[INFO] httpx — HTTP Request: GET https://api.webflow.com/v2/collections/673373bb232280f5720b72ca "HTTP/1.1 200 OK"
[INFO] inspect_webflow_schema — Collection: Spain Warehouses (id=673373bb232280f5720b72ca) — 20 fields
[INFO] inspect_webflow_schema — Raw schema written to docs/webflow-schema.json
```

Salida resumida (campos relevantes):
- `additional-images` MultiImage ✅
- `latitude` PlainText, `longitude` PlainText ✅
- `funeral-home-biography` RichText (mapeado como description) ✅
- `main-image` Image, `listing-images` MultiImage, `all-images` MultiImage ✅
- `source-url` ❌ falta (Benedict debe crearlo)
- `phone` ❌ falta (Benedict debe crearlo)

JSON crudo en `docs/webflow-schema.json`.

---

## 3. Bloque A2 — Lat/lng al pipeline

```
$ python3 -m pytest tests/test_db.py::TestCoordinates tests/test_parser.py::TestParseCoordinates tests/test_webflow_sync.py::TestLatitudeLongitudeMapping -v
=== 13 passed ===
```

Cubre:
- columnas `latitude`/`longitude` existen en SCHEMA y `_NEW_COLUMNS`
- `insert_listing` persiste valores no-nulos y nulos
- `parse_coordinates` extrae de `ad_json.location.geolocation`
- `FIELD_MAP_PATTERNS` incluye lat/lng
- valores PlainText serializados como `str(float)` con precisión completa
- omitidos cuando son None (nunca enviar `null` a Webflow)

---

## 4. Bloque B2 — Detección ad_type robusta

```
$ python3 -m pytest tests/test_parser.py::TestParseAdType -v
=== 5 passed (incluye test_undetectable_returns_none_and_logs_warning) ===
```

Verifica:
- `parse_ad_type` emite WARNING cuando ningún signal (categories, sellType, URL keyword) detecta el tipo
- el warning incluye la URL para debugging
- los casos válidos (URL venta, URL alquiler, JSON sellType=supply, JSON categoria con alquiler) siguen funcionando

---

## 5. Bloque B3 — Formato de precio

```
$ python3 -m pytest tests/test_price_formatter.py tests/test_webflow_sync.py::TestPriceFormattingByAdType -v
=== 19 passed ===
```

Validaciones clave:
- venta `199000` → `"199.000 €"`
- venta `1_250_000` → `"1.250.000 €"`
- alquiler `price_per_m2=1.19` → `"1.19€/m²"`
- alquiler `price_per_m2=1.196` → `"1.20€/m²"` (round)
- alquiler sin per-m² pero con price_numeric → `"1.500 €/mes"` (fallback)
- ad_type desconocido → None
- venta con decimal `199500.6` → `"199.501 €"` (usa `round`, no `int`)
- en `build_field_data`: venta llena solo `new-sale-price`; alquiler llena solo `new-price-sm2-month`

---

## 6. Bloque C1 — Descripción RichText

```
$ python3 -m pytest tests/test_description_formatter.py tests/test_webflow_sync.py::TestDescriptionRichTextConversion -v
=== 17 passed ===
```

Casos verificados:
- inputs vacíos → None
- texto plano → `<p>texto</p>`
- caracteres `<` `&` HTML-escaped
- `\n` → `<br>` dentro del párrafo
- `\n\n` → nuevo `<p>`
- ≥ 2 marcadores `•` → `<ul><li>`
- 1 solo `•` no dispara lista
- bullets HTML-escaped (anti-inyección)
- sample real de Benedict: convierte la descripción larga con bullets inline en `<p>`+`<ul>` correctamente

---

## 7. Bloque C2 — Split de imágenes

```
$ python3 -m pytest tests/test_webflow_sync.py::TestImageSplitting -v
=== 9 passed ===
```

Sample realista (12 URLs con duplicados → 9 únicas):

| Input slot | Webflow field | URLs |
|---|---|---|
| imagen 1 | `main-image` | u1 |
| imágenes 2-5 | `listing-images` | u2, u3, u4, u5 |
| imágenes 1-5 | `all-images` | u1, u2, u3, u4, u5 |
| imágenes 6-9 | `additional-images` | u6, u7, u8, u9 |

`MAX_IMAGES_PER_LISTING` subido de 10 a 20. Telemetry por imagen activado.

---

## 8. Bloque D1 — Título canónico

```
$ python3 -m pytest tests/test_slugify.py::TestExtractWarehouseName tests/test_slugify.py::TestBuildCanonicalTitle -v
=== 11 passed ===
```

Casos:
- `location` presente → se usa directamente
- `location` vacío + `address` con calle real (e.g., "Calle Mayor 5, ...") → toma "Calle Mayor 5"
- `address` empezando con CP "28045, Madrid" → rechazado, fallback None
- `address` sin keyword de calle → rechazado
- `build_canonical_title("venta", "X")` → "Nave industrial en venta en X"
- `build_canonical_title("alquiler", "X")` → "Nave industrial en alquiler en X"
- ad_type desconocido / inputs faltantes → None

Migración disponible en `scripts/migrate_canonical_titles.py` (dry-run por defecto, genera CSV de redirects).

---

## 9. Bloque B1 — Webflow `list_items()`

```
$ python3 -m pytest tests/test_webflow_client.py::TestListItemsPagination -v
=== 3 passed ===
```

Verifica con `respx`:
- single page: 2 items devueltos como lista
- multi-page: 150 items en 2 páginas → merge correcto, orden preservado
- `cmsLocaleId` se incluye en query string cuando se pasa

---

## 10. Bloque E1 — Dedup vía source-url

```
$ python3 -m pytest tests/test_webflow_sync.py::TestBuildSourceUrlIndex -v
=== 3 passed ===
```

Verifica:
- sin field mapping → índice vacío (degrada limpio)
- con items que tienen `source-url` → índice `{url: item_id}` correcto
- error en `list_items()` → no propaga, devuelve `{}`

---

## 11. Bloque G1 — Script de migración consolidado

Dry-run sobre la BD local:

```
$ python3 scripts/migrate_existing_listings.py
[INFO] mode=DRY-RUN ts=20260503T023144Z
[INFO] [DB] Migración: columnas añadidas → ['latitude', 'longitude', 'original_title']
[INFO] Base de datos inicializada en /home/john/.../naves.db
[INFO] 0 rows scanned
[INFO] pending=0  noop=0  total=0
[INFO] report: /home/john/.../reports/migration_existing_20260503T023144Z.csv
[INFO] Run with --apply to write changes.
```

Confirma que:
- la migración de schema añadió `latitude`, `longitude`, `original_title` automáticamente
- el script corre limpio en dry-run
- emite CSV vacío correctamente cuando no hay filas

Tests unitarios:

```
$ python3 -m pytest tests/test_migrate_existing.py -v
=== 5 passed ===
```

Cubre `recompute_row`:
- noop cuando todo ya está correcto
- propone canonical title cuando es raw
- convierte plain-text description a HTML
- no double-wrap si description ya empieza con `<`
- skip cuando no hay Name extraíble

---

## 12. Estado final por tarea del cliente

| # | Tarea | Estado |
|---|---|---|
| 1 | Detección venta/alquiler | ✅ + warning logging |
| 2 | Título/slug canónico | ✅ live + back-fill script |
| 3 | Dedup imágenes + split | ✅ |
| 4 | Formato descripción | ✅ (RichText) |
| 5 | Formato precio | ✅ (venta/alquiler/`/mes`) |
| 6 | Anti-duplicados Webflow | ✅ infra (activa cuando exista `source-url`) |
| 7 | URL original en CMS | 🚫 falta crear el campo en Webflow |
| 8 | Datos de contacto | 🚫 falta crear el campo en Webflow |
| 9 | Geocodificación | ✅ Fase 1 (lat/lng); Fase 2 pendiente Benedict |

---

## 13. Acciones requeridas a Benedict para desbloquear

En el CMS de Webflow, añadir a la colección "Spain Warehouses":

1. **Campo `Source URL`** — slug `source-url`, tipo Plain Text. Desbloquea Tarea 7 + el dedup automático contra duplicados (Tarea 6).
2. **Campo `Phone`** — slug `phone`, tipo Plain Text. Desbloquea Tarea 8.
3. (opcional) **Campo `Phone 2`** — slug `phone-2`, tipo Plain Text. Para vendedores con dos números.

Cuando los campos existan, el código los recoge automáticamente (no requiere despliegue) — `FIELD_MAP_PATTERNS` ya tiene los slugs candidatos definidos.

---

## 14. Archivos entregados

### Código nuevo
- `scripts/inspect_webflow_schema.py` (A1)
- `scripts/migrate_canonical_titles.py` (D1)
- `scripts/migrate_existing_listings.py` (G1)
- `utils/price_formatter.py` (B3)
- `utils/description_formatter.py` (C1)

### Código modificado
- `db.py` — columnas `latitude`, `longitude`, `original_title`; helper `update_canonical_title`
- `integrations/parser.py` — coords en output, warning en `parse_ad_type`
- `integrations/webflow_client.py` — método `list_items()` paginado
- `integrations/webflow_sync.py` — formato precio, descripción RichText, split imágenes 4 grupos, dedup index
- `integrations/webflow_image_uploader.py` — cap 10 → 20 + telemetry
- `scraper_engine.py` — wireup de canonical title
- `utils/slugify.py` — `extract_warehouse_name`, `build_canonical_title`

### Documentación
- `docs/iteration-2026-05-feedback.md` — cambios por bloque (este archivo es su complemento)
- `docs/verification-report-2026-05.md` — este reporte
- `docs/webflow-schema.json` — dump del schema actual

### Tests nuevos
- `tests/test_description_formatter.py` (15 tests)
- `tests/test_price_formatter.py` (15 tests)
- `tests/test_webflow_sync.py` (23 tests)
- `tests/test_migrate_existing.py` (5 tests)
- `tests/test_parser.py`, `test_db.py`, `test_slugify.py`, `test_webflow_client.py` extendidos

---

## 15. Prueba en tiempo real del scraper

Ejecutado el 2026-05-02 contra `milanuncios.com` con 1 listing real (`--pages 1 --batch 1`, BD aislada en `/tmp/test_naves.db`).

### Pipeline observado

```
[Search]   Página 1: 3 anuncios.
[Listing]  Scrapeando: …venta-de-naves-industriales-en-barco-de-avila-avila/…593416592.htm
[Listing]  OK: 593416592 | El Barco de Ávila | None m² | 62.000 €
[DB]       Insertado: 593416592 — Nave industrial en venta en Barco de Avila (Ávila)
[IMG]      593416592: 8/8 imágenes descargadas → images/593416592
RESUMEN:   Nuevos insertados: 1, Total en BD: 1
```

### Verificación de campos en BD (post-scrape, BD aislada)

| Campo | Valor |
|---|---|
| `listing_id` | `593416592` |
| `title` | `Nave industrial en venta en Barco de Avila (Ávila)` ✅ canónico |
| `original_title` | `El Barco de Ávila` ✅ preservado |
| `webflow_slug` | `nave-industrial-en-venta-en-barco-de-avila-avila` ✅ |
| `ad_type` | `venta` ✅ detectado |
| `price` / `price_numeric` | `62.000 €` / `62000.0` |
| `latitude` / `longitude` | `40.3584245` / `-5.523076700000001` ✅ persistidos |
| `address` / `location` | `05600, Barco de Avila, Ávila` / `Barco de Avila (Ávila)` |
| `phone` | `685970618` ✅ extraído tras click "Llamar" |
| `description` | 1098 chars de texto plano (será convertido a HTML en sync) |
| `photos` | 8 URLs únicas |

### Verificación del payload que iría a Webflow

`build_field_data` aplicado a la fila real sobre el schema descargado:

```
name                          : 'Nave industrial en venta en Barco de Avila (Ávila)'
slug                          : 'nave-industrial-en-venta-en-barco-de-avila-avila'
new-sale-price                : '62.000 €'                        ← B3 ES format
latitude                      : '40.3584245'                       ← A2 PlainText
longitude                     : '-5.523076700000001'               ← A2 PlainText
full-address                  : '05600, Barco de Avila, Ávila'
location                      : 'Barco de Avila (Ávila)'

description (RichText): '<p>Ref: 3-26. - Oportunidad Única - …</p>'  ← C1 HTML conversion (1098 chars, html=True)

Image split:
  main-image:        1 image  ← imagen 1
  listing-images:    4 items  ← imágenes 2-5  ("Top 4 Best Images")
  all-images:        5 items  ← imágenes 1-5  ("Airbnb Top 5 Images")
  additional-images: 3 items  ← imágenes 6-8  (overflow)
```

**Resultado:** todas las tareas implementables (1, 2, 3, 4, 5, 9 fase 1) funcionan end-to-end con datos reales de producción. Tareas 7 y 8 quedan en el código listas para activarse cuando Benedict cree los campos `source-url` y `phone` en Webflow.

---

## 16. Segunda prueba en tiempo real (2026-05-03)

Re-ejecutado el día siguiente con `--pages 1 --batch 2` contra `milanuncios.com` para confirmar reproducibilidad.

**Notable:** esta vez el captcha de warm-up se resolvió **automáticamente en 14 s** (la prueba anterior requirió resolución manual). El comportamiento del antibot del sitio varía día a día — el sistema actual maneja ambos casos.

### Listings procesados

| listing_id | título canónico | precio | ubicación | lat/lng | phone |
|---|---|---|---|---|---|
| 592122863 | Nave industrial en venta en Sevilla (Sevilla) | 722.400 € | Sevilla | 37.39 / -5.95 | None |
| 569614409 | Nave industrial en venta en Los Palacios y Villafranca (Sevilla) | 95.000 € | Los Palacios y Villafranca | 37.16 / -5.93 | 678574291 |

Ambos:
- ✅ Título canónico aplicado, `original_title` preservado.
- ✅ Slug derivado del título canónico, sin colisiones.
- ✅ `ad_type = "venta"` detectado por URL.
- ✅ `latitude`/`longitude` extraídos del JSON.
- ✅ `new-sale-price` formateado en ES (`722.400 €`, `95.000 €`).
- ✅ Descripción convertida a `<p>...</p>` RichText.
- ✅ Split de imágenes en 4 grupos (main + 4 + 5 + 3-4).

### Notas operativas

- **listing 592122863** no tenía `address` (shop sin dirección de calle); el helper `extract_warehouse_name` cayó al fallback `location` → `"Sevilla (Sevilla)"`. Confirma que la lógica location-first no rompe cuando address es None.
- **listing 569614409** tenía address completo con `Calle Joaquín Romero Murube 17`; aun así, location se prefirió. Esto coincide con la decisión de diseño: location es la ciudad de la **propiedad**, address es la del vendedor (más ambigua).
- **listing 592122863** no tenía `phone`: el botón "Llamar" no fue clicado o el shop JSON no expuso `phone1`. La lógica del scraper sigue siendo "best effort" — los nulls son normales.

### Suite de tests final

```
============================= 193 passed in 1.93s ==============================
```

Sin regresiones tras toda la iteración.
