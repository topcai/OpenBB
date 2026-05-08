"""Strategy App — A 'Xiaohongshu-style' financial news + trading-strategy feed.

This package is a thin layer on top of the OpenBB Platform (vendored in
`openbb_platform/`) that:

1. Aggregates multi-market news (stocks, crypto, FX, commodities)
2. Extracts the impacted assets via rules + LLM
3. Pulls real market quotes & ATR via OpenBB
4. Generates a structured trading strategy (direction / leverage / TP / SL)
   using an LLM constrained by a deterministic risk-engine

Nothing in this package modifies OpenBB itself.
"""

__version__ = "0.1.0"
