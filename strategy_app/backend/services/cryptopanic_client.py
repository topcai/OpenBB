"""Lightweight async HTTP client for the CryptoPanic public API.

Docs: https://cryptopanic.com/developers/api/

We only use the free `/api/v1/posts/` endpoint with `public=true`, which
returns ~20 most recent posts per call. No pagination needed for the demo.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx

from strategy_app.backend.schemas import NewsItem

logger = logging.getLogger(__name__)

API_URL = "https://cryptopanic.com/api/v1/posts/"
DEFAULT_TIMEOUT = 10.0


async def fetch_cryptopanic_posts(
    auth_token: str,
    *,
    limit: int = 30,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[NewsItem]:
    """Pull the most recent crypto-news posts.

    Returns an empty list (NEVER raises) on any failure, so the upstream
    aggregator can degrade gracefully when CryptoPanic is down or the token
    is missing.
    """

    if not auth_token:
        logger.info("CryptoPanic auth_token not configured, skipping.")
        return []

    params = {
        "auth_token": auth_token,
        "public": "true",
        "kind": "news",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(API_URL, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001 — degrade gracefully
        logger.warning("CryptoPanic fetch failed: %s", e)
        return []

    items: list[NewsItem] = []
    for raw in (data.get("results") or [])[:limit]:
        try:
            items.append(_parse_post(raw))
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed CryptoPanic post: %s", e)
            continue
    return items


def _parse_post(raw: dict[str, Any]) -> NewsItem:
    """Convert a single CryptoPanic post dict into our normalised NewsItem."""

    url = raw.get("url") or raw.get("source", {}).get("url") or ""
    title = raw.get("title") or ""
    nid = hashlib.sha1(f"cryptopanic:{url}:{title}".encode()).hexdigest()[:16]

    published_str = raw.get("published_at") or raw.get("created_at")
    if published_str:
        # CryptoPanic uses 'Z'-suffixed ISO format
        published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
    else:
        published_at = datetime.utcnow()

    raw_symbols = [
        c.get("code", "").upper()
        for c in (raw.get("currencies") or [])
        if c.get("code")
    ]

    return NewsItem(
        id=nid,
        source="cryptopanic",
        title=title,
        summary=None,                         # free tier doesn't return body
        url=url,
        published_at=published_at,
        raw_symbols=raw_symbols,
        image_url=None,
    )
