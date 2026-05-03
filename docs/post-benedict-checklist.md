# Post-Benedict checklist — completar Tareas 6, 7, 8

Documento operativo para cuando Benedict confirme la creación de los
campos faltantes en el CMS de Webflow. Sigue los pasos en orden;
cada uno es idempotente y reversible salvo donde se indica.

---

## Paso 0 — Confirmar lo que Benedict creó

Pídele que confirme literalmente los **slugs** (no los nombres
visibles) de los campos nuevos. El código depende del slug exacto.

Slugs esperados en `FIELD_MAP_PATTERNS`:

| DB column | Slugs candidatos (Webflow) | Tarea |
|---|---|---|
| `url` | `source-url`, `url`, `link`, `enlace`, `url-origen` | 7 |
| `phone` | `phone`, `telefono`, `teléfono`, `contacto` | 8 |
| `phone2` | (no mapeado todavía — añadir cuando confirme) | 8 |

Si Benedict creó los campos con cualquiera de los slugs anteriores, el
código los recoge automáticamente sin redeploy. Si usó otro slug,
añadirlo al `FIELD_MAP_PATTERNS` correspondiente en
`integrations/webflow_sync.py`.

---

## Paso 1 — Re-correr la introspección y commitear el snapshot

```bash
python3 scripts/inspect_webflow_schema.py
git diff docs/webflow-schema.json
git add docs/webflow-schema.json
git commit -m "chore: webflow schema snapshot post source-url/phone fields"
```

El output debe ahora marcar como `[FOUND ]` los campos
`Source URL (Task 7)` y `Phone 1 (Task 8)`.

---

## Paso 2 — Si Benedict creó `phone-2`, añadirlo al mapa

Editar `integrations/webflow_sync.py` y añadir:

```python
"phone2":           ["phone-2", "phone2", "telefono-2", "segundo-telefono"],
```

junto a la entrada existente de `phone`. Tests:

```bash
python3 -m pytest tests/test_webflow_sync.py -v
```

---

## Paso 3 — Smoke test del sync sobre 1 listing

Esto verifica que el `source-url` y `phone` llegan al CMS antes de
ejecutar la migración masiva.

```bash
DB_PATH=/tmp/test_naves.db rm -f /tmp/test_naves.db /tmp/test_naves.db-*
DB_PATH=/tmp/test_naves.db DISPLAY=:1 python3 scraper_engine.py --pages 1 --batch 1
DB_PATH=/tmp/test_naves.db python3 -c "
import sqlite3, asyncio
from integrations.webflow_sync import sync_pending_listings
asyncio.run(sync_pending_listings())
"
```

En el dashboard de Webflow, abrir el item draft recién creado y verificar:

- `Source URL` contiene la URL completa de Milanuncios.
- `Phone` contiene el teléfono (e.g. `685970618`).
- (si phone-2 se añadió) `Phone 2` vacío o con el secundario.

Si todo se ve bien, borrar el item de prueba en Webflow y limpiar:

```bash
rm -f /tmp/test_naves.db /tmp/test_naves.db-*
```

---

## Paso 4 — Back-fill de items ya publicados (Tarea 7)

Para que el dedup automático (Tarea 6) funcione contra los items
existentes, hay que rellenarles `source-url` retroactivamente. La BD
local ya tiene la URL de cada listing en su columna `url`.

```bash
# Dry-run
python3 scripts/migrate_existing_listings.py
# Inspeccionar reports/migration_existing_*.csv

# Aplicar
python3 scripts/migrate_existing_listings.py --apply
```

`migrate_existing_listings.py` ya envía el campo `url` (mapeado a
`source-url`) en el PATCH de Webflow.

---

## Paso 5 — Reaplicar el resto de mejoras a items publicados

El mismo script del Paso 4 también:

- Convierte descripciones a HTML donde aún sean texto plano.
- Reformatea precios (`62000` → `"62.000 €"` venta o `"1.19€/m²"` alquiler).
- Recompone título canónico + slug (cuidado — ver Paso 6).
- Re-aplica el split de imágenes en 4 grupos.
- Envía lat/lng como PlainText.

Si solo querés rellenar `source-url` sin tocar slugs/títulos, podés
filtrar el CSV antes de aprobar el `--apply` (revisar manualmente
qué filas tienen `fields_changed` que incluya `title`).

---

## Paso 6 — Manejo de redirects al renombrar slugs

