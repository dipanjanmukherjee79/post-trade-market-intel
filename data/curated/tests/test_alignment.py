"""Tests for src/transformation/alignment.py.

Coverage:
- Happy path: identical calendars produce all-complete rows
- Good Friday case: FRED row with NaN vix, no Yahoo row -> outer join produces
  a no_data row (both NaN) that the DQ stage will quarantine
- Publication lag case: Yahoo has the most recent date, FRED does not -> outer
  join keeps the Yahoo row with NaN vix (sp500_only category)
- FRED has dates Yahoo does not, and vice versa
- Column renames are correct and unambiguous
- Sort order is ascending by date
- Validation: missing columns, wrong date dtype, duplicate dates
- Empty inputs handled
- Summary buckets categorise every row exactly once, sum to total
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.transformation.alignment import (
    AlignmentError,
    AlignmentSummary,
    align_sources,
    summarise_alignment,
)


# --------------------------------------------------------------------- builders


def _fred_frame(dates: list[str], values: list[float | None]) -> pd.DataFrame:
    """Build a frame that mimics FREDIngestor._validate_schema output."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "value": values,
            "series_id": "VIXCLS",
            "source": "fred_vixcls",
            "fetched_at": pd.Timestamp("2026-05-23 07:30:00", tz="UTC"),
        }
    )


def _yahoo_frame(dates: list[str], closes: list[float | None]) -> pd.DataFrame:
    """Build a frame that mimics YahooIngestor._validate_schema output."""
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": [c - 5 if c is not None else None for c in closes],
            "high": [c + 10 if c is not None else None for c in closes],
            "low": [c - 10 if c is not None else None for c in closes],
            "close": closes,
            "volume": [1_000_000_000] * n,
            "ticker": "^GSPC",
            "source": "yahoo_gspc",
            "fetched_at": pd.Timestamp("2026-05-23 07:30:00", tz="UTC"),
        }
    )


# --------------------------------------------------------------------- happy path


def test_identical_calendars_produce_all_complete_rows():
    """Both sources cover the same three trading days. All rows complete."""
    fred = _fred_frame(
        ["2026-05-19", "2026-05-20", "2026-05-21"], [18.0, 18.5, 19.2]
    )
    yahoo = _yahoo_frame(
        ["2026-05-19", "2026-05-20", "2026-05-21"], [7400.0, 7410.0, 7405.0]
    )

    aligned = align_sources(fred, yahoo)

    assert len(aligned) == 3
    assert aligned["vix"].notna().all()
    assert aligned["sp500_close"].notna().all()
    # Sort order ascending
    assert aligned["date"].is_monotonic_increasing


def test_aligned_columns_are_renamed_and_unambiguous():
    """No suffix collisions; provenance per source."""
    fred = _fred_frame(["2026-05-19"], [18.0])
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0])

    aligned = align_sources(fred, yahoo)

    expected = {
        "date",
        "vix",
        "sp500_open",
        "sp500_high",
        "sp500_low",
        "sp500_close",
        "sp500_volume",
        "vix_fetched_at",
        "sp500_fetched_at",
    }
    assert set(aligned.columns) == expected
    # No pandas _x / _y suffix collisions
    assert not any("_x" in c or "_y" in c for c in aligned.columns)


# --------------------------------------------------------------------- real-world cases


