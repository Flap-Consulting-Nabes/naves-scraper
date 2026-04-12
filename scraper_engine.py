"""
Orquestador principal del scraper de Naves Industriales en MilAnuncios.

Uso:
    python scraper_engine.py                  # incremental (usa checkpoint)
    python scraper_engine.py --pages 2        # limitar a N páginas
    python scraper_engine.py --pages 1 --dry-run  # sin guardar en BD
    python scraper_engine.py --reset          # borrar checkpoint y empezar desde 0
"""
import argparse
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv
load_dotenv()

from checkpoint_manager import load_checkpoint, save_checkpoint, reset_checkpoint
from db import init_db, listing_exists, insert_listing, count_listings
from integrations.milanuncios import (
    scrape_search_page,
    scrape_listing,
    close_browser,
    start_keepalive,
    ScrapeBanException,
    SessionExpiredException,
    ListingNotFoundException,
)
from integrations.parser import parse_listing_id
from utils.csv_logger import CSVLogger
from utils.image_downloader import download_images
from utils.jitter import random_delay
from utils.slugify import generate_unique_slug

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

BAN_COOLDOWNS = [600, 1200, 2400, 3600]   # 10 → 20 → 40 → 60 min
MAX_BAN_RETRIES = 6

_SHUTDOWN = False


