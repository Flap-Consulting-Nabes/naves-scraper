# Iteración 2026-05 — Feedback del cliente Nabes

Tracking de las 9 tareas que Iñigo recopiló del feedback de Benedict tras el primer despliegue del scraper. Una sección por bloque del plan; cada bloque resume qué se cambió, dónde, y cómo verificarlo.

Plan completo (no commiteado): `~/.claude/plans/hi-i-igo-that-s-fine-witty-abelson.md`.

**Documentos hermanos:**
- `docs/verification-report-2026-05.md` — evidencia de pruebas + run en tiempo real.
- `docs/post-benedict-checklist.md` — pasos exactos para activar Tareas 6, 7, 8 cuando Benedict cree los campos en Webflow.
- `docs/webflow-schema.json` — snapshot actual del schema CMS.

---

## Estado por tarea

| # | Tarea | Estado | Bloque |
|---|---|---|---|
| 1 | Detección venta/alquiler | ✅ 4 capas (categories → sellType → URL → keyword scan) + audit script | B2 + B2-bis |
| 2 | Título/slug canónico `Nave industrial en {tipo} en {Name}` | ✅ implementado + script de back-fill | D1 |
| 3 | Dedup imágenes + split (main/top4/additional) | ✅ implementado | C2 |
| 4 | Formato descripción (RichText) | ✅ implementado | C1 |
| 5 | Formato precio (`199.000 €` / `1.19€/m²`) | ✅ implementado | B3 |
| 6 | Anti-duplicados Webflow | ✅ infra lista, activa cuando `source-url` exista | E1 |
| 7 | URL original en campo dedicado | 🚫 parcial: infra `list_items()` lista, falta el campo en CMS | B1 |
| 8 | Datos contacto "Llamar" | 🚫 bloqueado: Benedict debe crear `phone` | A3 |
| 9 | Geocodificación (lat/lng al pipeline) | ✅ Fase 1 completada (A2) | A2 |

---

## Bloque A1 — Auditoría del schema Webflow

**Fecha:** 2026-05-02
**Archivos creados:**
- `scripts/inspect_webflow_schema.py` — script de introspección (read-only).
- `docs/webflow-schema.json` — dump raw del schema actual de la colección "Spain Warehouses" (`673373bb...`, 20 campos).

**Hallazgos clave:**

| Campo Webflow | Tipo | Estado |
|---|---|---|
| `main-image` | Image | ✅ ya mapeado |
| `listing-images` "Top 4 Best Images" | MultiImage | ✅ existe |
| `all-images` "Airbnb Top 5 Images" | MultiImage | ✅ existe |
| `additional-images` | MultiImage | ✅ existe |
| `funeral-home-biography` "Description" | **RichText** | ✅ ya mapeado, requiere conversión `\n→<br>` (C1) |
| `new-sale-price` | PlainText | ✅ ya mapeado |
| `new-price-sm2-month` | PlainText | ✅ ya mapeado |
| `latitude` / `longitude` | **PlainText** (NO Map) | ✅ existen — simplifica A2 |
| `name` / `slug` | PlainText, required | ✅ |
| `google-place-id` | PlainText | bonus para futuro geocoding |
| `source-url` | — | ❌ **falta — Benedict debe crearlo** |
| `phone` / `phone-2` | — | ❌ **falta — Benedict debe crearlos** |

**Verificación:** correr `python3 scripts/inspect_webflow_schema.py` con `WEBFLOW_TOKEN` en el env regenera `docs/webflow-schema.json`.

---

## Bloque A2 — Latitude/longitude al pipeline

**Fecha:** 2026-05-02
**Cobertura:** Tarea 9 fase 1 (sin geocoding fallback).

### Cambios

