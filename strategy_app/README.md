# Strategy App — 金融小红书 Demo

A "Xiaohongshu-style" trading-strategy feed built on top of this OpenBB fork.
For each piece of market news (crypto, stocks, FX, commodities) the backend
produces a **structured** trading strategy card (direction, leverage, entry,
stop-loss, take-profit, position size, margin, reasoning). The Streamlit
frontend displays them as a waterfall feed.

> Demo only. No order routing. All numerics derived from a deterministic
> risk-engine (account = $10,000, 2% risk per trade, ATR-based stops).

---

## Quick start

### 1. Install Python deps

```bash
cd /workspace
# OpenBB itself
pip install -e openbb_platform/core
pip install -e openbb_platform/extensions/news
pip install -e openbb_platform/extensions/crypto
pip install -e openbb_platform/extensions/currency
pip install -e openbb_platform/extensions/equity
pip install -e openbb_platform/extensions/commodity
pip install -e openbb_platform/extensions/technical
pip install openbb-yfinance openbb-fmp openbb-cryptopanic 2>/dev/null || true
# Strategy App deps
pip install -r strategy_app/requirements.txt
```

### 2. Configure

```bash
cp strategy_app/.env.example strategy_app/.env
# Edit strategy_app/.env. Leave USE_MOCK=true for a key-less demo.
```

### 3. Run backend

```bash
bash strategy_app/scripts/run_backend.sh
# → http://127.0.0.1:8088/healthz
# → http://127.0.0.1:8088/feed?limit=10
```

### 4. Run frontend

```bash
bash strategy_app/scripts/run_frontend.sh
# → http://localhost:8501
```

---

## Project layout

```
strategy_app/
├── backend/
│   ├── main.py            # FastAPI entry
│   ├── config.py          # Pydantic settings
│   ├── schemas.py         # Pydantic models (News / Strategy / FeedCard)
│   ├── pipeline.py        # news → strategy orchestration
│   ├── services/
│   │   ├── news_aggregator.py
│   │   ├── cryptopanic_client.py
│   │   ├── asset_extractor.py
│   │   ├── market_data.py
│   │   ├── risk_engine.py     # 100% pure & unit-tested
│   │   └── llm_strategist.py
│   ├── storage/cache.py
│   └── prompts/
├── frontend/streamlit_app.py
├── tests/                 # pytest unit tests
└── scripts/               # run helpers
```

## Required API keys

| Provider | Used for | Free tier | Required |
|---|---|---|---|
| OpenAI (or Kimi / Zhipu) | LLM reasoning | yes (paid usage) | for non-mock |
| FMP | World stock news | 250 req/day | for non-mock |
| CryptoPanic | Crypto news | yes | for non-mock |

If any is missing the corresponding source is skipped or stubbed.

## Risk engine — deterministic numbers

The LLM is **never** allowed to invent a price. It only outputs:
`direction`, `confidence`, `suggested_leverage`, `horizon`, `reasoning_zh`.

All numerics come from `services/risk_engine.py`:

```
account_size       = $10,000
risk_per_trade     = 2%      → $200 max loss per card
sl_distance        = 1.5 × ATR(14, 1h)
tp_distance        = 2.0 × sl_distance       (R:R = 2)
position_size_usd  = risk_amount / (sl_distance / entry)
margin_usd         = position_size_usd / leverage
leverage_cap       = {CRYPTO:5, STOCK:2, FX:10, COMMODITY:5}
```

## Disclaimer

This software is for educational / demo purposes only. Nothing here is
investment advice. Do not trade real money based on its output.
