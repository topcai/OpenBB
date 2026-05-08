"""Pipeline orchestrator: news → assets → market → LLM → strategy → card."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import FeedCard, NewsItem, Strategy
from strategy_app.backend.services import (
    asset_extractor,
    llm_strategist,
    market_data,
    news_aggregator,
    risk_engine,
)
from strategy_app.backend.storage import cache

logger = logging.getLogger(__name__)

# Global semaphore so concurrent /feed requests share the same cap.
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _LLM_SEMAPHORE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_feed(limit: int = 20, *, force_refresh: bool = False) -> list[FeedCard]:
    """Build the latest feed.

    For each news item we first consult the cache (TTL = settings.cache_ttl_minutes).
    Cache misses go through the full pipeline. The card list is returned in the
    same order as the underlying news (newest first).
    """

    raw_news = await news_aggregator.fetch_recent(limit=limit * 2)
    if not raw_news:
        return []

    # Run uncached items concurrently to parallelise external API calls.
    cached_cards: dict[str, FeedCard] = {}
    work_queue: list[NewsItem] = []
    for n in raw_news:
        if not force_refresh:
            c = cache.get(n.id)
            if c is not None:
                cached_cards[n.id] = c
                continue
        work_queue.append(n)

    new_cards: dict[str, FeedCard] = {}
    if work_queue:
        results = await asyncio.gather(
            *(_build_one(n) for n in work_queue),
            return_exceptions=True,
        )
        for n, r in zip(work_queue, results):
            if isinstance(r, Exception):
                logger.warning("Pipeline failed for news %s: %s", n.id, r)
                # Fall back to a card with no strategies so the news still shows.
                fallback = FeedCard(news=n, strategies=[])
                new_cards[n.id] = fallback
                continue
            new_cards[n.id] = r
            cache.set(n.id, r)

    cards: list[FeedCard] = []
    for n in raw_news:
        c = cached_cards.get(n.id) or new_cards.get(n.id)
        if c is not None:
            cards.append(c)
        if len(cards) >= limit:
            break
    return cards


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

async def _build_one(news: NewsItem) -> FeedCard:
    """Run the full pipeline for a single news item. Always returns a card
    (possibly with empty strategies)."""

    assets = await asset_extractor.extract(news, max_assets=2)
    strategies: list[Strategy] = []

    # Build per-asset strategies in parallel.
    sem = _llm_semaphore()

    async def _per_asset(asset) -> Optional[Strategy]:
        snap = await market_data.get_market_snapshot(asset)
        if snap is None:
            logger.debug("No snapshot for %s, skipping", asset.symbol)
            return None
        async with sem:  # cap concurrent LLM calls
            advice = await llm_strategist.advise(news, asset, snap)
        if advice is None:
            return None
        return risk_engine.build_strategy(
            asset=asset,
            snapshot=snap,
            direction=advice.direction,
            suggested_leverage=advice.suggested_leverage,
            confidence=advice.confidence,
            horizon=advice.horizon,
            reasoning_zh=advice.reasoning_zh,
        )

    if assets:
        per_asset = await asyncio.gather(*(_per_asset(a) for a in assets))
        strategies = [s for s in per_asset if s is not None]

    return FeedCard(news=news, strategies=strategies)
