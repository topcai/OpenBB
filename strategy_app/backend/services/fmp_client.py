"""Lightweight async HTTP client for the FinancialModelingPrep news API.

Avoids pulling in the full OpenBB provider stack (which would require
installing ~50 sub-packages). Uses the free-tier ``/stable/fmp-articles``
endpoint (the only news endpoint not behind a paywall on the free plan).

Docs: https://site.financialmodelingprep.com/developer/docs
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from strategy_app.backend.schemas import NewsItem

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
_API_URL = "https://financialmodelingprep.com/stable/fmp-articles"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


async def fetch_fmp_news(
    api_key: str,
    *,
    limit: int = 30,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[NewsItem]:
    """Pull recent FMP-authored articles. Returns [] on any failure."""

    if not api_key:
        return []

    # FMP returns up to 250 per page; the free-tier articles list is small,
    # so 1 page suffices for our demo limits.
    params = {"page": 0, "limit": min(limit, 50), "apikey": api_key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(_API_URL, params=params)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("FMP fetch failed: %s", e)
        return []

    if not isinstance(raw, list):
        logger.warning("Unexpected FMP payload: %r", str(raw)[:200])
        return []

    items: list[NewsItem] = []
    for row in raw[:limit]:
        try:
            items.append(_parse_row(row))
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed FMP row: %s", e)
    return items


# ---------------------------------------------------------------------------

def _parse_row(row: dict[str, Any]) -> NewsItem:
    url = row.get("link") or row.get("url") or ""
    title = row.get("title") or ""
    nid = hashlib.sha1(f"fmp:{url}:{title}".encode()).hexdigest()[:16]

    published_str = row.get("date") or row.get("publishedDate")
    published_at = _parse_dt(published_str)

    # Tickers are like "NYSE:PLNT,NASDAQ:AAPL". Strip exchange prefix.
    raw_ticker_field = row.get("tickers") or row.get("symbol") or ""
    if isinstance(raw_ticker_field, str):
        tokens = [t.strip() for t in raw_ticker_field.split(",") if t.strip()]
    elif isinstance(raw_ticker_field, list):
        tokens = [str(t).strip() for t in raw_ticker_field if t]
    else:
        tokens = []
    raw_symbols: list[str] = []
    for t in tokens:
        if ":" in t:
            t = t.split(":", 1)[1]
        t = t.upper().strip()
        if t:
            raw_symbols.append(t)

    image_url = row.get("image") or row.get("imageUrl")
    if isinstance(image_url, list) and image_url:
        image_url = image_url[0]
    if image_url and not isinstance(image_url, str):
        image_url = None

    summary_html = row.get("content") or row.get("text") or row.get("excerpt")
    summary = _html_to_text(summary_html) if summary_html else None

    return NewsItem(
        id=nid,
        source="fmp",
        title=title,
        summary=summary,
        url=url,
        published_at=published_at,
        raw_symbols=raw_symbols,
        image_url=image_url,
    )


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _html_to_text(html: str) -> str:
    """Strip tags + collapse whitespace + truncate. Cheap & no extra deps."""
    text = _HTML_TAG_RE.sub(" ", html or "")
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > 600:
        text = text[:600].rstrip() + "…"
    return text
