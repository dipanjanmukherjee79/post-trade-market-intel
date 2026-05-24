"""Tests for src/metrics/computations.py.

Coverage:
- SMA: first (window-1) rows are NaN; subsequent rows match arithmetic mean
- SMA: NaN in the window propagates (min_periods=window)
- SMA: invalid window argument raises
- Daily % change: first row NaN, subsequent rows match formula
- Daily % change: gap (quarantined day absent) compares against prior present row
- compose: serving dataset has all curated columns + 2 metric columns
- compose: empty curated -> empty serving with metric columns present
- compose: missing required column raises
- compose: sort order is enforced even if input is shuffled
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.metrics.computations import (
    SMA_FAST_WINDOW,
    SMA_SLOW_WINDOW,
    compute_daily_pct_change,
    compute_serving_dataset,
    compute_sma,
)


# --------------------------------------------------------------------- builders


def _curated_frame(dates: list[str], closes: list[float | None]) -> pd.DataFrame:
    """Build a frame that mimics the curated (silver) layer schema."""
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "vix": [18.0 + (i % 5) for i in range(n)],
            "sp500_open": [(c - 5) if c is not None else None for c in closes],
            "sp500_high": [(c + 10) if c is not None else None for c in closes],
            "sp500_low": [(c - 10) if c is not None else None for c in closes],
            "sp500_close": closes,
            "sp500_volume": [1_000_000_000] * n,
            "vix_fetched_at": pd.Timestamp("2026-05-23 07:30:00", tz="UTC"),
            "sp500_fetched_at": pd.Timestamp("2026-05-23 07:30:00", tz="UTC"),
        }
    )


# --------------------------------------------------------------------- SMA


def test_sma_first_19_rows_are_nan():
    """With default 20-day window, the first 19 rows must be NaN."""
    dates = [f"2026-04-{d:02d}" for d in range(1, 26)]
    closes = [7000.0 + i for i in range(25)]
    df = _curated_frame(dates, closes)

    sma = compute_sma(df)

    assert sma.iloc[:19].isna().all()
    assert sma.iloc[19:].notna().all()


def test_sma_20th_value_matches_mean_of_first_20():
    """SMA at index 19 should equal the arithmetic mean of indices 0..19."""
    dates = [f"2026-04-{d:02d}" for d in range(1, 26)]
    closes = [7000.0 + i for i in range(25)]
    df = _curated_frame(dates, closes)

    sma = compute_sma(df)

    expected_first = sum(closes[:20]) / 20
    assert sma.iloc[19] == pytest.approx(expected_first)


def test_sma_nan_in_window_propagates():
    """One NaN close inside the window -> SMA at that point is NaN.

    Note: this case shouldn't actually occur in our curated layer (DQ
    quarantines NaN rows), but the metric function defends against it.
    """
    dates = [f"2026-04-{d:02d}" for d in range(1, 26)]
    closes: list[float | None] = [7000.0 + i for i in range(25)]
    closes[5] = None  # inject NaN
    df = _curated_frame(dates, closes)

    sma = compute_sma(df)

    # The SMA at index 19 needs values 0..19 — one is NaN, so SMA is NaN
    assert pd.isna(sma.iloc[19])
    # By index 25 (would need to look back to index 6+), all 20 prior values
    # are present, so SMA would be defined. Our test only goes to index 24.
    # At index 24 the window is 5..24 which includes the NaN at 5 -> still NaN
    assert pd.isna(sma.iloc[24])


def test_sma_custom_window():
    """A custom window of 5 should produce SMA from row 4 onwards."""
    dates = [f"2026-04-{d:02d}" for d in range(1, 11)]
    closes = [7000.0 + i for i in range(10)]
    df = _curated_frame(dates, closes)

    sma = compute_sma(df, window=5)

    assert sma.iloc[:4].isna().all()
    assert sma.iloc[4] == pytest.approx(sum(closes[:5]) / 5)


def test_sma_rejects_invalid_window():
    df = _curated_frame(["2026-04-01"], [7000.0])
    with pytest.raises(ValueError, match="window"):
        compute_sma(df, window=0)


def test_sma_fewer_rows_than_window_all_nan():
    """If the frame has fewer rows than the window, every SMA value is NaN."""
    dates = [f"2026-04-{d:02d}" for d in range(1, 6)]
    closes = [7000.0 + i for i in range(5)]
    df = _curated_frame(dates, closes)

    sma = compute_sma(df, window=SMA_SLOW_WINDOW)

    assert sma.isna().all()


# --------------------------------------------------------------------- daily % change


def test_pct_change_first_row_is_nan():
    df = _curated_frame(["2026-04-01", "2026-04-02"], [7000.0, 7100.0])
    pct = compute_daily_pct_change(df)
    assert pd.isna(pct.iloc[0])


def test_pct_change_formula():
    """Second row: (7100 - 7000) / 7000 * 100 = 1.4286..."""
    df = _curated_frame(["2026-04-01", "2026-04-02"], [7000.0, 7100.0])
    pct = compute_daily_pct_change(df)
    assert pct.iloc[1] == pytest.approx((7100.0 - 7000.0) / 7000.0 * 100.0)


def test_pct_change_gap_compares_against_prior_row():
    """Quarantined day is absent from curated. Next valid day's % change
    compares against the most recent prior present row — i.e. across the gap.
    Matches METRICS.md's documented industry-convention behaviour.
    """
    # Simulate a gap: 04-02 to 04-06 (skipping a quarantined 04-03)
    df = _curated_frame(["2026-04-02", "2026-04-06"], [7000.0, 7050.0])
    pct = compute_daily_pct_change(df)
    # Second row's % change should compare 7050 against 7000, not against
    # the absent quarantined date
    assert pct.iloc[1] == pytest.approx((7050.0 - 7000.0) / 7000.0 * 100.0)


def test_pct_change_negative_values():
    """Down days produce negative percentages."""
    df = _curated_frame(["2026-04-01", "2026-04-02"], [7100.0, 7000.0])
    pct = compute_daily_pct_change(df)
    assert pct.iloc[1] < 0
    assert pct.iloc[1] == pytest.approx((7000.0 - 7100.0) / 7100.0 * 100.0)


# --------------------------------------------------------------------- compose


def test_serving_dataset_has_all_curated_columns_plus_metrics():
    """Design contract: serving preserves curated columns (no ETL needed if
    dashboard adds tooltips on OHLC). Three metric columns are appended:
    sp500_sma_10, sp500_sma_20, sp500_pct_change.
    """
    df = _curated_frame(
        [f"2026-04-{d:02d}" for d in range(1, 26)],
        [7000.0 + i for i in range(25)],
    )
    serving = compute_serving_dataset(df)

    # Every curated column survives
    for col in df.columns:
        assert col in serving.columns
    # Plus the three metrics
    assert "sp500_sma_10" in serving.columns
    assert "sp500_sma_20" in serving.columns
    assert "sp500_pct_change" in serving.columns


def test_serving_dataset_sma_10_defined_earlier_than_sma_20():
    """The fast SMA must produce values starting at index 9, the slow at 19.

    This is the design rationale for having both: with a 90-day window, the
    10-day SMA gives more usable coverage at the start of the visible range.
    """
    df = _curated_frame(
        [f"2026-04-{d:02d}" for d in range(1, 26)],
        [7000.0 + i for i in range(25)],
    )
    serving = compute_serving_dataset(df)

    # SMA_10: NaN for first 9 rows, defined from row 9 onwards
    assert serving["sp500_sma_10"].iloc[:9].isna().all()
    assert pd.notna(serving["sp500_sma_10"].iloc[9])
    # SMA_20: NaN for first 19 rows, defined from row 19 onwards
    assert serving["sp500_sma_20"].iloc[:19].isna().all()
    assert pd.notna(serving["sp500_sma_20"].iloc[19])


def test_serving_dataset_sma_10_first_value_correct():
    """SMA_10 at index 9 should be the arithmetic mean of indices 0..9."""
    df = _curated_frame(
        [f"2026-04-{d:02d}" for d in range(1, 26)],
        [7000.0 + i for i in range(25)],
    )
    serving = compute_serving_dataset(df)

    expected = sum([7000.0 + i for i in range(10)]) / 10
    assert serving["sp500_sma_10"].iloc[9] == pytest.approx(expected)


def test_serving_dataset_row_count_matches_input():
    df = _curated_frame(
        [f"2026-04-{d:02d}" for d in range(1, 26)],
        [7000.0 + i for i in range(25)],
    )
    serving = compute_serving_dataset(df)
    assert len(serving) == len(df)


def test_serving_dataset_empty_input():
    """Empty curated -> empty serving with metric columns still present
    (downstream schema contract holds)."""
    df = _curated_frame([], [])
    serving = compute_serving_dataset(df)
    assert len(serving) == 0
    assert "sp500_sma_10" in serving.columns
    assert "sp500_sma_20" in serving.columns
    assert "sp500_pct_change" in serving.columns


def test_serving_dataset_missing_required_column_raises():
    df = _curated_frame(["2026-04-01"], [7000.0])
    df = df.drop(columns=["sp500_close"])
    with pytest.raises(ValueError, match="missing required columns"):
        compute_serving_dataset(df)


def test_serving_dataset_sorts_by_date():
    """Even if curated arrives unsorted, serving must be ascending by date —
    SMA and pct_change depend on order."""
    df = _curated_frame(
        ["2026-04-03", "2026-04-01", "2026-04-02"], [7020.0, 7000.0, 7010.0]
    )
    serving = compute_serving_dataset(df)
    assert serving["date"].is_monotonic_increasing