| Archivo | Cambio |
|---|---|
| `db.py` | Añadidas columnas `latitude REAL`, `longitude REAL` al `SCHEMA` y a `_NEW_COLUMNS` (migración automática). Incluidas en `INSERT OR IGNORE` y devueltas por `get_listings_paginated` y `get_unsynced_listings`. |
| `integrations/parser.py` | `parse_listing_page` ahora invoca `parse_coordinates(ad)` y emite `latitude`/`longitude` en el dict final (líneas 800-band). |
| `integrations/webflow_sync.py` | `FIELD_MAP_PATTERNS` extendido con entradas `latitude → ["latitude","lat"]` y `longitude → ["longitude","lng","lon"]`. Sin handling especial: el loop genérico de `build_field_data` los serializa como `str(float)` para campos PlainText (que es lo que confirma A1). |
| `tests/conftest.py` | `sample_listing` ahora incluye `latitude=39.5021`, `longitude=-0.4396`. |
| `tests/test_db.py` | Nueva clase `TestCoordinates` (4 tests): columnas existen, insert persiste, insert acepta None, paginación las devuelve. |
| `tests/test_parser.py` | Nueva clase `TestParseCoordinates` (4 tests): None safety, geolocation parsing, partial geolocation. |
| `tests/test_webflow_sync.py` | Nuevo archivo (5 tests): mapeo de FIELD_MAP_PATTERNS, resolve_field_mapping con lat/lng PlainText, serialización a string, omisión cuando None, regresión de Number→float. |

### Verificación

```
python3 -m pytest tests/test_db.py tests/test_parser.py tests/test_webflow_sync.py -v
# 21 tests passed (4 nuevos en db, 4 nuevos en parser, 5 nuevos en webflow_sync, resto regresión)

python3 -m pytest tests/ -v
# 125 passed in 1.76s — sin regresiones
```

### Nota sobre Codex Finding 1 (Map field shape)

El Codex review preventivo asumió que el campo coords podría ser tipo `Map` compuesto `{lat, lng}`. La introspección de A1 demostró que en la colección real son **dos PlainText separados**. Por tanto el handling especial propuesto en el plan no es necesario y se descarta — el loop genérico cubre el caso.

### Pendiente

- Fase 2 (geocoding fallback con Nominatim/Google) — pendiente confirmación de Benedict sobre nivel de precisión aceptable.

---

## Bloque B2 — Verificación de `ad_type` + warning logging

**Fecha:** 2026-05-02
**Cobertura:** Tarea 1.

### Cambios

| Archivo | Cambio |
|---|---|
| `integrations/parser.py` | `parse_ad_type` ahora emite `logger.warning("[parser] ad_type undetectable for url=%s", url)` cuando ningún signal (categories, sellType, URL keyword) detecta el tipo. La precedencia explícita queda documentada en el docstring. |
| `tests/test_parser.py` | Nuevo test `test_undetectable_returns_none_and_logs_warning` con `caplog` que valida (a) None devuelto y (b) mensaje WARNING emitido en el logger correcto. |

Sin cambios estructurales: la detección actual basada en `categories[].slug/name`, `sellType=="supply"`, y URL fallback ya cubre los casos esperados de Milanuncios. El warning logging hace visibles los outliers en producción sin romper el pipeline.

### Verificación

```
python3 -m pytest tests/test_parser.py -v
# 18 passed (incluye el nuevo test_undetectable_returns_none_and_logs_warning)
```

En producción, los warnings aparecerán en `logs/scraper.log` con el patrón `[parser] ad_type undetectable for url=...` — útil para que Alejandro filtre URLs anómalas y decidir si es necesario reforzar la detección.

---

## Bloque B3 — Formato de precio por tipo de operación

**Fecha:** 2026-05-02
**Cobertura:** Tarea 5.

### Cambios

| Archivo | Cambio |
|---|---|
| `utils/price_formatter.py` | **Nuevo**. Función `format_price_display(ad_type, price_numeric, price_per_m2)`. Venta → `"199.000 €"` (separador miles ES). Alquiler con `price_per_m2` → `"1.19€/m²"` (2 decimales). Alquiler sin `price_per_m2` → fallback `"1.500 €/mes"`. `round()` en vez de `int()` evita truncar céntimos. |
| `integrations/webflow_sync.py` | Importa `format_price_display` y lo llama en `build_field_data` después del loop genérico. Mapea según `ad_type`: venta → `new-sale-price`, alquiler → `new-price-sm2-month`. Limpia el campo del otro tipo para no enviar precios cruzados. |
| `tests/test_price_formatter.py` | **Nuevo**. 11 tests: venta básica, miles altos, redondeo no-truncamiento, redondeo a la baja, None, alquiler con per-m², con redondeo, padding de cero, fallback /mes, precedencia per-m² sobre /mes, ambos missing, tipos desconocidos (parametrizado con None/""/unknown/transfer). |
| `tests/test_webflow_sync.py` | Nueva clase `TestPriceFormattingByAdType` (4 tests) que valida el override desde `build_field_data`: venta llena `new-sale-price`, alquiler llena `new-price-sm2-month`, fallback `/mes` cuando no hay per-m², `ad_type=None` deja el str() genérico. |

