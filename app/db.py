"""Short-lived SQLite connections and consecutive, transactional migrations."""

import sqlite3
import logging
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.constants import MIGRATIONS_DIR

logger = logging.getLogger(__name__)
DATA_LOCK = RLock()


def connect(data_dir: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(data_dir / "app.db", timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(data_dir: Path, target_version: int | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for folder in ("documents", "backups"):
        (data_dir / folder).mkdir(exist_ok=True)
    migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [int(path.name.split("_")[0]) for path in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise RuntimeError("Database migrations must be numbered consecutively.")
    target = len(migrations) if target_version is None else target_version
    if target < 0 or target > len(migrations):
        raise ValueError("Unknown target database version.")
    with closing(connect(data_dir)) as connection:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > target:
            raise RuntimeError("The database is newer than this app. Do not downgrade it.")
        if current == target:
            return
        existing = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        if existing or current:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = data_dir / "backups" / f"pre-migration-{stamp}-v{current}.db"
            with closing(sqlite3.connect(backup_path)) as backup:
                connection.backup(backup)
        # executescript otherwise commits implicitly: explicitly wrap the entire batch.
        sql = "\n".join(path.read_text(encoding="utf-8") for path in migrations[current:target])
        try:
            connection.executescript(
                f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {target};\nCOMMIT;"
            )
        except Exception:
            connection.rollback()
            raise


def check_search(data_dir: Path) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat()
    with closing(connect(data_dir)) as connection:
        try:
            connection.execute("CREATE VIRTUAL TABLE temp.search_probe USING fts5(content)")
            connection.execute("INSERT INTO search_probe VALUES ('search capability check')")
            match = connection.execute(
                "SELECT count(*) FROM search_probe WHERE search_probe MATCH 'capability'"
            ).fetchone()[0]
            if match != 1:
                raise sqlite3.DatabaseError("The FTS5 phrase check returned an unexpected result.")
            available, detail = True, f"FTS5 query passed with SQLite {sqlite3.sqlite_version}."
        except sqlite3.Error as error:
            logger.exception("Search capability check failed.")
            available, detail = False, f"Search check failed: {error}"
        with connection:
            connection.execute(
                "INSERT INTO checks(name, available, checked_at, detail) VALUES ('fts5', ?, ?, ?)",
                (int(available), checked_at, detail),
            )
    return {"available": available, "checked_at": checked_at, "detail": detail}
