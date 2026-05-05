"""4-layer ad-type detection cascade for MilAnuncios listings.

Codex review R1: extracted from the 1000-line `parser.py` so the keyword
tables and the cascade live in their own focused module. Re-exported
from `integrations.parser` so external imports keep working unchanged.

Returns one of:
  - "venta"            single-mode sale
  - "alquiler"         single-mode rent
  - "venta_alquiler"   the listing offers both modalities (added 2026-05-04)
  - None               undetectable (logs WARNING)
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Spanish keyword families ────────────────────────────────────────────────
_VENTA_KEYWORDS = (
    r"\bventa\b", r"\bvende(?:n|se)?\b", r"\bvendo\b", r"\ben\s+venta\b",
    r"\bse\s+vende\b", r"\bventas?\b", r"\bcompra(?:venta)?\b",
    r"\bse\s+traspasa\b", r"\btraspaso\b",
)
_ALQUILER_KEYWORDS = (
    r"\balquiler\b", r"\balquila(?:n|se)?\b", r"\balquilo\b",
    r"\ben\s+alquiler\b", r"\bse\s+alquila\b", r"\barriendo?\b",
    r"\barriend[oa]\b", r"\brenta\b", r"\bse\s+renta\b", r"\brentar\b",
    r"\b\d+(?:[.,]\d+)?\s*€?\s*/\s*m[²2]\b", r"\b€\s*/\s*mes\b",
    r"\bmensuale?s?\b",
)
_VENTA_RE = re.compile("|".join(_VENTA_KEYWORDS), re.IGNORECASE)
_ALQUILER_RE = re.compile("|".join(_ALQUILER_KEYWORDS), re.IGNORECASE)

_DUAL_MIN_HITS = 2  # both venta_hits >= 2 AND alquiler_hits >= 2 → dual offering


def _scan_text_for_ad_type(text: str) -> tuple[int, int]:
    """Return (venta_hits, alquiler_hits) keyword counts for `text`."""
    if not text:
        return 0, 0
    return (
        len(_VENTA_RE.findall(text)),
        len(_ALQUILER_RE.findall(text)),
    )


def parse_ad_type(
    url: str,
    ad_json: dict | None = None,
    title: str | None = None,
    description: str | None = None,
) -> str | None:
    """Detecta si el anuncio es de venta, alquiler o ambos.

    Resolución por capas (la primera que decide gana):

    1. **JSON categories** — `ad_json.categories[].slug/name` con palabra
       `venta` o `alquiler`.
    2. **JSON sellType** — `supply` → venta, `demand` → alquiler.
    3. **URL keyword** — `/venta/` o `/alquiler/` en la URL.
    4. **Keyword scan en título + descripción** (NUEVO 2026-05-04). Cuenta
       hits regex de keywords ES (`venta`, `vendo`, `se vende`, `traspaso`
       vs `alquiler`, `alquila`, `arriendo`, `renta`, `€/m²`, `€/mes`,
       `mensual`). Decide por mayoría; empate → None con WARN.

    Cuando el body tiene >= _DUAL_MIN_HITS hits de **ambas** familias
    (`venta` Y `alquiler`), el anuncio se clasifica como
    `"venta_alquiler"` — modalidad dual — y el caso "URL says X / body
    says both" devuelve la modalidad dual en lugar del hint de URL. Esto
    cubre anuncios donde el anunciante ofrece la misma propiedad bajo
    ambas modalidades (p.ej. la frase "VENTA o ALQUILER" + alquiler
    keywords + venta keywords).

    Esta capa cubre anuncios mal categorizados en la fuente — p.ej. un
    listing publicado bajo `/venta-de-naves/...` pero cuyo cuerpo dice
    "se alquila por 1500 €/mes". Los reportes de bloque se llaman desde
    `audit_ad_types.py` para revisar listings ya scrapeados.

    Emits a WARNING when none of the signals are present.
    """
    if ad_json:
        for cat in ad_json.get("categories", []):
            slug = cat.get("slug", "")
            name = cat.get("name", "").lower()
            if "alquiler" in slug or "alquiler" in name:
                return "alquiler"
            if "venta" in slug or "venta" in name:
                return "venta"
        sell_type = ad_json.get("sellType", "")
        if sell_type == "supply":
            return "venta"
        if sell_type == "demand":
            return "alquiler"

    url_lower = url.lower()
    url_says_alquiler = "alquiler" in url_lower
    url_says_venta = "venta" in url_lower

    body = " ".join(filter(None, [title or "", description or ""]))
    venta_hits, alquiler_hits = _scan_text_for_ad_type(body)

    is_dual = (
        venta_hits >= _DUAL_MIN_HITS and alquiler_hits >= _DUAL_MIN_HITS
    )

    # Cross-check URL hint with the body. If they agree, decide quickly.
    if url_says_alquiler and not url_says_venta:
        if is_dual:
            # WARNING (Codex review B6): dual classification can fire on
            # comparative-pricing venta listings ("precio de venta 900 €/m²;
            # alquiler estimado 6 €/m²"). Surface for audit so genuine
            # mis-classifications are caught.
            logger.warning(
                "[parser] URL says alquiler but body offers both "
                "(%d venta / %d alquiler hits) — using venta_alquiler. url=%s",
                venta_hits, alquiler_hits, url,
            )
            return "venta_alquiler"
        if venta_hits > alquiler_hits and venta_hits >= 2:
            logger.warning(
                "[parser] URL says alquiler but body votes venta "
                "(%d venta vs %d alquiler hits) — using body. url=%s",
                venta_hits, alquiler_hits, url,
            )
            return "venta"
        return "alquiler"

    if url_says_venta and not url_says_alquiler:
        if is_dual:
            # WARNING (Codex review B6): see paired log above.
            logger.warning(
                "[parser] URL says venta but body offers both "
                "(%d venta / %d alquiler hits) — using venta_alquiler. url=%s",
                venta_hits, alquiler_hits, url,
            )
            return "venta_alquiler"
        if alquiler_hits > venta_hits and alquiler_hits >= 2:
            logger.warning(
                "[parser] URL says venta but body votes alquiler "
                "(%d alquiler vs %d venta hits) — using body. url=%s",
                alquiler_hits, venta_hits, url,
            )
            return "alquiler"
        return "venta"

    # No URL hint — rely solely on the body.
    if is_dual:
        return "venta_alquiler"
    if venta_hits or alquiler_hits:
        if venta_hits > alquiler_hits:
            return "venta"
        if alquiler_hits > venta_hits:
            return "alquiler"
        logger.warning(
            "[parser] ad_type tied in body (%d/%d) — leaving None. url=%s",
            venta_hits, alquiler_hits, url,
        )
        return None

    logger.warning("[parser] ad_type undetectable for url=%s", url)
    return None
