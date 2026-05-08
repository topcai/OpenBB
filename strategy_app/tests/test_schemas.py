"""Tests for strategy_app.backend.schemas — basic validation rules."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from strategy_app.backend.schemas import (
    ExtractedAsset,
    LLMStrategyAdvice,
    NewsItem,
    Strategy,
)


def test_news_item_minimal():
    n = NewsItem(
        id="abc", source="cryptopanic",
        title="t", url="https://x/y",
        published_at=datetime.now(timezone.utc),
    )
    assert n.raw_symbols == []


def test_strategy_rejects_neutral():
    with pytest.raises(ValidationError):
        Strategy(
            asset=ExtractedAsset(
                symbol="BTC-USD", asset_type="CRYPTO",
                yfinance_symbol="BTC-USD",
            ),
            direction="NEUTRAL",  # type: ignore[arg-type]
            confidence=0.5, horizon="INTRADAY",
            entry_price=1, leverage=1,
            margin_usd=1, position_size_usd=1,
            stop_loss=0.5, take_profit=2,
            risk_reward_ratio=2, risk_amount_usd=200,
            reasoning_zh="x", atr_used=0.1,
            generated_at=datetime.now(timezone.utc),
        )


def test_llm_advice_validates_ranges():
    with pytest.raises(ValidationError):
        LLMStrategyAdvice(
            direction="LONG", confidence=2.0,   # > 1
            suggested_leverage=3, horizon="INTRADAY",
            reasoning_zh="x",
        )
    with pytest.raises(ValidationError):
        LLMStrategyAdvice(
            direction="LONG", confidence=0.5,
            suggested_leverage=99,              # > 20
            horizon="INTRADAY", reasoning_zh="x",
        )
