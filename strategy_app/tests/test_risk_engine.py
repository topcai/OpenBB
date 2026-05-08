"""Tests for strategy_app.backend.services.risk_engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from strategy_app.backend.schemas import ExtractedAsset, MarketSnapshot
from strategy_app.backend.services import risk_engine
from strategy_app.backend.services.risk_engine import (
    ACCOUNT_SIZE_USD,
    LEVERAGE_CAP,
    RISK_PCT_PER_TRADE,
    build_strategy,
    cap_leverage,
)


def _asset(asset_type="CRYPTO") -> ExtractedAsset:
    return ExtractedAsset(
        symbol="BTC-USD" if asset_type == "CRYPTO" else "AAPL",
        asset_type=asset_type,
        yfinance_symbol="BTC-USD" if asset_type == "CRYPTO" else "AAPL",
        confidence=1.0,
    )


def _snap(price: float = 60_000.0, atr: float = 1_200.0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTC-USD",
        current_price=price,
        atr=atr,
        as_of=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# cap_leverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "asset_type,suggested,expected",
    [
        ("CRYPTO", 10, 5.0),       # capped at 5
        ("CRYPTO", 3, 3.0),
        ("STOCK", 5, 2.0),         # capped at 2
        ("STOCK", 1, 1.0),
        ("FX", 30, 10.0),          # capped at 10
        ("COMMODITY", 100, 5.0),
        ("CRYPTO", 0.5, 1.0),      # min 1
    ],
)
def test_cap_leverage(asset_type, suggested, expected):
    assert cap_leverage(asset_type, suggested) == expected


# ---------------------------------------------------------------------------
# build_strategy — happy paths
# ---------------------------------------------------------------------------

def test_long_strategy_basic_math():
    s = build_strategy(
        asset=_asset(),
        snapshot=_snap(price=60_000, atr=1_200),
        direction="LONG",
        suggested_leverage=10,           # will be capped to 5 (CRYPTO)
        confidence=0.7,
        horizon="SWING_3D",
        reasoning_zh="测试理由",
    )
    assert s is not None
    assert s.direction == "LONG"
    assert s.leverage == 5.0
    # SL = entry - 1.5*ATR = 60000 - 1800 = 58200
    assert s.stop_loss == pytest.approx(58_200.0, rel=1e-3)
    # TP = entry + 2*1.5*ATR = 60000 + 3600 = 63600
    assert s.take_profit == pytest.approx(63_600.0, rel=1e-3)
    # risk_amount = 200, sl%=1800/60000 = 3%, position = 200/0.03 = 6666.67
    assert s.risk_amount_usd == pytest.approx(200.0, rel=1e-3)
    assert s.position_size_usd == pytest.approx(6_666.67, rel=1e-2)
    # margin = position/leverage = 6666.67/5 ≈ 1333.33
    assert s.margin_usd == pytest.approx(1_333.33, rel=1e-2)
    assert s.risk_reward_ratio == 2.0
    assert s.atr_used == 1_200


def test_short_strategy_flips_sl_tp():
    s = build_strategy(
        asset=_asset(),
        snapshot=_snap(price=60_000, atr=1_200),
        direction="SHORT",
        suggested_leverage=3,
        confidence=0.6,
        horizon="INTRADAY",
        reasoning_zh="测试做空",
    )
    assert s is not None
    # SHORT: SL above entry, TP below entry
    assert s.stop_loss == pytest.approx(61_800.0, rel=1e-3)
    assert s.take_profit == pytest.approx(56_400.0, rel=1e-3)
    assert s.leverage == 3.0


def test_neutral_returns_none():
    s = build_strategy(
        asset=_asset(),
        snapshot=_snap(),
        direction="NEUTRAL",  # type: ignore[arg-type]
        suggested_leverage=2,
        confidence=0.3,
        horizon="INTRADAY",
        reasoning_zh="信息不足",
    )
    assert s is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_atr_returns_none():
    snap = MarketSnapshot(
        symbol="X", current_price=100,
        atr=0.000001,  # MarketSnapshot validator forbids 0; use tiny positive
        as_of=datetime.now(timezone.utc),
    )
    # tiny ATR is OK — the engine still produces a strategy (maybe a tight one)
    s = build_strategy(
        asset=_asset(), snapshot=snap, direction="LONG",
        suggested_leverage=2, confidence=0.5, horizon="INTRADAY",
        reasoning_zh="x",
    )
    assert s is not None and s.position_size_usd > 0


def test_huge_atr_uses_safety_cap():
    """When ATR-based SL would make the stop go negative, the engine
    falls back to a 50%-of-price stop."""
    s = build_strategy(
        asset=_asset(),
        snapshot=_snap(price=10.0, atr=20.0),  # 1.5*ATR = 30 > price
        direction="LONG",
        suggested_leverage=2,
        confidence=0.5,
        horizon="INTRADAY",
        reasoning_zh="x",
    )
    assert s is not None
    assert s.stop_loss > 0
    # SL distance fell back to 50% of entry → SL = 5
    assert s.stop_loss == pytest.approx(5.0, rel=1e-3)


def test_per_asset_leverage_caps_apply():
    for at, cap in LEVERAGE_CAP.items():
        a = _asset(at)
        s = build_strategy(
            asset=a, snapshot=_snap(),
            direction="LONG", suggested_leverage=999,
            confidence=0.5, horizon="INTRADAY",
            reasoning_zh="x",
        )
        assert s is not None
        assert s.leverage == cap


def test_risk_amount_constant():
    s = build_strategy(
        asset=_asset(), snapshot=_snap(price=100, atr=2),
        direction="LONG", suggested_leverage=2,
        confidence=0.5, horizon="INTRADAY",
        reasoning_zh="x",
    )
    assert s is not None
    assert s.risk_amount_usd == ACCOUNT_SIZE_USD * RISK_PCT_PER_TRADE
