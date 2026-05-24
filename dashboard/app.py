"""Market Intelligence Dashboard.

Renders the serving (gold) layer produced by `scripts/run_pipeline.py`:
- KPI strip with latest values
- S&P 500 close with fast (10-day) and slow (20-day) SMA overlays
- VIX with horizontal RAG threshold lines at 20 and 30
- Per-day RAG signal history across the window
- DQ transparency section showing quarantined dates from the latest run
- Methodology disclosure for reviewers wanting the depth

Read-only dashboard. The data file is committed to the repo so the dashboard
works without a live pipeline -- see ADR-0001 for the storage decision.

To run locally:
    streamlit run dashboard/app.py
    # or: make dashboard

To deploy:
    Streamlit Community Cloud (free tier) -- point at dashboard/app.py.
    The dashboard reads committed Parquet, so deploys cleanly.

All architectural decisions visible in this dashboard are documented in
ADRs 0001-0006 and METRICS.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --- Configuration ------------------------------------------------------------

# Resolve project root from this file's location so the dashboard works
# regardless of where streamlit is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVING_PATH = PROJECT_ROOT / "data" / "serving" / "serving.parquet"
QUARANTINE_LOG_PATH = PROJECT_ROOT / "logs" / "dq_quarantine.log"

# RAG color palette -- saturated traffic-light tones (not the cartoon primaries).
COLOR_GREEN = "#22c55e"
COLOR_AMBER = "#f59e0b"
COLOR_RED = "#ef4444"
COLOR_NEUTRAL = "#1f2937"  # close price line
COLOR_SMA_FAST = "#3b82f6"  # blue, fast SMA
COLOR_SMA_SLOW = "#8b5cf6"  # purple, slow SMA
COLOR_UNAVAILABLE = "#9ca3af"

RAG_COLORS = {
    "green": COLOR_GREEN,
    "amber": COLOR_AMBER,
    "red": COLOR_RED,
    "unavailable": COLOR_UNAVAILABLE,
}

# RAG signal thresholds (from ADR-0003).
VIX_GREEN_UPPER = 20.0
VIX_RED_LOWER = 30.0


# --- Page setup ---------------------------------------------------------------

st.set_page_config(
    page_title="Post-Trade Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- Data loading -------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_serving_data() -> pd.DataFrame:
    """Load the serving (gold) layer. Returns empty frame if not available."""
    if not SERVING_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(SERVING_PATH).sort_values("date").reset_index(drop=True)
    return df


@st.cache_data(show_spinner=False)
def load_quarantine_log() -> list[dict]:
    """Load all quarantine log entries. Returns empty list if not available."""
    if not QUARANTINE_LOG_PATH.exists():
        return []
    entries: list[dict] = []
    with QUARANTINE_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# --- Sections -----------------------------------------------------------------


def render_header() -> None:
    st.title("Post-Trade Market Intelligence")
    st.caption(
        "90-day market activity dashboard | S&P 500 + VIX | "
        "RAG signal based on volatility regime"
    )


def render_no_data_message() -> None:
    st.error(
        f"**No serving data found.**\n\n"
        f"Expected file: `{SERVING_PATH.relative_to(PROJECT_ROOT)}`\n\n"
        "To produce it, run the pipeline locally:\n\n"
        "```bash\n"
        "# Set FRED_API_KEY in .env (free from https://fred.stlouisfed.org/docs/api/api_key.html)\n"
        "make run\n"
        "```\n\n"
        "Takes about 3 seconds end-to-end. After it completes, refresh this page."
    )


def render_kpi_strip(df: pd.DataFrame) -> None:
    """Top-row KPIs: latest values from the most recent dashboard day."""
    latest = df.iloc[-1]

    col1, col2, col3, col4, col5 = st.columns(5)

    rag = latest["rag_signal"]
    rag_color = RAG_COLORS.get(rag, COLOR_UNAVAILABLE)

    with col1:
        st.metric("Latest Signal", rag.upper())
        st.markdown(
            f"<div style='background-color: {rag_color}; "
            f"height: 8px; border-radius: 4px; margin-top: -8px;'></div>",
            unsafe_allow_html=True,
        )

    with col2:
        pct = latest["sp500_pct_change"]
        delta_str = f"{pct:+.2f}%" if pd.notna(pct) else None
        st.metric(
            "S&P 500 Close",
            f"{latest['sp500_close']:.2f}",
            delta=delta_str,
        )

    with col3:
        st.metric("VIX", f"{latest['vix']:.2f}")

    with col4:
        sma10 = latest["sp500_sma_10"]
        st.metric(
            "SMA 10-day (fast)",
            f"{sma10:.2f}" if pd.notna(sma10) else "n/a",
        )

    with col5:
        sma20 = latest["sp500_sma_20"]
        st.metric(
            "SMA 20-day (slow)",
            f"{sma20:.2f}" if pd.notna(sma20) else "n/a",
        )

    st.caption(
        f"As of **{latest['date'].strftime('%A, %d %B %Y')}**. "
        f"Window: {df['date'].min().strftime('%d %b %Y')} -> "
        f"{df['date'].max().strftime('%d %b %Y')} "
        f"({len(df)} trading days)."
    )


def render_sp500_chart(df: pd.DataFrame) -> None:
    st.subheader("S&P 500 Close with Fast and Slow Moving Averages")

    fig = go.Figure()

    # Slow SMA first so close line ends up on top
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["sp500_sma_20"],
        mode="lines",
        name="SMA 20-day (slow)",
        line=dict(color=COLOR_SMA_SLOW, width=2),
        connectgaps=False,
        hovertemplate="%{x|%d %b %Y}<br>SMA 20: %{y:.2f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["sp500_sma_10"],
        mode="lines",
        name="SMA 10-day (fast)",
        line=dict(color=COLOR_SMA_FAST, width=1.75),
        connectgaps=False,
        hovertemplate="%{x|%d %b %Y}<br>SMA 10: %{y:.2f}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["sp500_close"],
        mode="lines",
        name="Close",
        line=dict(color=COLOR_NEUTRAL, width=2.5),
        hovertemplate="%{x|%d %b %Y}<br>Close: %{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=20, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="S&P 500 Index",
        showlegend=True,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_vix_chart(df: pd.DataFrame) -> None:
    st.subheader("VIX (Volatility Index) with RAG Thresholds")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["vix"],
        mode="lines",
        name="VIX",
        line=dict(color=COLOR_NEUTRAL, width=2),
        connectgaps=False,
        hovertemplate="%{x|%d %b %Y}<br>VIX: %{y:.2f}<extra></extra>",
    ))

    # Horizontal threshold lines at 20 (green/amber) and 30 (amber/red)
    fig.add_hline(
        y=VIX_GREEN_UPPER,
        line=dict(color=COLOR_GREEN, width=1.5, dash="dash"),
        annotation_text=f"Green / Amber threshold ({VIX_GREEN_UPPER:.0f})",
        annotation_position="bottom right",
        annotation_font_color=COLOR_GREEN,
    )
    fig.add_hline(
        y=VIX_RED_LOWER,
        line=dict(color=COLOR_RED, width=1.5, dash="dash"),
        annotation_text=f"Amber / Red threshold ({VIX_RED_LOWER:.0f})",
        annotation_position="top right",
        annotation_font_color=COLOR_RED,
    )

    fig.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=20, b=40),
        hovermode="x unified",
        xaxis_title=None,
        yaxis_title="VIX",
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_rag_history(df: pd.DataFrame) -> None:
    st.subheader("RAG Signal History")

    # Map signal to a numeric value for the heatmap colorscale
    signal_to_num = {"green": 0, "amber": 1, "red": 2, "unavailable": -1}
    z_values = [[signal_to_num.get(s, -1) for s in df["rag_signal"]]]

    fig = go.Figure(go.Heatmap(
        x=df["date"],
        y=["RAG"],
        z=z_values,
        colorscale=[
            [0.0, COLOR_GREEN],
            [0.5, COLOR_AMBER],
            [1.0, COLOR_RED],
        ],
        zmin=0,
        zmax=2,
        showscale=False,
        text=[df["rag_signal"].str.upper().tolist()],
        hovertemplate="%{x|%d %b %Y}<br>Signal: %{text}<extra></extra>",
        xgap=1,
    ))

    fig.update_layout(
        height=120,
        margin=dict(l=20, r=20, t=10, b=30),
        xaxis_title=None,
        yaxis=dict(showticklabels=False, showgrid=False),
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True)

    # Signal distribution summary below the band
    dist = df["rag_signal"].value_counts()
    total = len(df)
    parts: list[str] = []
    for signal in ["green", "amber", "red", "unavailable"]:
        if signal in dist.index:
            count = int(dist[signal])
            pct = count / total * 100
            parts.append(f"**{signal.title()}**: {count} days ({pct:.0f}%)")
    st.caption(" · ".join(parts))


def render_dq_transparency(quarantine_entries: list[dict]) -> None:
    if not quarantine_entries:
        return

    # Pull the latest run's entries -- quarantine log appends across runs,
    # but the dashboard shows the most recent run's state.
    df_q = pd.DataFrame(quarantine_entries)
    if "run_at" in df_q.columns:
        latest_run = df_q["run_at"].max()
        df_q = df_q[df_q["run_at"] == latest_run].reset_index(drop=True)

    label = (
        f"Data Quality -- {len(df_q)} date(s) quarantined in the latest run "
        "(click to expand)"
    )
    with st.expander(label, expanded=False):
        st.markdown(
            "Trading days where one or both sources had missing or invalid data. "
            "Every excluded row is preserved with its full provenance -- **no silent drops**. "
            "See `logs/dq_quarantine.log` for the full audit trail and "
            "ADR-0006 for the alignment policy that produced these decisions."
        )

        display_cols = ["date", "reason", "vix", "sp500_close"]
        display_cols = [c for c in display_cols if c in df_q.columns]
        st.dataframe(
            df_q[display_cols],
            hide_index=True,
            use_container_width=True,
        )


def render_methodology() -> None:
    with st.expander("About this dashboard / methodology", expanded=False):
        st.markdown("""