def test_good_friday_case_produces_no_data_row():
    """FRED returns a row for Good Friday with NaN value (the "." translation);
    Yahoo omits it entirely. The outer-joined row has NaN vix AND NaN sp500_close,
    plus a real vix_fetched_at (FRED published) and NaT for sp500_fetched_at
    (Yahoo did not). The DQ stage uses this distinction.
    """
    fred = _fred_frame(
        ["2026-04-02", "2026-04-03", "2026-04-06"],
        [22.0, None, 21.5],  # April 3 is Good Friday -> "." -> NaN
    )
    yahoo = _yahoo_frame(
        ["2026-04-02", "2026-04-06"], [7300.0, 7320.0]  # no April 3
    )

    aligned = align_sources(fred, yahoo)

    # All three dates retained (outer join, not inner)
    assert len(aligned) == 3
    good_friday_row = aligned[aligned["date"] == pd.Timestamp("2026-04-03")].iloc[0]
    assert pd.isna(good_friday_row["vix"])
    assert pd.isna(good_friday_row["sp500_close"])
    # FRED published a row, so its fetched_at is real
    assert pd.notna(good_friday_row["vix_fetched_at"])
    # Yahoo did not, so its fetched_at is NaT
    assert pd.isna(good_friday_row["sp500_fetched_at"])


def test_publication_lag_case_keeps_yahoo_row():
    """Yahoo has the most recent date; FRED does not (publication lag).
    Outer join must keep the Yahoo row — losing it would be the silent data
    loss this whole architecture is designed to prevent. See ADR-0006.
    """
    fred = _fred_frame(["2026-05-20", "2026-05-21"], [18.0, 18.5])
    yahoo = _yahoo_frame(
        ["2026-05-20", "2026-05-21", "2026-05-22"], [7400.0, 7410.0, 7420.0]
    )

    aligned = align_sources(fred, yahoo)

    assert len(aligned) == 3
    may22 = aligned[aligned["date"] == pd.Timestamp("2026-05-22")].iloc[0]
    # Yahoo data present
    assert may22["sp500_close"] == 7420.0
    # FRED missing — but it's an absent row, not a "." placeholder
    assert pd.isna(may22["vix"])
    assert pd.isna(may22["vix_fetched_at"])
    assert pd.notna(may22["sp500_fetched_at"])


def test_fred_only_date_is_retained():
    """Symmetric to the Yahoo-only case: FRED has a date Yahoo doesn't."""
    fred = _fred_frame(["2026-05-19", "2026-05-20"], [18.0, 18.5])
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0])

    aligned = align_sources(fred, yahoo)

    assert len(aligned) == 2
    may20 = aligned[aligned["date"] == pd.Timestamp("2026-05-20")].iloc[0]
    assert may20["vix"] == 18.5
    assert pd.isna(may20["sp500_close"])


# --------------------------------------------------------------------- validation


def test_missing_fred_column_raises():
    fred = _fred_frame(["2026-05-19"], [18.0]).drop(columns=["value"])
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0])

    with pytest.raises(AlignmentError, match="FRED.*missing"):
        align_sources(fred, yahoo)


def test_missing_yahoo_column_raises():
    fred = _fred_frame(["2026-05-19"], [18.0])
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0]).drop(columns=["close"])

    with pytest.raises(AlignmentError, match="Yahoo.*missing"):
        align_sources(fred, yahoo)


def test_non_datetime_date_column_raises():
    fred = _fred_frame(["2026-05-19"], [18.0])
    fred["date"] = fred["date"].astype(str)  # break the dtype
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0])

    with pytest.raises(AlignmentError, match="datetime"):
        align_sources(fred, yahoo)


def test_duplicate_dates_in_fred_raises():
    """If an ingestor produces duplicate dates, alignment must refuse to merge
    rather than silently produce a Cartesian product."""
    fred = _fred_frame(["2026-05-19", "2026-05-19"], [18.0, 18.1])
    yahoo = _yahoo_frame(["2026-05-19"], [7400.0])

    with pytest.raises(AlignmentError, match="duplicate"):
        align_sources(fred, yahoo)


def test_duplicate_dates_in_yahoo_raises():
    fred = _fred_frame(["2026-05-19"], [18.0])
    yahoo = _yahoo_frame(["2026-05-19", "2026-05-19"], [7400.0, 7405.0])

    with pytest.raises(AlignmentError, match="duplicate"):
        align_sources(fred, yahoo)


