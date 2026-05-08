"""Tiingo news client.

Tiingo's news endpoint covers stocks (US + international) and crypto with
real-time updates. Free tier allows 500 req/h with full news access.

Docs: https://www.tiingo.com/documentation/news
Endpoint: GET https://api.tiingo.com/tiingo/news?token=...&limit=N
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from strategy_app.backend.schemas import NewsItem

logger = logging.getLogger(__name__)

_API_URL = "https://api.tiingo.com/tiingo/news"
DEFAULT_TIMEOUT = 12.0


async def fetch_tiingo_news(
    token: str,
    *,
    limit: int = 50,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[NewsItem]:
    """Pull recent Tiingo news. Returns [] on any failure."""

    if not token:
        return []

    params = {
        "token": token,
        "limit": min(limit, 1000),
        "sortBy": "publishedDate",
    }
    headers = {"Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(_API_URL, params=params, headers=headers)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("Tiingo news fetch failed: %s", e)
        return []

    if not isinstance(raw, list):
        logger.warning("Unexpected Tiingo payload: %r", str(raw)[:200])
        return []

    items: list[NewsItem] = []
    for row in raw[:limit]:
        try:
            items.append(_parse(row))
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed Tiingo row: %s", e)
    return items


def _parse(row: dict[str, Any]) -> NewsItem:
    title = row.get("title") or ""
    url = row.get("url") or ""
    nid = hashlib.sha1(f"tiingo:{row.get('id') or url}:{title}".encode()).hexdigest()[:16]

    published_str = row.get("publishedDate") or row.get("crawlDate")
    published_at = _parse_dt(published_str)

    # Tickers: list[str] or comma-string. Tiingo uses lowercase.
    tickers_field = row.get("tickers") or []
    if isinstance(tickers_field, str):
        raw_symbols = [t.strip().upper() for t in tickers_field.split(",") if t.strip()]
    elif isinstance(tickers_field, list):
        raw_symbols = [str(t).upper() for t in tickers_field if t]
    else:
        raw_symbols = []
    raw_symbols = raw_symbols[:5]

    description = row.get("description") or ""
    if isinstance(description, str) and len(description) > 600:
        description = description[:600].rstrip() + "…"

    return NewsItem(
        id=nid,
        source=f"tiingo:{row.get('source') or 'news'}",
        title=title.strip(),
        summary=description or None,
        url=url,
        published_at=published_at,
        raw_symbols=raw_symbols,
        image_url=None,    # tiingo doesn't return image URLs
    )


def _parse_dt(s: Any) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    if isinstance(s, str):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:  # noqa: BLE001
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
