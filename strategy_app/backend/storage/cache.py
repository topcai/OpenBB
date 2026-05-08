"""SQLite-backed cache for FeedCard objects.

Single-table TTL cache. Avoid re-running LLM for the same news within the
TTL window so the demo is responsive and cheap.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import FeedCard

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent / "cache.sqlite"
_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_cards (
            news_id    TEXT PRIMARY KEY,
            json_blob  TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        c = _connect()
        try:
            yield c
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(news_id: str) -> Optional[FeedCard]:
    """Return cached card or ``None`` if missing / expired."""
    settings = get_settings()
    ttl_seconds = settings.cache_ttl_minutes * 60

    with _conn() as c:
        row = c.execute(
            "SELECT json_blob, created_at FROM feed_cards WHERE news_id = ?",
            (news_id,),
        ).fetchone()
    if not row:
        return None
    blob, created_at = row
    age = datetime.now(timezone.utc).timestamp() - created_at
    if age > ttl_seconds:
        return None
    try:
        return FeedCard.model_validate_json(blob)
    except Exception as e:  # noqa: BLE001
        logger.warning("Bad cache blob for %s: %s", news_id, e)
        return None


def set(news_id: str, card: FeedCard) -> None:  # noqa: A001 - intentional shadowing
    blob = card.model_dump_json()
    now = datetime.now(timezone.utc).timestamp()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO feed_cards(news_id, json_blob, created_at) "
            "VALUES (?, ?, ?)",
            (news_id, blob, now),
        )
        c.commit()


def clear() -> None:
    with _conn() as c:
        c.execute("DELETE FROM feed_cards")
        c.commit()
