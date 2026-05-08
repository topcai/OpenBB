"""Biztoc news client (via RapidAPI).

Biztoc aggregates ~250 financial news outlets with high refresh rate.
Free RapidAPI tier is small (~50 req/month) but it's an aggressive aggregator
so even 1 call/refresh covers a lot of headlines.

Endpoint: GET https://biztoc.p.rapidapi.com/news/latest
Headers:  X-RapidAPI-Key, X-RapidAPI-Host
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from strategy_app.backend.schemas import NewsItem

logger = logging.getLogger(__name__)

_API_URL = "https://biztoc.p.rapidapi.com/news/latest"
DEFAULT_TIMEOUT = 12.0


async def fetch_biztoc_news(
    api_key: str,
    *,
    limit: int = 50,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[NewsItem]:
    """Pull latest Biztoc news. Returns [] on any failure."""

    if not api_key:
        return []

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "biztoc.p.rapidapi.com",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(_API_URL, headers=headers)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("Biztoc fetch failed: %s", e)
        return []

    if not isinstance(raw, list):
        if isinstance(raw, dict) and "message" in raw:
            logger.warning("Biztoc API error: %s", raw["message"])
        else:
            logger.warning("Unexpected Biztoc payload: %r", str(raw)[:200])
        return []

    items: list[NewsItem] = []
    for row in raw[:limit]:
        try:
            items.append(_parse(row))
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed Biztoc row: %s", e)
    return items


def _parse(row: dict[str, Any]) -> NewsItem:
    title = (row.get("title") or "").strip()
    url = row.get("url") or row.get("link") or ""
    nid = hashlib.sha1(
        f"biztoc:{row.get('id') or row.get('uid') or url}:{title}".encode()
    ).hexdigest()[:16]

    published = row.get("published") or row.get("created")
    published_at = _parse_dt(published)

    # Tags can be inferred but Biztoc rarely tags tickers reliably; leave empty.
    tags = row.get("tags") or []
    if isinstance(tags, list):
        raw_symbols = [
            str(t).upper() for t in tags if isinstance(t, str) and t.isalpha()
        ][:5]
    else:
        raw_symbols = []

    image_url = None
    img = row.get("img") or row.get("images")
    if isinstance(img, dict):
        image_url = img.get("o") or img.get("s") or img.get("url")
    elif isinstance(img, list) and img:
        first = img[0]
        if isinstance(first, dict):
            image_url = first.get("o") or first.get("s") or first.get("url")
        elif isinstance(first, str):
            image_url = first
    elif isinstance(img, str):
        image_url = img

    body = row.get("body") or row.get("body_preview")
    if body and isinstance(body, str) and len(body) > 600:
        body = body[:600].rstrip() + "…"

    return NewsItem(
        id=nid,
        source=f"biztoc:{row.get('site') or row.get('domain') or 'news'}",
        title=title,
        summary=body or None,
        url=url,
        published_at=published_at,
        raw_symbols=raw_symbols,
        image_url=image_url,
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
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except Exception:  # noqa: BLE001
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
