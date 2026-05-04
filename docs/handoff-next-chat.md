# Handoff para el siguiente chat — Milanuncios scraper

Documento de continuidad para retomar sin contexto perdido. Pegar el
resumen "Mensaje para el siguiente chat" (al final) en una conversación
nueva con Claude Code.

---

## Estado actual del proyecto (2026-05-04)

### Lo que está terminado y commiteado en `main`

11 commits con la iteración 2026-05 completa:

```
067c774 feat(B2-bis): keyword-scan layer 4 for ad_type + audit script
1af72da docs: second real-time scrape verification (2 listings)
aa59510 docs: post-Benedict activation checklist
286b63b docs: append real-time scrape verification to iteration report
86f122e docs: iteration 2026-05 change log + verification report
daa6d4c feat(G1): migration script for already-scraped warehouses
f5d3e54 feat(D1): canonical title + slug ('Nave industrial en {tipo} en {Name}')
f00f6c3 feat(B1,C2): Webflow list_items() pagination + image cap raised to 20
6b63227 feat(B3,C1): price formatter + description RichText helpers
40fd15d feat(A2): persist latitude/longitude through scraper → DB → Webflow
d03b784 feat(A1): Webflow schema introspection script
```

### Tareas resueltas (9 de Benedict)

| # | Tarea | Estado |
|---|---|---|
| 1 | venta/alquiler | ✅ 4 capas (categories → sellType → URL → keyword scan) + `audit_ad_types.py` |
| 2 | Título/slug canónico | ✅ live + back-fill `migrate_canonical_titles.py` |
| 3 | Dedup imágenes + split | ✅ main / top4 / all-5 / additional |
| 4 | Descripción RichText | ✅ `\n→<br>` + bullets `•→<ul>` |
| 5 | Precio | ✅ `199.000 €` venta / `1.19€/m²` alquiler / `1.500 €/mes` fallback |
| 6 | Anti-duplicados Webflow | ✅ infra (no-op hasta que exista `source-url` en CMS) |
| 7 | URL original en CMS | 🚫 falta crear `source-url` en Webflow |
| 8 | Datos de contacto | 🚫 falta crear `phone` en Webflow |
| 9 | Geocodificación | ✅ Fase 1 (lat/lng al pipeline); Fase 2 pendiente |

**201 tests passing**, 0 regresiones.

### Pruebas en tiempo real ejecutadas

| Fecha | Listings | Resultado |
|---|---|---|
| 2026-05-02 | 1 (Barco de Ávila, 62.000 €) | ✅ canonical title, lat/lng, phone, descripción HTML, split imágenes |
| 2026-05-03 | 2 (Sevilla, Los Palacios) | ✅ ambos venta, payload Webflow correcto |
| 2026-05-04 | 2 (Almàssera, Beniparrell) | ✅ ambos alquiler detectados; audit reporta `noop=2 flip=0` |

### Documentación commiteada

| Archivo | Propósito |
|---|---|
| `docs/iteration-2026-05-feedback.md` | Change log por bloque (A1, A2, B1, B2, B2-bis, B3, C1, C2, D1, E1, G1) |
| `docs/verification-report-2026-05.md` | Evidencia de pruebas + 2 runs reales |
| `docs/post-benedict-checklist.md` | Pasos exactos cuando Benedict cree los campos |
| `docs/webflow-schema.json` | Snapshot del CMS |
| `docs/handoff-next-chat.md` | Este archivo |

---

## Bloqueador único: Benedict debe crear campos en Webflow

Pídele que añada estos campos en la colección "Spain Warehouses":

### Mínimo para desbloquear las tareas prometidas

1. **`Source URL`** → slug `source-url` (Plain Text) — Tareas 6 + 7
2. **`Phone`** → slug `phone` (Plain Text) — Tarea 8

### Recomendados (el scraper ya los extrae, se descartan al sync)

