"""Deterministic risk-engine.

The single source of truth for every numeric field on a Strategy. Pure
functions, no I/O, no LLM. Fully unit-tested.

Design rules
------------
* The LLM only chooses *direction* / *confidence* / *suggested_leverage* /
  *horizon* / *reasoning_zh*. Everything else (entry/SL/TP/position/margin)
  is computed here.
* Stop-loss distance is derived from ATR so the dollar-risk-per-trade is
  always bounded.
* Leverage is hard-capped per asset class.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from strategy_app.backend.schemas import (
    AssetType,
    Direction,
    ExtractedAsset,
    Horizon,
    MarketSnapshot,
    Strategy,
)

# ---------------------------------------------------------------------------
# Tunables (kept module-level so tests can monkeypatch if needed)
# ---------------------------------------------------------------------------

ACCOUNT_SIZE_USD: float = 10_000.0
RISK_PCT_PER_TRADE: float = 0.02            # → $200 max loss per trade
ATR_SL_MULT: float = 1.5
RR_RATIO: float = 2.0                        # TP distance = 2 × SL distance

LEVERAGE_CAP: dict[AssetType, float] = {
    "CRYPTO": 5.0,
    "STOCK": 2.0,
    "FX": 10.0,
    "COMMODITY": 5.0,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cap_leverage(asset_type: AssetType, suggested: float) -> float:
    """Clamp the LLM-suggested leverage to the per-asset-class hard cap."""
    cap = LEVERAGE_CAP[asset_type]
    return max(1.0, min(float(suggested), cap))


def build_strategy(
    asset: ExtractedAsset,
    snapshot: MarketSnapshot,
    direction: Direction,
    suggested_leverage: float,
    confidence: float,
    horizon: Horizon,
    reasoning_zh: str,
    *,
    account_size_usd: float = ACCOUNT_SIZE_USD,
    risk_pct: float = RISK_PCT_PER_TRADE,
    atr_sl_mult: float = ATR_SL_MULT,
    rr_ratio: float = RR_RATIO,
) -> Optional[Strategy]:
    """Convert an LLM signal + market snapshot into a fully-specified Strategy.

    Returns ``None`` when ``direction == "NEUTRAL"`` (no trade).
    """

    if direction == "NEUTRAL":
        return None

    if snapshot.atr <= 0 or snapshot.current_price <= 0:
        return None

    leverage = cap_leverage(asset.asset_type, suggested_leverage)
    entry = snapshot.current_price
    sl_distance = atr_sl_mult * snapshot.atr
    tp_distance = rr_ratio * sl_distance

    # Bound SL distance so we never have a non-positive stop price (very volatile
    # / very low-priced assets).
    if sl_distance >= entry:
        sl_distance = entry * 0.5
        tp_distance = rr_ratio * sl_distance

    if direction == "LONG":
        stop_loss = entry - sl_distance
        take_profit = entry + tp_distance
    else:  # SHORT
        stop_loss = entry + sl_distance
        take_profit = max(entry - tp_distance, entry * 0.01)

    risk_amount = account_size_usd * risk_pct
    # Position notional such that hitting SL loses exactly `risk_amount`.
    # %-move from entry to SL = sl_distance / entry
    pct_move_to_sl = sl_distance / entry
    position_size_usd = risk_amount / pct_move_to_sl
    margin_usd = position_size_usd / leverage

    return Strategy(
        asset=asset,
        direction=direction,
        confidence=confidence,
        horizon=horizon,
        entry_type="MARKET",
        entry_price=round(entry, 6),
        leverage=leverage,
        margin_usd=round(margin_usd, 2),
        position_size_usd=round(position_size_usd, 2),
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        risk_reward_ratio=rr_ratio,
        risk_amount_usd=round(risk_amount, 2),
        reasoning_zh=reasoning_zh,
        atr_used=snapshot.atr,
        generated_at=datetime.now(timezone.utc),
    )
