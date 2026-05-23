"""FRED API ingestor.

Fetches daily time-series observations from the FRED API. The shared retry,
timeout, logging, and idempotent-write logic lives in `base.py`. This module
adds only the FRED-specific HTTP fetch and the response schema validation.

API docs: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
Auth:     requires FRED_API_KEY env var. Register free at
          https://fred.stlouisfed.org/docs/api/api_key.html

FRED-specific quirks documented here so the team understands them:

1. Holiday placeholder. FRED publishes a row for every US business day, but on
   market holidays the `value` is the literal string "." (a single period).
   We translate "." to NaN at schema-validation time. Weekends are absent
   entirely (no row at all). See METRICS.md "Missing data policy."

2. No timezone in the response. The `date` field is a naive ISO date string.
   By convention we treat all FRED daily series as `America/New_York` close.
   The transformation layer is responsible for any timezone normalisation.

3. Rate limit. 120 requests per 60s per API key (well-documented). We treat
   429 responses as TRANSIENT failures and let the base class back off.

4. HTTP error classification:
   - 5xx, 429, network errors           -> transient (retried)
   - 400, 401, 403, 404 and other 4xx   -> permanent (quarantined, not retried)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.ingestion.base import Ingestor

logger = logging.getLogger(__name__)


class FREDError(Exception):
    """Raised for FRED-specific permanent errors.

    Examples: invalid API key (HTTP 400 with a specific message), unknown series
    id (HTTP 400), malformed response payload. Permanent failures are not
    retried — the base class will quarantine and continue.
    """


class FREDIngestor(Ingestor):
    """Ingestor for a single FRED daily time series.

    One instance ingests one series. The series id is part of the source_name
    so each series writes to its own Parquet file in the raw layer.

    Example:
        >>> ing = FREDIngestor(series_id="VIXCLS", output_dir="data/raw")
        >>> result = ing.fetch(datetime(2026, 2, 1), datetime(2026, 5, 1))
        >>> if result.outcome == IngestionOutcome.SUCCESS:
        ...     print(f"Got {result.rows_fetched} rows")
    """

    # Class-level default — overridden per-instance with the series id
    source_name = "fred"

    # Treat both stdlib timeout/connection errors AND requests' typed equivalents
    # as transient. Anything else (including FREDError) is permanent.
    transient_exceptions = (
        TimeoutError,
        ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    )

    base_url = "https://api.stlouisfed.org/fred/series/observations"
    request_timeout_seconds = 30.0

    def __init__(
        self,
        series_id: str,
        output_dir: Path | str,
        api_key: str | None = None,
    ):
        """Initialise the FRED ingestor.

        Args:
            series_id: FRED series identifier (e.g. "VIXCLS", "DFF", "SP500").
            output_dir: Directory for raw Parquet output.
            api_key: Optional API key. Falls back to FRED_API_KEY env var.
                     Raises ValueError if neither source provides one.
        """
        if not series_id:
            raise ValueError("series_id must be a non-empty FRED series identifier")

        self.series_id = series_id
        self.api_key = api_key or os.environ.get("FRED_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "FRED_API_KEY not set. Either pass api_key= or set the env var. "
                "Register a free key at "
                "https://fred.stlouisfed.org/docs/api/api_key.html"
            )

        # Per-instance source_name so each series gets a unique output path
        super().__init__(
            output_dir=output_dir,
            source_name=f"fred_{series_id.lower()}",
        )

    # ---------------------------------------------------------------- fetch

    def _fetch_raw(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch raw observations from FRED for the inclusive date range."""
        params: dict[str, str] = {
            "series_id": self.series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.strftime("%Y-%m-%d"),
            "observation_end": end.strftime("%Y-%m-%d"),
        }

        # Log without exposing the API key
        log_params = {**params, "api_key": "REDACTED"}
        logger.debug("FRED request: %s params=%s", self.base_url, log_params)

        response = requests.get(
            self.base_url,
            params=params,
            timeout=self.request_timeout_seconds,
        )

        # Classify HTTP errors before parsing.
        # Transient: 5xx, 429. Raise as ConnectionError so base class retries.
        if response.status_code >= 500 or response.status_code == 429:
            raise ConnectionError(
                f"FRED API transient error: HTTP {response.status_code} "
                f"for series_id={self.series_id}"
            )

        # Permanent: 4xx other than 429. Raise FREDError so base classifies permanent.
        if response.status_code != 200:
            # Body may contain useful diagnostic info — include first 200 chars only
            body_preview = response.text[:200] if response.text else "<empty>"
            raise FREDError(
                f"FRED API permanent error: HTTP {response.status_code} "
                f"for series_id={self.series_id}. Body: {body_preview}"
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            # Non-JSON response on a 200 — treat as permanent (something is broken upstream)
            raise FREDError(
                f"FRED API returned non-JSON 200 response: {exc}. "
                f"Body preview: {response.text[:200]}"
            ) from exc

        observations = payload.get("observations")
        if observations is None:
            # Successful HTTP but unexpected payload shape — permanent (schema change)
            raise FREDError(
                f"FRED response missing 'observations' key. "
                f"Got keys: {list(payload.keys())}"
            )

        return pd.DataFrame(observations)

    # ---------------------------------------------------------------- validate

    def _validate_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate response shape and translate FRED-specific value conventions.

        - Raises ValueError (permanent) if required columns are missing.
        - Translates the "." holiday placeholder to NaN via pd.to_numeric.
        - Parses date strings to datetime.
        - Adds provenance columns: series_id, source, fetched_at.

        Note: NaN rows ARE retained in the raw layer (lossless). The data quality
        stage in the transformation layer decides whether to quarantine them.
        """
        if df.empty:
            # Empty df is not a schema violation — base will classify as EMPTY outcome
            return df

        required = {"date", "value"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"FRED response missing required columns: {sorted(missing)}. "
                f"Got: {sorted(df.columns)}"
            )

        result = df.copy()

        # Parse dates — raise (permanent) if the format is wrong
        result["date"] = pd.to_datetime(
            result["date"], format="%Y-%m-%d", errors="raise"
        )

        # Translate "." (holiday placeholder) and any other non-numeric to NaN.
        # This is the type-normalisation step, not a data-quality decision.
        result["value"] = pd.to_numeric(result["value"], errors="coerce")

        # Keep only the columns we care about for the raw layer.
        # Drop realtime_start / realtime_end — they exist for FRED's vintage data
        # use case which we don't need here.
        result = result[["date", "value"]].copy()

        # Provenance — useful for downstream debugging and lineage
        result["series_id"] = self.series_id
        result["source"] = self.source_name
        result["fetched_at"] = pd.Timestamp.now("UTC")

        return result
