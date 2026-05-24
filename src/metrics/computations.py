"""Metric computations for the serving (gold) layer.

Implements the three metrics defined in METRICS.md:

- `sp500_sma_20`     -- 20-day Simple Moving Average of S&P 500 close
- `sp500_pct_change` -- Daily percentage change of S&P 500 close
- `vix`              -- raw VIX value (pass-through from curated; included for
                        completeness in the serving layer)

All functions are pure: they take the curated DataFrame as input and return
either a Series (single metric) or DataFrame (composed serving dataset). No I/O.
The orchestrator in `scripts/run_pipeline.py` reads the curated parquet, calls
these, and writes the result to `data/serving/serving.parquet`.

Design note: `compute_serving_dataset()` preserves all curated columns rather
than trimming to metric-relevant ones. This is deliberate — the dashboard may
add tooltips or secondary panels using `sp500_open`, `sp500_high`, etc, and
making the serving layer narrower now would force an ETL change later. The
columnar storage cost is trivial.

See METRICS.md for the metric contract (plain-language definitions, edge cases,
validation expectations) and ADR-0004 for the architectural separation of
transformation from metric computation.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# Required columns from the curated (silver) layer. Matches the output schema
# of `src/quality/checks.py:assess_alignment`. Validated fail-fast in the
# composed function — individual metric functions trust their inputs.
_REQUIRED_CURATED_COLUMNS = frozenset({"date", "vix", "sp500_close"})

# SMA windows. Two timescales tell different stories: the fast window catches
# regime changes, the slow window shows the underlying trend (~one trading
# month). Documented in METRICS.md. The choice of (10, 20) follows common
# trading-dashboard convention; an ARB-grade production deployment would
# expose both as configuration.
SMA_FAST_WINDOW = 10
SMA_SLOW_WINDOW = 20


# ----------------------------------------------------------------- metrics


def compute_sma(
    curated_df: pd.DataFrame,
    window: int = SMA_SLOW_WINDOW,
) -> pd.Series:
    """Rolling Simple Moving Average of `sp500_close` over `window` trading days.

    For each trading day t in the curated frame, the SMA is the arithmetic
    mean of `sp500_close` on trading days t-(window-1) through t inclusive.
    Trading days are defined by the order of the curated frame — alignment
    has already done the calendar work.

    The composed serving layer computes SMAs at two windows (SMA_FAST_WINDOW=10
    and SMA_SLOW_WINDOW=20) — see `compute_serving_dataset()`.

    Edge cases per METRICS.md:
    - First (window-1) days have undefined SMA -> NaN.
    - Any window containing fewer than `window` valid closes -> NaN
      (pandas' default min_periods behaviour with min_periods=window).

    Args:
        curated_df: Silver-layer DataFrame, must contain `sp500_close`.
        window: Number of trading days in the rolling window. Defaults to
                SMA_SLOW_WINDOW (20).

    Returns:
        Series of SMA values, indexed identically to curated_df.

    Note: The serving layer in v1 keeps the lookback internal to the visible
    curated window — the first (window-1) days of any case-study run will
    have NaN. A production deployment would fetch an additional 20-day window
    beyond the visible range so both SMAs are defined on every dashboard day.
    See the Metric 1 edge cases section in METRICS.md.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    return curated_df["sp500_close"].rolling(window=window, min_periods=window).mean()


def compute_daily_pct_change(curated_df: pd.DataFrame) -> pd.Series:
    """Daily percentage change of `sp500_close`.

    For each trading day t (after the first), returns:

        (close_t - close_{t-1}) / close_{t-1} * 100

    The frame is expected to be sorted by date ascending (alignment ensures this).
    The first row has no prior day and returns NaN.

    Note on calendar handling per METRICS.md: gaps caused by holidays or
    quarantined days are absent from the curated frame entirely. The
    comparison for any row is against the prior *row*, which is the prior
    valid trading day in the curated calendar. This matches industry
    convention (the Tuesday-after-Monday-holiday compares to Friday).

    Args:
        curated_df: Silver-layer DataFrame, must contain `sp500_close` and be
                    sorted by date ascending.

    Returns:
        Series of percentage changes, indexed identically to curated_df.
        First row is NaN.
    """
    return curated_df["sp500_close"].pct_change() * 100.0


def compute_serving_dataset(curated_df: pd.DataFrame) -> pd.DataFrame:
    """Compose the serving (gold) layer from curated data + computed metrics.

    Output columns:
    - All columns from `curated_df` (preserved verbatim, including OHLCV
      and provenance columns — see design note in module docstring)
    - `sp500_sma_10`: fast 10-day rolling SMA of sp500_close
    - `sp500_sma_20`: slow 20-day rolling SMA of sp500_close
    - `sp500_pct_change`: daily percentage change of sp500_close

    The two SMA timescales serve different analytical purposes (fast catches
    regime changes, slow shows the trend), and both are useful in the dashboard.
    See METRICS.md Metric 1 for the rationale.

    Args:
        curated_df: Silver-layer DataFrame produced by the DQ stage.

    Returns:
        Gold-layer DataFrame, sorted by date ascending, with three metric
        columns appended.

    Raises:
        ValueError: if the curated frame is missing required columns.
    """
    missing = _REQUIRED_CURATED_COLUMNS - set(curated_df.columns)
    if missing:
        raise ValueError(
            f"curated DataFrame missing required columns: {sorted(missing)}. "
            f"Got: {sorted(curated_df.columns)}"
        )

    if len(curated_df) == 0:
        # Empty in -> empty out, with the metric columns present so the
        # downstream schema contract holds.
        out = curated_df.copy()
        out["sp500_sma_10"] = pd.Series(dtype="float64")
        out["sp500_sma_20"] = pd.Series(dtype="float64")
        out["sp500_pct_change"] = pd.Series(dtype="float64")
        return out

    # Sort by date ascending — alignment guarantees this, but metrics depend
    # on the order so we re-establish it defensively.
    result = curated_df.sort_values("date").reset_index(drop=True).copy()
    result["sp500_sma_10"] = compute_sma(result, window=SMA_FAST_WINDOW)
    result["sp500_sma_20"] = compute_sma(result, window=SMA_SLOW_WINDOW)
    result["sp500_pct_change"] = compute_daily_pct_change(result)

    logger.info(
        "Computed serving dataset: %d rows | SMA_10 defined on %d rows | "
        "SMA_20 defined on %d rows | pct_change defined on %d rows",
        len(result),
        int(result["sp500_sma_10"].notna().sum()),
        int(result["sp500_sma_20"].notna().sum()),
        int(result["sp500_pct_change"].notna().sum()),
    )
    return result
