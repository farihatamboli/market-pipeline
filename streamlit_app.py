"""
streamlit_app/app.py — Streamlit research dashboard.

A separate, analyst-facing UI for deep-dive research:
  - Historical tick explorer with full OHLCV
  - Signal quality analysis with forward returns
  - P&L simulation runner with interactive config
  - Correlation heatmap across symbols
  - Live benchmark results viewer

Run:
    pip install streamlit
    streamlit run streamlit_app/app.py

Or with custom DB:
    TIMESCALE_URL=postgresql://... streamlit run streamlit_app/app.py
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(
    page_title   = "MDP Research Dashboard",
    page_icon    = "📈",
    layout       = "wide",
    initial_sidebar_state = "expanded",
)

# ── Dark theme CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #07090d; }
[data-testid="stSidebar"] { background: #0c1118; border-right: 1px solid #1c2b3a; }
.metric-card {
    background: #0c1118; border: 1px solid #1c2b3a; border-radius: 6px;
    padding: 16px; margin: 4px 0;
}
h1, h2, h3 { color: #e2eef8 !important; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ───────────────────────────────────────────────────────────────

@st.cache_resource
def get_store():
    """Try TimescaleDB first, fall back to SQLite."""
    import os
    if os.environ.get("TIMESCALE_URL"):
        try:
            from src.timescale_store import TimescaleStore
            store = TimescaleStore(); store.initialize()
            return store, "TimescaleDB"
        except Exception as e:
            st.warning(f"TimescaleDB unavailable: {e} — using SQLite")

    from src.storage import DataStore
    store = DataStore(); store.initialize()
    return store, "SQLite"


@st.cache_data(ttl=60)
def load_ticks(symbol: str, n: int = 500) -> pd.DataFrame:
    store, _ = get_store()
    ticks = store.get_recent(symbol, n)
    if not ticks:
        # Demo data
        random.seed(42)
        base = {"AAPL":182,"MSFT":415,"NVDA":875,"TSLA":175,"SPY":512}.get(symbol,150)
        p, now = float(base), datetime.utcnow()
        rows = []
        for i in range(n):
            p += random.gauss(0, base*0.001)
            rows.append({
                "timestamp": now - timedelta(minutes=n-i),
                "price": round(p,2), "volume": int(random.lognormvariate(11,.8)),
                "open": round(p-.1,2), "high": round(p+.3,2),
                "low": round(p-.3,2), "vwap": round(p+random.gauss(0,.1),2)
            })
        return pd.DataFrame(rows)

    df = pd.DataFrame([{
        "timestamp": t.timestamp, "price": t.price, "volume": t.volume,
        "open": t.open, "high": t.high, "low": t.low, "vwap": t.vwap,
    } for t in ticks])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def run_backtest(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """Run signal detection and return DataFrame of signals with forward returns."""
    from src.fetcher import Tick
    from src.signals import SignalDetector, Signal

    detector = SignalDetector()
    records  = []

    ticks = [Tick(
        symbol=symbol, timestamp=row.timestamp, price=row.price,
        volume=row.volume, open=row.open, high=row.high, low=row.low, vwap=row.vwap
    ) for row in df.itertuples()]

    for i in range(20, len(ticks)):
        history = ticks[max(0, i-50):i+1]
        for sig in detector.detect(ticks[i], history):
            row = {
                "ts": sig.timestamp, "type": sig.signal_type,
                "price": sig.price, "message": sig.message,
            }
            for fwd in [1, 5, 15]:
                if i+fwd < len(ticks):
                    fp = ticks[i+fwd].price
                    row[f"ret_{fwd}m"] = round((fp - sig.price)/sig.price*100, 4)
            records.append(row)

    return pd.DataFrame(records) if records else pd.DataFrame()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    _, db_type = get_store()
    st.caption(f"Database: **{db_type}**")

    SYMBOLS = ["AAPL","MSFT","NVDA","TSLA","SPY","META","GOOGL","AMZN","JPM","V"]
    symbol = st.selectbox("Primary Symbol", SYMBOLS, index=0)
    compare_syms = st.multiselect("Compare Symbols", [s for s in SYMBOLS if s!=symbol], default=["MSFT","SPY"])
    n_ticks = st.slider("Ticks to load", 100, 1000, 300, 50)

    st.markdown("---")
    st.markdown("### P&L Simulator")
    sim_capital = st.number_input("Capital ($)", 10_000, 1_000_000, 100_000, step=10_000)
    sim_size    = st.slider("Position size (%)", 1, 20, 5) / 100
    sim_hold    = st.slider("Hold bars", 5, 60, 15)
    sim_stop    = st.slider("Stop loss (%)", 0.1, 2.0, 0.5) / 100
    run_sim_btn = st.button("▶ Run Simulation", type="primary")

# ── Load data ─────────────────────────────────────────────────────────────────
df = load_ticks(symbol, n_ticks)

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(f"# 📈 MDP Research Dashboard")
st.caption(f"Symbol: **{symbol}** · {len(df):,} ticks loaded · DB: {db_type}")

# ── Metrics row ────────────────────────────────────────────────────────────────
if not df.empty:
    last = df.iloc[-1]
    first_p = df["price"].iloc[0]
    chg_pct = (last.price - first_p) / first_p * 100

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Last Price",  f"${last.price:.2f}", f"{chg_pct:+.2f}%")
    c2.metric("High",        f"${df['high'].max():.2f}")
    c3.metric("Low",         f"${df['low'].min():.2f}")
    c4.metric("VWAP",        f"${df['vwap'].mean():.2f}")
    c5.metric("Avg Volume",  f"{df['volume'].mean():,.0f}")

# ── Tabs ────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Price Explorer",
    "🔬 Signal Analysis",
    "💰 P&L Simulator",
    "🔗 Correlation",
    "⚡ Benchmarks",
])

# ── Tab 1: Price Explorer ──────────────────────────────────────────────────────
with tab1:
    st.subheader(f"{symbol} — Price & Indicators")
    if not df.empty:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        # Compute indicators
        prices = df["price"].values
        ma20 = pd.Series(prices).rolling(20).mean()
        ma50 = pd.Series(prices).rolling(50).mean()
        bb_mid = ma20
        bb_std = pd.Series(prices).rolling(20).std()
        bb_up  = bb_mid + 2*bb_std
        bb_lo  = bb_mid - 2*bb_std

        fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3], shared_xaxes=True, vertical_spacing=0.04)

        # Price
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["price"], name="Price",
            line=dict(color="#00e5a0", width=1.5), fill="tozeroy",
            fillcolor="rgba(0,229,160,0.05)"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["vwap"], name="VWAP",
            line=dict(color="#f5a623", width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=ma20, name="MA20",
            line=dict(color="#38bdf8", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=ma50, name="MA50",
            line=dict(color="#a78bfa", width=1)), row=1, col=1)
        # BB
        fig.add_trace(go.Scatter(x=df["timestamp"], y=bb_up, name="BB Upper",
            line=dict(color="rgba(167,139,250,0.4)", width=1, dash="dash"), showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=bb_lo, name="BB Lower",
            line=dict(color="rgba(167,139,250,0.4)", width=1, dash="dash"),
            fill="tonexty", fillcolor="rgba(167,139,250,0.05)"), row=1, col=1)

        # Volume
        fig.add_trace(go.Bar(x=df["timestamp"], y=df["volume"], name="Volume",
            marker_color="rgba(56,189,248,0.3)", marker_line_color="#38bdf8", marker_line_width=0.5), row=2, col=1)

        fig.update_layout(
            height=500, template="plotly_dark", paper_bgcolor="#07090d", plot_bgcolor="#0c1118",
            margin=dict(l=0,r=0,t=20,b=0), legend=dict(orientation="h", y=1.02),
            xaxis_showgrid=True, xaxis_gridcolor="#1c2b3a",
            yaxis_showgrid=True,  yaxis_gridcolor="#1c2b3a",
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 2: Signal Analysis ─────────────────────────────────────────────────────
with tab2:
    st.subheader("Signal Quality Analysis")
    with st.spinner("Running signal detection..."):
        sig_df = run_backtest(symbol, df)

    if sig_df.empty:
        st.info("No signals detected in this data range. Try increasing tick count.")
    else:
        st.metric("Total Signals", len(sig_df))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Signal Frequency**")
            counts = sig_df["type"].value_counts().reset_index()
            counts.columns = ["Signal Type", "Count"]
            st.dataframe(counts, use_container_width=True, hide_index=True)

        with col2:
            st.markdown("**Forward Return Summary**")
            ret_cols = [c for c in sig_df.columns if c.startswith("ret_")]
            if ret_cols:
                summary = sig_df.groupby("type")[ret_cols].agg(["mean","std"]).round(4)
                st.dataframe(summary, use_container_width=True)

        st.markdown("**Hit Rates**")
        if "ret_5m" in sig_df.columns:
            hit_rates = sig_df.groupby("type")["ret_5m"].apply(lambda x: (x>0).mean()*100).round(1)
            for sig_type, hr in hit_rates.items():
                color = "🟢" if hr > 55 else "🟡" if hr > 45 else "🔴"
                st.markdown(f"{color} **{sig_type}**: {hr}% hit rate at +5m")

        with st.expander("View all signals"):
            st.dataframe(sig_df, use_container_width=True, hide_index=True)

# ── Tab 3: P&L Simulator ──────────────────────────────────────────────────────
with tab3:
    st.subheader("Paper Trading P&L Simulator")
    if run_sim_btn or st.session_state.get("sim_ran"):
        st.session_state["sim_ran"] = True
        from src.pnl_simulator import PnLSimulator, SimConfig
        from src.fetcher import Tick as T
        from src.signals import SignalDetector

        cfg = SimConfig(initial_capital=sim_capital, position_size=sim_size,
                        hold_bars=sim_hold, stop_loss_pct=sim_stop)
        sim = PnLSimulator(cfg); detector = SignalDetector(); history = []
        ticks = [T(symbol=symbol,timestamp=r.timestamp,price=r.price,volume=r.volume,
                   open=r.open,high=r.high,low=r.low,vwap=r.vwap) for r in df.itertuples()]

        for tick in ticks:
            history.append(tick)
            for sig in detector.detect(tick, history[-50:]):
                sim.on_signal(sig)
            sim.on_tick(tick)

        report = sim.report()
        if "error" in report:
            st.warning(report["error"])
        else:
            s = report["summary"]; t = report["trade_stats"]; k = report["risk_metrics"]
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Final Capital", f"${s['final_capital']:,.0f}", f"{s['total_return_pct']:+.2f}%")
            c2.metric("Hit Rate",      f"{t['hit_rate_pct']}%")
            c3.metric("Sharpe",        f"{k['sharpe_ratio']}")
            c4.metric("Max Drawdown",  f"{k['max_drawdown_pct']}%")

            # Equity curve
            if report["equity_curve"]:
                eq_df = pd.DataFrame(report["equity_curve"])
                eq_df["ts"] = pd.to_datetime(eq_df["ts"])
                import plotly.express as px
                fig = px.line(eq_df, x="ts", y="equity", title="Equity Curve",
                    template="plotly_dark", color_discrete_sequence=["#00e5a0"])
                fig.update_layout(paper_bgcolor="#07090d", plot_bgcolor="#0c1118",
                    margin=dict(l=0,r=0,t=40,b=0))
                fig.add_hline(y=sim_capital, line_dash="dot", line_color="#f5a623", annotation_text="Initial capital")
                st.plotly_chart(fig, use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Trade Stats**")
                st.dataframe(pd.DataFrame([t]).T.rename(columns={0:"Value"}), use_container_width=True)
            with col2:
                st.markdown("**By Signal Type**")
                st.dataframe(pd.DataFrame(report["by_signal_type"]).T, use_container_width=True)
    else:
        st.info("Configure parameters in the sidebar and click **▶ Run Simulation**")

# ── Tab 4: Correlation ─────────────────────────────────────────────────────────
with tab4:
    st.subheader("Cross-Symbol Correlation")
    all_syms = [symbol] + compare_syms

    with st.spinner(f"Loading data for {all_syms}..."):
        price_data = {}
        for sym in all_syms:
            d = load_ticks(sym, n_ticks)
            if not d.empty:
                price_data[sym] = d.set_index("timestamp")["price"]

    if len(price_data) >= 2:
        price_df = pd.DataFrame(price_data).dropna()
        returns  = price_df.pct_change().dropna()
        corr     = returns.corr()

        import plotly.graph_objects as go
        fig = go.Figure(go.Heatmap(
            z=corr.values, x=corr.columns, y=corr.index,
            colorscale=[[0,"#ff4060"],[0.5,"#0c1118"],[1,"#00e5a0"]],
            zmid=0, zmin=-1, zmax=1,
            text=corr.round(2).values, texttemplate="%{text}",
        ))
        fig.update_layout(
            title="Return Correlation Matrix",
            template="plotly_dark", paper_bgcolor="#07090d", plot_bgcolor="#0c1118",
            margin=dict(l=0,r=0,t=50,b=0), height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Normalised price chart
        st.markdown("**Normalised Price (% from start)**")
        norm = price_df.div(price_df.iloc[0]) * 100 - 100
        import plotly.express as px
        COLORS_LIST = ["#00e5a0","#38bdf8","#f5a623","#a78bfa","#ff4060","#fb923c"]
        fig2 = go.Figure()
        for i, sym in enumerate(norm.columns):
            fig2.add_trace(go.Scatter(x=norm.index, y=norm[sym], name=sym,
                line=dict(color=COLORS_LIST[i % len(COLORS_LIST)], width=1.5)))
        fig2.update_layout(
            template="plotly_dark", paper_bgcolor="#07090d", plot_bgcolor="#0c1118",
            margin=dict(l=0,r=0,t=20,b=0), height=350, yaxis_ticksuffix="%"
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Select at least 2 symbols in the sidebar for correlation analysis.")

# ── Tab 5: Benchmarks ─────────────────────────────────────────────────────────
with tab5:
    st.subheader("⚡ Pipeline Performance Benchmarks")
    results_path = Path("benchmarks/results/latest.json")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ Run Benchmarks Now", type="primary"):
            with st.spinner("Running benchmarks (~30s)..."):
                import subprocess
                result = subprocess.run(
                    [sys.executable, "benchmarks/bench_pipeline.py", "--ticks", "500"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    st.success("Benchmarks complete!")
                else:
                    st.error(f"Error: {result.stderr}")
    with col2:
        st.caption("Runs signal detection, storage, and E2E latency profiling")

    if results_path.exists():
        import json
        data = json.loads(results_path.read_text())
        ts   = data.get("timestamp","")[:19]
        st.caption(f"Last run: {ts}")

        det = data.get("signal_detection", {})
        e2e = data.get("e2e", {})
        mem = data.get("memory", {})

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Detection Mean",    f"{det.get('mean_ms','—')} ms")
        c2.metric("Detection P99",     f"{det.get('p99_ms','—')} ms")
        c3.metric("E2E Mean",          f"{e2e.get('mean_ms','—')} ms")
        c4.metric("Peak Memory",       f"{mem.get('peak_kb','—')} KB")

        # Per-detector table
        per_det = data.get("per_detector", [])
        if per_det:
            st.markdown("**Per-Detector Latency**")
            st.dataframe(pd.DataFrame(per_det), use_container_width=True, hide_index=True)

        # Benchmark image
        img_path = Path("benchmarks/results/latest.png")
        if img_path.exists():
            st.image(str(img_path), caption="Latency distributions", use_column_width=True)
    else:
        st.info("No benchmark results yet. Click **▶ Run Benchmarks Now** above.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Market Data Pipeline — Research Dashboard · [GitHub](https://github.com/YOUR_USERNAME/market-pipeline)")
