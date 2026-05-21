"""Base ingestion contract.

This module defines the abstract Ingestor base class that all source-specific
ingestion modules extend. The base enforces:

- Retry with exponential backoff + jitter for transient failures
- Failure classification into transient / permanent / empty / success
- Structured logging of every attempt
- Idempotent writes — same date range produces the same Parquet output path
- Normalised return type — never raises to the caller; always returns
  an IngestionResult describing the outcome

Source-specific subclasses (FRED, Yahoo) implement only the source-native
fetch and schema validation. Everything operational is provided here.

See ADR-0005 for the contract pattern and ADR-0001 for the medallion storage layout.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

logger = logging.getLogger(__name__)


class IngestionOutcome(str, Enum):
    """Classification of an ingestion attempt's outcome.

    SUCCESS:            Data was fetched, validated, and written to the raw layer.
    TRANSIENT_FAILURE:  Recoverable failure (timeout, rate limit, network). Retried
                        up to max_attempts. Final state if retries exhausted.
    PERMANENT_FAILURE:  Non-recoverable failure (schema change, 404, auth error).
                        Not retried. Quarantined with logged reason.
    EMPTY:              Successful fetch but no data returned for the requested period.
                        Logged but not an error.
    """

    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    EMPTY = "empty"


@dataclass
class IngestionResult:
    """Normalised result of a single ingestion attempt.

    Every call to Ingestor.fetch() returns one of these. The caller (the pipeline
    orchestrator) inspects the outcome to decide whether to continue, retry the
    whole pipeline, or alert. Ingestors never raise to the caller.
    """

    source: str
    outcome: IngestionOutcome
    rows_fetched: int
    date_range: tuple[datetime, datetime] | None
    attempts: int
    duration_seconds: float
    output_path: Path | None = None
    error_message: str | None = None
    data: pd.DataFrame | None = None  # populated on SUCCESS only


def retry_with_backoff(
    fn: Callable[[], Any],
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    transient_exceptions: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
) -> Any:
    """Retry a zero-arg callable with exponential backoff + jitter on transient failures.

    Permanent exceptions (anything not in ``transient_exceptions``) are re-raised
    immediately without retry. This is deliberate — schema changes and auth errors
    are not made better by waiting.

    Args:
        fn: Zero-arg callable to invoke.
        max_attempts: Total attempts including the first one. Must be >= 1.
        base_delay_seconds: Delay before the first retry. Doubles on each subsequent retry.
        max_delay_seconds: Cap on the computed delay.
        transient_exceptions: Exception types that trigger retry.

    Returns:
        Whatever fn() returns on success.

    Raises:
        The last exception encountered, if max_attempts is exhausted, or any
        non-transient exception immediately.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except transient_exceptions as exc:
            if attempt >= max_attempts:
                logger.warning(
                    "Max attempts (%d) reached after transient failure: %s",
                    max_attempts,
                    exc,
                )
                raise
            delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            jitter = random.uniform(0, delay * 0.25)
            sleep_for = delay + jitter
            logger.info(
                "Transient failure on attempt %d/%d: %s. Retrying in %.2fs.",
                attempt,
                max_attempts,
                exc,
                sleep_for,
            )
            time.sleep(sleep_for)


