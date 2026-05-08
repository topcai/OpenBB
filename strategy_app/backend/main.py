"""FastAPI entry — exposes the strategy feed as a small JSON API.

Endpoints
---------
GET  /healthz       Simple liveness probe.
GET  /feed          Latest feed cards (cached). ?limit=20.
POST /refresh       Wipe cache + rebuild feed. Returns the fresh list.
GET  /              Tiny landing page so visiting the host in a browser
                    returns something human-readable instead of 404.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from strategy_app.backend.config import get_settings
from strategy_app.backend.pipeline import build_feed
from strategy_app.backend.schemas import FeedCard
from strategy_app.backend.storage import cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("strategy_app.api")

settings = get_settings()

app = FastAPI(
    title="Strategy App — 金融小红书 Demo",
    description=(
        "A small backend that turns multi-market news into structured trading-"
        "strategy cards. Demo only — not investment advice."
    ),
    version="0.1.0",
)

# Streamlit dev frontend lives on a different port — allow CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing() -> str:
    return (
        "<html><body style='font-family:sans-serif;max-width:680px;margin:40px auto;'>"
        "<h2>Strategy App backend</h2>"
        "<p>Try <a href='/feed?limit=10'>/feed?limit=10</a> or "
        "<a href='/docs'>/docs</a>.</p>"
        f"<p>Mode: <b>{'MOCK' if settings.use_mock else 'LIVE'}</b></p>"
        "</body></html>"
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "use_mock": settings.use_mock,
        "has_llm": settings.has_llm,
        "has_fmp": settings.has_fmp,
        "has_tiingo": settings.has_tiingo,
        "has_biztoc": settings.has_biztoc,
        "has_cryptopanic": settings.has_cryptopanic,
        # yfinance is always on (free, no key)
        "has_yfinance": True,
    }


@app.get("/feed", response_model=list[FeedCard])
async def feed(
    limit: int = Query(default=settings.default_feed_limit, ge=1, le=100),
) -> list[FeedCard]:
    return await build_feed(limit=limit)


@app.post("/refresh", response_model=list[FeedCard])
async def refresh(
    limit: int = Query(default=settings.default_feed_limit, ge=1, le=100),
) -> list[FeedCard]:
    cache.clear()
    return await build_feed(limit=limit, force_refresh=True)