def _handle_sigterm(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    logger.info("SIGTERM recibido — cerrando al terminar la iteración actual.")


signal.signal(signal.SIGTERM, _handle_sigterm)

DB_PATH = os.getenv("DB_PATH", "naves.db")
MIN_SURFACE_M2 = int(os.getenv("MIN_SURFACE_M2", "1000"))
MAX_PAGES_ENV = int(os.getenv("MAX_PAGES", "0"))
DOWNLOAD_IMAGES = os.getenv("DOWNLOAD_IMAGES", "true").lower() == "true"


async def run(
    max_pages: int = 0,
    dry_run: bool = False,
    reset: bool = False,
    batch_size: int = 0,
) -> None:
    if reset:
        reset_checkpoint()

    conn = None if dry_run else init_db(DB_PATH)
    if conn:
        logger.info(f"Anuncios en BD al inicio: {count_listings(conn)}")

    csv_log = CSVLogger()
    logger.info(f"CSV log: {csv_log.filepath}")

    # Inicia tarea de fondo que renueva el token anti-bot cada 10 min
    await start_keepalive(interval_seconds=600)

    total_new = 0
    total_skipped = 0
    stop_reason = "fin de páginas"
    effective_max = max_pages or MAX_PAGES_ENV or 999_999
    ban_retries = 0
    outer_while = True

    try:
        while outer_while:
            if _SHUTDOWN:
                stop_reason = "SIGTERM"
                break

            # Re-cargar checkpoint al inicio de cada iteración (permite reanudar tras ban)
            checkpoint = load_checkpoint()
            page_num = checkpoint.get("last_page", 1)
            logger.info(f"Empezando desde página {page_num}")

            hit_ban = False
            consecutive_duplicates = 0

            while page_num <= effective_max:
                if _SHUTDOWN:
                    logger.info("Shutdown solicitado — saliendo del loop principal.")
                    stop_reason = "SIGTERM"
                    outer_while = False
                    break

                logger.info(f"\n{'='*50}")
                logger.info(f"PÁGINA {page_num} / {'∞' if effective_max == 999_999 else effective_max}")
                logger.info(f"{'='*50}")

                # 1. Obtener URLs de esta página
                try:
                    listing_urls = await scrape_search_page(page_num, min_m2=MIN_SURFACE_M2)
                except ScrapeBanException as e:
                    logger.error(f"Ban en búsqueda: {e}")
                    hit_ban = True
                    break
                except SessionExpiredException as e:
                    logger.error(f"Sesión expirada: {e} — ejecuta save_session.py")
                    stop_reason = "sesión expirada"
                    outer_while = False
                    break

                if not listing_urls:
                    logger.info("Sin resultados — fin de paginación.")
                    break

                stop_pagination = False

                # 2. Procesar cada anuncio
                for url in listing_urls:
                    if _SHUTDOWN:
                        logger.info("Shutdown solicitado — saliendo del loop de anuncios.")
                        stop_pagination = True
                        stop_reason = "SIGTERM"
                        outer_while = False
                        break

                    listing_id = parse_listing_id(url)
                    if not listing_id:
                        logger.warning(f"No se pudo extraer ID de: {url}")
                        continue

                    # Deduplicación rápida antes de hacer request
                    if not dry_run and listing_exists(conn, listing_id):
                        consecutive_duplicates += 1
                        logger.info(f"[SKIP] Ya existe: {listing_id} ({consecutive_duplicates}/10 consecutivos)")
                        csv_log.log(listing_id, url, "", "", "", "", "duplicate")
                        total_skipped += 1
                        if consecutive_duplicates >= 10:
                            logger.info("[Stop] Se han encontrado 10 anuncios duplicados seguidos. Fin del scraping incremental.")
                            stop_pagination = True  # modo incremental: parar
                            break
                        continue

                    if dry_run:
                        logger.info(f"[DRY-RUN] {listing_id} — {url}")
                        csv_log.log(listing_id, url, "", "", "", "", "dry_run")
                        random_delay(0.5, 1.0)
                        if batch_size and total_new + 1 > total_new:
                            total_new += 1
                            if total_new >= batch_size:
                                logger.info(f"[Batch] Límite de {batch_size} anuncios alcanzado.")
                                stop_pagination = True
                                stop_reason = f"batch limit ({batch_size})"
                                break
                        continue

                    # Scraping del detalle
                    try:
                        data = await scrape_listing(url)
                    except ListingNotFoundException:
                        logger.warning(f"Anuncio eliminado: {url}")
                        csv_log.log(listing_id, url, "", "", "", "", "not_found")
                        continue
                    except ScrapeBanException as e:
                        logger.error(f"Ban al scrapear anuncio: {e}")
                        csv_log.log(listing_id, url, "", "", "", "", "ban")
                        hit_ban = True
                        stop_pagination = True
                        break
                    except SessionExpiredException as e:
                        logger.error(f"Sesión expirada: {e}")
                        csv_log.log(listing_id, url, "", "", "", "", "session_expired")
                        stop_pagination = True
                        stop_reason = "sesión expirada"
                        outer_while = False
                        break
                    except Exception as e:
                        logger.error(f"Error inesperado en {url}: {e}")
                        csv_log.log(listing_id, url, "", "", "", "", "error")
                        continue

                    # Compute the final unique slug BEFORE insert so the row
                    # is stored with its slug in a single transaction and so
                    # image filenames match the Webflow page slug.
                    data["webflow_slug"] = generate_unique_slug(
                        conn, data.get("title"), listing_id
                    )

                    inserted = insert_listing(conn, data)
                    if inserted:
                        consecutive_duplicates = 0  # resetear contador
                        total_new += 1
                        save_checkpoint(page_num, listing_id)
                        csv_log.log(
                            listing_id, url,
                            data.get("title", ""),
                            data.get("surface_m2", ""),
                            data.get("price", ""),
                            data.get("province", ""),
                            "inserted",
                        )
                        if DOWNLOAD_IMAGES and data.get("photos"):
                            await download_images(
                                conn, listing_id, data["photos"], data["webflow_slug"]
                            )
                        if batch_size and total_new >= batch_size:
                            logger.info(f"[Batch] Límite de {batch_size} anuncios alcanzado.")
                            stop_pagination = True
                            stop_reason = f"batch limit ({batch_size})"
                            break
                    else:
                        consecutive_duplicates += 1
                        total_skipped += 1
                        csv_log.log(listing_id, url, "", "", "", "", "duplicate")
                        if consecutive_duplicates >= 10:
                            logger.info("[Stop] Se han encontrado 10 anuncios duplicados seguidos (post-scrape). Fin del scraping incremental.")
                            stop_pagination = True
                            break

                    random_delay(5.0, 12.0)

                if stop_pagination:
                    logger.info("Paginación detenida.")
                    break

                page_num += 1
                random_delay(3.0, 8.0)

            # --- Fin del loop de páginas ---

            if hit_ban:
                ban_retries += 1
                if ban_retries > MAX_BAN_RETRIES:
                    logger.error(
                        f"[BAN FATAL] Baneado {MAX_BAN_RETRIES} veces. Deteniendo permanentemente."
                    )
                    stop_reason = f"ban fatal ({MAX_BAN_RETRIES} intentos)"
                    break
                cooldown = BAN_COOLDOWNS[min(ban_retries - 1, len(BAN_COOLDOWNS) - 1)]
                logger.warning(
                    f"[BAN] Cerrando browser y esperando {cooldown // 60} min "
                    f"(intento {ban_retries}/{MAX_BAN_RETRIES})..."
                )
                await close_browser()
                await asyncio.sleep(cooldown)
                logger.info("[BAN] Cooldown completo. Reanudando desde checkpoint...")
                # outer_while sigue True → repite desde checkpoint
            else:
                outer_while = False   # fin normal, SIGTERM, sesión expirada, etc.

    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")
    finally:
        await close_browser()
        csv_log.close()
        logger.info(f"CSV log guardado en: {csv_log.filepath}")
        if conn:
            total_final = count_listings(conn)
            conn.close()
            logger.info(f"\n{'='*50}")
            logger.info(f"RESUMEN:")
            logger.info(f"  Nuevos insertados  : {total_new}")
            logger.info(f"  Duplicados omitidos: {total_skipped}")
            logger.info(f"  Total en BD        : {total_final}")
            logger.info(f"  Razón de parada    : {stop_reason}")
            logger.info(f"{'='*50}")


def parse_args():
    parser = argparse.ArgumentParser(description="Scraper Naves Industriales MilAnuncios")
    parser.add_argument("--pages", type=int, default=0, help="Máximo de páginas (0=sin límite)")
    parser.add_argument("--batch", type=int, default=0, help="Máximo de anuncios nuevos por ejecución (0=sin límite)")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra URLs, no guarda en BD")
    parser.add_argument("--reset", action="store_true", help="Borra checkpoint y empieza desde 0")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(
        max_pages=args.pages,
        dry_run=args.dry_run,
        reset=args.reset,
        batch_size=args.batch,
    ))
