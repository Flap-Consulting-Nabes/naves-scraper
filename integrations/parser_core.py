"""Core parsing primitives shared by every other parser submodule.

Codex review R1: extracted from `integrations/parser.py` so the JSON
extraction layer lives on its own. Re-exported from
`integrations.parser` for backward compatibility.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_initial_props_json(html: str) -> dict:
    """Extract and parse the JSON embedded in `window.__INITIAL_PROPS__`.

    Returns the full dict or `{}` when the marker isn't found (typically
    because the page was blocked or the layout changed).
    """
    m = re.search(
        r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\((.+?)\);\s*</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return {}
    try:
        return json.loads(json.loads(m.group(1)))
    except Exception as e:
        logger.warning(f"Error parseando __INITIAL_PROPS__: {e}")
        return {}


def _get_attribute_value(attributes: list, attr_type: str) -> str | None:
    """Look up an attribute by `type` in MilAnuncios's `attributes` list."""
    for attr in attributes:
        if attr.get("type") == attr_type:
            return attr.get("value")
    return None
