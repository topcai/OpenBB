"""Asset extraction: news → list[ExtractedAsset].

Two-tier strategy:
1. **Rule-based** — if the news already carries a ticker symbol or contains
   any of ~50 well-known asset names, map directly. Zero LLM cost. Covers
   ~80%+ of practical news.
2. **LLM fallback** — if rules find nothing, optionally ask the LLM to extract
   ticker(s). Skipped silently when no API key is configured.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import AssetType, ExtractedAsset, NewsItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol catalogue (display, asset_type, yfinance_symbol, search keywords)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _AssetEntry:
    display: str
    asset_type: AssetType
    yfinance: str
    keywords: tuple[str, ...]   # case-insensitive substring / token matches


_CATALOGUE: tuple[_AssetEntry, ...] = (
    # ---- Crypto ----
    _AssetEntry("BTC-USD", "CRYPTO", "BTC-USD", ("BTC", "BITCOIN", "比特币")),
    _AssetEntry("ETH-USD", "CRYPTO", "ETH-USD", ("ETH", "ETHEREUM", "以太坊", "以太")),
    _AssetEntry("SOL-USD", "CRYPTO", "SOL-USD", ("SOL", "SOLANA")),
    _AssetEntry("BNB-USD", "CRYPTO", "BNB-USD", ("BNB", "BINANCE COIN")),
    _AssetEntry("XRP-USD", "CRYPTO", "XRP-USD", ("XRP", "RIPPLE")),
    _AssetEntry("DOGE-USD", "CRYPTO", "DOGE-USD", ("DOGE", "DOGECOIN", "狗狗币")),
    _AssetEntry("ADA-USD", "CRYPTO", "ADA-USD", ("ADA", "CARDANO")),
    _AssetEntry("AVAX-USD", "CRYPTO", "AVAX-USD", ("AVAX", "AVALANCHE")),
    _AssetEntry("LINK-USD", "CRYPTO", "LINK-USD", ("LINK", "CHAINLINK")),
    _AssetEntry("DOT-USD", "CRYPTO", "DOT-USD", ("DOT", "POLKADOT")),
    _AssetEntry("MATIC-USD", "CRYPTO", "MATIC-USD", ("MATIC", "POLYGON")),
    _AssetEntry("LTC-USD", "CRYPTO", "LTC-USD", ("LTC", "LITECOIN", "莱特币")),
    _AssetEntry("TRX-USD", "CRYPTO", "TRX-USD", ("TRX", "TRON", "波场")),
    _AssetEntry("BCH-USD", "CRYPTO", "BCH-USD", ("BCH", "BITCOIN CASH")),

    # ---- US equities (mega caps & active names) ----
    _AssetEntry("AAPL", "STOCK", "AAPL", ("AAPL", "APPLE", "苹果")),
    _AssetEntry("MSFT", "STOCK", "MSFT", ("MSFT", "MICROSOFT", "微软")),
    _AssetEntry("NVDA", "STOCK", "NVDA", ("NVDA", "NVIDIA", "英伟达")),
    _AssetEntry("TSLA", "STOCK", "TSLA", ("TSLA", "TESLA", "特斯拉")),
    _AssetEntry("META", "STOCK", "META", ("META", "FACEBOOK", "脸书")),
    _AssetEntry("GOOGL", "STOCK", "GOOGL", ("GOOGL", "GOOG", "GOOGLE", "ALPHABET", "谷歌")),
    _AssetEntry("AMZN", "STOCK", "AMZN", ("AMZN", "AMAZON", "亚马逊")),
    _AssetEntry("AMD", "STOCK", "AMD", ("AMD",)),
    _AssetEntry("NFLX", "STOCK", "NFLX", ("NFLX", "NETFLIX", "网飞")),
    _AssetEntry("INTC", "STOCK", "INTC", ("INTC", "INTEL", "英特尔")),
    _AssetEntry("BABA", "STOCK", "BABA", ("BABA", "ALIBABA", "阿里巴巴")),
    _AssetEntry("PDD", "STOCK", "PDD", ("PDD", "PINDUODUO", "拼多多")),
    _AssetEntry("JPM", "STOCK", "JPM", ("JPM", "JPMORGAN", "摩根大通")),
    _AssetEntry("BAC", "STOCK", "BAC", ("BAC", "BANK OF AMERICA")),
    _AssetEntry("COIN", "STOCK", "COIN", ("COIN", "COINBASE")),
    _AssetEntry("MSTR", "STOCK", "MSTR", ("MSTR", "MICROSTRATEGY")),

    # ---- FX (yfinance =X suffix) ----
    _AssetEntry("EURUSD", "FX", "EURUSD=X", ("EUR/USD", "EURUSD", "EUR-USD", "欧元美元")),
    _AssetEntry("USDJPY", "FX", "JPY=X",    ("USD/JPY", "USDJPY", "美元日元")),
    _AssetEntry("GBPUSD", "FX", "GBPUSD=X", ("GBP/USD", "GBPUSD", "英镑美元")),
    _AssetEntry("AUDUSD", "FX", "AUDUSD=X", ("AUD/USD", "AUDUSD", "澳元美元")),
    _AssetEntry("USDCNH", "FX", "CNY=X",    ("USD/CNH", "USDCNH", "USD/CNY", "人民币")),
    _AssetEntry("USDCHF", "FX", "CHF=X",    ("USD/CHF", "USDCHF")),
    _AssetEntry("DXY",    "FX", "DX-Y.NYB", ("DXY", "DOLLAR INDEX", "美元指数")),

    # ---- Commodities (yfinance futures) ----
    _AssetEntry("XAUUSD", "COMMODITY", "GC=F", ("GOLD", "XAU", "黄金")),
    _AssetEntry("XAGUSD", "COMMODITY", "SI=F", ("SILVER", "XAG", "白银")),
    _AssetEntry("WTI",    "COMMODITY", "CL=F", ("WTI", "CRUDE", "OIL", "原油", "石油")),
    _AssetEntry("BRENT",  "COMMODITY", "BZ=F", ("BRENT",)),
    _AssetEntry("NATGAS", "COMMODITY", "NG=F", ("NATGAS", "NATURAL GAS", "天然气")),
    _AssetEntry("COPPER", "COMMODITY", "HG=F", ("COPPER", "铜")),
    # ETF proxies
    _AssetEntry("GLD",    "COMMODITY", "GLD",  ("GLD",)),
    _AssetEntry("USO",    "COMMODITY", "USO",  ("USO",)),
)


# Build an exact-symbol lookup table from the catalogue + raw_symbols field.
_BY_RAW_SYMBOL: dict[str, _AssetEntry] = {}
for _e in _CATALOGUE:
    for _kw in _e.keywords:
        if re.fullmatch(r"[A-Z0-9-]+", _kw):
            _BY_RAW_SYMBOL[_kw] = _e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract(news: NewsItem, max_assets: int = 3) -> list[ExtractedAsset]:
    """Return up to ``max_assets`` likely-impacted assets for a news item."""

    # 1. Direct ticker hit from news.raw_symbols.
    found: dict[str, ExtractedAsset] = {}
    for sym in news.raw_symbols:
        sym_u = sym.upper().strip()
        entry = _BY_RAW_SYMBOL.get(sym_u)
        if entry:
            found[entry.display] = _to_asset(entry, confidence=1.0)

    # 2. Substring scan against title + summary.
    if len(found) < max_assets:
        haystack = f"{news.title} {news.summary or ''}".upper()
        for entry in _CATALOGUE:
            if entry.display in found:
                continue
            for kw in entry.keywords:
                kw_u = kw.upper()
                # Use word-boundary match for any single-token ASCII keyword
                # to avoid "INTEL"-igence → INTC false positives.
                if re.fullmatch(r"[A-Z0-9./-]+", kw_u):
                    if re.search(rf"(?<![A-Z0-9]){re.escape(kw_u)}(?![A-Z0-9])", haystack):
                        found[entry.display] = _to_asset(entry, confidence=0.85)
                        break
                else:
                    # Multi-word or Chinese — plain substring is fine.
                    if kw_u in haystack:
                        found[entry.display] = _to_asset(entry, confidence=0.9)
                        break
            if len(found) >= max_assets:
                break

    if found:
        return list(found.values())[:max_assets]

    # 3. LLM fallback — only if a key is configured.
    settings = get_settings()
    if settings.has_llm and not settings.use_mock:
        return await _llm_extract(news, max_assets=max_assets)

    return []


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _to_asset(entry: _AssetEntry, confidence: float) -> ExtractedAsset:
    return ExtractedAsset(
        symbol=entry.display,
        asset_type=entry.asset_type,
        yfinance_symbol=entry.yfinance,
        confidence=confidence,
    )


_LLM_PROMPT = """You are a financial news analyst. Given a news headline+summary,
identify which TRADEABLE ASSETS the news is most likely to move.

