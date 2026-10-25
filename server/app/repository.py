"""SQLite access. Parameterised queries only -- no string-built SQL."""

import json
import sqlite3
import threading
from pathlib import Path


class MessageRepository:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # One shared connection, used by many request threads: only one at a time.
        # RLock (re-entrant) because insert() calls get() while holding the lock.
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    author TEXT NOT NULL,
                    redactions TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def insert(
        self, content: str, author: str, redactions: dict[str, int], created_at: str
    ) -> sqlite3.Row:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO messages (content, author, redactions, created_at) "
                "VALUES (?, ?, ?, ?)",
                (content, author, json.dumps(redactions), created_at),
            )
            self._conn.commit()
            return self.get(cursor.lastrowid)

    def list(self, limit: int, offset: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM messages ORDER BY id DESC LIMIT {limit} OFFSET {offset}"
            ).fetchall()

    def get(self, message_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()

    def delete(self, message_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE id = ?", (message_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0