"""Yahoo Finance news aggregator — truly real-time, free, no API key.

Yahoo Finance updates news within minutes of publication. We fan-out across
a curated set of "popular" tickers covering the four asset classes, then
dedupe in the upstream aggregator.

Schema (yfinance ≥ 0.2.40):
    Ticker.news → list[dict] with shape {"id", "content": {...}}
    where content has: title, summary, description (HTML),
    pubDate / displayTime, contentType (STORY|VIDEO),
    thumbnail.{originalUrl,resolutions[].url},
    canonicalUrl.url, clickThroughUrl.url
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from strategy_app.backend.schemas import NewsItem

logger = logging.getLogger(__name__)


# A representative spread across the four markets we support, biased toward
# tickers that have constant news flow. Yahoo will return stories tagged with
# OTHER tickers too, so this set effectively becomes a sampler, not a filter.
_FANOUT_SYMBOLS: tuple[str, ...] = (
    # Mega-cap stocks (lots of news flow)
    "AAPL", "NVDA", "TSLA", "MSFT", "META", "AMZN", "GOOGL",
    # Crypto
    "BTC-USD", "ETH-USD", "SOL-USD",
    # FX (Yahoo carries macro news under these)
    "EURUSD=X", "JPY=X",
    # Commodities
    "GC=F", "CL=F",
    # Broad indices for macro/general news coverage
    "^GSPC", "^IXIC",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_yfinance_news(
    *,
    limit: int = 50,
    symbols: Iterable[str] | None = None,
) -> list[NewsItem]:
    """Pull recent Yahoo Finance news. Returns [] on any failure."""

    symbols = tuple(symbols) if symbols is not None else _FANOUT_SYMBOLS

    try:
        # yfinance is sync; offload to a thread.
        rows = await asyncio.to_thread(_pull_all, symbols)
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance news fetch failed: %s", e)
        return []

    items: list[NewsItem] = []
    for raw, src_sym in rows:
        try:
            item = _parse(raw, src_sym)
            if item is not None:
                items.append(item)
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed yfinance news row: %s", e)

    # Sort newest first, then truncate.
    items.sort(key=lambda x: x.published_at, reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _pull_all(symbols: tuple[str, ...]) -> list[tuple[dict, str]]:
    import yfinance as yf  # local import — heavy

    out: list[tuple[dict, str]] = []
    for sym in symbols:
        try:
            news = yf.Ticker(sym).news or []
        except Exception as e:  # noqa: BLE001
            logger.debug("yfinance news for %s failed: %s", sym, e)
            continue
        for n in news:
            out.append((n, sym))
    return out


def _parse(raw: dict[str, Any], source_symbol: str) -> NewsItem | None:
    # yfinance v8 wraps fields in 'content'. Older versions are flat. Handle both.
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw

    title = content.get("title") or ""
    if not title:
        return None

    # URL: prefer canonicalUrl, fall back to clickThroughUrl.
    url = ""
    cu = content.get("canonicalUrl")
    if isinstance(cu, dict):
        url = cu.get("url") or ""
    if not url:
        ct = content.get("clickThroughUrl")
        if isinstance(ct, dict):
            url = ct.get("url") or ""
    if not url:
        url = content.get("link") or ""

    # ID: stable hash of title+url
    nid = hashlib.sha1(f"yfinance:{url}:{title}".encode()).hexdigest()[:16]

    # Date: pubDate / providerPublishTime / displayTime
    published_at = _parse_dt(
        content.get("pubDate")
        or content.get("displayTime")
        or content.get("providerPublishTime")
    )

    # Summary: prefer summary, fall back to stripped description HTML.
    summary = content.get("summary") or content.get("description") or ""
    if summary:
        summary = _HTML_TAG_RE.sub(" ", summary)
        summary = _WS_RE.sub(" ", summary).strip()
        if len(summary) > 600:
            summary = summary[:600].rstrip() + "…"
    summary = summary or None

    # Image
    image_url = None
    thumb = content.get("thumbnail")
    if isinstance(thumb, dict):
        image_url = thumb.get("originalUrl")
        if not image_url:
            res = thumb.get("resolutions") or []
            if res and isinstance(res, list):
                image_url = res[0].get("url") if isinstance(res[0], dict) else None

    # Tickers Yahoo associates with the story. Some entries come back as
    # `relatedTickers: list[str]`; otherwise we know the fan-out symbol that
    # surfaced the story.
    related = content.get("relatedTickers") or raw.get("relatedTickers") or []
    if isinstance(related, list):
        raw_symbols = [str(s).upper() for s in related if s][:5]
    else:
        raw_symbols = []
    if not raw_symbols:
        # Fall back to the symbol whose feed yielded this story.
        raw_symbols = [_to_display_symbol(source_symbol)]

    return NewsItem(
        id=nid,
        source="yfinance",
        title=title.strip(),
        summary=summary,
        url=url,
        published_at=published_at,
        raw_symbols=raw_symbols,
        image_url=image_url,
    )


def _parse_dt(s: Any) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    # ISO string?
    if isinstance(s, str):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            try:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except Exception:  # noqa: BLE001
                return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    # Unix-seconds int?
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except Exception:  # noqa: BLE001
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _to_display_symbol(yf_sym: str) -> str:
    """Map a yfinance ticker back to a friendly raw_symbol for downstream
    asset extraction (BTC-USD → BTC, EURUSD=X → EURUSD, GC=F → GOLD)."""
    if yf_sym.endswith("-USD"):
        return yf_sym[:-4]
    if yf_sym.endswith("=X"):
        return yf_sym[:-2]
    if yf_sym in ("GC=F",):
        return "GOLD"
    if yf_sym in ("CL=F",):
        return "WTI"
    if yf_sym.startswith("^"):
        return yf_sym  # leave as is, asset-extractor will skip
    return yf_sym
