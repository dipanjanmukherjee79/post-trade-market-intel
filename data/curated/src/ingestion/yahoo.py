"""Yahoo Finance ingestor for daily OHLCV equity data.

Uses yfinance.Ticker().history() to fetch daily OHLCV bars. yfinance is a known
fragile dependency — it scrapes Yahoo's website and breaks when Yahoo restructures
their frontend HTML/JSON. This ingestor is explicitly designed to surface
yfinance failures loudly rather than silently producing corrupt data.

Failure modes handled explicitly:

1. Network errors (Timeout, ConnectionError)            -> TRANSIENT (retried)
2. yfinance rate limit (YFRateLimitError)               -> TRANSIENT (retried)
3. DataFrame with ALL Close values NaN                  -> PERMANENT (scraper broken)
4. DataFrame with >50% Close values NaN                 -> PERMANENT (partial scraper failure)
5. Required OHLCV columns missing                       -> PERMANENT (schema change)
6. Empty DataFrame                                      -> EMPTY (base classifies; the
                                                            orchestrator decides whether
                                                            to escalate for actively-traded
                                                            tickers, where EMPTY over a
                                                            multi-day window is suspect)

Design rationale for the all-NaN handling:
    EMPTY means the source legitimately had no data to return — a Saturday, a
    pre-IPO date range, an extended market closure. A DataFrame full of NaN is a
    qualitatively different signal: the response envelope is structurally valid
    but the content is broken. Treating it as EMPTY would silently hide a real
    upstream failure. We fail loudly instead. See AGENT_LOG for the discussion.

The 50% NaN threshold is a v1 heuristic. Proper data-quality tooling
(Great Expectations, Soda Core, or a custom expectation layer) would replace
this with a configurable, versioned expectation. Documented as v2 work.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pandas as pd
import requests
import yfinance as yf

# Defensive import — newer yfinance versions expose typed exceptions, older
# versions do not. If missing, we fall back to a local placeholder so the
# transient_exceptions tuple stays well-typed. Real rate-limit handling for
# older versions falls through to the requests-level transient catches.
try:
    from yfinance.exceptions import YFRateLimitError  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    class YFRateLimitError(Exception):
        """Placeholder when yfinance does not expose its typed rate-limit error."""


from src.ingestion.base import Ingestor

logger = logging.getLogger(__name__)


class YahooDataError(Exception):
    """Raised when Yahoo returned a response shape that indicates upstream failure.

    Canonical examples:
    - All-NaN Close column (scraper broken)
    - >50% NaN Close column (partial scraper failure, heuristic threshold)
    - Missing required OHLCV columns (schema change)

    Treated as PERMANENT_FAILURE by the base class — never retried, always alerted.
    """


class YahooIngestor(Ingestor):
    """Daily OHLCV ingestor for Yahoo Finance tickers via yfinance.

    One instance ingests one ticker. The ticker name is part of source_name,
    giving each ticker a unique raw output path.

    Example:
        >>> ing = YahooIngestor(ticker="^GSPC", output_dir="data/raw")
        >>> result = ing.fetch(datetime(2026, 2, 1), datetime(2026, 5, 1))
        >>> if result.outcome == IngestionOutcome.SUCCESS:
        ...     print(f"Got {result.rows_fetched} OHLCV rows")
    """

    # Class-level default — overridden per-instance with the ticker
    source_name = "yahoo"

    # Transient exceptions: network and rate-limit. yfinance wraps requests,
    # so we cover both the requests-level types and the yfinance-typed path.
    transient_exceptions = (
        TimeoutError,
        ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        YFRateLimitError,
    )

    # OHLCV columns yfinance returns from .history(). Kept in raw layer (lossless).
    # The transformation layer picks what it needs.
    expected_columns: ClassVar[frozenset[str]] = frozenset(
        {"Open", "High", "Low", "Close", "Volume"}
    )

    # Heuristic: above this NaN fraction in Close, treat the response as
    # corrupted. Documented as a v1 heuristic; proper DQ tooling would
    # replace this with a configurable expectation.
    max_nan_close_fraction: ClassVar[float] = 0.5

    request_timeout_seconds: ClassVar[float] = 30.0

    def __init__(self, ticker: str, output_dir: Path | str):
        """Initialise the Yahoo ingestor.

        Args:
            ticker: Yahoo Finance ticker (e.g. "^GSPC" for S&P 500, "AAPL" for Apple).
            output_dir: Directory for raw Parquet output.
        """
        if not ticker:
            raise ValueError("ticker must be a non-empty Yahoo Finance ticker")

        self.ticker = ticker
        # Normalise the ticker for use in source_name / filenames.
        # ^GSPC -> gspc, BRK.B -> brk_b, EURUSD=X -> eurusd_x
        normalised = (
            ticker.lower().lstrip("^").replace(".", "_").replace("=", "_")
        )
        super().__init__(
            output_dir=output_dir,
            source_name=f"yahoo_{normalised}",
        )

    # ---------------------------------------------------------------- fetch

    def _fetch_raw(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch daily OHLCV from Yahoo via yfinance.

        yfinance's history() accepts date strings interpreted in the ticker's
        local timezone. For ^GSPC that's America/New_York.

        auto_adjust=True means Close is split/dividend-adjusted. For an index
        like ^GSPC this is equivalent to the raw close; for individual equities
        it gives the analytically correct series for rolling-window calculations.
        """
        logger.debug(
            "Yahoo request: ticker=%s start=%s end=%s",
            self.ticker,
            start.date(),
            end.date(),
        )

        ticker_obj = yf.Ticker(self.ticker)
        df = ticker_obj.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            actions=False,
            timeout=self.request_timeout_seconds,
        )
        return df

    # ---------------------------------------------------------------- validate

    def _validate_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate yfinance response shape and check for known upstream-failure patterns.

        - Empty DataFrame returns unchanged; base classifies as EMPTY.
        - Missing OHLCV columns -> permanent (schema change).
        - All-NaN Close column -> permanent (canonical scraper-broken signal).
        - >50% NaN Close -> permanent (heuristic threshold for partial failure).
        - Valid response -> normalise to lowercase columns, add provenance.
        """
        if df.empty:
            # Legitimately empty per the base contract. The orchestrator decides
            # whether EMPTY-for-this-ticker warrants escalation.
            return df

        # 1. Required columns present?
        missing = self.expected_columns - set(df.columns)
        if missing:
            raise YahooDataError(
                f"Yahoo response missing required columns: {sorted(missing)}. "
                f"Got: {sorted(df.columns)}. "
                f"Likely cause: yfinance scraper schema change."
            )

        # 2. Canonical scraper-broken signal — DataFrame has rows but every
        #    Close is NaN. This is qualitatively different from EMPTY and must
        #    be surfaced as a permanent failure, not silently swallowed.
        if df["Close"].isna().all():
            raise YahooDataError(
                f"yfinance returned {len(df)} rows but ALL Close values are NaN. "
                f"This is the canonical signal that the upstream scraper has "
                f"broken — likely a Yahoo Finance frontend change. Investigate "
                f"before retrying."
            )

        # 3. Partial scraper failure heuristic.
        nan_fraction = df["Close"].isna().mean()
        if nan_fraction > self.max_nan_close_fraction:
            raise YahooDataError(
                f"yfinance returned {len(df)} rows but {nan_fraction:.0%} have "
                f"NaN Close. This exceeds the "
                f"{self.max_nan_close_fraction:.0%} threshold and suggests a "
                f"partial scraper failure. NOTE: threshold is a v1 heuristic; "
                f"proper DQ tooling would replace it with a configurable "
                f"expectation."
            )

        # 4. Normalise shape: promote the date index to a column, standardise
        #    to lowercase column names (consistent with FRED ingestor output),
        #    add provenance.
        result = df.reset_index().copy()

        # yfinance's index column is "Date" for daily data
        if "Date" in result.columns:
            result = result.rename(columns={"Date": "date"})
        elif "Datetime" in result.columns:
            result = result.rename(columns={"Datetime": "date"})
        else:
            # Shouldn't happen if .history() behaved normally, but defensive
            raise YahooDataError(
                f"Yahoo response missing date column after reset_index. "
                f"Columns: {sorted(result.columns)}"
            )

        # Drop time component — yfinance returns midnight market-local;
        # we want a clean date column on the raw layer.
        result["date"] = (
            pd.to_datetime(result["date"]).dt.tz_localize(None).dt.normalize()
        )

        # Keep OHLCV (lossless raw layer)
        result = result[["date", "Open", "High", "Low", "Close", "Volume"]].copy()
        result = result.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        # Provenance
        result["ticker"] = self.ticker
        result["source"] = self.source_name
        result["fetched_at"] = pd.Timestamp.now("UTC")

        return result
