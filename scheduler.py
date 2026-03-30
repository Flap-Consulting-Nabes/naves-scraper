"""
Scheduler APScheduler para ejecuciones automáticas del scraper.

Persiste el job en scheduler.db (SQLite) para sobrevivir reinicios.
La expresión cron se lee de config.json en cada arranque.
"""
import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from api.dependencies import get_config

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {
            "default": SQLAlchemyJobStore(url="sqlite:///scheduler.db")
        }
        _scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone="Europe/Madrid",
            job_defaults={"coalesce": True, "max_instances": 1},
        )
        _register_jobs(_scheduler)
    return _scheduler


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    cfg = get_config()
    cron_expr = cfg.get("cron_expr", "0 6 * * *")
    max_pages = cfg.get("max_pages", 0)

    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone="Europe/Madrid")
    except Exception as e:
        logger.warning("[Scheduler] Expresión cron inválida '%s': %s — usando default 6am", cron_expr, e)
        trigger = CronTrigger(hour=6, minute=0, timezone="Europe/Madrid")

    scheduler.add_job(
        func=_scheduled_scrape,
        trigger=trigger,
        id="scraper_cron",
        name="Scraper programado",
        replace_existing=True,
        kwargs={"max_pages": max_pages},
    )
    logger.info("[Scheduler] Job registrado: cron='%s', max_pages=%s", cron_expr, max_pages)


async def _scheduled_scrape(max_pages: int = 0) -> None:
    """Función ejecutada por APScheduler en cada disparo del cron."""
    from api.scraper_job import launch_scraper
    logger.info("[Scheduler] Iniciando scrape automático (max_pages=%s)", max_pages)
    launched = await launch_scraper(max_pages=max_pages, dry_run=False, reset=False)
    if not launched:
        logger.warning("[Scheduler] No se pudo iniciar: el scraper ya está en ejecución")
