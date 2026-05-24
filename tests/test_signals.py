"""Tests for src/signals/rag.py.

Coverage:
- compute_rag_signal: all four bands (GREEN, AMBER, RED, UNAVAILABLE)
- compute_rag_signal: explicit boundary tests at 19.99, 20.0, 30.0, 30.01
- compute_rag_signal: handles None and NaN
- enrich_with_signal: adds column without mutating input
- enrich_with_signal: missing 'vix' column raises
- enrich_with_signal: NaN VIX rows get 'unavailable' string
- enrich_with_signal: empty frame produces empty result with column present
- enrich_with_signal: signal values are strings (for clean Parquet/JSON serialization)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.rag import (
    RagBand,
    compute_rag_signal,
    enrich_with_signal,
)


# --------------------------------------------------------------------- compute_rag_signal


def test_green_for_low_vix():
    assert compute_rag_signal(15.0) == RagBand.GREEN


def test_amber_for_mid_vix():
    assert compute_rag_signal(25.0) == RagBand.AMBER


def test_red_for_high_vix():
    assert compute_rag_signal(45.0) == RagBand.RED


def test_unavailable_for_none():
    assert compute_rag_signal(None) == RagBand.UNAVAILABLE


def test_unavailable_for_nan():
    assert compute_rag_signal(float("nan")) == RagBand.UNAVAILABLE


# Boundary tests — these pin the ADR-0003 contract exactly.
# Any change to threshold semantics must update both this test set and ADR-0003.


def test_boundary_just_below_green_upper_is_green():
    assert compute_rag_signal(19.99) == RagBand.GREEN


def test_boundary_at_green_upper_is_amber():
    """vix == 20.0 belongs to AMBER (lower bound inclusive on the amber band)."""
    assert compute_rag_signal(20.0) == RagBand.AMBER


def test_boundary_at_red_lower_is_amber():
    """vix == 30.0 belongs to AMBER (upper bound inclusive on the amber band)."""
    assert compute_rag_signal(30.0) == RagBand.AMBER


def test_boundary_just_above_red_lower_is_red():
    assert compute_rag_signal(30.01) == RagBand.RED


# --------------------------------------------------------------------- enrich_with_signal


def _serving_frame(vix_values: list[float | None]) -> pd.DataFrame:
    """Build a minimal serving frame for signal-enrichment tests."""
    n = len(vix_values)
    return pd.DataFrame(
        {
            "date": pd.to_datetime([f"2026-04-{d:02d}" for d in range(1, n + 1)]),
            "vix": vix_values,
            "sp500_close": [7000.0 + i for i in range(n)],
        }
    )


def test_enrich_adds_signal_column():
    df = _serving_frame([15.0, 25.0, 35.0])
    out = enrich_with_signal(df)
    assert "rag_signal" in out.columns
    assert out["rag_signal"].tolist() == ["green", "amber", "red"]


def test_enrich_does_not_mutate_input():
    df = _serving_frame([15.0, 25.0])
    enrich_with_signal(df)
    # Original df should still not have the column
    assert "rag_signal" not in df.columns


def test_enrich_nan_rows_get_unavailable():
    df = _serving_frame([15.0, None, 35.0])
    out = enrich_with_signal(df)
    assert out["rag_signal"].tolist() == ["green", "unavailable", "red"]


def test_enrich_empty_frame_has_signal_column():
    """Empty in -> empty out, with signal column present so downstream
    schema contract holds."""
    df = _serving_frame([])
    out = enrich_with_signal(df)
    assert len(out) == 0
    assert "rag_signal" in out.columns


def test_enrich_missing_vix_column_raises():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-04-01"])})
    with pytest.raises(ValueError, match="vix"):
        enrich_with_signal(df)


def test_enrich_signal_values_are_strings():
    """Stored as strings (not enum instances) so Parquet/JSON serialize cleanly."""
    df = _serving_frame([15.0, 25.0, 35.0])
    out = enrich_with_signal(df)
    for value in out["rag_signal"]:
        assert isinstance(value, str)


def test_enrich_signal_history_realistic_pattern():
    """Realistic case: signal traverses bands across a window (the case study's
    March 2026 narrative)."""
    df = _serving_frame([18.0, 19.5, 21.0, 29.5, 31.0, 28.0, 22.0, 18.5])
    out = enrich_with_signal(df)
    assert out["rag_signal"].tolist() == [
        "green",
        "green",
        "amber",
        "amber",
        "red",
        "amber",
        "amber",
        "green",
    ]
