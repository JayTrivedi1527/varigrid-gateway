"""Local SQLite ring buffer for offline replay.

When a push fails (network down, Varigrid blip, etc.) the reading
goes here. A replay task drains it as soon as connectivity returns.

Capped — old rows roll off when we hit `max_rows` so we never fill
the disk on a long outage. 100k rows ≈ 50 sensors at 30s for 17 hours.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterable
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS buffered_readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id   TEXT    NOT NULL,
    ts          TEXT    NOT NULL,        -- ISO 8601 UTC
    value       REAL    NOT NULL,
    quality     TEXT    NOT NULL DEFAULT 'good',
    queued_at   REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_buffered_queued ON buffered_readings(queued_at);
"""


class Buffer:
    def __init__(self, path: str, max_rows: int = 100_000):
        self.path     = path
        self.max_rows = max_rows
        self._lock    = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        # check_same_thread=False so the asyncio loop can use it from
        # any executor thread; the lock guarantees no concurrent writes.
        conn = sqlite3.connect(self.path, check_same_thread=False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def append(self, sensor_id: str, ts: str, value: float, quality: str = "good") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO buffered_readings (sensor_id, ts, value, quality) VALUES (?, ?, ?, ?)",
                (sensor_id, ts, value, quality),
            )
            # Trim to max_rows (oldest first)
            count = c.execute("SELECT COUNT(*) FROM buffered_readings").fetchone()[0]
            if count > self.max_rows:
                excess = count - self.max_rows
                c.execute(
                    "DELETE FROM buffered_readings WHERE id IN (SELECT id FROM buffered_readings ORDER BY id LIMIT ?)",
                    (excess,),
                )

    def take(self, batch_size: int) -> list[tuple[int, str, str, float, str]]:
        """Returns up to batch_size rows: (id, sensor_id, ts, value, quality).
        Caller must call drop(ids) once successfully pushed."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, sensor_id, ts, value, quality FROM buffered_readings ORDER BY id LIMIT ?",
                (batch_size,),
            ).fetchall()
        return rows

    def drop(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self._conn() as c:
            c.execute(f"DELETE FROM buffered_readings WHERE id IN ({placeholders})", ids)

    def size(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM buffered_readings").fetchone()[0]
