"""Pydantic models shared across the strategy_app backend.

These objects are the wire-format between modules AND between backend & frontend.
Keep field names stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enums (kept as plain Literals so JSON-serialisation stays trivial)
# ---------------------------------------------------------------------------

AssetType = Literal["CRYPTO", "STOCK", "FX", "COMMODITY"]
Direction = Literal["LONG", "SHORT", "NEUTRAL"]
Horizon = Literal["INTRADAY", "SWING_3D", "SWING_2W"]
EntryType = Literal["MARKET", "LIMIT"]


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class NewsItem(BaseModel):
    """A normalised news article from any provider."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable hash of url+title")
    source: str = Field(..., description="Provider key, e.g. 'cryptopanic', 'fmp'")
    title: str
    summary: Optional[str] = None
    url: str
    published_at: datetime
    raw_symbols: list[str] = Field(default_factory=list)
    image_url: Optional[str] = None


class ExtractedAsset(BaseModel):
    """An asset that a news article is likely to move."""

    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., description="Display symbol, e.g. 'BTC-USD', 'AAPL'")
    asset_type: AssetType
    yfinance_symbol: str = Field(..., description="Symbol used to query yfinance")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MarketSnapshot(BaseModel):
    """Latest price + volatility snapshot for a single asset."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    current_price: float = Field(..., gt=0)
    atr: float = Field(..., gt=0, description="ATR(14) on 1h candles")
    as_of: datetime


class Strategy(BaseModel):
    """A fully-specified trade idea, ready to display."""

    model_config = ConfigDict(extra="ignore")

    asset: ExtractedAsset
    direction: Direction
    confidence: float = Field(..., ge=0.0, le=1.0)
    horizon: Horizon

    entry_type: EntryType = "MARKET"
    entry_price: float = Field(..., gt=0)
    leverage: float = Field(..., ge=1.0)

    margin_usd: float = Field(..., gt=0)
    position_size_usd: float = Field(..., gt=0)

    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    risk_reward_ratio: float = Field(..., gt=0)
    risk_amount_usd: float = Field(..., gt=0)

    reasoning_zh: str

    atr_used: float = Field(..., gt=0)
    generated_at: datetime

    @field_validator("direction")
    @classmethod
    def _no_neutral_strategy(cls, v: Direction) -> Direction:
        # NEUTRAL means "no trade" — we should never instantiate a Strategy in that
        # case. Caller must drop NEUTRAL signals before constructing this model.
        if v == "NEUTRAL":
            raise ValueError("Strategy must have a directional bias (LONG/SHORT)")
        return v


class FeedCard(BaseModel):
    """A single feed entry: one news article + 0..N derived strategies."""

    model_config = ConfigDict(extra="ignore")

    news: NewsItem
    strategies: list[Strategy] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM-side contract (what the strategist is allowed to return).
# Kept separate from `Strategy` so we can validate model output explicitly.
# ---------------------------------------------------------------------------

class LLMStrategyAdvice(BaseModel):
    """Structured JSON we expect from the LLM strategist."""

    model_config = ConfigDict(extra="ignore")

    direction: Direction
    confidence: float = Field(..., ge=0.0, le=1.0)
    suggested_leverage: float = Field(..., ge=1.0, le=20.0)
    horizon: Horizon
    reasoning_zh: str = Field(..., min_length=1, max_length=600)
