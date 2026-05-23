"""Tests for src/quality/checks.py.

Coverage:
- Reason classification for each of the five QuarantineReason enum values
- The two real-world cases we observed: April 3 (BOTH_MISSING) and
  May 22 (FRED_PUBLICATION_LAG)
- The split invariant: promoted + quarantined == total
- Empty input handling
- Schema validation on the aligned input
- Promoted rows do NOT get the quarantine columns
- Explicit run_at parameter for deterministic testing
- All-complete and all-quarantined edge cases
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.quality.checks import (
    QualityResult,
    QuarantineReason,
    _classify_quarantine_reason,
    assess_alignment,
)


# --------------------------------------------------------------------- builders


_FETCHED_AT = pd.Timestamp("2026-05-23 07:30:00", tz="UTC")
_RUN_AT = pd.Timestamp("2026-05-23 12:00:00", tz="UTC")


def _aligned_row(
    date: str,
    vix: float | None,
    sp500_close: float | None,
    vix_fetched: bool,
    sp500_fetched: bool,
) -> dict:
    """Build a single aligned-row dict mirroring align_sources output schema."""
    return {
        "date": pd.Timestamp(date),
        "vix": vix,
        "sp500_open": (sp500_close - 5) if sp500_close is not None else None,
        "sp500_high": (sp500_close + 10) if sp500_close is not None else None,
        "sp500_low": (sp500_close - 10) if sp500_close is not None else None,
        "sp500_close": sp500_close,
        "sp500_volume": 1_000_000_000 if sp500_close is not None else None,
        "vix_fetched_at": _FETCHED_AT if vix_fetched else pd.NaT,
        "sp500_fetched_at": _FETCHED_AT if sp500_fetched else pd.NaT,
    }


def _aligned_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- reason classification


def test_classifier_rejects_complete_row():
    """A row with both vix and sp500_close present must not be classified — it
    should never reach the classifier; the upstream split filters it out.
    """
    row = pd.Series(_aligned_row("2026-05-19", 18.0, 7400.0, True, True))
    with pytest.raises(ValueError, match="complete row"):
        _classify_quarantine_reason(row)


def test_classifier_fred_publication_lag():
    """vix NaN AND vix_fetched_at NaT -> FRED didn't return a row -> lag.
    This is the May 22 case from live data.
    """
    row = pd.Series(
        _aligned_row("2026-05-22", None, 7460.0, vix_fetched=False, sp500_fetched=True)
    )
    assert (
        _classify_quarantine_reason(row)
        == QuarantineReason.FRED_PUBLICATION_LAG.value
    )


def test_classifier_fred_value_null():
    """vix NaN AND vix_fetched_at present -> FRED returned '.' for a holiday."""
    row = pd.Series(
        _aligned_row("2026-04-03", None, 7300.0, vix_fetched=True, sp500_fetched=True)
    )
    assert (
        _classify_quarantine_reason(row) == QuarantineReason.FRED_VALUE_NULL.value
    )


def test_classifier_yahoo_publication_lag():
    """sp500_close NaN AND sp500_fetched_at NaT -> Yahoo had no row for this date."""
    row = pd.Series(
        _aligned_row("2026-05-22", 18.5, None, vix_fetched=True, sp500_fetched=False)
    )
    assert (
        _classify_quarantine_reason(row)
        == QuarantineReason.YAHOO_PUBLICATION_LAG.value
    )


def test_classifier_yahoo_value_null():
    """sp500_close NaN AND sp500_fetched_at present -> Yahoo returned a null Close."""
    row = pd.Series(
        _aligned_row("2026-05-19", 18.0, None, vix_fetched=True, sp500_fetched=True)
    )
    assert (
        _classify_quarantine_reason(row) == QuarantineReason.YAHOO_VALUE_NULL.value
    )


def test_classifier_both_missing():
    """Both vix and sp500_close NaN -> BOTH_MISSING regardless of fetched_at flags.
    This is the April 3 Good Friday case from live data.
    """
    row = pd.Series(
        _aligned_row("2026-04-03", None, None, vix_fetched=True, sp500_fetched=False)
    )
    assert _classify_quarantine_reason(row) == QuarantineReason.BOTH_MISSING.value


# --------------------------------------------------------------------- assess_alignment


def test_all_rows_complete_all_promoted():
    aligned = _aligned_frame(
        [
            _aligned_row("2026-05-19", 18.0, 7400.0, True, True),
            _aligned_row("2026-05-20", 18.5, 7410.0, True, True),
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    assert len(result.promoted) == 2
    assert len(result.quarantined) == 0
    # Promoted frame does NOT have quarantine columns
    assert "quarantine_reason" not in result.promoted.columns
    assert "quarantine_run_at" not in result.promoted.columns


def test_all_rows_quarantined_no_promote():
    aligned = _aligned_frame(
        [
            _aligned_row("2026-04-03", None, None, True, False),  # both_missing
            _aligned_row("2026-05-22", None, 7460.0, False, True),  # fred_lag
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    assert len(result.promoted) == 0
    assert len(result.quarantined) == 2
    assert "quarantine_reason" in result.quarantined.columns
    assert set(result.quarantined["quarantine_reason"]) == {
        QuarantineReason.BOTH_MISSING.value,
        QuarantineReason.FRED_PUBLICATION_LAG.value,
    }


def test_mixed_split_with_real_world_cases():
    """Combination matching what the live pipeline produced today: 2 complete,
    1 sp500_only (May 22 → fred_lag), 1 no_data (April 3 → both_missing).
    """
    aligned = _aligned_frame(
        [
            _aligned_row("2026-04-02", 22.0, 7300.0, True, True),  # complete
            _aligned_row("2026-04-03", None, None, True, False),  # both_missing
            _aligned_row("2026-05-19", 18.0, 7400.0, True, True),  # complete
            _aligned_row("2026-05-22", None, 7460.0, False, True),  # fred_lag
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    assert len(result.promoted) == 2
    assert len(result.quarantined) == 2
    reasons = list(result.quarantined["quarantine_reason"])
    assert QuarantineReason.BOTH_MISSING.value in reasons
    assert QuarantineReason.FRED_PUBLICATION_LAG.value in reasons


def test_split_invariant_holds():
    """promoted + quarantined always equals input row count."""
    aligned = _aligned_frame(
        [
            _aligned_row("2026-04-02", 22.0, 7300.0, True, True),
            _aligned_row("2026-04-03", None, None, True, False),
            _aligned_row("2026-05-22", None, 7460.0, False, True),
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)
    assert len(result.promoted) + len(result.quarantined) == len(aligned)


def test_run_at_is_applied_to_all_quarantined_rows():
    """A single run_at value should appear on every quarantined row."""
    aligned = _aligned_frame(
        [
            _aligned_row("2026-04-03", None, None, True, False),
            _aligned_row("2026-05-22", None, 7460.0, False, True),
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    assert (result.quarantined["quarantine_run_at"] == _RUN_AT).all()
    assert result.run_at == _RUN_AT


def test_run_at_defaults_to_now_when_not_provided():
    aligned = _aligned_frame(
        [_aligned_row("2026-04-03", None, None, True, False)]
    )
    before = pd.Timestamp.now(tz="UTC")
    result = assess_alignment(aligned)
    after = pd.Timestamp.now(tz="UTC")

    assert before <= result.run_at <= after


def test_empty_aligned_produces_empty_result():
    """Empty input -> empty promoted, empty quarantined, no crashes."""
    aligned = _aligned_frame([])
    # When constructing an empty frame with no rows, we still need columns
    # — replicate the alignment-output schema explicitly.
    aligned = pd.DataFrame(
        columns=[
            "date",
            "vix",
            "sp500_open",
            "sp500_high",
            "sp500_low",
            "sp500_close",
            "sp500_volume",
            "vix_fetched_at",
            "sp500_fetched_at",
        ]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    assert len(result.promoted) == 0
    assert len(result.quarantined) == 0
    assert isinstance(result, QualityResult)


def test_missing_required_column_raises():
    """If alignment's output schema breaks, DQ must refuse to operate on it."""
    aligned = _aligned_frame([_aligned_row("2026-05-19", 18.0, 7400.0, True, True)])
    aligned = aligned.drop(columns=["sp500_close"])

    with pytest.raises(ValueError, match="missing required columns"):
        assess_alignment(aligned, run_at=_RUN_AT)


def test_quarantined_rows_preserve_original_columns():
    """Quarantined frame should still have all the original aligned columns,
    just with the two quarantine columns appended."""
    aligned = _aligned_frame(
        [_aligned_row("2026-05-22", None, 7460.0, False, True)]
    )
    result = assess_alignment(aligned, run_at=_RUN_AT)

    for col in aligned.columns:
        assert col in result.quarantined.columns
    assert "quarantine_reason" in result.quarantined.columns
    assert "quarantine_run_at" in result.quarantined.columns