### Observación importante (banker's rounding)

`round(199500.5)` en Python 3 devuelve `199500` por banker's rounding (PEP 3141, redondeo a número par). Esto NO afecta la lógica del cliente porque los precios de Milanuncios casi nunca tienen `.5` exacto. El test usa `199500.6 → 199501` para evitar la ambigüedad y dejar claro que el redondeo funciona como se espera.

### Verificación

```
python3 -m pytest tests/ -v
# 145 passed (anteriormente 125). +20 tests nuevos en B3.
```

---

## Bloque C1 — Formato de descripción RichText

**Fecha:** 2026-05-02
**Cobertura:** Tarea 4. A1 confirmó que el campo `funeral-home-biography` es **RichText**.

### Cambios

| Archivo | Cambio |
|---|---|
| `utils/description_formatter.py` | **Nuevo**. Función `format_description_html(raw)`. (1) Normaliza `\r\n`/`\r` → `\n`. (2) Divide párrafos en líneas en blanco. (3) Si un párrafo contiene ≥ 2 marcadores `•`: el texto antes del primer bullet se preserva en `<p>` y los bullets posteriores se agrupan en `<ul><li>`. (4) Saltos de línea simples se convierten a `<br>`. (5) HTML-escape en todo el contenido para evitar inyección. |
| `integrations/webflow_sync.py` | `build_field_data` ahora detecta `ftype == "RichText"` para `db_field == "description"` y aplica `format_description_html`. Otros campos RichText pasan por el `str()` genérico (no rompemos nada existente). |
| `tests/test_description_formatter.py` | **Nuevo**. 15 tests: inputs vacíos (None/""/whitespace), single paragraph, escape HTML, br dentro de párrafo, múltiples párrafos, líneas blancas múltiples colapsadas, bullets al inicio, bullets inline tras texto, bullet único NO dispara lista, bullets HTML-escaped, sample realista con descripción tipo Benedict. |
| `tests/test_webflow_sync.py` | Nueva clase `TestDescriptionRichTextConversion` (2 tests): RichText → HTML; PlainText legacy → texto crudo (regresión). |

### Observación: bullet único

Si solo hay 1 marcador `•` en el texto (e.g., "Una opción • interesante"), no se dispara la conversión a lista — se mantiene como párrafo normal. Esto evita que falsos positivos de Unicode rompan textos legítimos.

### Verificación

```
python3 -m pytest tests/ -v
# 162 passed (anteriormente 145). +17 tests nuevos en C1.
```

Quedó pendiente discutir con Benedict: ¿quiere que también detectemos `* `, `- ` o numerados como bullets? Por ahora solo `•` (que es lo que realmente aparece en los anuncios de Milanuncios).

---

## Bloque C2 — Dedup + split de imágenes en 3 grupos

**Fecha:** 2026-05-02
**Cobertura:** Tarea 3.

### Cambios

| Archivo | Cambio |
|---|---|
| `integrations/webflow_image_uploader.py` | `MAX_IMAGES_PER_LISTING` subido de 10 a 20 (justificado en comentario: ~80 s/listing en peor caso). Telemetry: `[Webflow] Image %d/%d uploaded in %.1fs (%s)` por imagen subida. |
| `integrations/webflow_sync.py` | Refactor del bloque de imágenes en `build_field_data`: dedup explícita preservando orden + split en 4 campos según convención del cliente: `main-image` (1), `listing-images` "Top 4 Best Images" (img 2-5), `all-images` "Airbnb Top 5 Images" (img 1-5 = main + top4), `additional-images` (img 6+). El campo `additional-images` se omite si no hay overflow. |
| `tests/test_webflow_sync.py` | Nueva clase `TestImageSplitting` con 9 tests: dedup preserva orden, main es la primera, listing-images contiene 2-5, all-images contiene main+top4, additional contiene overflow, additional omitido si no hay overflow, alt text usa el name, sin imágenes omite todos los campos, sample realista con 12 URLs y 3 duplicados. |