**Sources**
- VIX: CBOE Volatility Index via the FRED API (series `VIXCLS`), daily close
- S&P 500: Yahoo Finance via `yfinance` (ticker `^GSPC`), daily OHLCV

**Pipeline**
Raw ingestion -> outer-join alignment -> data-quality split -> metric computation -> RAG signal classification. All architectural decisions documented in ADRs 0001-0006 in the repo.

**Metrics**
- **SMA 10-day (fast)** -- captures regime changes the moment they begin
- **SMA 20-day (slow)** -- shows the underlying trend (~one trading month)
- **Daily % change** -- `(close_t - close_{t-1}) / close_{t-1} * 100`

**RAG signal thresholds** (fixed, per ADR-0003)
- VIX < 20 -> **Green** (low volatility regime)
- 20 <= VIX <= 30 -> **Amber** (elevated; monitor)
- VIX > 30 -> **Red** (stressed market)

**Limitations**
- The 10-day SMA is undefined for the first 9 days; the 20-day SMA for the first 19 days. These are rendered as **gaps**, not zeros or interpolated values. A production deployment would fetch an additional lookback window so both SMAs are defined on every dashboard day -- see METRICS.md Metric 1.
- Two typical quarantine cases for a 90-day window: market holidays (one source publishes a null value, the other omits the row) and source publication lag (the most recent trading day hasn't been published yet by the slower source). Both are visible in the Data Quality section above and explained in ADR-0006.
""")


# --- Main ---------------------------------------------------------------------


def main() -> None:
    render_header()

    df = load_serving_data()
    if df.empty:
        render_no_data_message()
        return

    render_kpi_strip(df)
    st.markdown("---")
    render_sp500_chart(df)
    render_vix_chart(df)
    render_rag_history(df)

    quarantine_entries = load_quarantine_log()
    if quarantine_entries:
        st.markdown("---")
        render_dq_transparency(quarantine_entries)

    st.markdown("---")
    render_methodology()


if __name__ == "__main__":
    main()
