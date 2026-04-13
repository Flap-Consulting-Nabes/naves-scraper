"""
Gestión de checkpoint para reanudar el scraping tras interrupciones.
Guarda el estado en checkpoint.json.
"""
import json
import logging
import os
from pathlib import Path

CHECKPOINT_FILE = str(Path(__file__).parent / "checkpoint.json")

logger = logging.getLogger(__name__)


def load_checkpoint() -> dict:
    """Carga el checkpoint existente o devuelve estado inicial."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_page = int(data.get("last_page", 1))
                last_listing_id = data.get("last_listing_id")
                if not isinstance(last_listing_id, (str, type(None))):
                    last_listing_id = None
                data = {"last_page": max(1, last_page), "last_listing_id": last_listing_id}
                logger.info(f"Checkpoint cargado: página {data['last_page']}, último ID {data['last_listing_id']}")
                return data
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            logger.warning(f"No se pudo leer checkpoint ({e}), empezando desde el inicio.")
    return {"last_page": 1, "last_listing_id": None}


def save_checkpoint(page: int, listing_id: str | None) -> None:
    """Persiste el progreso actual."""
    data = {"last_page": page, "last_listing_id": listing_id}
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Checkpoint guardado: página {page}, ID {listing_id}")
    except OSError as e:
        logger.error(f"Error guardando checkpoint: {e}")


def reset_checkpoint() -> None:
    """Elimina el checkpoint para forzar un scraping completo desde cero."""
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        logger.info("Checkpoint eliminado. Se empezará desde el inicio.")
