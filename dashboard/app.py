"""Streamlit entry point: streamlit run dashboard/app.py."""
# ruff: noqa: E402 -- Streamlit launches this file with dashboard/ on sys.path.

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import session_demo
from dashboard.data import load_report
from src.calendar import latest_completed
from src.config import Settings

st.set_page_config(
    page_title="Quant Trading | Portfolio", page_icon=":material/monitoring:", layout="wide"
)
st.markdown(
    """<style>
.block-container {padding-top:2rem; max-width:1440px;}
h1 {font-size:2rem !important; letter-spacing:0 !important;}
h2,h3 {letter-spacing:0 !important;}
[data-testid="stMetricValue"] {font-size:1.65rem;}
[data-testid="stMetricLabel"] {color:#525b63;}
@media (max-width:760px) {
 [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
   display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:1rem;
 }
 [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div {
   width:100% !important; min-width:0 !important;
 }
 [data-testid="stMetricValue"] {font-size:1.35rem;}
}
</style>""",
    unsafe_allow_html=True,
)

settings = Settings.from_env()
mode = st.segmented_control("Account", ["Historical demo", "Live paper"], default="Historical demo")
demo_mode = mode != "Live paper"
st.title("Historical Simulation — Paper Money Only" if demo_mode else "Live Paper Portfolio")

if demo_mode:
    st.caption("SPY · QQQ · AAPL · NVDA · MSFT | 20 / 50 SMA | $100,000 starting capital")
    with st.form("demo"):
        left, right = st.columns(2)
        start = left.date_input("Start", date(2025, 1, 1))
        end = right.date_input("End", date.fromisoformat(latest_completed()))
        submitted = st.form_submit_button(
            "Run Demo Simulation", icon=":material/play_arrow:", type="primary"
        )
    if submitted:
        try:
            with st.spinner("Downloading five-symbol history and simulating trading sessions…"):
                result = session_demo.run_session_demo(start.isoformat(), end.isoformat(), settings)
            st.session_state["demo_report"] = result
            st.session_state["demo_requested_end"] = end.isoformat()
        except Exception as exc:
            st.error(f"Demo unavailable: {exc}")
            if "demo_report" in st.session_state:
                st.warning(
                    "Showing the previous successful simulation; this request did not replace it."
                )

with st.sidebar:
    st.header("Quant Trading")
    st.caption("PAPER ACCOUNTS ONLY")
    if not demo_mode:
        st.caption("LIVE PAPER · READ ONLY")
    if st.button("Refresh", icon=":material/refresh:", width="stretch"):
        st.rerun()

if demo_mode:
    report = st.session_state.get("demo_report")
    if report is None:
        st.metric("Starting capital", "$100,000.00")
        st.stop()
else:
    try:
        report = load_report(settings.database, expect_demo=False)
    except Exception:
        st.warning(
            "No live paper account is connected to this deployment. Historical demo is available independently."
        )
        st.stop()

history = report.snapshots
last = history.iloc[-1]
as_of = last["date"].date().isoformat()
if demo_mode and as_of < st.session_state.get("demo_requested_end", as_of):
    st.info(f"Results end on {as_of}, the latest common trading session with available data.")
st.caption(
    f"{'HISTORICAL DEMO' if demo_mode else 'LIVE PAPER'}  ·  {report.strategy}  ·  As of {as_of} close  ·  USD"
)
if not demo_mode and as_of != latest_completed():
    st.warning(f"Stale account snapshot: {as_of}. Latest completed session: {latest_completed()}.")
alpha = last.cumulative_return - last.spy_return
comparison = (
    "Outperformed SPY"
    if alpha > 0.00000001
    else "Underperformed SPY"
    if alpha < -0.00000001
    else "Matched SPY"
)
color = "green" if alpha >= 0 else "red"
st.markdown(f"### :{color}[{comparison} by {abs(alpha) * 100:.2f} percentage points]")
st.caption(
    f"Since {history.iloc[0]['date'].date()} · Strategy {last.cumulative_return:+.2%} · SPY total return {last.spy_return:+.2%}"
)

cols = st.columns(4)
cols[0].metric("Portfolio value", f"${last.equity:,.2f}")
cols[1].metric("Cash", f"${last.cash:,.2f}")
cols[2].metric(
    "Latest session P&L" if demo_mode or as_of != date.today().isoformat() else "Today's P&L",
    f"${last.daily_pnl:+,.2f}",
    f"{last.daily_return:+.2%}",
)
cols[3].metric("Total return", f"{last.cumulative_return:+.2%}")
cols = st.columns(4)
cols[0].metric("SPY return", f"{last.spy_return:+.2%}")
cols[1].metric(
    "Alpha vs SPY",
    f"{alpha * 100:+.2f} pp",
    help="Cumulative return difference, not regression alpha.",
)
sharpe = report.metrics["sharpe_ratio"]
cols[2].metric("Sharpe ratio", "N/A" if sharpe is None else f"{sharpe:.2f}")
cols[3].metric("Maximum drawdown", f"{report.metrics['maximum_drawdown']:.2%}")
cols = st.columns(2)
cols[0].metric("Starting capital", "$100,000.00")
cols[1].metric("Number of trades", str(len(report.trades)))
st.divider()

