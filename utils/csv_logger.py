import csv
import os
from datetime import datetime


class CSVLogger:
    COLUMNS = [
        "listing_id", "url", "title", "surface_m2",
        "price", "province", "status", "timestamp",
    ]

    def __init__(self):
        os.makedirs("logs", exist_ok=True)
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = f"logs/scraper_{run_ts}.csv"
        self._fh = open(self.filepath, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.COLUMNS)
        self._writer.writeheader()
        self._fh.flush()

    def log(
        self,
        listing_id: str,
        url: str,
        title: str,
        surface_m2,
        price: str,
        province: str,
        status: str,
    ) -> None:
        self._writer.writerow({
            "listing_id": listing_id or "",
            "url":        url or "",
            "title":      (title or "")[:120],
            "surface_m2": surface_m2 or "",
            "price":      price or "",
            "province":   province or "",
            "status":     status,
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
        })
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()