### Mapeo Webflow → cliente

| Slug Webflow | Etiqueta Webflow | Contenido | Pedido por Benedict |
|---|---|---|---|
| `main-image` | Main Image | imagen 1 (primera deduplicada) | "main image" |
| `listing-images` | Top 4 Best Images | imágenes 2-5 | "top 4 images... how they appear in order" |
| `all-images` | Airbnb Top 5 Images | imágenes 1-5 (main + top 4) | "main image + the top 4" |
| `additional-images` | Additional Images | imágenes 6+ | "anything outside those should go to the additional images field" |

### Verificación

```
python3 -m pytest tests/ -v
# 171 passed (anteriormente 162). +9 tests nuevos en C2.
```

---

## Bloque D1 — Título y slug canónicos

**Fecha:** 2026-05-02
**Cobertura:** Tarea 2.

### Cambios

| Archivo | Cambio |
|---|---|
| `utils/slugify.py` | Nueva función `extract_warehouse_name(data)` con regla **location primero, address con calle real como fallback**. Rechaza `address` que empiece por código postal o que no contenga keyword de calle (`calle`, `avda`, `polígono`, `carretera`, `paseo`, etc.). Nueva función `build_canonical_title(ad_type, name)` que devuelve `"Nave industrial en {venta\|alquiler} en {name}"` o None si falta cualquier input. |
| `db.py` | Nueva columna `original_title TEXT` (en SCHEMA y `_NEW_COLUMNS`). Helper nuevo `update_canonical_title(conn, listing_id, new_title, new_slug, original_title)` que usa `COALESCE(original_title, ?)` para no sobrescribir el título original en re-runs. SELECTs de `get_unsynced_listings` actualizado para devolver `original_title`. |
| `scraper_engine.py` | En `run()` (línea ~195), antes de `generate_unique_slug` y `insert_listing`: persiste `original_title`, calcula `canonical_name = extract_warehouse_name(data)`, calcula `canonical_title = build_canonical_title(ad_type, canonical_name)`. Si éxito, sobrescribe `data["title"]`. Si no, log WARN con `listing_id` + valores y conserva el título crudo. |
| `scripts/migrate_canonical_titles.py` | **Nuevo**. Script de back-fill modelado en `migrate_slugs.py`. (a) Lee todos los listings, (b) calcula nuevo título canónico + slug, (c) clasifica como `pending`/`noop`/`skipped_no_canonical`, (d) modo `--dry-run` por defecto + confirmación interactiva en `--apply` (omitible con `--yes`), (e) escribe `reports/migration_canonical_titles_{ts}.csv` con todas las filas y `reports/redirects_{ts}.csv` con `old_slug,new_slug` para que Benedict cargue redirects en Webflow Site Settings, (f) PATCH a Webflow vía `update_items` (omitible con `--skip-webflow`). |
| `tests/test_slugify.py` | 11 tests nuevos: `TestExtractWarehouseName` (location preferido, fallback a address con calle, rechazo CP-only, rechazo address sin calle, ambos vacíos, dict vacío); `TestBuildCanonicalTitle` (venta, alquiler, ad_type desconocido, inputs faltantes). |

### Riesgo de URLs rotas

Renombrar el slug de un item Webflow ya publicado **no genera redirect automático**. Las URLs públicas existentes harán 404. Antes de ejecutar `--apply` en producción:
1. Correr `--dry-run` para revisar el CSV de cambios.
2. Cargar el CSV de redirects en **Webflow Site Settings → Hosting → Redirects** (manualmente; la API de Redirects no está disponible en todos los planes).
3. Solo entonces correr `--apply`.

### Verificación

```
python3 -m pytest tests/ -v
# 182 passed (anteriormente 171). +11 tests nuevos en D1.

python3 scripts/migrate_canonical_titles.py
# Default dry-run: imprime resumen y escribe reports/*.csv sin tocar nada.

python3 scripts/migrate_canonical_titles.py --apply --skip-webflow
# Solo BD local: útil para verificar antes de tocar Webflow.
```

---

## Bloque B1 — Infra de paginación de Webflow

**Fecha:** 2026-05-02
**Cobertura:** Tarea 7 (parcial — falta crear el campo en Webflow).

### Cambios

