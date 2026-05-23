"""Source alignment for the transformation layer.

Outer-joins raw FRED VIX and Yahoo S&P 500 DataFrames on trading day to produce
a single aligned dataset. The aligned dataset is the input to the data quality
(DQ) stage in `src/quality/`.

This module does NOT decide what makes a row "valid". It only aligns. Routing
incomplete rows to quarantine is the DQ stage's responsibility. The separation
matters because it makes both stages independently testable and keeps the
medallion contract clean: alignment produces a candidate silver layer, DQ
decides what's actually promoted.

Alignment is a pure function over DataFrames — no file I/O at this level. The
orchestrator in `scripts/run_pipeline.py` reads raw Parquet files and passes
the loaded DataFrames in. Tests construct synthetic DataFrames directly without
touching disk.

See ADR-0006 for the policy rationale (outer join vs inner join, stateless
rebuild for late-arriving records).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


# Required columns each ingestor produces in its raw output. Derived from
# FREDIngestor._validate_schema and YahooIngestor._validate_schema. Kept here
# as the alignment-stage contract — if either ingestor's output schema changes
# without updating this set, alignment fails fast at the validation step.
FRED_REQUIRED_COLUMNS = frozenset({"date", "value", "fetched_at"})
YAHOO_REQUIRED_COLUMNS = frozenset(
    {"date", "open", "high", "low", "close", "volume", "fetched_at"}
)


class AlignmentError(Exception):
    """Raised when alignment preconditions are violated.

    Examples:
    - Input DataFrame missing a required column
    - 'date' column is not datetime-typed
    - Duplicate dates within a single source's input
    - pandas merge invariant violation (one-to-one assertion failed)
    """


@dataclass(frozen=True)
class AlignmentSummary:
    """Summary statistics for an aligned dataset.

    Used by the orchestrator to log alignment outcomes and by the DQ stage to
    cross-check that the aligned dataset's shape matches expectations.

    Invariant: complete_rows + vix_only_rows + sp500_only_rows + no_data_rows
               == total_rows
    """

    total_rows: int
    complete_rows: int  # both sources have non-NaN data
    vix_only_rows: int  # FRED has vix, Yahoo's close is NaN
    sp500_only_rows: int  # Yahoo has close, FRED's vix is NaN
    no_data_rows: int  # both vix and sp500_close NaN (e.g. holiday in FRED only)
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None


# ----------------------------------------------------------------- helpers


def _validate_input(df: pd.DataFrame, name: str, required: frozenset[str]) -> None:
    """Validate that an input DataFrame meets alignment preconditions.

    Raises AlignmentError on violation. Does not modify the DataFrame.
    """
    missing = required - set(df.columns)
    if missing:
        raise AlignmentError(
            f"{name} input missing required columns: {sorted(missing)}. "
            f"Got: {sorted(df.columns)}"
        )

    if len(df) == 0:
        # Empty input is acceptable — nothing more to validate.
        return

    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        raise AlignmentError(
            f"{name} input 'date' column must be datetime-typed; "
            f"got dtype={df['date'].dtype}"
        )

    dup_count = int(df["date"].duplicated().sum())
    if dup_count > 0:
        raise AlignmentError(
            f"{name} input has {dup_count} duplicate date(s). "
            f"Each ingestor must produce one row per trading day."
        )


# ----------------------------------------------------------------- public


def align_sources(fred_df: pd.DataFrame, yahoo_df: pd.DataFrame) -> pd.DataFrame:
    """Outer-join FRED VIX and Yahoo S&P 500 DataFrames on trading day.

    Args:
        fred_df:  Raw FRED VIX output from FREDIngestor.
        yahoo_df: Raw Yahoo OHLCV output from YahooIngestor.

    Returns:
        Aligned DataFrame, sorted by date ascending. Columns:

            date              -- trading day (tz-naive midnight America/New_York)
            vix               -- VIX closing value, NaN where FRED had no data
            sp500_open        -- S&P 500 open price, NaN where Yahoo had no row
            sp500_high        -- S&P 500 daily high, NaN where Yahoo had no row
            sp500_low         -- S&P 500 daily low,  NaN where Yahoo had no row
            sp500_close       -- S&P 500 close price, NaN where Yahoo had no row
            sp500_volume      -- S&P 500 trading volume, NaN where Yahoo had no row
            vix_fetched_at    -- FRED ingestion timestamp, NaT where no FRED row
            sp500_fetched_at  -- Yahoo ingestion timestamp, NaT where no Yahoo row

    NaN semantics in the aligned output:
        Two distinct cases produce NaN in `vix`:
        (a) FRED returned a row but the value was the holiday placeholder ('.')
            -- vix_fetched_at is a real timestamp.
        (b) FRED returned no row at all (e.g. publication lag)
            -- vix_fetched_at is NaT.
        The DQ stage uses this distinction to choose a quarantine reason code.

    Raises:
        AlignmentError: if either input is missing required columns, has a
                        non-datetime date column, or contains duplicate dates.
    """
    _validate_input(fred_df, "FRED", FRED_REQUIRED_COLUMNS)
    _validate_input(yahoo_df, "Yahoo", YAHOO_REQUIRED_COLUMNS)

    # Project and rename — avoid suffix collisions on shared columns
    # (`source`, `fetched_at`) and produce an unambiguous wide schema.
    fred_renamed = (
        fred_df.rename(columns={"value": "vix", "fetched_at": "vix_fetched_at"})[
            ["date", "vix", "vix_fetched_at"]
        ]
        .copy()
    )
    yahoo_renamed = (
        yahoo_df.rename(
            columns={
                "open": "sp500_open",
                "high": "sp500_high",
                "low": "sp500_low",
                "close": "sp500_close",
                "volume": "sp500_volume",
                "fetched_at": "sp500_fetched_at",
            }
        )[
            [
                "date",
                "sp500_open",
                "sp500_high",
                "sp500_low",
                "sp500_close",
                "sp500_volume",
                "sp500_fetched_at",
            ]
        ]
        .copy()
    )

    try:
        aligned = pd.merge(
            fred_renamed,
            yahoo_renamed,
            on="date",
            how="outer",
            validate="one_to_one",  # belt-and-braces; _validate_input already caught dupes
        )
    except pd.errors.MergeError as exc:
        # If this fires, it means duplicates slipped past _validate_input —
        # either the validation logic missed something or the input mutated.
        raise AlignmentError(f"Merge invariant violated: {exc}") from exc

    aligned = aligned.sort_values("date").reset_index(drop=True)

    logger.info(
        "Aligned %d rows from FRED=%d + Yahoo=%d",
        len(aligned),
        len(fred_renamed),
        len(yahoo_renamed),
    )
    return aligned


def summarise_alignment(aligned_df: pd.DataFrame) -> AlignmentSummary:
    """Compute summary counts for an aligned DataFrame.

    Categorises every row into exactly one of four buckets based on which
    source-side values are present (notna):

    - complete:     vix present AND sp500_close present
    - vix_only:     vix present, sp500_close NaN
    - sp500_only:   sp500_close present, vix NaN
    - no_data:      both NaN  (e.g. Good Friday: FRED row with '.', no Yahoo row)

    The four counts sum to total_rows by construction.
    """
    if len(aligned_df) == 0:
        return AlignmentSummary(
            total_rows=0,
            complete_rows=0,
            vix_only_rows=0,
            sp500_only_rows=0,
            no_data_rows=0,
            date_range=None,
        )

    vix_present = aligned_df["vix"].notna()
    sp_present = aligned_df["sp500_close"].notna()

    complete = int((vix_present & sp_present).sum())
    vix_only = int((vix_present & ~sp_present).sum())
    sp_only = int((~vix_present & sp_present).sum())
    no_data = int((~vix_present & ~sp_present).sum())

    # Sanity invariant — if this ever fails, something is wrong with the
    # categorisation logic, not with the data.
    total = len(aligned_df)
    assert complete + vix_only + sp_only + no_data == total, (
        f"Alignment summary buckets do not sum to total: "
        f"{complete} + {vix_only} + {sp_only} + {no_data} != {total}"
    )

    return AlignmentSummary(
        total_rows=total,
        complete_rows=complete,
        vix_only_rows=vix_only,
        sp500_only_rows=sp_only,
        no_data_rows=no_data,
        date_range=(aligned_df["date"].min(), aligned_df["date"].max()),
    )
