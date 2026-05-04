"""
Audit ad_type for every listing already in the local DB.

Iteración 2026-05-04. Re-runs `parse_ad_type` over every row using the
new four-layer detection (categories → sellType → URL → body keyword
scan) and compares against the value currently stored in `listings.ad_type`.

Three modes of disagreement get reported:

  - DB has venta but new scan votes alquiler (or vice-versa)
  - DB is NULL and new scan can decide
  - New scan tied (None) but DB had a value — flagged for review

Usage:
    python scripts/audit_ad_types.py                      # dry-run report only
    python scripts/audit_ad_types.py --apply              # write corrections to DB
    python scripts/audit_ad_types.py --listing-id 123456  # single row
    python scripts/audit_ad_types.py --csv reports/audit.csv

Output: reports/audit_ad_types_{ts}.csv with columns
listing_id, url, current_ad_type, proposed_ad_type, reason, decision.
"""
import argparse
import csv
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db import init_db
from integrations.parser import (
    _scan_text_for_ad_type,
    parse_ad_type,
    parse_initial_props_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("audit_ad_types")

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="Write the proposed ad_type back to the DB.")
    p.add_argument("--listing-id", type=str, default=None,
                   help="Audit only this listing_id.")
    p.add_argument("--csv", type=Path, default=None,
                   help="Override the default report path.")
    return p.parse_args()


def _ad_json_from_html(raw_html: str | None) -> dict | None:
    if not raw_html:
        return None
    try:
        props = parse_initial_props_json(raw_html)
    except Exception:
        return None
    return (props or {}).get("ad")


def audit_row(row: dict) -> dict:
    """Return an audit dict per row (no DB writes)."""
    ad_json = _ad_json_from_html(row.get("raw_html"))
    title = row.get("original_title") or row.get("title")
    description = row.get("description")
    proposed = parse_ad_type(
        row.get("url") or "",
        ad_json=ad_json,
        title=title,
        description=description,
    )
    venta_hits, alquiler_hits = _scan_text_for_ad_type(
        " ".join(filter(None, [title, description]))
    )

    current = row.get("ad_type")
    if current == proposed:
        decision = "noop"
    elif current is None and proposed is not None:
        decision = "fill_null"
    elif proposed is None and current is not None:
        decision = "review_keep"  # body tied, keep DB value
    else:
        decision = "flip"  # current and proposed disagree

    return {
        "listing_id": row["listing_id"],
        "url": row.get("url", ""),
        "current_ad_type": current or "",
        "proposed_ad_type": proposed or "",
        "venta_hits": venta_hits,
        "alquiler_hits": alquiler_hits,
        "decision": decision,
    }


def write_report(audits: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "listing_id", "url", "current_ad_type", "proposed_ad_type",
        "venta_hits", "alquiler_hits", "decision",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(audits)


def main() -> int:
    args = parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = args.csv or REPORT_DIR / f"audit_ad_types_{ts}.csv"

    conn = init_db(DB_PATH)
    try:
        sql = "SELECT * FROM listings"
        params: tuple = ()
        if args.listing_id:
            sql += " WHERE listing_id = ?"
            params = (args.listing_id,)
        sql += " ORDER BY scraped_at ASC"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        logger.info("[audit_ad_types] %d rows scanned", len(rows))

        audits = [audit_row(r) for r in rows]
        flips = [a for a in audits if a["decision"] == "flip"]
        fills = [a for a in audits if a["decision"] == "fill_null"]
        reviews = [a for a in audits if a["decision"] == "review_keep"]

        logger.info(
            "[audit_ad_types] noop=%d  fill_null=%d  flip=%d  review=%d",
            sum(1 for a in audits if a["decision"] == "noop"),
            len(fills), len(flips), len(reviews),
        )

        for a in flips:
            logger.warning(
                "[FLIP] %s: %s → %s  (hits venta=%d alquiler=%d)  %s",
                a["listing_id"], a["current_ad_type"],
                a["proposed_ad_type"],
                a["venta_hits"], a["alquiler_hits"], a["url"],
            )

        if args.apply and (flips or fills):
            for a in flips + fills:
                conn.execute(
                    "UPDATE listings SET ad_type = ? WHERE listing_id = ?",
                    (a["proposed_ad_type"], a["listing_id"]),
                )
            conn.commit()
            logger.info(
                "[audit_ad_types] DB updated: %d rows", len(flips) + len(fills),
            )

        write_report(audits, csv_path)
        logger.info("[audit_ad_types] report: %s", csv_path)
        if not args.apply and (flips or fills):
            logger.info("Run with --apply to write corrections.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