| Archivo | Cambio |
|---|---|
| `integrations/webflow_client.py` | Nuevo método `WebflowClient.list_items(cms_locale_id=None, page_limit=100, throttle_seconds=0.6)`. Pagina vía `offset/limit`, throttle de 0.6 s entre requests para respetar el límite de 60 req/min de Webflow. Usable por E1 (dedup index) y por scripts de migración. |
| `tests/test_webflow_client.py` | 3 tests con `respx`: single page, multi-page (150 items), envío correcto de `cmsLocaleId`. |

### Bloqueador del cliente

El campo `source-url` no existe aún en la colección Webflow. Hasta que Benedict lo cree:
- El back-fill `scripts/backfill_source_url.py` no se construye (no hay nada que rellenar).
- El dedup de E1 (descrito abajo) funciona como **no-op silencioso**: detecta la ausencia del slug y deshabilita el índice sin error.

**Acción para Benedict:** crear en Webflow CMS un campo `Source URL` con slug `source-url` (Plain Text). El código ya lo recogerá automáticamente vía `FIELD_MAP_PATTERNS["url"]`.

---

## Bloque E1 — Dedup contra Webflow vía source-url

**Fecha:** 2026-05-02
**Cobertura:** Tarea 6.

### Cambios

| Archivo | Cambio |
|---|---|
| `integrations/webflow_sync.py` | Nuevo helper `_build_source_url_index(client, field_mapping, locale_id)`. Devuelve `{source_url: item_id}` recorriendo todos los items de la colección. Si la colección no tiene `source-url` mapeado o `list_items` falla, devuelve `{}` con log informativo (no bloquea sync). En `sync_pending_listings`, antes del loop de creación: si `row.url` ya está en el índice, copia el `webflow_item_id` a la BD local y omite la creación con log `[SKIP-WEBFLOW] %s ya existe como %s`. |
| `tests/test_webflow_sync.py` | Clase `TestBuildSourceUrlIndex`: índice vacío cuando el campo no está mapeado, mapeo correcto cuando hay items, error en `list_items` no propaga (degrada a `{}`). |

### Comportamiento

- **Hoy** (sin `source-url` en CMS): el índice queda vacío. Sync se comporta como antes — sin dedup contra Webflow. No hay regresión.
- **Tras Benedict crear `source-url`**: el primer sync que toque cada item lo poblará. Desde el siguiente run, los duplicados se detectan automáticamente.
- **Stale references**: si Benedict borra un item manualmente en Webflow tras un sync, la BD local mantiene un `webflow_item_id` huérfano. La mitigación opcional `--verify-ids` se difiere a una iteración futura.

### Verificación

```
python3 -m pytest tests/ -v
# 188 passed (anteriormente 182). +6 tests nuevos en B1+E1.
```

---

## Bloque B2-bis — Detección reforzada por keywords (capa 4)

**Fecha:** 2026-05-04
**Cobertura:** Tarea 1 (refuerzo).

### Motivación

La detección anterior (categories → sellType → URL) era robusta pero ciega a casos en los que la fuente categoriza mal. El cliente pidió una capa adicional de seguridad que escanee título + descripción con regex en español.

### Cambios

| Archivo | Cambio |
|---|---|
| `integrations/parser.py` | `parse_ad_type` ahora acepta `title=` y `description=`. Nueva capa 4: `_scan_text_for_ad_type` cuenta hits de regex. Si URL y body discrepan con `≥ 2` hits a favor del body, se loguea WARN y el body gana. Nuevos signals para alquiler: `alquiler`, `alquila`, `arriendo`, `renta`, `1.19€/m²`, `€/mes`, `mensual`. Nuevos signals para venta: `venta`, `vendo`, `se vende`, `compraventa`, `traspaso`. También se acepta `sellType="demand"` → alquiler. |
| `integrations/parser.py` | `parse_listing_page` pasa título y descripción al `parse_ad_type` para activar la capa 4 desde la primera scrapada. |
| `scripts/migrate_existing_listings.py` | `recompute_row` re-evalúa el `ad_type` para **todas** las filas (no solo NULL) para que la migración pueda corregir listings mal categorizados. |
| `scripts/audit_ad_types.py` | **Nuevo**. Recorre todas las filas, re-aplica `parse_ad_type` con title+description+raw_html, compara contra `ad_type` actual y clasifica como `noop`/`fill_null`/`flip`/`review_keep`. Modo `--dry-run` por defecto + `--apply` para escribir correcciones. CSV en `reports/audit_ad_types_{ts}.csv`. |
| `tests/test_parser.py` | 8 tests nuevos: body alquiler con URL neutra, body venta con URL neutra, patrón `€/m²` activa alquiler, body fuerte sobreescribe URL (con WARN), body débil deja URL ganar, `sellType=demand`, `traspaso → venta`, body empatado → None. |