Allowed answers MUST be chosen from this exact list (return the `symbol` field):
{catalogue}

Output ONLY valid JSON of this shape:
{{
  "assets": [
    {{ "symbol": "BTC-USD", "confidence": 0.0-1.0 }},
    ...
  ]
}}

Rules:
- Maximum 3 assets.
- If no asset is clearly impacted, return {{ "assets": [] }}.
- Do NOT invent symbols not in the list.

# News
TITLE: {title}
SUMMARY: {summary}
"""


async def _llm_extract(news: NewsItem, max_assets: int) -> list[ExtractedAsset]:
    """Best-effort LLM extraction. Returns [] on any failure."""
    settings = get_settings()
    try:
        from openai import AsyncOpenAI
    except Exception as e:  # noqa: BLE001
        logger.warning("openai SDK not installed: %s", e)
        return []

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
    )

    catalogue_str = "\n".join(f"- {e.display} ({e.asset_type})" for e in _CATALOGUE)
    prompt = _LLM_PROMPT.format(
        catalogue=catalogue_str,
        title=news.title,
        summary=news.summary or "(no summary)",
    )

    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM asset extraction failed: %s", e)
        return []

    by_symbol = {e.display: e for e in _CATALOGUE}
    out: list[ExtractedAsset] = []
    for a in (data.get("assets") or [])[:max_assets]:
        sym = a.get("symbol")
        conf = float(a.get("confidence") or 0)
        if sym in by_symbol and conf >= 0.4:
            out.append(_to_asset(by_symbol[sym], confidence=conf))
    return out