class Ingestor(ABC):
    """Abstract base for source-specific ingestors.

    Subclasses implement source-specific fetch and schema validation. The base
    class provides retry, timeout-aware logging, failure classification, idempotent
    output paths, and the normalised IngestionResult return type.

    Subclasses MUST set ``source_name``. They MAY override ``max_attempts`` and
    ``transient_exceptions`` if the default policy does not fit the source's
    real-world failure characteristics.

    Subclasses MUST implement ``_fetch_raw`` and ``_validate_schema``.
    """

    # Subclass contract — set on the subclass, not the instance
    source_name: ClassVar[str] = ""
    max_attempts: ClassVar[int] = 3
    transient_exceptions: ClassVar[tuple[type[BaseException], ...]] = (
        TimeoutError,
        ConnectionError,
    )

    def __init__(self, output_dir: Path | str):
        if not self.source_name:
            raise ValueError(
                f"{type(self).__name__}.source_name must be set on the subclass"
            )
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ contract

    @abstractmethod
    def _fetch_raw(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch raw data for the inclusive date range [start, end].

        Returns a DataFrame in the source's native shape. May raise:
        - A transient exception (in self.transient_exceptions) — base class will retry.
        - Any other exception — base class will classify as permanent failure.

        Must NOT catch and swallow exceptions internally — the base class needs
        them to make the retry/quarantine decision.
        """

    @abstractmethod
    def _validate_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate the raw DataFrame against the expected source schema.

        Returns a cleaned DataFrame (e.g. typed columns, normalised dates). Any
        violation should raise a descriptive exception — the base class will
        classify it as permanent failure and the row will land in quarantine.
        """

    # ------------------------------------------------------------------ helpers

    def _output_path(self, start: datetime, end: datetime) -> Path:
        """Deterministic output path. Same date range → same file. Idempotent."""
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")
        return self.output_dir / f"{self.source_name}_{start_str}_{end_str}.parquet"

    # ------------------------------------------------------------------ public

    def fetch(self, start: datetime, end: datetime) -> IngestionResult:
        """Fetch data for [start, end], validate, write Parquet, return result.

        This is the only public entrypoint. It never raises to the caller.
        Inspect the returned IngestionResult.outcome to decide what to do.
        """
        t0 = time.perf_counter()
        attempts_made = 0

        try:
            def _attempt() -> pd.DataFrame:
                nonlocal attempts_made
                attempts_made += 1
                return self._fetch_raw(start, end)

            raw_df = retry_with_backoff(
                _attempt,
                max_attempts=self.max_attempts,
                transient_exceptions=self.transient_exceptions,
            )

            if raw_df is None or raw_df.empty:
                duration = time.perf_counter() - t0
                logger.info(
                    "%s: empty result for %s to %s (%d attempts, %.2fs)",
                    self.source_name,
                    start.date(),
                    end.date(),
                    attempts_made,
                    duration,
                )
                return IngestionResult(
                    source=self.source_name,
                    outcome=IngestionOutcome.EMPTY,
                    rows_fetched=0,
                    date_range=(start, end),
                    attempts=attempts_made,
                    duration_seconds=duration,
                )

            validated = self._validate_schema(raw_df)
            output_path = self._output_path(start, end)
            validated.to_parquet(output_path, index=False)

            duration = time.perf_counter() - t0
            logger.info(
                "%s: ingested %d rows for %s to %s in %.2fs (attempts=%d) -> %s",
                self.source_name,
                len(validated),
                start.date(),
                end.date(),
                duration,
                attempts_made,
                output_path,
            )
            return IngestionResult(
                source=self.source_name,
                outcome=IngestionOutcome.SUCCESS,
                rows_fetched=len(validated),
                date_range=(start, end),
                attempts=attempts_made,
                duration_seconds=duration,
                output_path=output_path,
                data=validated,
            )

        except self.transient_exceptions as exc:
            # Transient exception that exhausted retries
            duration = time.perf_counter() - t0
            logger.error(
                "%s: transient failure exhausted after %d attempts: %s",
                self.source_name,
                attempts_made,
                exc,
            )
            return IngestionResult(
                source=self.source_name,
                outcome=IngestionOutcome.TRANSIENT_FAILURE,
                rows_fetched=0,
                date_range=(start, end),
                attempts=attempts_made,
                duration_seconds=duration,
                error_message=str(exc),
            )

        except Exception as exc:
            # Anything else — permanent failure
            duration = time.perf_counter() - t0
            logger.exception(
                "%s: permanent failure for %s to %s after %d attempts",
                self.source_name,
                start.date(),
                end.date(),
                attempts_made,
            )
            return IngestionResult(
                source=self.source_name,
                outcome=IngestionOutcome.PERMANENT_FAILURE,
                rows_fetched=0,
                date_range=(start, end),
                attempts=attempts_made,
                duration_seconds=duration,
                error_message=str(exc),
            )