Si el back-fill cambia slugs de items publicados (e.g.
`nave-522617673` → `nave-industrial-en-venta-en-carretera-de-camposoto-75`),
las URLs públicas viejas harán **404**. Webflow no auto-redirige.

**Antes de `--apply`** sobre items publicados:

1. Ejecutar el dry-run y revisar `reports/redirects_*.csv` (lo genera
   `migrate_canonical_titles.py`, lanzarlo aparte si es necesario):

   ```bash
   python3 scripts/migrate_canonical_titles.py
   ```

2. Cargar el CSV manualmente en Webflow Site Settings →
   Hosting → Redirects (la API de Redirects no está disponible en
   todos los planes; verificar antes con Benedict).

3. Solo entonces correr el `--apply` masivo del Paso 4.

---

## Paso 7 — Activar el dedup contra Webflow (Tarea 6)

No requiere ningún cambio de código. La próxima vez que corra
`sync_pending_listings()`:

1. `_build_source_url_index` cargará todos los items de Webflow vía
   `WebflowClient.list_items()`.
2. Construirá `{source_url: item_id}` con los items que ahora tienen
   `source-url` poblado (gracias al Paso 4).
3. Cualquier listing nuevo cuya `url` ya esté en el índice se omitirá
   con log `[SKIP-WEBFLOW] %s ya existe como %s`.

Verificación: correr `sync_pending_listings()` dos veces seguidas; la
segunda no debe crear duplicados.

---

## Paso 8 — Confirmar geocoding (Tarea 9 fase 2) o cerrarla

Pendiente: confirmar con Benedict si los anuncios sin coordenadas
(que los hay — `parse_coordinates` devuelve None para muchos) deben
geocodificarse via Nominatim/Google. Hasta su confirmación, la fase 2
queda fuera de scope.

Plan inicial si aprueba Nominatim (gratuito):

- Añadir `utils/geocoder.py` con cache local en SQLite.
- Nuevo paso opcional en `migrate_existing_listings.recompute_row`:
  cuando `latitude/longitude` siguen siendo None tras parsear
  `raw_html`, intentar geocode con `address+zipcode+location`.
- Throttle: 1 req/seg (límite de uso aceptable de Nominatim).

---

## Paso 9 — Confirmar formato de bullets en descripción

Pendiente: confirmar con Benedict si quiere que detectemos también `*`
y `- ` como marcadores de lista, o solo `•` (que es lo único que
realmente aparece en los anuncios de Milanuncios). Hasta entonces el
helper solo trata `•`.

Si quiere ampliar:

- Editar `utils/description_formatter._BULLET_RE` para incluir las
  variantes adicionales.
- Añadir tests con muestras reales en `tests/test_description_formatter.py`.

---

## Paso 10 — Decisión sobre el cap de imágenes

Subido de 10 a 20 en C2. Si Benedict ve listings con más de 20
imágenes que se truncan visiblemente, evaluar subir a 30 y medir el
tiempo de upload por listing.

Métrica disponible en los logs gracias a la telemetry:

```
[Webflow] Image %d/%d uploaded in %.1fs (%s)
```

---

## Comandos rápidos de verificación

```bash
# Tests
python3 -m pytest tests/ -v

# Schema actual
python3 scripts/inspect_webflow_schema.py

# Dry-run del scraper sobre 1 listing
DB_PATH=/tmp/t.db DISPLAY=:1 python3 scraper_engine.py --pages 1 --batch 1 --dry-run

# Real scrape sobre 1 listing en BD aislada
DB_PATH=/tmp/t.db DISPLAY=:1 python3 scraper_engine.py --pages 1 --batch 1

# Migración de naves ya scrapeadas (dry-run)
python3 scripts/migrate_existing_listings.py

# Migración back-fill de slugs canónicos (dry-run, genera redirects CSV)
python3 scripts/migrate_canonical_titles.py
```

---

## Quién hace qué

| Acción | Responsable |
|---|---|
| Crear campos `source-url`, `phone`, `phone-2` en Webflow CMS | **Benedict** |
| Confirmar slugs exactos de los campos creados | **Benedict** |
| Confirmar formato de bullets para descripción | **Benedict** |
| Aprobar fase de geocoding (Nominatim vs Google) | **Benedict** |
| Cargar redirects CSV en Webflow Site Settings | **Benedict** o **Iñigo** |
| Pasos 1-7 (introspección, smoke test, migración, sync) | **Iñigo** / **Alejandro** |