### Resultado de la prueba en tiempo real (2026-05-04)

Scraping de 2 listings reales de Milanuncios en BD aislada:

| listing_id | URL | ad_type detectado | hits venta | hits alquiler |
|---|---|---|---|---|
| 536607171 | `…/alquiler-de-naves…/almassera…` | alquiler ✅ | 0 | 2 |
| 591003228 | `…/alquiler-de-naves…/beniparrell…` | alquiler ✅ | 0 | 1 |

Audit posterior: `noop=2 fill_null=0 flip=0 review=0` — todo concuerda.

### Verificación

```bash
python3 -m pytest tests/ -v
# 201 passed (anteriormente 193). +8 tests nuevos en B2-bis.

python3 scripts/audit_ad_types.py
# Dry-run: lee BD, no escribe nada. CSV en reports/audit_ad_types_*.csv

python3 scripts/audit_ad_types.py --apply
# Reescribe ad_type en filas con `flip` o `fill_null`
```

---

## Bloque G1 — Migración consolidada de naves ya scrapeadas

**Fecha:** 2026-05-02
**Cobertura:** lo que el cliente pidió ("script para mejorar y actualizar las naves ya scrapeadas").

### Cambios

| Archivo | Cambio |
|---|---|
| `scripts/migrate_existing_listings.py` | **Nuevo**. Script único que reaplica todas las reglas de la iteración a las filas existentes en BD y a sus items en Webflow. |
| `tests/test_migrate_existing.py` | **Nuevo**. 5 tests unitarios sobre `recompute_row`: noop cuando ya está canónico, propone canonical title cuando es raw, descripción plaintext → HTML, descripción ya HTML no se modifica, skip cuando no hay Name extraíble. |

### Lo que hace el script

Por cada fila (orden `scraped_at ASC`):

1. **`ad_type`** — re-parsea desde `url` + `raw_html` cuando está NULL.
2. **lat/lng** — extrae de `raw_html` cuando faltan (cubre filas pre-A2).
3. **descripción** — convierte a HTML con `format_description_html` solo si no empieza ya por `<` (no double-wrap).
4. **título canónico** — `extract_warehouse_name` + `build_canonical_title`. Si propone cambio, captura `original_title`.
5. **slug** — `generate_unique_slug` con `exclude_listing_id` (re-cómputo deterministico, colisiones gestionadas).
6. **precio** — formato display via `format_price_display(ad_type, price_numeric, price_per_m2)` aplicado al payload de Webflow.
7. **imágenes** — `build_field_data` re-aplica el split (main / top4 / all-5 / additional). No re-descarga, solo reordena las URLs ya guardadas.

### CLI

```
python scripts/migrate_existing_listings.py                    # dry-run (default)
python scripts/migrate_existing_listings.py --listing-id 123   # solo una fila
python scripts/migrate_existing_listings.py --apply            # BD + Webflow PATCH (con confirmación)
python scripts/migrate_existing_listings.py --apply --yes      # sin confirmación
python scripts/migrate_existing_listings.py --apply --skip-webflow  # solo BD local
```

### Outputs

- `reports/migration_existing_{timestamp}.csv`: una fila por listing con `fields_changed`, `old_title`, `new_title`, `old_slug`, `new_slug`, `ad_type`, `status` (`pending`/`noop`).
- Para los items con cambio de slug: el script `migrate_canonical_titles.py` (D1) ya genera el `redirects_*.csv` complementario para Webflow Site Settings → Redirects.

### Verificación

```
python3 -m pytest tests/ -v
# 193 passed (anteriormente 188). +5 tests nuevos en G1.

python3 scripts/migrate_existing_listings.py
# Dry-run: lee BD, no escribe nada, deja CSV en reports/
```

---

## Bloques restantes

Pendientes — se irán documentando aquí conforme se ejecuten.
