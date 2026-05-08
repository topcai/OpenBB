"""Market data layer.

Fetches recent OHLC and computes ATR(14) for any of the assets in our
catalogue. Uses yfinance directly (free, no API key, covers stocks, FX,
commodities futures, and major crypto via the ``XXX-USD`` convention).

Mock mode returns plausible hard-coded snapshots so the demo runs offline.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import ExtractedAsset, MarketSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock prices keyed by display symbol — used when USE_MOCK or yfinance fails.
# Numbers are roughly realistic so downstream UI looks sensible.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _MockSnap:
    price: float
    atr: float


_MOCK_PRICES: dict[str, _MockSnap] = {
    # Crypto
    "BTC-USD":  _MockSnap(70_500.0, 1_500.0),
    "ETH-USD":  _MockSnap(3_700.0,  85.0),
    "SOL-USD":  _MockSnap(165.0,    7.0),
    "BNB-USD":  _MockSnap(620.0,    14.0),
    "XRP-USD":  _MockSnap(0.62,     0.025),
    "DOGE-USD": _MockSnap(0.16,     0.008),
    "ADA-USD":  _MockSnap(0.45,     0.020),
    "AVAX-USD": _MockSnap(36.0,     1.6),
    "LINK-USD": _MockSnap(15.0,     0.6),
    "DOT-USD":  _MockSnap(7.2,      0.3),
    "MATIC-USD":_MockSnap(0.72,     0.03),
    "LTC-USD":  _MockSnap(82.0,     2.5),
    "TRX-USD":  _MockSnap(0.12,     0.004),
    "BCH-USD":  _MockSnap(420.0,    16.0),
    # Stocks
    "AAPL": _MockSnap(195.0, 2.4),
    "MSFT": _MockSnap(420.0, 4.5),
    "NVDA": _MockSnap(950.0, 22.0),
    "TSLA": _MockSnap(180.0, 5.5),
    "META": _MockSnap(490.0, 7.0),
    "GOOGL":_MockSnap(170.0, 2.4),
    "AMZN": _MockSnap(185.0, 2.6),
    "AMD":  _MockSnap(160.0, 4.5),
    "NFLX": _MockSnap(620.0, 9.0),
    "INTC": _MockSnap(31.0,  0.8),
    "BABA": _MockSnap(85.0,  1.6),
    "PDD":  _MockSnap(140.0, 3.5),
    "JPM":  _MockSnap(200.0, 2.3),
    "BAC":  _MockSnap(38.0,  0.5),
    "COIN": _MockSnap(225.0, 8.0),
    "MSTR": _MockSnap(1300.0,55.0),
    # FX
    "EURUSD":_MockSnap(1.0850, 0.0025),
    "USDJPY":_MockSnap(155.20, 0.40),
    "GBPUSD":_MockSnap(1.2650, 0.0028),
    "AUDUSD":_MockSnap(0.6620, 0.0018),
    "USDCNH":_MockSnap(7.2300, 0.0040),
    "USDCHF":_MockSnap(0.9050, 0.0020),
    "DXY":   _MockSnap(105.20, 0.30),
    # Commodities
    "XAUUSD": _MockSnap(2_460.0, 18.0),
    "XAGUSD": _MockSnap(29.0,    0.45),
    "WTI":    _MockSnap(72.0,    1.2),
    "BRENT":  _MockSnap(76.0,    1.1),
    "NATGAS": _MockSnap(2.50,    0.07),
    "COPPER": _MockSnap(4.40,    0.05),
    "GLD":    _MockSnap(228.0,   1.8),
    "USO":    _MockSnap(78.0,    1.0),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_market_snapshot(asset: ExtractedAsset) -> Optional[MarketSnapshot]:
    """Return current price + ATR(14, 1h) for the given asset.

    In mock mode (or on yfinance failure) returns a deterministic stub.
    Returns ``None`` if both real and mock paths fail.
    """

    settings = get_settings()

    if not settings.use_mock:
        snap = await _fetch_yfinance_snapshot(asset)
        if snap is not None:
            return snap
        logger.info("yfinance failed for %s, falling back to mock", asset.symbol)

    return _mock_snapshot(asset)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _mock_snapshot(asset: ExtractedAsset) -> Optional[MarketSnapshot]:
    m = _MOCK_PRICES.get(asset.symbol)
    if m is None:
        return None
    return MarketSnapshot(
        symbol=asset.symbol,
        current_price=m.price,
        atr=m.atr,
        as_of=datetime.now(timezone.utc),
    )


async def _fetch_yfinance_snapshot(asset: ExtractedAsset) -> Optional[MarketSnapshot]:
    """Run blocking yfinance call in a thread."""
    try:
        df = await asyncio.to_thread(_yf_download_1h, asset.yfinance_symbol)
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance download failed for %s: %s", asset.yfinance_symbol, e)
        return None

    if df is None or df.empty:
        return None

    try:
        atr = _compute_atr(df, period=14)
        price = float(df["Close"].iloc[-1])
        last_atr = float(atr.iloc[-1])
    except Exception as e:  # noqa: BLE001
        logger.warning("ATR/price computation failed for %s: %s", asset.symbol, e)
        return None

    if not (price > 0 and last_atr > 0):
        return None

    return MarketSnapshot(
        symbol=asset.symbol,
        current_price=price,
        atr=last_atr,
        as_of=datetime.now(timezone.utc),
    )


def _yf_download_1h(symbol: str) -> Optional["pd.DataFrame"]:
    """Pull ~30 days of 1h OHLC. Returns None on failure."""
    import yfinance as yf  # local import — heavy

    df = yf.download(
        tickers=symbol,
        period="60d",
        interval="1h",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return None
    # yfinance sometimes returns a multi-index column when only 1 ticker — flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _compute_atr(df: "pd.DataFrame", period: int = 14) -> "pd.Series":
    """Wilder ATR — classic formulation."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder's smoothing ≈ EMA with alpha = 1/period
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr
