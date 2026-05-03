"""Convert raw scraped description text into Webflow RichText-compatible HTML.

Iteración 2026-05 (Tarea 4):
The Webflow `description` field (slug `funeral-home-biography`) is RichText.
The scraper currently sends plain text with embedded `\n` characters and
inline bullets `•` separated by spaces, which renders as a single unbroken
paragraph in the frontend (see Benedict's screenshot).

This formatter:
  1. Splits paragraphs on blank lines (``\n\n+``).
  2. Within each paragraph, converts inline bullets `•` into a `<ul><li>`
     list when at least 2 bullets are detected (avoids false positives on
     stray Unicode bullets).
  3. Preserves single newlines inside a paragraph as `<br>`.
  4. HTML-escapes the original text so user content cannot inject markup.

The output is a string of HTML safe to assign to the RichText field.
"""
from __future__ import annotations

import html
import re

# At least two bullet markers in the same paragraph trigger list rendering.
_BULLET_RE = re.compile(r"\s*•\s*")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_MIN_BULLETS_FOR_LIST = 2


def format_description_html(raw: str | None) -> str | None:
    """Return RichText-compatible HTML for `raw`, or None if input is empty."""
    if not raw:
        return None

    cleaned = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return None

    paragraphs = _PARAGRAPH_SPLIT_RE.split(cleaned)
    rendered: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        rendered.append(_render_paragraph(para))

    return "".join(rendered)


def _render_paragraph(para: str) -> str:
    """Render a single paragraph block — either as <ul> or as <p>."""
    # Count actual bullet markers; split produces N+1 chunks for N bullets.
    bullet_count = para.count("•")
    if bullet_count < _MIN_BULLETS_FOR_LIST:
        return f"<p>{_inline_breaks(para)}</p>"

    prefix, _, rest = para.partition("•")
    prefix = prefix.strip()
    # `rest` starts immediately after the first bullet marker; split it on
    # subsequent bullets to recover only the bullet contents.
    bullets = [b.strip() for b in _BULLET_RE.split(rest) if b.strip()]
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    head = f"<p>{_inline_breaks(prefix)}</p>" if prefix else ""
    return f"{head}<ul>{items}</ul>"


def _inline_breaks(text: str) -> str:
    """HTML-escape and convert single newlines to <br> within a paragraph."""
    return html.escape(text).replace("\n", "<br>")
