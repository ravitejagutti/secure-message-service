"""Business logic. The only path to the database: every write goes through
redact() first, so the repository never sees raw content."""

import json
import sqlite3
from datetime import datetime, timezone

from .redaction import redact
from .repository import MessageRepository


class MessageService:
    def __init__(self, repository: MessageRepository):
        self._repository = repository

    def create(self, content: str, author: str) -> dict:
        result = redact(content)
        created_at = datetime.now(timezone.utc).isoformat()
        row = self._repository.insert(result.text, author, result.counts, created_at)
        return _row_to_dict(row)

    def list(self, limit: int, offset: int) -> list[dict]:
        rows = self._repository.list(limit, offset)
        return [_row_to_dict(row) for row in rows]

    def get(self, message_id: int) -> dict | None:
        row = self._repository.get(message_id)
        return _row_to_dict(row) if row else None

    def delete(self, message_id: int) -> bool:
        return self._repository.delete(message_id)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "content": row["content"],
        "author": row["author"],
        "created_at": row["created_at"],
        "redactions": json.loads(row["redactions"]),
    }
