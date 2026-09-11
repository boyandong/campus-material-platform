from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import PackageStatus, utc_now


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS packages (
                    id TEXT PRIMARY KEY,
                    package_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS package_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(package_id) REFERENCES packages(id)
                );
                CREATE INDEX IF NOT EXISTS idx_package_events_package_time
                    ON package_events(package_id, created_at);
                """
            )
            active = (
                PackageStatus.COPYING_INPUTS.value,
                PackageStatus.PARSING_QUESTIONNAIRE.value,
                PackageStatus.SCANNING_FILES.value,
                PackageStatus.COMPARING.value,
                PackageStatus.BUILDING_PRODUCT.value,
                PackageStatus.GENERATING_CARD.value,
                PackageStatus.QUALITY_CHECK.value,
                PackageStatus.PRIVACY_SCAN.value,
                PackageStatus.GENERATING_PREVIEWS.value,
                PackageStatus.PRICING.value,
            )
            placeholders = ",".join("?" for _ in active)
            db.execute(
                f"UPDATE packages SET status=?, stage=?, updated_at=? WHERE status IN ({placeholders})",
                (
                    PackageStatus.INTERRUPTED.value,
                    "interrupted_on_restart",
                    utc_now(),
                    *active,
                ),
            )

    def create_package(self, package_id: str, package_path: Path) -> None:
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO packages(id, package_path, status, stage, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (
                    package_id,
                    str(package_path),
                    PackageStatus.CREATED.value,
                    "created",
                    now,
                    now,
                ),
            )
        self.add_event(package_id, "package_created")

    def update_package(
        self,
        package_id: str,
        status: PackageStatus,
        stage: str,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE packages SET status=?, stage=?, error=?, updated_at=? WHERE id=?",
                (status.value, stage, error, utc_now(), package_id),
            )
        self.add_event(
            package_id,
            "stage_changed",
            {"status": status.value, "stage": stage, "error": error},
        )

    def get_package(self, package_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM packages WHERE id=?", (package_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_packages(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM packages ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_event(
        self, package_id: str, event_name: str, details: dict[str, Any] | None = None
    ) -> None:
        safe_details = {
            k: v
            for k, v in (details or {}).items()
            if k not in {"contact", "questionnaire_text", "api_key"}
        }
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO package_events(package_id, event_name, details_json, created_at) VALUES(?,?,?,?)",
                (
                    package_id,
                    event_name,
                    json.dumps(safe_details, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def list_events(self, package_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT event_name, details_json, created_at FROM package_events WHERE package_id=? ORDER BY id",
                (package_id,),
            ).fetchall()
        return [
            {
                "event_name": row["event_name"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
