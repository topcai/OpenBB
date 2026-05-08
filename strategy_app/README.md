# Strategy App — 金融小红书 Demo

A "Xiaohongshu-style" trading-strategy feed built on top of this OpenBB fork.

For each piece of market news (crypto, stocks, FX, commodities) the backend
produces a **structured** trading strategy card — direction, leverage, entry,
stop-loss, take-profit, position size, margin, reasoning. The Streamlit
frontend displays them as a 3-column waterfall feed.

> ⚠️ Demo only. No order routing. All numerics derived from a deterministic
> risk-engine (account = $10,000, 2% risk per trade, ATR-based stops). Nothing
> here is investment advice.

![demo](../assets/.placeholder)

---

## TL;DR — Run in 2 minutes (no API keys needed)

```bash
cd /workspace

# 1. Install deps
pip install -r strategy_app/requirements.txt

# 2. Configure (defaults are mock mode → no keys required)
cp strategy_app/.env.example strategy_app/.env

# 3. Start backend (FastAPI on :8088)
bash strategy_app/scripts/run_backend.sh
#   → http://127.0.0.1:8088/healthz
#   → http://127.0.0.1:8088/feed?limit=10
#   → http://127.0.0.1:8088/docs

# 4. Start frontend in another shell (Streamlit on :8501)
bash strategy_app/scripts/run_frontend.sh
#   → http://localhost:8501
```

That's it. You'll see ~10 sample news items, each rendered as a Xiaohongshu-style
card with one or more structured strategy recommendations.

---

## Switching from mock to real data

Edit `strategy_app/.env`:

```bash
USE_MOCK=false

# LLM — pick one provider; OpenAI is easiest. Kimi/Zhipu work via base_url.
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
# Kimi:  OPENAI_BASE_URL=https://api.moonshot.cn/v1   LLM_MODEL=moonshot-v1-8k
# Zhipu: OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4   LLM_MODEL=glm-4-flash

# News providers — at least one of these for real data
FMP_API_KEY=...           # https://site.financialmodelingprep.com/ (250/day free)
CRYPTOPANIC_AUTH_TOKEN=...# https://cryptopanic.com/developers/api/ (free)
```

Then `POST /refresh` (or click "🧹 清缓存" in the sidebar) to pull live news.

| Source | Used for | Free tier | Required |
|---|---|---|---|
| OpenAI / Kimi / Zhipu | LLM reasoning | yes (paid usage) | non-mock |
| FMP | Stocks / FX / commodities news (via OpenBB) | 250 req/day | non-mock |
| CryptoPanic | Crypto news | yes | optional |
| yfinance | Real-time prices + ATR for all markets | free, no key | always |

If a key is missing the corresponding source is silently skipped — the demo
will still produce strategies for the other markets.

---

## Architecture

```
                     ┌───────────────────────────────────────┐
                     │  Streamlit frontend  (:8501)          │
                     │  小红书 3-column waterfall            │
                     └────────────────┬──────────────────────┘
                                      │ HTTP JSON
                                      ▼
       ┌─────────────────────────────────────────────────────────┐
       │  Strategy Service  (FastAPI :8088)                      │
       │   GET  /healthz                                         │
       │   GET  /feed?limit=20         cached FeedCard list      │
       │   POST /refresh               wipe cache + rebuild      │
       │                                                         │
       │  Pipeline:                                              │
       │   news_aggregator → asset_extractor → market_data       │
       │      → llm_strategist → risk_engine → cache             │
       └────┬───────────────────┬───────────────┬────────────────┘
            │                   │               │
            ▼                   ▼               ▼
  ┌──────────────────┐  ┌──────────────┐  ┌────────────────────┐
  │ OpenBB (FMP news)│  │  yfinance    │  │ OpenAI/Kimi/Zhipu  │
  │  + CryptoPanic   │  │ price + ATR  │  │  LLM strategist    │
  └──────────────────┘  └──────────────┘  └────────────────────┘
```

OpenBB itself is **not modified** — `strategy_app/` is a sibling package that
imports `openbb` only when the FMP path is enabled.

---

## Risk engine — deterministic numbers

The LLM is **never** allowed to invent a price. It only outputs five fields:
`direction`, `confidence`, `suggested_leverage`, `horizon`, `reasoning_zh`.

All numerics come from `services/risk_engine.py` (100 % unit-tested):

```
account_size       = $10,000
risk_per_trade     = 2%      → $200 max loss per card
sl_distance        = 1.5 × ATR(14, 1h)
tp_distance        = 2.0 × sl_distance       (R:R = 2)
position_size_usd  = risk_amount / (sl_distance / entry)
margin_usd         = position_size_usd / leverage
leverage_cap       = {CRYPTO:5, STOCK:2, FX:10, COMMODITY:5}
```

Example (BTC at $70,500 with ATR $1,500, LLM says LONG / suggested 10x):

```
leverage          = min(10, 5) = 5×                  (capped, CRYPTO)
sl_distance       = 1.5 × 1500 = $2,250
tp_distance       = 2.0 × 2250 = $4,500
stop_loss         = 70500 - 2250 = $68,250
take_profit       = 70500 + 4500 = $75,000
risk_amount       = $200
pct_to_sl         = 2250 / 70500 = 3.19 %
position_size_usd = 200 / 0.0319 = $6,266.67
margin_usd        = 6266.67 / 5 = $1,253.33
```

Same news feeding the LLM with `suggested_leverage=10` will always yield the
same TP/SL — only the LLM-controlled fields can drift.

---

## Project layout

```
strategy_app/
├── backend/
│   ├── main.py                # FastAPI entry
│   ├── config.py              # pydantic-settings, .env loader
│   ├── schemas.py             # NewsItem / Strategy / FeedCard / LLMStrategyAdvice
│   ├── pipeline.py            # news → strategy orchestration
│   ├── services/
│   │   ├── news_aggregator.py   # OpenBB + CryptoPanic + mock fixture
│   │   ├── cryptopanic_client.py
│   │   ├── asset_extractor.py   # 50+ symbols, rules + LLM fallback
│   │   ├── market_data.py       # yfinance price + Wilder ATR
│   │   ├── risk_engine.py       # ⭐ deterministic, fully unit-tested
│   │   └── llm_strategist.py    # OpenAI-compatible (works with Kimi/Zhipu)
│   ├── storage/cache.py       # SQLite TTL cache
│   └── prompts/strategy.md    # 中文 prompt
├── frontend/
│   └── streamlit_app.py       # 3-column 小红书风格瀑布流
├── tests/
│   ├── test_risk_engine.py    # 14 tests
│   ├── test_schemas.py        #  3 tests
│   └── fixtures/sample_news.json
├── scripts/
│   ├── run_backend.sh
│   └── run_frontend.sh
├── .env.example
├── README.md
└── requirements.txt
```

## Run the tests

```bash
cd /workspace
python3 -m pytest strategy_app/tests/ -v
```

## API

```bash
curl http://127.0.0.1:8088/healthz
curl http://127.0.0.1:8088/feed?limit=5 | jq .
curl -X POST http://127.0.0.1:8088/refresh
```

Interactive docs: http://127.0.0.1:8088/docs

## Disclaimer

This software is for educational and demonstration purposes only.
Nothing in this repository constitutes investment, financial, or trading
advice. Past performance and back-tested numbers do not guarantee future
results. Trading derivatives with leverage carries the risk of losing more
than your initial deposit. Do not trade real money based on the output of
this code.