3. **`Ad Type`** → slug `ad-type` (Plain Text) — filtros venta/alquiler
4. **`Province`** → slug `province` (Plain Text)
5. **`Zipcode`** → slug `zipcode` (Plain Text)
6. **`Published Date`** → slug `published-date` (Date)
7. **`Property Type`** → slug `property-type` (Plain Text)
8. **`Condition`** → slug `condition` (Plain Text)
9. **`Energy Certificate`** → slug `energy-certificate` (Plain Text)
10. **`Rooms`** → slug `rooms` (Number)
11. **`Bathrooms`** → slug `bathrooms` (Number)
12. **`Floor`** → slug `floor` (Plain Text)
13. **`Seller Type`** → slug `seller-type` (Plain Text)
14. **`Seller Name`** → slug `seller` (Plain Text)
15. (opcional) **`Phone 2`** → slug `phone-2` (Plain Text)

Cuando los cree, el código los recoge automáticamente vía
`FIELD_MAP_PATTERNS` en `integrations/webflow_sync.py` — sin redeploy.

---

## Cuando Benedict confirme los campos

Sigue el playbook `docs/post-benedict-checklist.md`. Resumen:

1. Re-correr `python3 scripts/inspect_webflow_schema.py` y commitear el snapshot.
2. Smoke test con `DB_PATH=/tmp/t.db DISPLAY=:1 python3 scraper_engine.py --pages 1 --batch 1` + sync.
3. Inspeccionar el item draft creado en Webflow UI.
4. **Antes de cualquier renombrado de slugs**: generar `reports/redirects_*.csv` con `python3 scripts/migrate_canonical_titles.py` y cargarlo manualmente en Webflow Site Settings → Hosting → Redirects.
5. `python3 scripts/audit_ad_types.py --apply` para corregir clasificaciones venta/alquiler en filas existentes según el nuevo keyword scan.
6. `python3 scripts/migrate_existing_listings.py --apply` para reaplicar todas las reglas a items publicados.

---

## Pendientes con Benedict (no bloquean el inicio)

- Confirmar nivel de precisión geográfica para Tarea 9 fase 2 (Nominatim vs Google Maps).
- Confirmar si quiere también `* ` y `- ` como bullets en descripciones (hoy solo `•`).
- Confirmar si el cap de 20 imágenes por listing es suficiente (algunos tienen 30+).

---

## Mensaje para el siguiente chat

```
Hola Claude. Continuación de la iteración 2026-05 del scraper Milanuncios.

CONTEXTO RÁPIDO:
- Repo: /home/john/Desktop/Projects/Nabes/milanuncions_scraper
- main está limpio, 11 commits con la iteración terminada (201 tests passing).
- Documentación completa en docs/iteration-2026-05-feedback.md,
  docs/verification-report-2026-05.md, docs/post-benedict-checklist.md,
  docs/handoff-next-chat.md (este archivo lo lees para context completo).

ESTADO:
- 9 tareas de feedback de Benedict implementadas excepto 7 y 8, que
  están bloqueadas porque faltan campos en Webflow CMS:
    * source-url (Plain Text)  — desbloquea Tareas 6 + 7
    * phone (Plain Text)       — desbloquea Tarea 8
  El código ya está listo: cuando los campos existan, FIELD_MAP_PATTERNS
  los recoge sin redeploy.

- Detección venta/alquiler tiene 4 capas, la última es keyword scan
  sobre título+descripción (palabras clave: venta/vendo/se vende/
  traspaso vs alquiler/alquila/arriendo/renta/€/m²/€/mes/mensual).

- Hay 3 scripts de migración listos pero sin ejecutar todavía:
    * scripts/audit_ad_types.py
    * scripts/migrate_canonical_titles.py
    * scripts/migrate_existing_listings.py

QUÉ HACER AHORA (cuando aplique):
1. Si Benedict ya creó los campos en Webflow: seguir
   docs/post-benedict-checklist.md paso a paso.
2. Si todavía no: empezar por leer docs/iteration-2026-05-feedback.md
   para entender qué cambió, y trabajar sobre las pendientes:
   geocoding fase 2, bullets adicionales en descripción, o lo que
   pida Alejandro/Benedict.

NORMAS DE TRABAJO:
- Inglés en código/commits/docs (Rule 1 AGENTS.md).
- No commit sin confirmación explícita.
- Tests primero, simplicidad sobre abstracción.
- Si una decisión es arquitectónica (libs/schemas/contracts), validar
  con Codex antes de AskUserQuestion (Rule 2).
```
