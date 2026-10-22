"""Audit log: one line per security-relevant event, written to stdout.

Deletes are permanent, so the audit log keeps the record of *what happened*
(who created or deleted which message, failed logins) without keeping the data.
Written to stdout (`docker compose logs app`) and, when AUDIT_LOG_FILE is set,
also to that file. docker-compose.yml sets it to logs/audit.log on a volume, so
the trail survives restarts, rebuilds and `docker compose down`. The file
rotates at 5 MB, keeping 3 old copies.

Never logged: message content (even redacted), passwords, tokens or hashes.

    2026-10-22T18:00:05Z AUDIT message.deleted id=42 by=alice
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import time

_logger = logging.getLogger("audit")
if not _logger.handlers:                         # configure once, even if imported twice
    _formatter = logging.Formatter("%(asctime)s AUDIT %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    _formatter.converter = time.gmtime           # timestamps in UTC
    _handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    _log_file = os.environ.get("AUDIT_LOG_FILE")
    if _log_file:                                # persistent copy, e.g. logs/audit.log on a volume
        os.makedirs(os.path.dirname(_log_file) or ".", exist_ok=True)
        _handlers.append(
            logging.handlers.RotatingFileHandler(
                _log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
        )
    for _handler in _handlers:
        _handler.setFormatter(_formatter)
        _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False                    # don't duplicate into uvicorn's logs

# Anything that isn't a safe, printable character becomes "_", so values taken
# from the request (a URL path, an IP) can't break a line or fake another entry.
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:/=,@-]")


def format_event(event: str, **fields: object) -> str:
    """'message.deleted', id=42, by='alice'  ->  'message.deleted id=42 by=alice'"""
    parts = [event] + [f"{key}={_UNSAFE.sub('_', str(value))}" for key, value in fields.items()]
    return " ".join(parts)


def audit(event: str, **fields: object) -> None:
    _logger.info(format_event(event, **fields))


def redaction_summary(counts: dict[str, int]) -> str:
    """{'EMAIL': 1, 'IPV4': 2} -> 'EMAIL=1,IPV4=2'; {} -> 'none'"""
    return ",".join(f"{kind}={n}" for kind, n in sorted(counts.items())) or "none"
