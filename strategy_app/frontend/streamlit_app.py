"""Streamlit '小红书风格' waterfall feed.

Run:
    bash strategy_app/scripts/run_frontend.sh
or:
    streamlit run strategy_app/frontend/streamlit_app.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="金融小红书 · Strategy Feed",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8088")

ASSET_EMOJI = {
    "CRYPTO": "🪙", "STOCK": "📈", "FX": "💱", "COMMODITY": "🛢️",
}
ASSET_LABEL_ZH = {
    "CRYPTO": "加密", "STOCK": "股票", "FX": "外汇", "COMMODITY": "大宗",
}
DIRECTION_LABEL = {"LONG": "做多", "SHORT": "做空"}
DIRECTION_COLOR = {"LONG": "#2ecc71", "SHORT": "#e74c3c"}
HORIZON_LABEL = {"INTRADAY": "日内", "SWING_3D": "波段·3天", "SWING_2W": "波段·2周"}

# Pleasant gradient palette for image-less cards.
GRADIENTS = [
    "linear-gradient(135deg,#fbc2eb,#a6c1ee)",
    "linear-gradient(135deg,#84fab0,#8fd3f4)",
    "linear-gradient(135deg,#ffecd2,#fcb69f)",
    "linear-gradient(135deg,#a1c4fd,#c2e9fb)",
    "linear-gradient(135deg,#ffd2e8,#fad0c4)",
    "linear-gradient(135deg,#d4fc79,#96e6a1)",
    "linear-gradient(135deg,#cfd9df,#e2ebf0)",
    "linear-gradient(135deg,#fdcbf1,#e6dee9)",
]


# ---------------------------------------------------------------------------
# Custom CSS — 小红书风格卡片
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Tighter top padding */
    div.block-container { padding-top: 1.2rem; padding-bottom: 4rem; }
    /* Card */
    .xhs-card {
        background: white;
        border-radius: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        margin-bottom: 1rem;
        overflow: hidden;
        transition: transform 0.15s ease;
    }
    .xhs-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.10); }
    .xhs-cover {
        width: 100%;
        height: 180px;
        background-size: cover;
        background-position: center;
        display: flex; align-items: center; justify-content: center;
        font-size: 4rem;
        color: rgba(255,255,255,0.85);
        text-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .xhs-body { padding: 12px 14px 6px 14px; }
    .xhs-title {
        font-size: 0.95rem; line-height: 1.35;
        color: #222; font-weight: 600;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
        overflow: hidden; text-overflow: ellipsis;
    }
    .xhs-meta {
        font-size: 0.75rem; color: #999;
        margin-top: 6px;
        display: flex; justify-content: space-between;
    }
    .badge {
        display: inline-block;
        padding: 2px 8px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 600;
        margin-right: 4px;
    }
    .badge-long  { background: #e8f8ef; color: #1e8e4f; }
    .badge-short { background: #fde8e8; color: #c0392b; }
    .badge-asset { background: #f0f2f5; color: #555; }
    .strat-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 4px 12px;
        font-size: 0.78rem; color: #555;
        margin-top: 8px;
    }
    .strat-key { color: #999; }
    .reasoning {
        margin-top: 10px;
        padding: 8px 10px;
        background: #fafafa;
        border-radius: 8px;
        font-size: 0.78rem; color: #444; line-height: 1.4;
    }
    .empty-strat {
        margin-top: 10px;
        padding: 10px;
        background: #fafafa; border-radius: 8px;
        text-align: center; color: #aaa; font-size: 0.78rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 📈 金融小红书\n**Strategy Feed Demo**")
    st.caption("基于新闻的多市场结构化策略推荐")

    selected_asset_types = st.multiselect(
        "市场过滤",
        options=["CRYPTO", "STOCK", "FX", "COMMODITY"],
        default=["CRYPTO", "STOCK", "FX", "COMMODITY"],
        format_func=lambda x: f"{ASSET_EMOJI[x]} {ASSET_LABEL_ZH[x]}",
    )
    only_with_strategy = st.toggle("只看带策略的卡片", value=False)
    limit = st.slider("拉取数量", min_value=5, max_value=50, value=20, step=5)

    st.divider()

    col_a, col_b = st.columns(2)
    if col_a.button("🔄 刷新", use_container_width=True):
        st.session_state["_force_refresh"] = True
    if col_b.button("🧹 清缓存", use_container_width=True):
        try:
            httpx.post(f"{BACKEND_URL}/refresh", params={"limit": limit}, timeout=60)
            st.success("缓存已清空")
        except Exception as e:
            st.error(f"清缓存失败: {e}")

    st.divider()
    try:
        h = httpx.get(f"{BACKEND_URL}/healthz", timeout=5).json()
        mode = "MOCK" if h.get("use_mock") else "LIVE"
        st.caption(f"后端：{BACKEND_URL}")
        st.caption(
            f"模式: **{mode}**  ·  LLM: {'✅' if h.get('has_llm') else '❌'}  "
            f"·  FMP: {'✅' if h.get('has_fmp') else '❌'}  "
            f"·  CryptoPanic: {'✅' if h.get('has_cryptopanic') else '❌'}"
        )
    except Exception:
        st.caption(f"❌ 无法连接后端 {BACKEND_URL}")

    st.divider()
    st.caption(
        "⚠️ 仅供演示。所有策略由规则引擎生成（账户 $10,000，单笔风险 2%），"
        "不构成投资建议。"
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_feed(limit: int, force_refresh: bool) -> list[dict]:
    url = f"{BACKEND_URL}/{'refresh' if force_refresh else 'feed'}"
    method = "post" if force_refresh else "get"
    r = httpx.request(method, url, params={"limit": limit}, timeout=120)
    r.raise_for_status()
    return r.json()


force_refresh = st.session_state.pop("_force_refresh", False)
if force_refresh:
    _load_feed.clear()

with st.spinner("加载中…"):
    try:
        cards = _load_feed(limit, force_refresh)
    except Exception as e:
        st.error(f"无法加载：{e}\n\n请确认后端已启动：`bash strategy_app/scripts/run_backend.sh`")
        st.stop()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _fmt_price(x: float) -> str:
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 10:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


def _fmt_time_zh(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return iso_str
    delta = datetime.now(timezone.utc) - dt
    sec = int(delta.total_seconds())
    if sec < 60: return f"{sec}秒前"
    if sec < 3600: return f"{sec // 60}分钟前"
    if sec < 86400: return f"{sec // 3600}小时前"
    return f"{sec // 86400}天前"


def _filter_card(card: dict) -> bool:
    if only_with_strategy and not card.get("strategies"):
        return False
    if not selected_asset_types:
        return False
    if card.get("strategies"):
        kept = [s for s in card["strategies"]
                if s["asset"]["asset_type"] in selected_asset_types]
        if not kept:
            return False
        # mutate a copy so the original isn't disturbed across reruns
        card["strategies"] = kept
    return True


def _render_card(card: dict, gradient_idx: int) -> str:
    """Return HTML for a single feed card."""
    news = card["news"]
    strategies = card.get("strategies", [])

    # Cover: image if available, else gradient + emoji
    image = news.get("image_url")
    if image:
        cover_html = f'<div class="xhs-cover" style="background-image:url({image})"></div>'
    else:
        # Pick emoji based on first strategy's asset_type, else news source
        emoji = "📰"
        if strategies:
            emoji = ASSET_EMOJI.get(strategies[0]["asset"]["asset_type"], "📰")
        cover_html = (
            f'<div class="xhs-cover" '
            f'style="background:{GRADIENTS[gradient_idx % len(GRADIENTS)]};">{emoji}</div>'
        )

    # Strategies
    strat_html = ""
    if not strategies:
        strat_html = '<div class="empty-strat">本条暂无明确策略</div>'
    else:
        parts = []
        for s in strategies:
            d = s["direction"]
            color = DIRECTION_COLOR[d]
            badge_cls = "badge-long" if d == "LONG" else "badge-short"
            parts.append(
                f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid #f0f0f0;">'
                f'  <div>'
                f'    <span class="badge {badge_cls}">{DIRECTION_LABEL[d]} {s["leverage"]:.0f}×</span>'
                f'    <span class="badge badge-asset">{ASSET_EMOJI[s["asset"]["asset_type"]]} {s["asset"]["symbol"]}</span>'
                f'    <span style="font-size:0.72rem;color:#888;">置信度 {s["confidence"]:.0%}</span>'
                f'  </div>'
                f'  <div class="strat-grid">'
                f'    <div><span class="strat-key">入场</span> {_fmt_price(s["entry_price"])}</div>'
                f'    <div><span class="strat-key">周期</span> {HORIZON_LABEL[s["horizon"]]}</div>'
                f'    <div><span class="strat-key">止损</span> <span style="color:#e74c3c">{_fmt_price(s["stop_loss"])}</span></div>'
                f'    <div><span class="strat-key">止盈</span> <span style="color:#2ecc71">{_fmt_price(s["take_profit"])}</span></div>'
                f'    <div><span class="strat-key">保证金</span> ${s["margin_usd"]:,.0f}</div>'
                f'    <div><span class="strat-key">仓位价值</span> ${s["position_size_usd"]:,.0f}</div>'
                f'    <div><span class="strat-key">单笔风险</span> ${s["risk_amount_usd"]:.0f}</div>'
                f'    <div><span class="strat-key">盈亏比</span> 1:{s["risk_reward_ratio"]:.1f}</div>'
                f'  </div>'
                f'  <div class="reasoning">💡 {s["reasoning_zh"]}</div>'
                f'</div>'
            )
        strat_html = "".join(parts)

    return (
        f'<div class="xhs-card">'
        f'  {cover_html}'
        f'  <div class="xhs-body">'
        f'    <div class="xhs-title">{news["title"]}</div>'
        f'    <div class="xhs-meta">'
        f'      <span>📡 {news["source"]}</span>'
        f'      <span>{_fmt_time_zh(news["published_at"])}</span>'
        f'    </div>'
        f'    {strat_html}'
        f'  </div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Main grid
# ---------------------------------------------------------------------------

filtered = [c for c in cards if _filter_card(c)]

st.markdown(
    f"### 🔥 实时策略推荐  "
    f"<span style='font-size:0.85rem;color:#999;font-weight:normal;'>"
    f"共 {len(filtered)} 条"
    f"</span>",
    unsafe_allow_html=True,
)

if not filtered:
    st.info("当前条件下无内容。试着调整左侧的市场过滤或刷新。")
    st.stop()

NUM_COLS = 3
cols = st.columns(NUM_COLS, gap="small")

for i, card in enumerate(filtered):
    with cols[i % NUM_COLS]:
        st.markdown(_render_card(card, gradient_idx=i), unsafe_allow_html=True)
