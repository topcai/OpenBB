"""LLM strategist.

Given a news article + impacted asset + market snapshot, returns an
``LLMStrategyAdvice``: direction, confidence, suggested_leverage, horizon,
reasoning_zh. Numbers are bounded; the calling pipeline feeds these into
``risk_engine.build_strategy`` to materialise the actual TP/SL.

In mock mode this module returns a deterministic heuristic stub so the
demo runs without any LLM key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from strategy_app.backend.config import get_settings
from strategy_app.backend.schemas import (
    Direction,
    ExtractedAsset,
    Horizon,
    LLMStrategyAdvice,
    MarketSnapshot,
    NewsItem,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "strategy.md"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def advise(
    news: NewsItem,
    asset: ExtractedAsset,
    snapshot: MarketSnapshot,
) -> Optional[LLMStrategyAdvice]:
    """Produce a strategy advice. Returns ``None`` on failure."""
    settings = get_settings()

    if settings.use_mock or not settings.has_llm:
        return _mock_advice(news, asset)

    return await _llm_advice(news, asset, snapshot)


# ---------------------------------------------------------------------------
# Mock heuristic — picks a direction from sentiment-keywords in the title.
# ---------------------------------------------------------------------------

_BULLISH_KW = (
    "beats", "beat", "surge", "surges", "record", "high", "rally", "rallies",
    "gain", "gains", "up", "jump", "jumps", "rises", "soars", "approves",
    "approval", "inflows", "boost", "upgrade", "raise", "raises", "above",
    "突破", "暴涨", "上涨", "新高", "利好", "通过",
)
_BEARISH_KW = (
    "miss", "misses", "drop", "drops", "tumble", "tumbles", "below", "low",
    "fall", "falls", "outage", "halt", "ban", "bans", "delay", "delayed",
    "downgrade", "lawsuit", "fraud", "warning", "loss", "losses",
    "暴跌", "下跌", "新低", "利空", "禁令", "停摆",
)


def _mock_advice(news: NewsItem, asset: ExtractedAsset) -> LLMStrategyAdvice:
    text = f"{news.title} {news.summary or ''}".lower()
    bull_hits = sum(1 for kw in _BULLISH_KW if kw in text)
    bear_hits = sum(1 for kw in _BEARISH_KW if kw in text)

    if bull_hits == bear_hits:
        # Deterministic but "varied" tie-break by hashing the news id so the
        # mock feed isn't all NEUTRAL.
        h = int(hashlib.sha1(news.id.encode()).hexdigest(), 16)
        if h % 3 == 0:
            direction: Direction = "NEUTRAL"
            confidence = 0.30
        elif h % 3 == 1:
            direction = "LONG"
            confidence = 0.55
        else:
            direction = "SHORT"
            confidence = 0.55
    elif bull_hits > bear_hits:
        direction = "LONG"
        confidence = min(0.55 + 0.10 * (bull_hits - bear_hits), 0.85)
    else:
        direction = "SHORT"
        confidence = min(0.55 + 0.10 * (bear_hits - bull_hits), 0.85)

    horizon: Horizon = (
        "INTRADAY" if asset.asset_type in ("CRYPTO", "FX") else "SWING_3D"
    )
    leverage = {"CRYPTO": 3, "STOCK": 2, "FX": 5, "COMMODITY": 3}[asset.asset_type]

    arrow = "做多" if direction == "LONG" else ("做空" if direction == "SHORT" else "观望")
    reasoning = (
        f"【模拟分析】关键词命中：看涨 {bull_hits}、看跌 {bear_hits}。"
        f"事件对 {asset.symbol} 形成{arrow}信号，置信度 {confidence:.2f}。"
        "此结论由本地启发式规则生成（mock 模式），仅用于演示链路。"
    )

    return LLMStrategyAdvice(
        direction=direction,
        confidence=round(confidence, 2),
        suggested_leverage=float(leverage),
        horizon=horizon,
        reasoning_zh=reasoning,
    )


# ---------------------------------------------------------------------------
# Real LLM call
# ---------------------------------------------------------------------------

async def _llm_advice(
    news: NewsItem,
    asset: ExtractedAsset,
    snapshot: MarketSnapshot,
) -> Optional[LLMStrategyAdvice]:
    settings = get_settings()
    try:
        from openai import AsyncOpenAI
    except Exception as e:  # noqa: BLE001
        logger.warning("openai SDK not installed: %s", e)
        return None

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        timeout=settings.llm_timeout_seconds,
    )

    prompt = _load_prompt().format(
        title=news.title,
        summary=news.summary or "(无)",
        published_at=news.published_at.isoformat(),
        symbol=asset.symbol,
        asset_type=asset.asset_type,
        current_price=snapshot.current_price,
        atr=snapshot.atr,
    )

    # Try with native JSON mode first, fall back to plain text if the
    # endpoint rejects `response_format` (some self-hosted / proxy endpoints
    # don't implement it).
    content: Optional[str] = None
    for use_json_mode in (True, False):
        kwargs: dict = dict(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await client.chat.completions.create(**kwargs)
            content = (resp.choices[0].message.content or "").strip()
            break
        except Exception as e:  # noqa: BLE001
            if use_json_mode:
                logger.info(
                    "LLM endpoint rejected json_object mode (%s); retrying as text",
                    e,
                )
                continue
            logger.warning("LLM strategist failed for %s: %s", asset.symbol, e)
            return None

    if not content:
        return None

    try:
        data = json.loads(_strip_code_fence(content))
        return LLMStrategyAdvice.model_validate(data)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "LLM output not parseable for %s: %s. Raw=%r",
            asset.symbol, e, content[:200],
        )
        return None


def _strip_code_fence(s: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrappers some models add."""
    s = s.strip()
    if s.startswith("```"):
        # Drop the opening fence line and the trailing fence.
        lines = s.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def _load_prompt() -> str:
    if not _PROMPT_PATH.exists():
        # Should never happen, but degrade to a minimal inline prompt.
        return (
            'Output JSON: direction(LONG|SHORT|NEUTRAL), confidence(0-1), '
            'suggested_leverage(1-10), horizon(INTRADAY|SWING_3D|SWING_2W), '
            'reasoning_zh. News: {title} / {summary}. Asset: {symbol}.'
        )
    return _PROMPT_PATH.read_text(encoding="utf-8")
