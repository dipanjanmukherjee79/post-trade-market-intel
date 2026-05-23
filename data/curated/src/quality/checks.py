"""Data quality assessment for the aligned dataset.

Pure functions that take the aligned DataFrame from `src/transformation/alignment.py`
and split it into two frames:

- **Promoted**: rows where all metric-required inputs (vix, sp500_close) are present.
                Eligible for the curated silver layer.
- **Quarantined**: rows where any required input is NaN. Tagged with a typed
                  reason code derived from the source-side provenance columns,
                  and routed to the quarantine log by the orchestrator.

This module does no I/O. The orchestrator in `scripts/run_pipeline.py` is
responsible for writing the promoted frame to the curated layer and appending
the quarantine entries to `logs/dq_quarantine.log`. See ADR-0006 for the
stateless-rebuild rationale.

The reason taxonomy distinguishes two qualitatively different missing-data
cases per source:

- **Publication lag** — the source had no row at all for this date. Detectable
  because the source's `*_fetched_at` is NaT. Resolves on the next run if
  the source catches up.
- **Value null** — the source returned a row but the value field was null
  (e.g. FRED's "." holiday placeholder). Detectable because the source's
  `*_fetched_at` is a real timestamp but the value is NaN. Does not resolve
  on later runs; this is a true upstream "no value" signal.

This distinction is operationally important: publication lag is recoverable,
value null is permanent. The DQ log records both with separate reason codes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

logger = logging.getLogger(__name__)


class QuarantineReason(str, Enum):
    """Typed reason code for a quarantined row.

    Stored as the row's `quarantine_reason` column and serialised to the
    quarantine log. String-valued so it serialises cleanly to JSON.
    """

    FRED_PUBLICATION_LAG = "fred_publication_lag"
    """FRED returned no row for this date — likely upstream publication lag."""

    FRED_VALUE_NULL = "fred_value_null"
    """FRED returned a row with null value (e.g. '.' holiday placeholder)."""

    YAHOO_PUBLICATION_LAG = "yahoo_publication_lag"
    """Yahoo returned no row for this date — non-trading day or scraper issue."""

    YAHOO_VALUE_NULL = "yahoo_value_null"
    """Yahoo returned a row with null Close — would be a real upstream DQ event."""

    BOTH_MISSING = "both_missing"
    """Both vix and sp500_close are NaN. Composite of any of the above per source."""


@dataclass(frozen=True)
class QualityResult:
    """Result of a DQ assessment on an aligned DataFrame.

    Invariant: len(promoted) + len(quarantined) == len(aligned_df).
    """

    promoted: pd.DataFrame  # Schema: same as aligned input
    quarantined: pd.DataFrame  # Schema: aligned + 'quarantine_reason' + 'quarantine_run_at'
    run_at: pd.Timestamp  # Single timestamp shared across this assessment


# Columns the aligned DataFrame must have for DQ to work. Matches the output
# schema of `src/transformation/alignment.py:align_sources`.
_REQUIRED_ALIGNED_COLUMNS = frozenset(
    {"date", "vix", "sp500_close", "vix_fetched_at", "sp500_fetched_at"}
)


# ----------------------------------------------------------------- helpers


def _classify_quarantine_reason(row: pd.Series) -> str:
    """Return the QuarantineReason value for a single quarantined row.

    Uses the *_fetched_at provenance columns to distinguish publication lag
    (source had no row) from value null (source returned a null value).
    """
    vix_present = pd.notna(row["vix"])
    sp_present = pd.notna(row["sp500_close"])

    if vix_present and sp_present:
        # Caller bug: this row should not be in the quarantine set.
        raise ValueError(
            "complete row passed to _classify_quarantine_reason — "
            "DQ split is upstream of this function"
        )

    # Both missing: composite case. Detail is preserved in the row itself
    # (the *_fetched_at columns), but the reason code flattens to BOTH_MISSING.
    if not vix_present and not sp_present:
        return QuarantineReason.BOTH_MISSING.value

    # Only vix is missing (sp500 present)
    if not vix_present:
        vix_fetched = pd.notna(row["vix_fetched_at"])
        return (
            QuarantineReason.FRED_VALUE_NULL.value
            if vix_fetched
            else QuarantineReason.FRED_PUBLICATION_LAG.value
        )

    # Only sp500 is missing (vix present)
    sp_fetched = pd.notna(row["sp500_fetched_at"])
    return (
        QuarantineReason.YAHOO_VALUE_NULL.value
        if sp_fetched
        else QuarantineReason.YAHOO_PUBLICATION_LAG.value
    )


def _validate_aligned_input(aligned_df: pd.DataFrame) -> None:
    """Fail-fast on schema violations from upstream."""
    missing = _REQUIRED_ALIGNED_COLUMNS - set(aligned_df.columns)
    if missing:
        raise ValueError(
            f"aligned DataFrame missing required columns: {sorted(missing)}. "
            f"Got: {sorted(aligned_df.columns)}"
        )


# ----------------------------------------------------------------- public


def assess_alignment(
    aligned_df: pd.DataFrame,
    run_at: pd.Timestamp | None = None,
) -> QualityResult:
    """Split the aligned DataFrame into (promoted, quarantined) frames.

    A row is promoted when both required metric inputs (`vix`, `sp500_close`)
    are non-null. Otherwise it is quarantined with a typed reason code.

    Args:
        aligned_df: Output of `align_sources()` — wide-shaped DataFrame keyed
            on date with vix and S&P 500 OHLCV columns plus provenance.
        run_at: Optional explicit timestamp for this assessment. Used as the
            `quarantine_run_at` column on every quarantined row. Defaults to
            current UTC time. Pass an explicit value in tests for determinism.

    Returns:
        QualityResult with the split frames and the run timestamp.

    Raises:
        ValueError: if the input DataFrame is missing required columns.
    """
    _validate_aligned_input(aligned_df)
    if run_at is None:
        run_at = pd.Timestamp.now(tz="UTC")

    if len(aligned_df) == 0:
        return QualityResult(
            promoted=aligned_df.copy(),
            quarantined=aligned_df.copy(),
            run_at=run_at,
        )

    vix_present = aligned_df["vix"].notna()
    sp_present = aligned_df["sp500_close"].notna()
    complete_mask = vix_present & sp_present

    promoted = aligned_df[complete_mask].copy().reset_index(drop=True)
    quarantined = aligned_df[~complete_mask].copy().reset_index(drop=True)

    if len(quarantined) > 0:
        quarantined["quarantine_reason"] = quarantined.apply(
            _classify_quarantine_reason, axis=1
        )
        quarantined["quarantine_run_at"] = run_at

    # Sanity invariant — if this fails, the split logic itself is broken.
    assert len(promoted) + len(quarantined) == len(aligned_df), (
        f"DQ split lost rows: {len(promoted)} + {len(quarantined)} "
        f"!= {len(aligned_df)}"
    )

    logger.info(
        "DQ assessment: %d promoted, %d quarantined (run_at=%s)",
        len(promoted),
        len(quarantined),
        run_at.isoformat(),
    )
    return QualityResult(promoted=promoted, quarantined=quarantined, run_at=run_at)