period = st.segmented_control("Chart period", ["All", "1Y", "6M", "3M"], default="All")
shown = (
    history
    if period == "All"
    else history[
        history.date >= last["date"] - pd.DateOffset(months={"1Y": 12, "6M": 6, "3M": 3}[period])
    ]
)


def line_chart(columns: dict[str, tuple[str, str]], percent: bool = False) -> go.Figure:
    fig = go.Figure()
    for label, (column, shade) in columns.items():
        fig.add_trace(
            go.Scatter(
                x=shown.date,
                y=shown[column],
                name=label,
                mode="lines",
                line={"color": shade, "width": 2.5},
            )
        )
    fig.update_layout(
        height=350,
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#30383d"),
    )
    fig.update_yaxes(tickformat=".0%" if percent else "$,.0f", gridcolor="#e7ebed")
    return fig


equity, relative = st.columns(2)
with equity:
    st.subheader("Portfolio equity")
    fig = line_chart({"Portfolio": ("equity", "#087e8b")})
    fig.add_hline(y=100000, line_dash="dot", line_color="#8a959e")
    st.plotly_chart(fig, width="stretch")
with relative:
    st.subheader("Strategy vs SPY")
    st.plotly_chart(
        line_chart(
            {"Strategy": ("cumulative_return", "#087e8b"), "SPY": ("spy_return", "#b15b22")}, True
        ),
        width="stretch",
    )

positions_tab, trades_tab, daily_tab = st.tabs(
    ["Final positions" if demo_mode else "Current positions", "Recent trades", "Daily P&L history"]
)
with positions_tab:
    if report.positions.empty:
        st.info("No open positions. Account is in cash.")
    else:
        st.dataframe(
            report.positions,
            hide_index=True,
            width="stretch",
            column_config={
                col: st.column_config.NumberColumn(format="$%.2f")
                for col in report.positions
                if "($)" in col
            },
        )
with trades_tab:
    side = st.segmented_control("Side", ["All", "BUY", "SELL"], default="All")
    trades = report.trades if side == "All" else report.trades[report.trades.side == side]
    st.dataframe(
        trades.head(100),
        hide_index=True,
        width="stretch",
        column_config={
            "timestamp": "Execution time (UTC)",
            "symbol": "Symbol",
            "side": "Side",
            "quantity": st.column_config.NumberColumn("Shares", format="%.4f"),
            "price": st.column_config.NumberColumn("Execution price", format="$%.2f"),
            "cost": st.column_config.NumberColumn("Fees", format="$%.2f"),
            "realized": st.column_config.NumberColumn("Realized P&L", format="$%.2f"),
        },
    )
    st.download_button(
        "Download trades",
        report.trades.to_csv(index=False),
        "trades.csv",
        "text/csv",
        icon=":material/download:",
    )
with daily_tab:
    fig = go.Figure(
        go.Bar(
            x=shown.date,
            y=shown.daily_pnl,
            marker_color=["#087f5b" if x >= 0 else "#c43e45" for x in shown.daily_pnl],
        )
    )
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), yaxis_tickprefix="$")
    st.plotly_chart(fig, width="stretch")
    daily = history[
        ["date", "equity", "daily_pnl", "daily_return", "cumulative_return", "spy_return"]
    ].copy()
    for column in ("daily_return", "cumulative_return", "spy_return"):
        daily[column] *= 100
    st.dataframe(
        daily.sort_values("date", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "date": st.column_config.DateColumn("Session", format="YYYY-MM-DD"),
            "equity": st.column_config.NumberColumn("Equity", format="$%.2f"),
            "daily_pnl": st.column_config.NumberColumn("Daily P&L", format="$%.2f"),
            "daily_return": st.column_config.NumberColumn("Daily return", format="%.2f%%"),
            "cumulative_return": st.column_config.NumberColumn("Total return", format="%.2f%%"),
            "spy_return": st.column_config.NumberColumn("SPY return", format="%.2f%%"),
        },
    )
    st.download_button(
        "Download daily history",
        history.to_csv(index=False),
        "daily-history.csv",
        "text/csv",
        icon=":material/download:",
    )