def test_empty_inputs_produce_empty_output():
    """Empty in -> empty out, no crash, no validation failure on dtype check."""
    fred = _fred_frame([], [])
    yahoo = _yahoo_frame([], [])

    aligned = align_sources(fred, yahoo)
    assert len(aligned) == 0
    # Columns should still be present in the schema
    assert "vix" in aligned.columns
    assert "sp500_close" in aligned.columns


def test_one_empty_input_keeps_the_other():
    """If only one source has data, all its rows survive with NaN for the other."""
    fred = _fred_frame([], [])
    yahoo = _yahoo_frame(["2026-05-19", "2026-05-20"], [7400.0, 7410.0])

    aligned = align_sources(fred, yahoo)
    assert len(aligned) == 2
    assert aligned["vix"].isna().all()
    assert aligned["sp500_close"].notna().all()


# --------------------------------------------------------------------- summary


def test_summary_categorises_all_four_buckets():
    """One row in each category; counts add up to total."""
    fred = _fred_frame(
        ["2026-04-01", "2026-04-02", "2026-04-03"],
        [20.0, None, 21.0],
        # 04-01 complete (both have), 04-02 sp500_only (vix is NaN),
        # 04-03 will be no_data if Yahoo also lacks it -- adjust below
    )
    yahoo = _yahoo_frame(
        ["2026-04-01", "2026-04-02", "2026-04-04"],
        [7300.0, 7310.0, 7330.0],
        # 04-01 complete, 04-02 sp500 present, 04-04 vix_only-from-Yahoo's perspective
    )
    # Adjust the build: we want one of each bucket.
    # Better to construct deliberately:
    fred = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-05"]
            ),
            "value": [
                20.0,  # complete with Yahoo 04-01
                None,  # sp500_only-from-Yahoo (vix NaN, yahoo has close)
                None,  # no_data (FRED row with NaN, no Yahoo row)
                21.5,  # vix_only (no Yahoo row for 04-05)
            ],
            "series_id": "VIXCLS",
            "source": "fred_vixcls",
            "fetched_at": pd.Timestamp("2026-05-23 07:30:00", tz="UTC"),
        }
    )
    yahoo = _yahoo_frame(
        ["2026-04-01", "2026-04-02"], [7300.0, 7310.0]
    )

    aligned = align_sources(fred, yahoo)
    summary = summarise_alignment(aligned)

    # Four buckets, one each
    assert summary.total_rows == 4
    assert summary.complete_rows == 1  # 04-01
    assert summary.sp500_only_rows == 1  # 04-02 (vix NaN, sp present)
    assert summary.no_data_rows == 1  # 04-03 (both NaN)
    assert summary.vix_only_rows == 1  # 04-05 (vix present, sp absent)
    # Invariant
    assert (
        summary.complete_rows
        + summary.vix_only_rows
        + summary.sp500_only_rows
        + summary.no_data_rows
        == summary.total_rows
    )


def test_summary_empty_aligned_dataset():
    fred = _fred_frame([], [])
    yahoo = _yahoo_frame([], [])
    aligned = align_sources(fred, yahoo)
    summary = summarise_alignment(aligned)

    assert summary == AlignmentSummary(
        total_rows=0,
        complete_rows=0,
        vix_only_rows=0,
        sp500_only_rows=0,
        no_data_rows=0,
        date_range=None,
    )


def test_summary_date_range_reflects_outer_join():
    """date_range should span min(FRED, Yahoo) to max(FRED, Yahoo)."""
    fred = _fred_frame(["2026-04-01", "2026-04-02"], [20.0, 20.5])
    yahoo = _yahoo_frame(["2026-04-02", "2026-04-03"], [7300.0, 7310.0])

    aligned = align_sources(fred, yahoo)
    summary = summarise_alignment(aligned)

    assert summary.date_range == (
        pd.Timestamp("2026-04-01"),
        pd.Timestamp("2026-04-03"),
    )
