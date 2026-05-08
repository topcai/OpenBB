"""News aggregator — fan-out fetch + dedup + sort.

Sources:
* OpenBB ``news.world`` (FMP provider — multi-market: stocks/forex/crypto)
* CryptoPanic (crypto-only, complementary coverage)
* Mock fixture (when settings.use_mock=True or no provider keys)

The aggregator never raises: any failing source contributes 0 items. This
lets the rest of the pipeline degrade gracefully.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import NewsItem
from strategy_app.backend.services.cryptopanic_client import fetch_cryptopanic_posts
from strategy_app.backend.services.fmp_client import fetch_fmp_news

logger = logging.getLogger(__name__)

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "sample_news.json"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_recent(limit: int = 50) -> list[NewsItem]:
    """Return up to ``limit`` recent news items, deduped + sorted desc."""

    settings = get_settings()

    if settings.use_mock:
        items = _load_mock_fixture()
    else:
        # Real mode: fan out to all configured providers in parallel.
        tasks: list[asyncio.Task[list[NewsItem]]] = []

        if settings.has_cryptopanic:
            tasks.append(asyncio.create_task(
                fetch_cryptopanic_posts(settings.cryptopanic_auth_token, limit=limit),
            ))

        if settings.has_fmp:
            tasks.append(asyncio.create_task(
                fetch_fmp_news(settings.fmp_api_key, limit=limit),
            ))

        if not tasks:
            logger.warning(
                "USE_MOCK=false but no provider keys configured. "
                "Falling back to fixture data so the demo still works.",
            )
            items = _load_mock_fixture()
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            items = []
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("News provider failed: %s", r)
                    continue
                items.extend(r)

    items = _dedup_by_title(items)
    items.sort(key=lambda x: x.published_at, reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_mock_fixture() -> list[NewsItem]:
    if not _FIXTURE_PATH.exists():
        logger.error("Mock fixture not found at %s", _FIXTURE_PATH)
        return []
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return [NewsItem.model_validate(d) for d in raw]


def _dedup_by_title(items: list[NewsItem], threshold: int = 88) -> list[NewsItem]:
    """Greedy dedup: keep the first item, drop later ones whose title is
    >= threshold% similar (rapidfuzz token_set_ratio)."""

    kept: list[NewsItem] = []
    for it in items:
        is_dup = False
        for k in kept:
            if fuzz.token_set_ratio(it.title, k.title) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(it)
    return kept


async def _fetch_openbb_world_news(limit: int = 50) -> list[NewsItem]:
    """Wrap ``obb.news.world(provider='fmp')`` and normalise to NewsItem.

    Imports are local + try/except so the demo can run even when OpenBB
    isn't fully installed (mock mode).
    """

    try:
        from openbb import obb  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenBB not importable: %s", e)
        return []

    settings = get_settings()
    try:
        # Set FMP key on the user credentials object (idempotent).
        try:
            obb.user.credentials.fmp_api_key = settings.fmp_api_key  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

        result = await asyncio.to_thread(
            lambda: obb.news.world(provider="fmp", limit=limit),  # type: ignore[union-attr]
        )
        rows = result.results if hasattr(result, "results") else []
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenBB news.world(fmp) failed: %s", e)
        return []

    items: list[NewsItem] = []
    for r in rows:
        try:
            items.append(_obb_row_to_news_item(r))
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping malformed OpenBB row: %s", e)
    return items


def _obb_row_to_news_item(row: Any) -> NewsItem:
    """Convert an OpenBB ``WorldNewsData`` row into our NewsItem."""

    d = row.model_dump() if hasattr(row, "model_dump") else dict(row)

    title = d.get("title") or ""
    url = d.get("url") or ""
    nid = hashlib.sha1(f"fmp:{url}:{title}".encode()).hexdigest()[:16]

    published = d.get("date")
    if isinstance(published, str):
        published = datetime.fromisoformat(published.replace("Z", "+00:00"))
    elif published is None:
        published = datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    raw_symbols_field = d.get("symbols") or ""
    if isinstance(raw_symbols_field, str):
        raw_symbols = [s.strip().upper() for s in raw_symbols_field.split(",") if s.strip()]
    elif isinstance(raw_symbols_field, list):
        raw_symbols = [str(s).upper() for s in raw_symbols_field]
    else:
        raw_symbols = []

    images = d.get("images")
    image_url = None
    if isinstance(images, str):
        image_url = images
    elif isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            image_url = first.get("url") or first.get("o")
        elif isinstance(first, str):
            image_url = first
    elif isinstance(images, dict):
        image_url = images.get("url") or images.get("o")

    return NewsItem(
        id=nid,
        source=d.get("source") or "fmp",
        title=title,
        summary=d.get("excerpt") or d.get("body"),
        url=url,
        published_at=published,
        raw_symbols=raw_symbols,
        image_url=image_url,
    )
